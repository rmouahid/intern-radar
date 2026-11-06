"""Operating metrics computed from the production database (`intern-radar metrics`).

Everything comes from tables the pipeline already fills: `runs` (one row per
run, with its counters and step timings), `llm_usage` (one row per LLM call)
and `jobs` (detection and notification times). Days are Europe/Paris days.
"""

import json
import math
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")


def percentile(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile, None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(math.ceil(pct / 100 * len(ordered)), 1) - 1]


@dataclass
class Day:
    day: date
    runs: int = 0
    new: int = 0  # new internship postings stored
    to_llm: int = 0  # kept by the rules and queued for LLM triage
    notified: int = 0
    tokens: int = 0  # input + output, every LLM purpose
    cost: float = 0.0  # API-equivalent USD

    @property
    def removed_by_rules(self) -> float | None:
        return 1 - self.to_llm / self.new if self.new else None


@dataclass
class Report:
    start: date
    end: date
    days: list[Day]
    run_p50: float | None
    run_p95: float | None
    stage_p50: dict[str, float]
    notify_p50: float | None  # seconds from detection to notification
    notify_p95: float | None
    by_purpose: dict[str, tuple[int, int, float]] = field(default_factory=dict)


def _paris_day(stamp: str) -> date:
    return datetime.fromisoformat(stamp).astimezone(PARIS).date()


def collect(db_path: str, start: date, end: date) -> Report:
    """Metrics for the Paris days `start` to `end` included."""
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        days = {start + timedelta(n): Day(start + timedelta(n))
                for n in range((end - start).days + 1)}  # fmt: skip
        durations: list[float] = []
        stages: dict[str, list[float]] = defaultdict(list)
        for started, duration, counters, timings in db.execute(
            "SELECT started_at, duration, counters, timings FROM runs"
        ):
            day = days.get(_paris_day(started))
            if day is None:
                continue
            counts = json.loads(counters)
            day.runs += 1
            day.new += counts.get("new", 0)
            day.to_llm += counts.get("candidates", 0)
            day.notified += counts.get("notified", 0)
            durations.append(duration)
            for stage, seconds in json.loads(timings).items():
                stages[stage].append(seconds)
        purposes: dict[str, list[float]] = defaultdict(lambda: [0, 0, 0.0])
        for at, purpose, tokens_in, tokens_out, cost in db.execute(
            "SELECT at, purpose, input, output, cost FROM llm_usage"
        ):
            day = days.get(_paris_day(at))
            if day is None:
                continue
            day.tokens += tokens_in + tokens_out
            day.cost = round(day.cost + cost, 6)
            totals = purposes[purpose]
            totals[0] += tokens_in
            totals[1] += tokens_out
            totals[2] += cost
        delays = [
            (
                datetime.fromisoformat(sent) - datetime.fromisoformat(seen)
            ).total_seconds()
            for seen, sent in db.execute(
                "SELECT first_seen, notified_at FROM jobs WHERE notified_at IS NOT NULL"
            )
            if start <= _paris_day(seen) <= end
        ]
    finally:
        db.close()
    return Report(
        start,
        end,
        list(days.values()),
        percentile(durations, 50),
        percentile(durations, 95),
        {stage: _median(values) for stage, values in stages.items()},
        percentile(delays, 50),
        percentile(delays, 95),
        {name: (int(t[0]), int(t[1]), t[2]) for name, t in sorted(purposes.items())},
    )


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.0%}".replace("%", " %")


def _duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    if seconds < 120:
        return f"{seconds:.0f} s"
    if seconds < 7200:
        return f"{seconds / 60:.0f} min"
    return f"{seconds / 3600:.1f} h"


def _median(values: list[float]) -> float:
    return percentile(values, 50) or 0


def render_markdown(report: Report) -> str:
    """The report committed as docs/metrics.md."""
    active = [d for d in report.days if d.runs]
    new = sum(d.new for d in active)
    to_llm = sum(d.to_llm for d in active)
    lines = [
        "# Operating metrics",
        "",
        f"Production database, {report.start} to {report.end} (Europe/Paris days),"
        f" {len(active)} days with at least one run. Regenerate with:",
        "",
        "```bash",
        "poetry run intern-radar metrics --out docs/metrics.md"
        f" --start {report.start} --end {report.end}",
        "```",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    removed = _pct(1 - to_llm / new if new else None)
    summary = [
        ("New internship postings per day (median)",
         f"{_median([d.new for d in active]):.0f}"),
        ("Removed by the rules before the LLM", f"{removed} of {new}"),
        ("LLM tokens per day (median, every purpose)",
         f"{_median([d.tokens for d in report.days]):,.0f}"),
        ("LLM cost per day (median, API-equivalent)",
         f"${_median([d.cost for d in report.days]):.2f}"),
        ("Run duration p50 / p95",
         f"{_duration(report.run_p50)} / {_duration(report.run_p95)}"),
        ("Detection to Telegram notification p50 / p95",
         f"{_duration(report.notify_p50)} / {_duration(report.notify_p95)}"),
    ]  # fmt: skip
    lines += [f"| {name} | {value} |" for name, value in summary]
    lines += [
        "",
        "Rules run before any LLM call: internship-title regex, France-only"
        " locations, out-of-scope fields, past cycles, offers older than the age"
        " limit, aggregator copies of postings already stored.",
        "",
        "## Per day",
        "",
        "| Day | Runs | New postings | Sent to the LLM | Removed by rules"
        " | Notified | LLM tokens | LLM cost |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]  # fmt: skip
    lines += [
        f"| {d.day} | {d.runs} | {d.new} | {d.to_llm} | {_pct(d.removed_by_rules)} |"
        f" {d.notified} | {d.tokens:,} | ${d.cost:.2f} |"
        for d in report.days
    ]
    lines += [
        "",
        "## Run duration per step (p50)",
        "",
        "| Step | p50 |",
        "|---|---:|",
    ]
    lines += [f"| {s} | {_duration(v)} |" for s, v in report.stage_p50.items()]
    lines += [
        "",
        "## LLM usage by purpose",
        "",
        "| Purpose | Input tokens | Output tokens | Cost (API-equivalent) |",
        "|---|---:|---:|---:|",
    ]
    lines += [
        f"| {name} | {tokens_in:,} | {tokens_out:,} | ${cost:.2f} |"
        for name, (tokens_in, tokens_out, cost) in report.by_purpose.items()
    ]
    return "\n".join(lines) + "\n"
