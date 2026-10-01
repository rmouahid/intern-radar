"""SQLite persistence: seen jobs, assessments, notification and health state."""

import json
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any

from intern_radar.chance import Chance
from intern_radar.grouping import group_key
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
    digested_at TEXT,
    group_key TEXT
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
CREATE TABLE IF NOT EXISTS llm_usage (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    purpose TEXT NOT NULL,
    model TEXT NOT NULL,
    input INTEGER NOT NULL,
    output INTEGER NOT NULL,
    cost REAL NOT NULL,
    seconds REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS applications (
    job_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    applied_at TEXT,
    reminded_at TEXT
);
CREATE TABLE IF NOT EXISTS resumes (
    job_id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    report TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chances (
    job_id TEXT PRIMARY KEY,
    percent INTEGER NOT NULL,
    reasons TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS application_events (
    id INTEGER PRIMARY KEY,
    job_id TEXT NOT NULL,
    status TEXT NOT NULL,
    at TEXT NOT NULL
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
        # LLM usage is recorded from the scoring worker threads (see
        # record_llm_usage); every other access happens in the main thread.
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._usage_lock = threading.Lock()
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        columns = {row["name"] for row in self._db.execute("PRAGMA table_info(jobs)")}
        with self._db:
            if "group_key" not in columns:
                self._db.execute("ALTER TABLE jobs ADD COLUMN group_key TEXT")
            rows = self._db.execute(
                "SELECT id, company, title FROM jobs WHERE group_key IS NULL"
            ).fetchall()
            self._db.executemany(
                "UPDATE jobs SET group_key = ? WHERE id = ?",
                [(group_key(r["company"], r["title"]), r["id"]) for r in rows],
            )
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS jobs_group_key ON jobs (group_key)"
            )

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
                f" status, group_key)"
                f" VALUES ({', '.join('?' * (len(JOB_COLUMNS) + 3))})",
                [*values, now.isoformat(), status, group_key(job.company, job.title)],
            )

    def get_job(self, job_id: str) -> Job | None:
        row = self._db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return _row_to_job(row) if row else None

    def job_ref(self, job_id: str) -> int | None:
        """Short numeric reference, for buttons limited to 64 bytes."""
        row = self._db.execute(
            "SELECT rowid FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
        return row["rowid"] if row else None

    def job_by_ref(self, ref: int) -> Job | None:
        row = self._db.execute("SELECT * FROM jobs WHERE rowid = ?", (ref,)).fetchone()
        return _row_to_job(row) if row else None

    def scored_job(self, job_id: str) -> ScoredJob | None:
        row = self._db.execute(
            "SELECT * FROM jobs WHERE id = ? AND assessment IS NOT NULL", (job_id,)
        ).fetchone()
        return _row_to_scored(row) if row else None

    def group_by_ref(self, ref: int) -> list[ScoredJob]:
        """The scored job `ref` first, then the other scored members of its group."""
        lead = self._db.execute(
            "SELECT * FROM jobs WHERE rowid = ? AND status = 'scored'"
            " AND assessment IS NOT NULL",
            (ref,),
        ).fetchone()
        if lead is None:
            return []
        others = self._db.execute(
            "SELECT * FROM jobs WHERE group_key = ? AND id != ? AND status = 'scored'"
            " AND assessment IS NOT NULL ORDER BY id",
            (lead["group_key"], lead["id"]),
        ).fetchall()
        return [_row_to_scored(row) for row in (lead, *others)]

    def has_similar(self, company: str, title: str) -> bool:
        row = self._db.execute(
            "SELECT 1 FROM jobs WHERE company = ? AND lower(title) = lower(?)"
            " AND source != 'adzuna' LIMIT 1",
            (company, title),
        ).fetchone()
        return row is not None

    def pending(self, limit: int | None = None) -> list[Job]:
        """Jobs to score, one per posting group; the others inherit its result."""
        # Top tiers first, newest first: the first run finds hundreds of offers
        # and the LLM only scores a few batches per run.
        rows = self._db.execute(
            "SELECT * FROM jobs WHERE status = 'pending' AND attempts < ?"
            " ORDER BY CASE tier WHEN 'S' THEN 0 WHEN 'A' THEN 1 WHEN 'B' THEN 2"
            " ELSE 3 END, first_seen DESC, id",
            (MAX_ATTEMPTS,),
        )
        jobs: list[Job] = []
        groups: set[str] = set()
        for row in rows:
            if limit is not None and len(jobs) >= limit:
                break
            if row["group_key"] not in groups:
                groups.add(row["group_key"])
                jobs.append(_row_to_job(row))
        return jobs

    def inherit_group_assessments(self) -> int:
        """Copy each scored group member's result to its pending members.

        Notification and digest dates are copied too, so a posting seen in a
        new country is not announced twice. Returns the number of jobs updated.
        """
        rows = self._db.execute(
            "SELECT p.id, s.assessment, s.score, s.notified_at, s.digested_at"
            " FROM jobs p JOIN jobs s ON s.group_key = p.group_key"
            " AND s.status = 'scored' WHERE p.status = 'pending'"
            " ORDER BY p.id, s.first_seen DESC"
        ).fetchall()
        updates: dict[str, tuple] = {}
        for row in rows:
            updates.setdefault(
                row["id"],
                (
                    row["assessment"],
                    row["score"],
                    row["notified_at"],
                    row["digested_at"],
                    row["id"],
                ),
            )
        with self._db:
            self._db.executemany(
                "UPDATE jobs SET status = 'scored', assessment = ?, score = ?,"
                " notified_at = ?, digested_at = ? WHERE id = ?",
                list(updates.values()),
            )
        return len(updates)

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

    def due_immediate(
        self,
        threshold: float,
        limit: int | None = None,
        min_posted: str | None = None,
    ) -> list[ScoredJob]:
        """`min_posted` (ISO date) skips offers first published before it."""
        rows = self._db.execute(
            "SELECT * FROM jobs WHERE status = 'scored' AND score >= ?"
            " AND notified_at IS NULL AND digested_at IS NULL"
            " AND (? IS NULL OR posted_at IS NULL OR substr(posted_at, 1, 10) >= ?)"
            " ORDER BY score DESC, id LIMIT ?",
            (threshold, min_posted, min_posted, -1 if limit is None else limit),
        )
        return [_row_to_scored(row) for row in rows]

    def rescore(
        self,
        score: Callable[[Job, Assessment], float | None],
        adjust: Callable[[Job, Assessment], Assessment] | None = None,
    ) -> int:
        """Recompute every stored final score; returns how many changed.

        `adjust` may first rewrite the stored assessment (deterministic
        overrides that depend on the profile); rewritten ones are saved.

        Notification and digest dates are kept, and offers already sent in a
        digest are not due as immediate ones, so nothing is sent twice.
        """
        rows = self._db.execute(
            "SELECT * FROM jobs WHERE status = 'scored' AND assessment IS NOT NULL"
        ).fetchall()
        updates = []
        for row in rows:
            scored = _row_to_scored(row)
            assessment = scored.assessment
            if adjust is not None:
                assessment = adjust(scored.job, assessment)
            new = score(scored.job, assessment)
            if new != scored.score or assessment != scored.assessment:
                updates.append((new, json.dumps(asdict(assessment)), row["id"]))
        with self._db:
            self._db.executemany(
                "UPDATE jobs SET score = ?, assessment = ? WHERE id = ?", updates
            )
        return len(updates)

    def clear_chances(self) -> int:
        """Forget stored interview-chance estimates (recomputed on demand)."""
        with self._db:
            return self._db.execute("DELETE FROM chances").rowcount

    def mark_notified(self, job_id: str, now: datetime) -> None:
        with self._db:
            self._db.execute(
                "UPDATE jobs SET notified_at = ? WHERE id = ?",
                (now.isoformat(), job_id),
            )

    def due_digest(
        self, low: float, high: float, min_posted: str | None = None
    ) -> list[ScoredJob]:
        rows = self._db.execute(
            "SELECT * FROM jobs WHERE status = 'scored' AND score >= ?"
            " AND score < ? AND digested_at IS NULL"
            " AND (? IS NULL OR posted_at IS NULL OR substr(posted_at, 1, 10) >= ?)"
            " ORDER BY score DESC, id",
            (low, high, min_posted, min_posted),
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

    def record_llm_usage(
        self, purpose: str, usage: dict[str, Any], now: datetime
    ) -> None:
        with self._usage_lock, self._db:
            self._db.execute(
                "INSERT INTO llm_usage (at, purpose, model, input, output, cost,"
                " seconds) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    now.isoformat(),
                    purpose,
                    usage["model"],
                    usage["input"],
                    usage["output"],
                    usage["cost"],
                    usage["seconds"],
                ),
            )

    def application_status(self, job_id: str) -> str | None:
        row = self._db.execute(
            "SELECT status FROM applications WHERE job_id = ?", (job_id,)
        ).fetchone()
        return row["status"] if row else None

    def set_application(self, job_id: str, status: str, now: datetime) -> None:
        stamp = now.isoformat()
        with self._db:
            self._db.execute(
                "INSERT INTO applications (job_id, status, updated_at, applied_at)"
                " VALUES (?, ?, ?, CASE WHEN ? = 'applied' THEN ? END)"
                " ON CONFLICT(job_id) DO UPDATE SET status = excluded.status,"
                " updated_at = excluded.updated_at,"
                " applied_at = COALESCE(applications.applied_at, excluded.applied_at)",
                (job_id, status, stamp, status, stamp),
            )
            self._db.execute(
                "INSERT INTO application_events (job_id, status, at) VALUES (?, ?, ?)",
                (job_id, status, stamp),
            )

    def application_history(self, job_id: str) -> list[tuple[str, str]]:
        """Status changes of one application, oldest first: (status, at)."""
        rows = self._db.execute(
            "SELECT status, at FROM application_events WHERE job_id = ? ORDER BY id",
            (job_id,),
        )
        return [(row["status"], row["at"]) for row in rows]

    def applications(self) -> list[tuple[Job, str, str, str | None]]:
        """Tracked offers: job, status, last update, application date."""
        rows = self._db.execute(
            "SELECT j.*, a.status AS a_status, a.updated_at AS a_updated,"
            " a.applied_at AS a_applied FROM applications a JOIN jobs j"
            " ON j.id = a.job_id ORDER BY a.updated_at DESC"
        )
        return [
            (_row_to_job(row), row["a_status"], row["a_updated"], row["a_applied"])
            for row in rows
        ]

    def due_reminders(self, before: datetime) -> list[tuple[Job, str]]:
        """Applications still waiting since `before`, never reminded."""
        rows = self._db.execute(
            "SELECT j.*, a.applied_at AS a_applied FROM applications a JOIN jobs j"
            " ON j.id = a.job_id WHERE a.status = 'applied'"
            " AND a.reminded_at IS NULL AND a.updated_at <= ? ORDER BY a.applied_at",
            (before.isoformat(),),
        )
        return [(_row_to_job(row), row["a_applied"]) for row in rows]

    def mark_reminded(self, job_id: str, now: datetime) -> None:
        with self._db:
            self._db.execute(
                "UPDATE applications SET reminded_at = ? WHERE job_id = ?",
                (now.isoformat(), job_id),
            )

    def save_resume(self, job_id: str, path: str, report: dict, now: datetime) -> None:
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO resumes (job_id, path, created_at, report)"
                " VALUES (?, ?, ?, ?)",
                (job_id, path, now.isoformat(), json.dumps(report)),
            )

    def resume(self, job_id: str) -> tuple[str, dict] | None:
        row = self._db.execute(
            "SELECT path, report FROM resumes WHERE job_id = ?", (job_id,)
        ).fetchone()
        return (row["path"], json.loads(row["report"])) if row else None

    def resumes_since(self, since: datetime) -> int:
        row = self._db.execute(
            "SELECT count(*) AS n FROM resumes WHERE created_at >= ?",
            (since.isoformat(),),
        ).fetchone()
        return row["n"]

    def chance(self, job_id: str) -> Chance | None:
        row = self._db.execute(
            "SELECT percent, reasons FROM chances WHERE job_id = ?", (job_id,)
        ).fetchone()
        if row is None:
            return None
        reasons = tuple((bool(p), str(t)) for p, t in json.loads(row["reasons"]))
        return Chance(row["percent"], reasons)

    def save_chance(self, job_id: str, chance: Chance) -> None:
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO chances (job_id, percent, reasons, created_at)"
                " VALUES (?, ?, ?, datetime('now'))",
                (job_id, chance.percent, json.dumps(chance.reasons)),
            )

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
