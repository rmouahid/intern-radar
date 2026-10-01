"""Read-only statistics for the dashboard, computed from the SQLite store."""

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from intern_radar.conventions import CONVENTIONS, convention_for
from intern_radar.description import clean_description
from intern_radar.skills import BY_NAME, find_skills
from intern_radar.tracking import STATUS_TEXT


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


# --- offers list -----------------------------------------------------------------

REGIONS: tuple[tuple[str, str], ...] = tuple(
    (key, convention.region) for key, convention in CONVENTIONS.items()
)
_REGION_KEY = {id(convention): key for key, convention in CONVENTIONS.items()}
VISA_GROUPS = {
    "none": ("free", "self_arranged"),  # no sponsor needed
    "sponsor": ("programme", "sponsorship_stated", "uncertain", "unlikely"),
}
PER_PAGE = 30


def region_key(location: str) -> str:
    return _REGION_KEY[id(convention_for(location))]


@dataclass(frozen=True)
class OfferFilters:
    min_score: float = 5.5
    tier: str = ""  # S, A, B or unlisted (discovery)
    region: str = ""  # a CONVENTIONS key
    visa: str = ""  # a VISA_GROUPS key
    status: str = ""  # an application status, "none" or "dismissed"
    days: int = 60  # publication age; 0 = any
    q: str = ""
    page: int = 1

    @classmethod
    def from_query(cls, query: dict[str, str], default_days: int) -> "OfferFilters":
        def number(name: str, default: float) -> float:
            try:
                return float(query.get(name, "") or default)
            except ValueError:
                return default

        return cls(
            min_score=number("min", 5.5),
            tier=query.get("tier", "")
            if query.get("tier") in ("S", "A", "B", "unlisted")
            else "",
            region=query.get("region", "")
            if query.get("region") in CONVENTIONS
            else "",
            visa=query.get("visa", "") if query.get("visa") in VISA_GROUPS else "",
            status=query.get("status", "").strip()[:20],
            days=int(number("days", default_days)),
            q=query.get("q", "").strip()[:80],
            page=max(1, int(number("page", 1))),
        )


@dataclass(frozen=True)
class OfferRow:
    ref: int
    company: str
    tier: str
    title: str
    location: str
    score: float
    posted_at: str | None
    relevance: int | None
    work_authorisation: str
    application: str | None
    notified: bool
    digested: bool
    chance: int | None
    other_places: int  # copies of the posting in other locations
    vote: int | None = None  # the candidate's 👍 (1) or 👎 (-1)
    job_id: str = ""
    first_seen: str = ""
    url: str = ""


def offers(
    db: sqlite3.Connection, filters: OfferFilters, today: date
) -> tuple[list[OfferRow], int]:
    """One page of offers (one per posting group) and the total matching."""
    selected = matching_offers(db, filters, today)
    start = (filters.page - 1) * PER_PAGE
    return selected[start : start + PER_PAGE], len(selected)


