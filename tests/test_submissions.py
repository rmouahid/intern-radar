import csv
import io
from datetime import UTC, datetime, timedelta

from intern_radar.dashboard import queries
from intern_radar.dashboard.app import Request
from intern_radar.dashboard.routes import Context, build_app
from intern_radar.store import Store
from tests.factories import make_assessment, make_job
from tests.test_kit import CONTACT, PROFILE

NOW = datetime(2026, 10, 2, 9, tzinfo=UTC)
HEADERS = {"host": "radar", "origin": "http://radar"}


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


def make_site(tmp_path):
    db = str(tmp_path / "s.db")
    data = tmp_path / "data"
    (data / "cvs").mkdir(parents=True)
    cv = data / "cvs" / "Alex_Martin_CV.pdf"
    cv.write_bytes(b"%PDF v1")
    store = Store(db)
    store.add(make_job(id="j1", company="Acme", title="ML Intern"), "pending", NOW)
    store.save_assessment("j1", make_assessment(work_authorisation="free"), 8.0)
    store.save_resume("j1", str(cv), {}, NOW)
    store.save_why("j1", "Because retrieval.", [], NOW)
    ref = store.job_ref("j1")
    store.close()
    clock = Clock()
    app = build_app(Context(db, clock=clock, profile=PROFILE, data_dir=data))
    return app, ref, db, cv, clock


def post(app, path, **form):
    return app.handle(Request("POST", path, {}, form, HEADERS))


def test_submit_records_a_frozen_snapshot_and_sets_applied(tmp_path):
    app, ref, db, cv, clock = make_site(tmp_path)
    response = post(app, f"/offers/{ref}/submit", lang="en")
    assert response.headers == (("Location", f"/offers/{ref}?done=submitted#kit"),)
    store = Store(db)
    assert store.application_status("j1") == "applied"
    (sent,) = store.submissions("j1")
    store.close()
    assert sent.why == "Because retrieval." and set(sent.files) == {"cv"}
    assert ("Full name", CONTACT.name) in sent.answers
    assert any(q.startswith("Are you legally") for q, _ in sent.answers)
    cv.write_bytes(b"%PDF v2")  # a later regeneration does not change the copy
    frozen = app.handle(Request("GET", f"/files/submission/{sent.id}/cv", {}))
    assert frozen.status == 200 and frozen.body == b"%PDF v1"
    assert (
        app.handle(Request("GET", f"/files/submission/{sent.id}/letter", {})).status
        == 404
    )
    page = app.handle(Request("GET", f"/submissions/{sent.id}", {})).body.decode()
    assert "Candidature envoyée" in page and "Because retrieval." in page
    assert CONTACT.name in page
    offer = app.handle(Request("GET", f"/offers/{ref}", {})).body.decode()
    assert f'href="/submissions/{sent.id}"' in offer and "Envois archivés" in offer


def test_a_second_submission_keeps_the_status_and_both_snapshots(tmp_path):
    app, ref, db, _, clock = make_site(tmp_path)
    post(app, f"/offers/{ref}/submit")
    store = Store(db)
    store.set_application("j1", "interview", NOW)
    store.close()
    clock.now = NOW + timedelta(days=1)
    post(app, f"/offers/{ref}/submit", lang="fr")
    store = Store(db)
    assert store.application_status("j1") == "interview"
    latest, first = store.submissions("j1")
    store.close()
    assert latest.at > first.at and latest.files["cv"] != first.files["cv"]
    assert ("Nom complet", CONTACT.name) in latest.answers


def test_board_and_export_show_the_submission(tmp_path):
    app, ref, db, _, _ = make_site(tmp_path)
    post(app, f"/offers/{ref}/submit")
    columns = queries.board(queries.connect(db), NOW, reminder_days=14)
    (card,) = columns["applied"]
    assert card.submitted_at.startswith("2026-10-02")
    board = app.handle(Request("GET", "/applications", {})).body.decode()
    assert "📎 envoyée le 2026-10-02" in board and f'href="/offers/{ref}#kit"' in board
    export = app.handle(Request("GET", "/applications.csv", {})).body
    header, row = list(csv.reader(io.StringIO(export.decode("utf-8-sig"))))
    by = dict(zip(header, row, strict=True))
    assert by["Envoyée le (kit)"] == "2026-10-02" and by["Documents envoyés"] == "CV"


def test_submission_routes_reject_unknown_and_foreign_requests(tmp_path):
    app, ref, _, _, _ = make_site(tmp_path)
    assert post(app, "/offers/999/submit").status == 404
    assert app.handle(Request("GET", "/submissions/42", {})).status == 404
    assert app.handle(Request("GET", "/files/submission/42/cv", {})).status == 404
    foreign = Request("POST", f"/offers/{ref}/submit", {}, {})
    assert app.handle(foreign).status == 403
