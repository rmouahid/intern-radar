import io
from datetime import UTC, datetime, timedelta

import pytest
from pypdf import PdfReader

from intern_radar.dashboard.app import Request
from intern_radar.dashboard.routes import Context
from intern_radar.dashboard.routes import build_app as build
from intern_radar.dashboard.worker import Services, Worker
from intern_radar.editing import (
    DocumentEditor,
    EditError,
    letter_from_report,
    letter_to_dict,
    resume_from_dict,
    resume_to_dict,
)
from intern_radar.letters.writer import Letter
from intern_radar.store import Store
from tests.factories import make_profile
from tests.resume.test_resume import CANDIDATE, CONTACT, FakeBackend, answer, service

NOW = datetime(2026, 9, 30, tzinfo=UTC)
LATER = NOW + timedelta(hours=2)
HEADERS = {"host": "radar", "origin": "http://radar"}
LETTER = Letter(
    "en", "Dear Hiring Team,", ("First paragraph.", "Second one."), "Kind regards,"
)


def pdf_text(data: bytes) -> str:
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(data)).pages)


def with_letter(store: Store, tmp_path, report=None):
    path = tmp_path / "letter" / "Alex_Martin_CoverLetter.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"old")
    report = report or {
        "ai_changes": 2,
        "text": LETTER.text(),
        "letter": letter_to_dict(LETTER),
    }
    store.save_letter("j1", str(path), report, NOW)
    return path


def test_letter_structure_round_trips_and_legacy_text_is_parsed():
    assert letter_from_report({"letter": letter_to_dict(LETTER)}) == LETTER
    legacy = letter_from_report({"text": "Madame,\n\nUn.\n\nDeux.\n\nCordialement,"})
    assert legacy == Letter("fr", "Madame,", ("Un.", "Deux."), "Cordialement,")
    with pytest.raises(EditError):
        letter_from_report({"text": "only one block"})


def test_edit_letter_renders_again_and_keeps_the_previous_report(tmp_path):
    svc, store, _, _ = service(tmp_path, FakeBackend(answer()))
    path = with_letter(store, tmp_path)
    editor = DocumentEditor(store, CONTACT)
    editor.edit_letter(
        "j1", "Dear Acme team,", ["New opening.", "  ", "Closing words."],
        "Best regards,", LATER,
    )  # fmt: skip
    saved_path, report = store.letter("j1")
    assert saved_path == str(path)
    text = pdf_text(path.read_bytes())
    assert "Dear Acme team," in text and "New opening." in text
    assert "Best regards," in text and "First paragraph." not in text
    assert report["letter"]["paragraphs"] == ["New opening.", "Closing words."]
    assert report["previous"]["text"] == LETTER.text()
    assert report["ai_changes"] == 2 and report["edited_at"] == LATER.isoformat()
    editor.edit_letter("j1", "Hi,", ["Again."], "Bye,", LATER)
    assert "previous" not in store.letter("j1")[1]["previous"]  # one level only
    with pytest.raises(EditError):
        editor.edit_letter("j1", "Hi,", ["", " "], "Bye,", LATER)


def test_resume_structure_round_trips_against_the_candidate(tmp_path):
    svc, store, _, _ = service(tmp_path, FakeBackend(answer()))
    svc.handle("j1")
    data = store.resume("j1")[1]["resume"]
    resume = resume_from_dict(data, CANDIDATE)
    assert resume_to_dict(resume) == data
    gone = {**data, "projects": [{"id": "deleted", "bullets": ["x"]}]}
    assert resume_from_dict(gone, CANDIDATE).projects == ()


def test_edit_resume_rewrites_bullets_and_summary(tmp_path):
    svc, store, _, _ = service(tmp_path, FakeBackend(answer()))
    path = svc.handle("j1")
    editor = DocumentEditor(store, CONTACT, lambda: CANDIDATE)
    first = editor.resume("j1").items[0][0].id
    editor.edit_resume(
        "j1", "AI engineering student", "Builds retrieval systems.",
        {first: "- Shipped a RAG agent\n\n• Wrote the evaluation suite"}, LATER,
    )  # fmt: skip
    text = pdf_text(path.read_bytes())
    assert "Shipped a RAG agent" in text and "Wrote the evaluation suite" in text
    assert "Builds retrieval systems." in text
    report = store.resume("j1")[1]
    assert report["resume"]["experiences"][0]["bullets"] == [
        "Shipped a RAG agent",
        "Wrote the evaluation suite",
    ]
    assert report["previous"]["items"] == 2


def test_resume_without_structure_or_candidate_cannot_be_edited(tmp_path):
    svc, store, _, _ = service(tmp_path, FakeBackend(answer()))
    store.save_resume("j1", str(tmp_path / "cv.pdf"), {"items": 2}, NOW)
    with pytest.raises(EditError, match="régénère"):
        DocumentEditor(store, CONTACT, lambda: CANDIDATE).resume("j1")
    svc2, store2, _, _ = service(tmp_path / "b", FakeBackend(answer()))
    svc2.handle("j1")
    with pytest.raises(EditError, match="candidate.json"):
        DocumentEditor(store2, CONTACT).resume("j1")


def make_site(tmp_path, worker=None):
    db = str(tmp_path / "site.db")
    store = Store(db)
    from tests.factories import make_assessment, make_job

    store.add(make_job(id="j1", company="Acme", title="ML Intern"), "pending", NOW)
    store.save_assessment("j1", make_assessment(), 8.0)
    ref = store.job_ref("j1")
    path = with_letter(store, tmp_path)
    store.close()
    ctx = Context(
        db, clock=lambda: LATER, profile=make_profile(contact=CONTACT),
        config_dir=tmp_path, worker=worker,
    )  # fmt: skip
    return build(ctx), ref, path, db


def post(app, path, **form):
    return app.handle(Request("POST", path, {}, form, HEADERS))


def test_letter_edit_routes(tmp_path):
    calls = []
    worker = Worker(
        lambda: Services(letter=lambda j: calls.append(j) or tmp_path, promote=bool)
    )
    app, ref, path, db = make_site(tmp_path, worker)
    detail = app.handle(Request("GET", f"/offers/{ref}", {})).body.decode()
    assert f"/offers/{ref}/letter/edit" in detail
    form = app.handle(Request("GET", f"/offers/{ref}/letter/edit", {})).body.decode()
    assert "Dear Hiring Team," in form and 'name="p1"' in form and 'name="p2"' in form
    response = post(
        app, f"/offers/{ref}/letter/edit", greeting="Hello,", p0="Para A.",
        p1="Para B.", p2="", closing="Thanks,", resend="1",
    )  # fmt: skip
    assert response.headers == (("Location", f"/offers/{ref}?done=edited_sent"),)
    worker.wait()
    assert calls == ["j1"]
    assert "Para B." in pdf_text(path.read_bytes())
    response = post(app, f"/offers/{ref}/letter/edit", greeting="", p0="x", closing="y")
    assert response.status == 400


def test_edit_routes_report_what_is_missing(tmp_path):
    app, ref, _, _ = make_site(tmp_path)
    cv = app.handle(Request("GET", f"/offers/{ref}/cv/edit", {}))
    assert cv.status == 404 and "aucun CV" in cv.body.decode()
    assert app.handle(Request("GET", f"/offers/{ref}/other/edit", {})).status == 404
    no_contact = build(Context(str(tmp_path / "site.db")))
    assert (
        no_contact.handle(Request("GET", f"/offers/{ref}/letter/edit", {})).status
        == 404
    )
    request = Request("POST", f"/offers/{ref}/letter/edit", {}, {"greeting": "x"})
    assert app.handle(request).status == 403