def matching_offers(
    db: sqlite3.Connection, filters: OfferFilters, today: date
) -> list[OfferRow]:
    """Every offer matching the filters, one per posting group, best first."""
    sql = [
        "SELECT j.rowid AS ref, j.*, a.status AS application, c.percent AS chance,"
        " json_extract(j.assessment, '$.work_authorisation') AS wa,"
        " json_extract(j.assessment, '$.ai_relevance') AS relevance,"
        " f.vote AS vote"
        " FROM jobs j LEFT JOIN applications a ON a.job_id = j.id"
        " LEFT JOIN feedback f ON f.job_id = j.id"
        " LEFT JOIN chances c ON c.job_id = j.id"
        " WHERE j.status = 'scored' AND j.score IS NOT NULL AND j.score >= ?"
    ]
    params: list[object] = [filters.min_score]
    if filters.tier:
        sql.append("AND j.tier = ?")
        params.append(filters.tier)
    if filters.days > 0:
        cutoff = (today - timedelta(days=filters.days)).isoformat()
        sql.append("AND (j.posted_at IS NULL OR substr(j.posted_at, 1, 10) >= ?)")
        params.append(cutoff)
    if filters.q:
        sql.append("AND (j.company LIKE ? OR j.title LIKE ?)")
        params += [f"%{filters.q}%", f"%{filters.q}%"]
    sql.append("ORDER BY j.score DESC, j.first_seen DESC, j.id")
    rows = db.execute(" ".join(sql), params).fetchall()
    groups: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        groups.setdefault(row["group_key"] or row["id"], []).append(row)
    selected = []
    for members in groups.values():
        lead = members[0]
        wa = lead["wa"] or "uncertain"
        status = lead["application"]
        if filters.region and region_key(lead["location"]) != filters.region:
            continue
        if filters.visa and wa not in VISA_GROUPS[filters.visa]:
            continue
        if filters.status == "none" and status is not None:
            continue
        if filters.status not in ("", "none") and status != filters.status:
            continue
        if not filters.status and status == "dismissed":
            continue  # dismissed offers are hidden unless asked for
        selected.append(
            OfferRow(
                ref=lead["ref"],
                company=lead["company"],
                tier=lead["tier"],
                title=lead["title"],
                location=lead["location"],
                score=lead["score"],
                posted_at=lead["posted_at"],
                relevance=lead["relevance"],
                work_authorisation=wa,
                application=status,
                notified=lead["notified_at"] is not None,
                digested=lead["digested_at"] is not None,
                chance=lead["chance"],
                other_places=len(members) - 1,
                vote=lead["vote"],
                job_id=lead["id"],
                first_seen=lead["first_seen"],
                url=lead["url"],
            )
        )
    return selected


# --- applications board ----------------------------------------------------------

# Ongoing applications first: on a phone the columns stack.
COLUMNS = (
    ("interview", "Entretien"),
    ("offer", "Offre"),
    ("applied", "Postulé"),
    ("to_apply", "À postuler"),
    ("closed", "Clôturé"),
)
COLUMN_OF = {
    "applied": "applied",
    "interview": "interview",
    "offer": "offer",
    "rejected": "closed",
    "no_answer": "closed",
}
TO_APPLY_DAYS = 30  # liked or notified offers stay "to apply" this long


@dataclass(frozen=True)
class BoardCard:
    ref: int
    company: str
    title: str
    score: float | None
    status: str | None
    since: str  # date the card entered its column
    deadline: str | None
    next_action: str
    next_action_date: str | None
    interviews: tuple[str, ...]
    reminder_due: bool
    liked: bool


@dataclass(frozen=True)
class Event:
    when: str  # YYYY-MM-DD or YYYY-MM-DDTHH:MM
    kind: str  # interview, deadline, action, reminder
    ref: int
    company: str
    title: str
    detail: str = ""


def _details(row: sqlite3.Row) -> tuple[str | None, str, str | None, tuple[str, ...]]:
    interviews = tuple(json.loads(row["interviews"])) if row["interviews"] else ()
    return (
        row["deadline"],
        row["next_action"] or "",
        row["next_action_date"],
        interviews,
    )


