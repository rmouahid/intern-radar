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


def test_run_status_and_start_parse_systemd(tmp_path):
    from intern_radar.dashboard.runner import run_status, start_run

    calls = []

    def fake(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:2] == ["systemctl", "show"]:
            out = (
                "ActiveState=inactive\nResult=success\n"
                "ExecMainStartTimestamp=Wed 2026-09-30 18:00:22 UTC\n"
                "ExecMainExitTimestamp=Wed 2026-09-30 18:03:39 UTC\n"
            )
        elif cmd[0] == "journalctl":
            out = "Started\nfetched=5 new=5 scored=3\nFinished\n"
        else:
            out = ""
        return subprocess.CompletedProcess(cmd, 0, out, "")

    status = run_status(fake)
    assert (status.running, status.result, status.summary) == (
        False,
        "success",
        "fetched=5 new=5 scored=3",
    )
    assert status.finished.endswith("18:03:39 UTC")
    assert start_run(fake) is True
    assert calls[-1] == [
        "systemctl",
        "start",
        "--no-block",
        "intern-radar-run.service",
    ]


def serve(db_path, running=False, trigger_ok=True):
    from intern_radar.dashboard.runner import RunStatus

    started = []

    def trigger():
        started.append(True)
        return trigger_ok

    status = RunStatus(running, "success", "Wed 18:00", "Wed 18:03", "fetched=5")
    server = make_server(
        db_path,
        "127.0.0.1",
        0,
        (5.5, 7.5),
        clock=lambda: NOW,
        status=lambda: status,
        trigger=trigger,
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"127.0.0.1:{server.server_address[1]}", started


def test_run_button_starts_a_run_from_the_page(db_path):
    server, host, started = serve(db_path)
    try:
        home = httpx.get(f"http://{host}/")
        assert "<button>Lancer un run</button>" in home.text
        assert "Dernier run ✅ réussi" in home.text and "fetched=5" in home.text
        post = httpx.post(f"http://{host}/run", headers={"Origin": f"http://{host}"})
        assert post.status_code == 303 and post.headers["location"] == "/?run=started"
        assert started == [True]
        notice = httpx.get(f"http://{host}/?run=started")
        assert "Run lancé" in notice.text
    finally:
        server.shutdown()
        server.server_close()


def test_run_button_refuses_foreign_origins_and_busy_runs(db_path):
    server, host, started = serve(db_path, running=True)
    try:
        assert httpx.post(f"http://{host}/run").status_code == 403
        evil = httpx.post(f"http://{host}/run", headers={"Origin": "http://evil.test"})
        assert evil.status_code == 403
        busy = httpx.post(f"http://{host}/run", headers={"Referer": f"http://{host}/"})
        assert busy.headers["location"] == "/?run=busy" and started == []
        page_html = httpx.get(f"http://{host}/").text
        assert "Run en cours" in page_html and "<button disabled>" in page_html
        assert 'http-equiv="refresh"' in page_html
    finally:
        server.shutdown()
        server.server_close()


def test_run_button_reports_systemd_refusal(db_path):
    server, host, _ = serve(db_path, trigger_ok=False)
    try:
        post = httpx.post(f"http://{host}/run", headers={"Origin": f"http://{host}"})
        assert post.headers["location"] == "/?run=error"
    finally:
        server.shutdown()
        server.server_close()
