import subprocess
import threading
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from intern_radar.dashboard import queries
from intern_radar.dashboard.server import make_server, render_dashboard, tailscale_ip
from intern_radar.store import Store
from tests.factories import make_assessment, make_job

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
USAGE = {"model": "haiku", "input": 15000, "output": 8000, "cost": 0.05, "seconds": 90}


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "radar.db")
    store = Store(path)
    for job_id, days, score, tier in (
        ("a", 1, 8.0, "S"),
        ("b", 2, 6.0, "B"),
        ("c", 10, None, "A"),
        ("<x>", 3, 2.0, "A"),
    ):
        seen = NOW - timedelta(days=days)
        store.add(
            make_job(id=job_id, company=f"Co {job_id}", tier=tier), "pending", seen
        )
        store.save_assessment(job_id, make_assessment(), score)
    store.add(make_job(id="r", company="Co r"), "rejected", NOW)
    store.mark_notified("a", NOW)
    store.mark_digested(["b"], NOW)
    store.set_application("a", "applied", NOW)
    store.set_application("a", "interview", NOW)
    store.record_source_result("Broken Co", "HTTP 500", NOW - timedelta(days=4))
    store.record_llm_usage("scoring", USAGE, NOW)
    store.record_llm_usage("letter", {**USAGE, "cost": 0.08}, NOW - timedelta(days=30))
    store.close()
    return path


def test_kpis(db_path):
    k = queries.kpis(queries.connect(db_path), NOW)
    assert (k.seen, k.seen_week, k.scored) == (5, 4, 4)
    assert (k.immediate, k.digested, k.applied, k.interviews, k.offers) == (
        1,
        1,
        1,
        1,
        0,
    )
    assert k.llm_cost_week == pytest.approx(0.05)


def test_weekly_funnel_counts_cohorts(db_path):
    weeks = queries.weekly_funnel(queries.connect(db_path), NOW)
    assert len(weeks) == 8 and weeks[0].start.weekday() == 0
    totals = [
        sum(getattr(w, f) for w in weeks)
        for f in ("seen", "passed", "scored", "surfaced", "applied", "interviews")
    ]
    assert totals == [5, 4, 4, 2, 1, 1]


def test_sources_include_failures(db_path):
    rows = queries.sources(queries.connect(db_path))
    assert rows[-1].company == "Broken Co" and rows[-1].last_error == "HTTP 500"
    assert next(r for r in rows if r.company == "Co a").offers == 1


def test_histogram_and_usage(db_path):
    db = queries.connect(db_path)
    bins = dict(queries.score_histogram(db))
    assert len(bins) == 20 and bins[8.0] == 1 and bins[6.0] == 1 and bins[2.0] == 1
    [usage] = queries.llm_usage(db, NOW)
    assert (usage.purpose, usage.calls, usage.tokens_out) == ("scoring", 1, 8000)


def test_connection_is_read_only(db_path):
    import sqlite3

    with pytest.raises(sqlite3.OperationalError):
        queries.connect(db_path).execute("DELETE FROM jobs")


def test_page_renders_every_section_and_escapes(db_path):
    html = render_dashboard(db_path, (5.5, 7.5), NOW)
    for title in (
        "Entonnoir",
        "Répartition des scores",
        "Candidatures",
        "Sources",
        "Usage LLM",
    ):
        assert title in html
    assert "Entretien obtenu" in html and "en échec depuis" in html
    assert "<x>" not in html and "Co &lt;x&gt;" in html
    assert "prefers-color-scheme: dark" in html and "<script" not in html


def test_empty_database_renders(tmp_path):
    path = str(tmp_path / "empty.db")
    Store(path).close()
    html = render_dashboard(path, (5.5, 7.5), NOW)
    assert "Aucune candidature suivie." in html and "Aucun appel enregistré." in html


def test_server_routes(db_path):
    server = make_server(db_path, "127.0.0.1", 0, (5.5, 7.5), clock=lambda: NOW)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        assert httpx.get(f"{base}/healthz").text == "ok"
        home = httpx.get(f"{base}/")
        assert home.status_code == 200 and "intern-radar" in home.text
        assert httpx.get(f"{base}/nope").status_code == 404
    finally:
        server.shutdown()
        server.server_close()


def test_tailscale_ip():
    def ok(*args, **kwargs):
        return subprocess.CompletedProcess(args, 0, "100.1.2.3\n", "")

    def missing(*args, **kwargs):
        raise FileNotFoundError("tailscale")

    assert tailscale_ip(ok) == "100.1.2.3"
    assert tailscale_ip(missing) is None