def board(
    db: sqlite3.Connection, now: datetime, reminder_days: int
) -> dict[str, list[BoardCard]]:
    """Cards by column; "to apply" holds liked or notified offers not tracked."""
    due_before = (now - timedelta(days=reminder_days)).isoformat()
    recent = (now - timedelta(days=TO_APPLY_DAYS)).isoformat()
    rows = db.execute(
        "SELECT j.rowid AS ref, j.company, j.title, j.score, j.notified_at,"
        " j.first_seen, j.group_key, j.id, a.status, a.updated_at, a.applied_at,"
        " a.reminded_at,"
        " f.vote, d.deadline, d.next_action, d.next_action_date, d.interviews"
        " FROM jobs j"
        " LEFT JOIN applications a ON a.job_id = j.id"
        " LEFT JOIN feedback f ON f.job_id = j.id"
        " LEFT JOIN application_details d ON d.job_id = j.id"
        " WHERE a.status IS NOT NULL"
        " OR ((f.vote = 1 OR j.notified_at >= ?) AND j.score IS NOT NULL)",
        (recent,),
    ).fetchall()
    columns: dict[str, list[BoardCard]] = {key: [] for key, _ in COLUMNS}
    # A posting listed in several places is one card (its best-scored copy);
    # a group with a tracked copy is not "to apply" any more.
    tracked = {row["group_key"] or row["id"] for row in rows if row["status"]}
    seen: set[str] = set()
    rows = sorted(rows, key=lambda r: -(r["score"] or 0))
    for row in rows:
        status = row["status"]
        column = "to_apply" if status is None else COLUMN_OF.get(status)
        if column is None:  # dismissed
            continue
        group = row["group_key"] or row["id"]
        if column == "to_apply":
            if group in tracked or group in seen:
                continue
            seen.add(group)
        deadline, action, action_date, interviews = _details(row)
        since = row["updated_at"] if status else row["notified_at"] or row["first_seen"]
        columns[column].append(
            BoardCard(
                ref=row["ref"],
                company=row["company"],
                title=row["title"],
                score=row["score"],
                status=status,
                since=(since or "")[:10],
                deadline=deadline,
                next_action=action,
                next_action_date=action_date,
                interviews=interviews,
                reminder_due=status == "applied"
                and row["reminded_at"] is None
                and row["updated_at"] <= due_before,
                liked=row["vote"] == 1,
            )
        )
    for key, cards in columns.items():
        if key == "to_apply":
            cards.sort(key=lambda c: (c.deadline or "9999", -(c.score or 0)))
        else:
            cards.sort(key=lambda c: (not c.reminder_due, c.since), reverse=False)
    return columns


def calendar(
    db: sqlite3.Connection, now: datetime, reminder_days: int, days: int = 60
) -> list[Event]:
    """Upcoming interviews, deadlines, next actions and reminders, soonest first."""
    today = now.date().isoformat()
    until = (now + timedelta(days=days)).date().isoformat() + "T99"
    rows = db.execute(
        "SELECT j.rowid AS ref, j.company, j.title, a.status, a.updated_at,"
        " a.reminded_at, d.deadline, d.next_action, d.next_action_date, d.interviews"
        " FROM jobs j LEFT JOIN applications a ON a.job_id = j.id"
        " LEFT JOIN application_details d ON d.job_id = j.id"
        " WHERE d.job_id IS NOT NULL OR a.status = 'applied'"
    ).fetchall()
    events: list[Event] = []
    for row in rows:
        closed = row["status"] in ("rejected", "offer", "dismissed")
        base = (row["ref"], row["company"], row["title"])
        if row["interviews"]:
            for when in json.loads(row["interviews"]):
                events.append(Event(when, "interview", *base))
        if row["deadline"] and not closed and row["status"] is None:
            events.append(Event(row["deadline"], "deadline", *base))
        if row["next_action_date"] and not closed:
            events.append(
                Event(row["next_action_date"], "action", *base, row["next_action"])
            )
        if row["status"] == "applied" and row["reminded_at"] is None:
            due = datetime.fromisoformat(row["updated_at"]) + timedelta(
                days=reminder_days
            )
            events.append(Event(max(due.date().isoformat(), today), "reminder", *base))
    upcoming = [ev for ev in events if today <= ev.when <= until]
    return sorted(upcoming, key=lambda ev: (ev.when, ev.kind, ev.company))


# --- skills insights -------------------------------------------------------------

TREND_WEEKS = 6


@dataclass(frozen=True)
class SkillDemand:
    name: str
    category: str
    offers: int  # relevant posting groups asking for it
    share: float  # of the relevant posting groups
    covered: bool  # the candidate profile shows it
    examples: tuple[tuple[int, str, str], ...]  # (ref, company, title), best first
    trend: tuple[int, ...]  # offers per week, oldest first (TREND_WEEKS weeks)


def _distinct_companies(rows: list[sqlite3.Row], limit: int = 3):
    """Best-scored offers from different companies, as (ref, company, title)."""
    seen: dict[str, tuple[int, str, str]] = {}
    for row in rows:
        if row["company"] not in seen:
            seen[row["company"]] = (row["ref"], row["company"], row["title"])
        if len(seen) == limit:
            break
    return tuple(seen.values())


