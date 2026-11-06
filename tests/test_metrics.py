from datetime import UTC, date, datetime, timedelta

import pytest

from intern_radar.metrics import collect, percentile, render_markdown, render_svg
from intern_radar.store import Store
from tests.factories import make_job

START = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
USAGE = {"model": "haiku", "input": 1000, "output": 200, "cost": 0.07, "seconds": 30.0}


def counters(new: int, candidates: int, notified: int = 0) -> dict[str, int]:
    return {"fetched": new, "new": new, "candidates": candidates, "notified": notified}


def make_store(tmp_path) -> Store:
    store = Store(str(tmp_path / "radar.db"))
    store.record_run(START, 100.0, counters(20, 5), [], {"collect": 80.0}, None)
    store.record_run(
        START + timedelta(hours=2), 300.0, counters(10, 5, 1), [], {"collect": 200.0},
        None,
    )  # fmt: skip
    store.record_run(START + timedelta(days=1), 50.0, counters(0, 0), [], {}, None)
    store.record_llm_usage("scoring", USAGE, START)
    store.record_llm_usage("letter", {**USAGE, "model": "sonnet"}, START)
    return store


def test_percentile_uses_the_nearest_rank():
    assert percentile([1, 2, 3, 4], 50) == 2
    assert percentile([1, 2, 3, 4], 95) == 4
    assert percentile([], 50) is None


def test_daily_counts_offers_rules_and_tokens(tmp_path):
    store = make_store(tmp_path)
    report = collect(str(tmp_path / "radar.db"), date(2026, 10, 1), date(2026, 10, 2))
    store.close()
    first, second = report.days
    assert (first.day, first.runs, first.new, first.to_llm) == (
        date(2026, 10, 1), 2, 30, 10,
    )  # fmt: skip
    assert first.removed_by_rules == pytest.approx(2 / 3)
    assert (first.tokens, first.cost) == (2400, 0.14)
    assert (second.runs, second.new, second.removed_by_rules) == (1, 0, None)


def test_latency_percentiles_cover_every_run(tmp_path):
    make_store(tmp_path).close()
    report = collect(str(tmp_path / "radar.db"), date(2026, 10, 1), date(2026, 10, 2))
    assert (report.run_p50, report.run_p95) == (100.0, 300.0)
    assert report.stage_p50 == {"collect": 80.0}


def test_detection_to_notification_delay(tmp_path):
    store = make_store(tmp_path)
    store.add(make_job(id="a"), "pending", START)
    store.mark_notified("a", START + timedelta(minutes=30))
    store.close()
    report = collect(str(tmp_path / "radar.db"), date(2026, 10, 1), date(2026, 10, 2))
    assert report.notify_p50 == 1800.0


def test_markdown_names_the_period_and_the_command(tmp_path):
    make_store(tmp_path).close()
    report = collect(str(tmp_path / "radar.db"), date(2026, 10, 1), date(2026, 10, 2))
    text = render_markdown(report)
    assert "2026-10-01 to 2026-10-02" in text
    assert "intern-radar metrics" in text
    assert "| 2026-10-01 | 2 | 30 | 10 | 67 % |" in text
    assert "scoring" in text and "letter" in text


def test_chart_draws_one_bar_pair_per_day_and_the_notified_offers(tmp_path):
    make_store(tmp_path).close()
    report = collect(str(tmp_path / "radar.db"), date(2026, 10, 1), date(2026, 10, 2))
    svg = render_svg(report)
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    assert "2026-10-01: 10 sent to the LLM" in svg
    assert "2026-10-01: 20 removed by the rules" in svg
    assert "2026-10-01: 1 notified" in svg
    assert "2026-10-02:" not in svg  # no posting that day: no bar


def test_chart_of_an_empty_period_is_still_valid_svg(tmp_path):
    make_store(tmp_path).close()
    report = collect(str(tmp_path / "radar.db"), date(2026, 9, 1), date(2026, 9, 3))
    svg = render_svg(report)
    assert "sent to the LLM</title>" not in svg
    assert svg.count("<line") == 6  # 0 to 10 in steps of 2
