import threading
from datetime import UTC, datetime
from pathlib import Path

from intern_radar.dashboard.app import Request
from intern_radar.dashboard.routes import Context, build_app
from intern_radar.dashboard.worker import DONE, FAILED, Services, Worker
from intern_radar.store import Store
from tests.factories import make_assessment, make_job

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
HEADERS = {"host": "radar", "origin": "http://radar"}


def make_db(tmp_path) -> tuple[str, int]:
    path = str(tmp_path / "web.db")
    store = Store(path)
    store.add(make_job(id="j1", company="Acme", title="ML Intern"), "pending", NOW)
    store.save_assessment("j1", make_assessment(), 8.0)
    ref = store.job_ref("j1")
    store.close()
    return path, ref


def post(app, path, **form):
    return app.handle(Request("POST", path, {}, form, HEADERS))


def recording_services(calls, gate=None, letter_ok=True):
    def letter(job_id):
        if gate is not None:
            gate.wait(5)
        calls.append(("letter", job_id))
        return Path("letter.pdf") if letter_ok else None

    def promote(ref):
        calls.append(("telegram", ref))
        return True

    return Services(letter=letter, promote=promote, resume=None)


def test_status_changes_follow_the_state_machine(tmp_path):
    path, ref = make_db(tmp_path)
    app = build_app(Context(path, clock=lambda: NOW))
    page = app.handle(Request("GET", f"/offers/{ref}", {})).body.decode()
    assert "✅ Postulé" in page and "🙈 Pas intéressé" in page
    response = post(app, f"/offers/{ref}/status", status="interview")
    assert response.headers == (("Location", f"/offers/{ref}?done=refused"),)
    response = post(app, f"/offers/{ref}/status", status="applied")
    assert response.headers == (("Location", f"/offers/{ref}?done=status"),)
    store = Store(path)
    assert store.application_status("j1") == "applied"
    store.close()
    page = app.handle(Request("GET", f"/offers/{ref}", {"done": "status"}))
    body = page.body.decode()
    assert "Statut mis à jour." in body and "🗣 Entretien" in body
    assert "✅ Postulé" not in body


def test_dismissed_offers_leave_the_default_list(tmp_path):
    path, ref = make_db(tmp_path)
    app = build_app(Context(path, clock=lambda: NOW))
    assert "Acme" in app.handle(Request("GET", "/offers", {})).body.decode()
    post(app, f"/offers/{ref}/status", status="dismissed")
    assert "Acme" not in app.handle(Request("GET", "/offers", {})).body.decode()


def test_actions_require_same_origin(tmp_path):
    path, ref = make_db(tmp_path)
    app = build_app(Context(path, clock=lambda: NOW))
    foreign = {"host": "radar", "origin": "http://evil"}
    request = Request("POST", f"/offers/{ref}/status", {}, {"status": "applied"})
    assert app.handle(request).status == 403
    request = Request("POST", f"/offers/{ref}/letter", {}, {}, foreign)
    assert app.handle(request).status == 403


def test_documents_are_generated_in_the_background(tmp_path):
    path, ref = make_db(tmp_path)
    calls, gate = [], threading.Event()
    worker = Worker(lambda: recording_services(calls, gate))
    app = build_app(Context(path, clock=lambda: NOW, worker=worker))
    response = post(app, f"/offers/{ref}/letter")
    assert response.headers == (("Location", f"/offers/{ref}?done=queued"),)
    # A second tap while the first runs is not queued twice.
    again = post(app, f"/offers/{ref}/letter")
    assert again.headers == (("Location", f"/offers/{ref}?done=already"),)
    page = app.handle(Request("GET", f"/offers/{ref}", {})).body.decode()
    assert 'http-equiv="refresh"' in page and "en cours" in page
    gate.set()
    worker.wait()
    assert calls == [("letter", "j1")]
    assert worker.state("letter", ref).state == DONE
    post(app, f"/offers/{ref}/telegram")
    worker.wait()
    assert calls[-1] == ("telegram", ref)


def test_failed_tasks_are_reported(tmp_path):
    path, ref = make_db(tmp_path)
    worker = Worker(lambda: recording_services([], letter_ok=False))
    app = build_app(Context(path, clock=lambda: NOW, worker=worker))
    post(app, f"/offers/{ref}/letter")
    post(app, f"/offers/{ref}/cv")  # no candidate profile: resume is None
    worker.wait()
    assert worker.state("letter", ref).state == FAILED
    cv = worker.state("cv", ref)
    assert cv.state == FAILED and "non configuré" in cv.error
    page = app.handle(Request("GET", f"/offers/{ref}", {})).body.decode()
    assert "échec" in page and 'http-equiv="refresh"' not in page


def test_services_that_cannot_be_built_fail_the_task(tmp_path):
    path, ref = make_db(tmp_path)

    def broken():
        raise RuntimeError("profile.yaml: set cv_url")

    worker = Worker(broken)
    app = build_app(Context(path, clock=lambda: NOW, worker=worker))
    post(app, f"/offers/{ref}/letter")
    worker.wait()
    assert worker.state("letter", ref).error == "profile.yaml: set cv_url"


def test_without_worker_actions_are_unavailable(tmp_path):
    path, ref = make_db(tmp_path)
    app = build_app(Context(path, clock=lambda: NOW))
    response = post(app, f"/offers/{ref}/cv")
    assert response.headers == (("Location", f"/offers/{ref}?done=unavailable"),)
    assert post(app, f"/offers/{ref}/unknown").status == 404
    assert post(app, "/offers/999/letter").status == 303  # unavailable first
