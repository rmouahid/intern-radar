"""Read-only statistics for the dashboard, computed from the SQLite store."""

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta


def connect(path: str) -> sqlite3.Connection:
    """Read-only connection: the dashboard can never change the data."""
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    db.row_factory = sqlite3.Row
    return db


def _count(db: sqlite3.Connection, sql: str, params: tuple = ()) -> int:
    return int(db.execute(sql, params).fetchone()[0] or 0)


@dataclass(frozen=True)
class Kpis:
    seen: int
    seen_week: int
    scored: int
    immediate: int
    digested: int
    applied: int
    interviews: int
    offers: int
    llm_cost_week: float


def kpis(db: sqlite3.Connection, now: datetime) -> Kpis:
    week = (now - timedelta(days=7)).isoformat()
    return Kpis(
        seen=_count(db, "SELECT count(*) FROM jobs"),
        seen_week=_count(
            db, "SELECT count(*) FROM jobs WHERE first_seen >= ?", (week,)
        ),
        scored=_count(db, "SELECT count(*) FROM jobs WHERE status = 'scored'"),
        immediate=_count(db, "SELECT count(*) FROM jobs WHERE notified_at IS NOT NULL"),
        digested=_count(
            db,
            "SELECT count(*) FROM jobs WHERE digested_at IS NOT NULL"
            " AND notified_at IS NULL",
        ),
        applied=_count(
            db, "SELECT count(*) FROM applications WHERE applied_at IS NOT NULL"
        ),
        interviews=_count(
            db,
            "SELECT count(*) FROM applications WHERE status IN ('interview', 'offer')",
        ),
        offers=_count(db, "SELECT count(*) FROM applications WHERE status = 'offer'"),
        llm_cost_week=float(
            db.execute(
                "SELECT coalesce(sum(cost), 0) FROM llm_usage WHERE at >= ?", (week,)
            ).fetchone()[0]
        ),
    )


@dataclass(frozen=True)
class Week:
    start: date
    seen: int
    passed: int
    scored: int
    surfaced: int
    applied: int
    interviews: int


def _monday(stamp: str) -> date:
    day = datetime.fromisoformat(stamp).date()
    return day - timedelta(days=day.weekday())


def weekly_funnel(db: sqlite3.Connection, now: datetime, weeks: int = 8) -> list[Week]:
    """Cohorts of offers by week first seen, newest first."""
    first = _monday(now.isoformat()) - timedelta(weeks=weeks - 1)
    rows = db.execute(
        "SELECT j.first_seen, j.status, j.notified_at, j.digested_at,"
        " a.status AS a_status, a.applied_at FROM jobs j"
        " LEFT JOIN applications a ON a.job_id = j.id WHERE j.first_seen >= ?",
        (first.isoformat(),),
    ).fetchall()
    counts = {first + timedelta(weeks=n): [0, 0, 0, 0, 0, 0] for n in range(weeks)}
    for row in rows:
        bucket = counts.get(_monday(row["first_seen"]))
        if bucket is None:
            continue
        bucket[0] += 1
        bucket[1] += row["status"] in ("pending", "scored")
        bucket[2] += row["status"] == "scored"
        bucket[3] += bool(row["notified_at"] or row["digested_at"])
        bucket[4] += row["applied_at"] is not None
        bucket[5] += row["a_status"] in ("interview", "offer")
    return [
        Week(start, *values) for start, values in sorted(counts.items(), reverse=True)
    ]


@dataclass(frozen=True)
class SourceRow:
    company: str
    source: str
    tier: str
    offers: int
    last_seen: str
    failing_since: str | None
    last_error: str | None


def sources(db: sqlite3.Connection) -> list[SourceRow]:
    """Per company: offers seen, last new offer and current failure streak."""
    health = {
        row["company"]: (row["first_failure"], row["last_error"])
        for row in db.execute("SELECT * FROM source_health")
    }
    rows = db.execute(
        "SELECT company, source, tier, count(*) AS n, max(first_seen) AS last"
        " FROM jobs GROUP BY company ORDER BY n DESC, company"
    ).fetchall()
    result = [
        SourceRow(
            r["company"],
            r["source"],
            r["tier"],
            r["n"],
            r["last"][:10],
            *health.pop(r["company"], (None, None)),
        )
        for r in rows
    ]
    result += [
        SourceRow(company, "—", "—", 0, "—", since, error)
        for company, (since, error) in sorted(health.items())
    ]
    return result


def score_histogram(
    db: sqlite3.Connection, step: float = 0.5
) -> list[tuple[float, int]]:
    """(bin start, count) for every scored offer with a score, 0 to 10."""
    bins = {round(n * step, 1): 0 for n in range(int(10 / step))}
    for (score,) in db.execute("SELECT score FROM jobs WHERE score IS NOT NULL"):
        start = min(round(int(score / step) * step, 1), 10 - step)
        bins[round(start, 1)] += 1
    return sorted(bins.items())


@dataclass(frozen=True)
class ApplicationRow:
    company: str
    title: str
    url: str
    status: str
    updated: str
    applied: str | None


def applications(db: sqlite3.Connection) -> list[ApplicationRow]:
    rows = db.execute(
        "SELECT j.company, j.title, j.url, a.status, a.updated_at, a.applied_at"
        " FROM applications a JOIN jobs j ON j.id = a.job_id"
        " ORDER BY a.updated_at DESC"
    )
    return [
        ApplicationRow(
            r["company"],
            r["title"],
            r["url"],
            r["status"],
            r["updated_at"][:10],
            (r["applied_at"] or "")[:10] or None,
        )
        for r in rows
    ]


@dataclass(frozen=True)
class UsageRow:
    day: str
    purpose: str
    calls: int
    tokens_in: int
    tokens_out: int
    cost: float


def llm_usage(db: sqlite3.Connection, now: datetime, days: int = 14) -> list[UsageRow]:
    since = (now - timedelta(days=days)).isoformat()
    rows = db.execute(
        "SELECT substr(at, 1, 10) AS day, purpose, count(*) AS calls,"
        " sum(input) AS tin, sum(output) AS tout, sum(cost) AS cost"
        " FROM llm_usage WHERE at >= ? GROUP BY day, purpose"
        " ORDER BY day DESC, purpose",
        (since,),
    )
    return [
        UsageRow(r["day"], r["purpose"], r["calls"], r["tin"], r["tout"], r["cost"])
        for r in rows
    ]