def skill_demand(
    db: sqlite3.Connection,
    profile_text: str,
    now: datetime,
    min_relevance: int = 7,
    days: int = 90,
) -> tuple[list[SkillDemand], int]:
    """Skills asked for by relevant offers, most requested first, and the
    number of relevant posting groups they were counted on."""
    since = (now - timedelta(days=days)).isoformat()
    rows = db.execute(
        "SELECT rowid AS ref, id, company, title, description, first_seen,"
        " group_key, score FROM jobs WHERE status = 'scored' AND score IS NOT NULL"
        " AND json_extract(assessment, '$.ai_relevance') >= ? AND first_seen >= ?"
        " ORDER BY score DESC",
        (min_relevance, since),
    ).fetchall()
    week_start = (now - timedelta(days=7 * TREND_WEEKS)).isoformat()
    counts: dict[str, list[sqlite3.Row]] = {}
    groups: set[str] = set()
    for row in rows:
        group = row["group_key"] or row["id"]
        if group in groups:
            continue  # the same posting elsewhere counts once
        groups.add(group)
        text = f"{row['title']}\n{clean_description(row['description'])}"
        for name in find_skills(text):
            counts.setdefault(name, []).append(row)
    covered = find_skills(profile_text)
    result = []
    for name, matched in counts.items():
        trend = [0] * TREND_WEEKS
        for row in matched:
            if row["first_seen"] >= week_start:
                age = (now - datetime.fromisoformat(row["first_seen"])).days // 7
                trend[TREND_WEEKS - 1 - min(age, TREND_WEEKS - 1)] += 1
        result.append(
            SkillDemand(
                name=name,
                category=BY_NAME[name].category,
                offers=len(matched),
                share=len(matched) / len(groups),
                covered=name in covered,
                examples=_distinct_companies(matched),
                trend=tuple(trend),
            )
        )
    result.sort(key=lambda s: (-s.offers, s.name))
    return result, len(groups)


# --- companies -------------------------------------------------------------------


@dataclass(frozen=True)
class CompanyRow:
    name: str
    tier: str
    source: str
    seen: int  # offers ever collected
    open: int  # posting groups currently in the offers list
    applications: int  # tracked applications (dismissed excluded)
    best: float | None  # best score of the open offers
    last_new: str | None  # date of the last new offer
    failing_since: str | None
    error: str | None
    watched: bool  # in companies.yaml (otherwise found by discovery)


def companies(
    db: sqlite3.Connection,
    watched: Sequence[tuple[str, str, str]],
    today: date,
    min_score: float = 5.5,
    days: int = 60,
) -> list[CompanyRow]:
    """Every watched or seen company, those with open offers first.

    `watched` lists (name, tier, source) from the configuration.
    """
    health = {
        row["company"]: (row["first_failure"], row["last_error"])
        for row in db.execute("SELECT * FROM source_health")
    }
    seen = {
        row["company"]: row
        for row in db.execute(
            "SELECT company, max(tier) AS tier, max(source) AS source, count(*) AS n,"
            " max(first_seen) AS last FROM jobs GROUP BY company"
        )
    }
    tracked = {
        row["company"]: row["n"]
        for row in db.execute(
            "SELECT j.company, count(*) AS n FROM applications a JOIN jobs j"
            " ON j.id = a.job_id WHERE a.status != 'dismissed' GROUP BY j.company"
        )
    }
    open_offers: dict[str, list[OfferRow]] = {}
    for row in matching_offers(db, OfferFilters(min_score=min_score, days=days), today):
        open_offers.setdefault(row.company, []).append(row)
    configured = {name: (tier, source) for name, tier, source in watched}
    result = []
    for name in sorted(set(configured) | set(seen)):
        row = seen.get(name)
        tier, source = configured.get(name) or (row["tier"], row["source"])
        offers = open_offers.get(name, [])
        failing_since, error = health.get(name, (None, None))
        result.append(
            CompanyRow(
                name=name,
                tier=tier,
                source=source,
                seen=row["n"] if row else 0,
                open=len(offers),
                applications=tracked.get(name, 0),
                best=max((o.score for o in offers), default=None),
                last_new=row["last"][:10] if row else None,
                failing_since=failing_since,
                error=error,
                watched=name in configured,
            )
        )
    result.sort(key=lambda c: (-c.open, -(c.best or 0), -c.seen, c.name))
    return result


