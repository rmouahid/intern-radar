"""SQLite persistence: seen jobs, assessments, notification and health state."""

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timedelta

from intern_radar.models import Assessment, Job, ScoredJob

MAX_ATTEMPTS = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    company TEXT NOT NULL,
    tier TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT NOT NULL,
    url TEXT NOT NULL,
    description TEXT NOT NULL,
    source TEXT NOT NULL,
    posted_at TEXT,
    first_seen TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    assessment TEXT,
    score REAL,
    notified_at TEXT,
    digested_at TEXT
);
CREATE TABLE IF NOT EXISTS source_health (
    company TEXT PRIMARY KEY,
    first_failure TEXT NOT NULL,
    last_error TEXT NOT NULL,
    alerted INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS llm_health (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    first_failure TEXT NOT NULL,
    alerted INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS letters (
    job_id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    report TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

JOB_COLUMNS = (
    "id",
    "company",
    "tier",
    "title",
    "location",
    "url",
    "description",
    "source",
    "posted_at",
)


def _row_to_job(row: sqlite3.Row) -> Job:
    return Job(**{column: row[column] for column in JOB_COLUMNS})


def _row_to_scored(row: sqlite3.Row) -> ScoredJob:
    assessment = Assessment(**json.loads(row["assessment"]))
    return ScoredJob(_row_to_job(row), assessment, row["score"])


class Store:
    def __init__(self, path: str) -> None:
        self._db = sqlite3.connect(path)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)

    def close(self) -> None:
        self._db.close()

    # --- jobs -------------------------------------------------------------

    def known_ids(self) -> set[str]:
        return {row["id"] for row in self._db.execute("SELECT id FROM jobs")}

    def add(self, job: Job, status: str, now: datetime) -> None:
        values = [getattr(job, column) for column in JOB_COLUMNS]
        if status != "pending":
            values[JOB_COLUMNS.index("description")] = ""
        with self._db:
            self._db.execute(
                f"INSERT OR IGNORE INTO jobs ({', '.join(JOB_COLUMNS)}, first_seen,"
                f" status) VALUES ({', '.join('?' * (len(JOB_COLUMNS) + 2))})",
                [*values, now.isoformat(), status],
            )

    def get_job(self, job_id: str) -> Job | None:
        row = self._db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return _row_to_job(row) if row else None

    def has_similar(self, company: str, title: str) -> bool:
        row = self._db.execute(
            "SELECT 1 FROM jobs WHERE company = ? AND lower(title) = lower(?)"
            " AND source != 'adzuna' LIMIT 1",
            (company, title),
        ).fetchone()
        return row is not None

    def pending(self, limit: int | None = None) -> list[Job]:
        # Top tiers first, newest first: the first run finds hundreds of offers
        # and the LLM only scores a few batches per run.
        sql = (
            "SELECT * FROM jobs WHERE status = 'pending' AND attempts < ?"
            " ORDER BY CASE tier WHEN 'S' THEN 0 WHEN 'A' THEN 1 WHEN 'B' THEN 2"
            " ELSE 3 END, first_seen DESC, id"
        )
        params: list[object] = [MAX_ATTEMPTS]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        return [_row_to_job(row) for row in self._db.execute(sql, params)]

    def record_attempt(self, job_ids: list[str]) -> None:
        with self._db:
            self._db.executemany(
                "UPDATE jobs SET attempts = attempts + 1 WHERE id = ?",
                [(job_id,) for job_id in job_ids],
            )

    def save_assessment(
        self, job_id: str, assessment: Assessment, score: float | None
    ) -> None:
        with self._db:
            self._db.execute(
                "UPDATE jobs SET status = 'scored', assessment = ?, score = ?"
                " WHERE id = ?",
                (json.dumps(asdict(assessment)), score, job_id),
            )

    def due_immediate(self, threshold: float, limit: int) -> list[ScoredJob]:
        rows = self._db.execute(
            "SELECT * FROM jobs WHERE status = 'scored' AND score >= ?"
            " AND notified_at IS NULL ORDER BY score DESC, id LIMIT ?",
            (threshold, limit),
        )
        return [_row_to_scored(row) for row in rows]

    def mark_notified(self, job_id: str, now: datetime) -> None:
        with self._db:
            self._db.execute(
                "UPDATE jobs SET notified_at = ? WHERE id = ?",
                (now.isoformat(), job_id),
            )

    def due_digest(self, low: float, high: float) -> list[ScoredJob]:
        rows = self._db.execute(
            "SELECT * FROM jobs WHERE status = 'scored' AND score >= ?"
            " AND score < ? AND digested_at IS NULL ORDER BY score DESC, id",
            (low, high),
        )
        return [_row_to_scored(row) for row in rows]

    def mark_digested(self, job_ids: list[str], now: datetime) -> None:
        with self._db:
            self._db.executemany(
                "UPDATE jobs SET digested_at = ? WHERE id = ?",
                [(now.isoformat(), job_id) for job_id in job_ids],
            )

    def scored(self, min_score: float) -> list[ScoredJob]:
        rows = self._db.execute(
            "SELECT * FROM jobs WHERE status = 'scored' AND score >= ?"
            " ORDER BY score DESC, id",
            (min_score,),
        )
        return [_row_to_scored(row) for row in rows]

    # --- health -----------------------------------------------------------

    def record_source_result(
        self, company: str, error: str | None, now: datetime
    ) -> None:
        with self._db:
            if error is None:
                self._db.execute(
                    "DELETE FROM source_health WHERE company = ?", (company,)
                )
            else:
                self._db.execute(
                    "INSERT INTO source_health (company, first_failure, last_error)"
                    " VALUES (?, ?, ?) ON CONFLICT(company)"
                    " DO UPDATE SET last_error = excluded.last_error",
                    (company, now.isoformat(), error),
                )

    def sources_to_alert(
        self, now: datetime, after: timedelta
    ) -> list[tuple[str, str]]:
        rows = self._db.execute(
            "SELECT company, first_failure, last_error FROM source_health"
            " WHERE alerted = 0 ORDER BY company"
        )
        return [
            (row["company"], row["last_error"])
            for row in rows
            if now - datetime.fromisoformat(row["first_failure"]) >= after
        ]

    def mark_source_alerted(self, company: str) -> None:
        with self._db:
            self._db.execute(
                "UPDATE source_health SET alerted = 1 WHERE company = ?", (company,)
            )

    def record_llm_result(self, ok: bool, now: datetime) -> None:
        with self._db:
            if ok:
                self._db.execute("DELETE FROM llm_health")
            else:
                self._db.execute(
                    "INSERT OR IGNORE INTO llm_health (id, first_failure)"
                    " VALUES (1, ?)",
                    (now.isoformat(),),
                )

    def llm_alert_due(self, now: datetime, after: timedelta) -> bool:
        row = self._db.execute(
            "SELECT first_failure, alerted FROM llm_health WHERE id = 1"
        ).fetchone()
        if row is None or row["alerted"]:
            return False
        return now - datetime.fromisoformat(row["first_failure"]) >= after

    def mark_llm_alerted(self) -> None:
        with self._db:
            self._db.execute("UPDATE llm_health SET alerted = 1")

    # --- letters and meta -------------------------------------------------

    def save_letter(self, job_id: str, path: str, report: dict, now: datetime) -> None:
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO letters (job_id, path, created_at, report)"
                " VALUES (?, ?, ?, ?)",
                (job_id, path, now.isoformat(), json.dumps(report)),
            )

    def letter(self, job_id: str) -> tuple[str, dict] | None:
        row = self._db.execute(
            "SELECT path, report FROM letters WHERE job_id = ?", (job_id,)
        ).fetchone()
        return (row["path"], json.loads(row["report"])) if row else None

    def letters_since(self, since: datetime) -> int:
        row = self._db.execute(
            "SELECT count(*) AS n FROM letters WHERE created_at >= ?",
            (since.isoformat(),),
        ).fetchone()
        return row["n"]

    def get_meta(self, key: str) -> str | None:
        row = self._db.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value)
            )