@dataclass(frozen=True)
class CompanyDetail:
    company: CompanyRow
    weekly: list[tuple[str, int]]  # (week start, offers first seen), oldest first
    offers: list[OfferRow]  # open offers, best first
    applications: list[tuple[int, str, str, str]]  # (ref, title, status, updated)


def company_detail(
    db: sqlite3.Connection,
    name: str,
    watched: Sequence[tuple[str, str, str]],
    now: datetime,
    min_score: float = 5.5,
    days: int = 60,
    weeks: int = 12,
) -> CompanyDetail | None:
    row = next(
        (
            c
            for c in companies(db, watched, now.date(), min_score, days)
            if c.name == name
        ),
        None,
    )
    if row is None:
        return None
    start = now.date() - timedelta(days=now.date().weekday() + 7 * (weeks - 1))
    counts = {
        r["week"]: r["n"]
        for r in db.execute(
            "SELECT date(first_seen, '-6 days', 'weekday 1') AS week, count(*) AS n"
            " FROM jobs WHERE company = ? AND first_seen >= ? GROUP BY week",
            (name, start.isoformat()),
        )
    }
    weekly = []
    for i in range(weeks):
        week = (start + timedelta(days=7 * i)).isoformat()
        weekly.append((week, counts.get(week, 0)))
    offers = [
        o
        for o in matching_offers(
            db, OfferFilters(min_score=min_score, days=days, q=name), now.date()
        )
        if o.company == name
    ]
    applications = [
        (r["ref"], r["title"], r["status"], r["updated_at"][:10])
        for r in db.execute(
            "SELECT j.rowid AS ref, j.title, a.status, a.updated_at FROM applications a"
            " JOIN jobs j ON j.id = a.job_id WHERE j.company = ?"
            " AND a.status != 'dismissed' ORDER BY a.updated_at DESC",
            (name,),
        )
    ]
    return CompanyDetail(row, weekly, offers, applications)


# --- runs ------------------------------------------------------------------------

STEP_LABELS = {
    "collect": "Collecte",
    "score": "Notation",
    "notify": "Notifications",
    "searches": "Recherches",
}


@dataclass(frozen=True)
class RunRow:
    started_at: str
    duration: float
    counters: dict[str, int]
    errors: list[str]
    timings: dict[str, float]
    crash: str | None


@dataclass(frozen=True)
class RunSummary:
    runs: list[RunRow]  # latest first
    median: float | None  # seconds
    steps: list[tuple[str, float]]  # average seconds per step, slowest first
    failing: list[tuple[str, int, str]]  # (source, runs failed, last error)


def runs(db: sqlite3.Connection, limit: int = 30) -> RunSummary:
    rows = [
        RunRow(
            r["started_at"],
            r["duration"],
            json.loads(r["counters"]),
            json.loads(r["errors"]),
            json.loads(r["timings"]),
            r["crash"],
        )
        for r in db.execute(
            "SELECT * FROM runs ORDER BY started_at DESC, id DESC LIMIT ?", (limit,)
        )
    ]
    durations = sorted(r.duration for r in rows)
    median = durations[len(durations) // 2] if durations else None
    totals: dict[str, list[float]] = {}
    failing: dict[str, tuple[int, str]] = {}
    for run in rows:
        for step, seconds in run.timings.items():
            totals.setdefault(step, []).append(seconds)
        for error in run.errors:
            source, _, message = error.partition(": ")
            if source in ("LLM", "saved searches") or not message:
                continue
            count, last = failing.get(source, (0, message))
            failing[source] = (count + 1, last)  # rows are latest first
    steps = sorted(
        ((step, sum(v) / len(v)) for step, v in totals.items()), key=lambda s: -s[1]
    )
    worst = sorted(failing.items(), key=lambda f: (-f[1][0], f[0]))
    return RunSummary(rows, median, steps, [(s, n, m) for s, (n, m) in worst])


# --- chance calibration ----------------------------------------------------------

CHANCE_BUCKETS = ((0, 5), (5, 10), (10, 20), (20, 40), (40, 101))
MIN_DECIDED = 5  # concluded applications needed before showing rates
REACHED = ("interview", "offer")
CONCLUDED = ("interview", "offer", "rejected", "no_answer")


@dataclass(frozen=True)
class CalibrationRow:
    label: str  # chance bucket ("5–10 %") or company type
    decided: int
    interviews: int
    predicted: float  # mean announced chance, in %

    @property
    def observed(self) -> float:
        return 100 * self.interviews / self.decided if self.decided else 0.0


@dataclass(frozen=True)
class Calibration:
    decided: int
    pending: int  # applied with a chance, no outcome yet
    buckets: list[CalibrationRow]
    tiers: list[CalibrationRow]


def calibration(db: sqlite3.Connection) -> Calibration:
    """Announced interview chance versus outcomes of concluded applications.

    An application reached the interview when it is, or ever was, at the
    interview or offer stage (a rejection after an interview still counts).
    """
    rows = db.execute(
        "SELECT j.tier, c.percent, a.status,"
        " EXISTS (SELECT 1 FROM application_events ev WHERE ev.job_id = a.job_id"
        " AND ev.status IN ('interview', 'offer')) AS reached"
        " FROM applications a JOIN chances c ON c.job_id = a.job_id"
        " JOIN jobs j ON j.id = a.job_id"
        " WHERE a.status NOT IN ('dismissed')"
    ).fetchall()
    decided = [
        (r["tier"], r["percent"], bool(r["reached"]) or r["status"] in REACHED)
        for r in rows
        if r["status"] in CONCLUDED
    ]
    pending = sum(1 for r in rows if r["status"] == "applied")

    def summarise(label: str, group: list[tuple[str, int, bool]]) -> CalibrationRow:
        return CalibrationRow(
            label,
            len(group),
            sum(1 for _, _, reached in group if reached),
            sum(p for _, p, _ in group) / len(group) if group else 0.0,
        )

    buckets = [
        summarise(
            f"{low}–{high} %" if high <= 100 else f"{low} % et plus",
            [d for d in decided if low <= d[1] < high],
        )
        for low, high in CHANCE_BUCKETS
    ]
    tiers = [
        summarise(tier, [d for d in decided if d[0] == tier])
        for tier in ("S", "A", "B", "unlisted")
    ]
    return Calibration(
        len(decided),
        pending,
        [b for b in buckets if b.decided],
        [t for t in tiers if t.decided],
    )


# --- applications export ---------------------------------------------------------

EXPORT_HEADER = (
    "Entreprise", "Poste", "Lieu", "Statut", "Mis à jour", "Candidature envoyée",
    "Date limite", "Entretiens", "Prochaine action", "Pour le", "Contact",
    "E-mail du contact", "Notes", "Score", "Chance (%)", "Lien",
)  # fmt: skip


def applications_export(db: sqlite3.Connection) -> list[tuple[str, ...]]:
    """One row per tracked application (dismissed offers excluded), latest first."""
    rows = db.execute(
        "SELECT j.company, j.title, j.location, j.url, j.score, a.status,"
        " a.updated_at, a.applied_at, c.percent, d.deadline, d.interviews,"
        " d.next_action, d.next_action_date, d.contact_name, d.contact_email,"
        " d.notes FROM applications a JOIN jobs j ON j.id = a.job_id"
        " LEFT JOIN chances c ON c.job_id = a.job_id"
        " LEFT JOIN application_details d ON d.job_id = a.job_id"
        " WHERE a.status != 'dismissed' ORDER BY a.updated_at DESC"
    )
    return [
        (
            r["company"],
            r["title"],
            r["location"],
            STATUS_TEXT.get(r["status"], r["status"]),
            r["updated_at"][:10],
            (r["applied_at"] or "")[:10],
            r["deadline"] or "",
            " ; ".join(
                w.replace("T", " ") for w in json.loads(r["interviews"] or "[]")
            ),
            r["next_action"] or "",
            r["next_action_date"] or "",
            r["contact_name"] or "",
            r["contact_email"] or "",
            r["notes"] or "",
            f"{r['score']:.1f}" if r["score"] is not None else "",
            str(r["percent"]) if r["percent"] is not None else "",
            r["url"],
        )
        for r in rows
    ]
