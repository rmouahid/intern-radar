import os
from datetime import UTC, date, datetime

import pytest

from intern_radar.candidate import parse_candidate, save_candidate
from intern_radar.config import Contact
from intern_radar.dashboard.app import Request
from intern_radar.dashboard.routes import Context, build_app
from intern_radar.dashboard.worker import FAILED, Services, Worker
from intern_radar.scorer import LLMError
from intern_radar.store import Store
from intern_radar.why import WhyService, WhyWriter
from tests.factories import make_assessment, make_job, make_profile
from tests.test_candidate import FakeBackend, profile_dict

NOW = datetime(2026, 10, 2, 9, tzinfo=UTC)
HEADERS = {"host": "radar", "origin": "http://radar"}
CONTACT = Contact("Alex Martin", "Paris", "+33 1", "a@x.io", "li/alex", "gh/alex")
PROFILE = make_profile(contact=CONTACT, window_start=date(2027, 3, 8))
CANDIDATE = parse_candidate(profile_dict())
JOB = make_job(
    id="j1", company="Acme", title="ML Intern", location="Berlin, Germany",
    description="Build retrieval systems for Acme's search team.",
)  # fmt: skip


def test_why_writer_flags_unverified_facts_and_cliches():
    backend = FakeBackend(
        {"text": "I built a RAG agent at Acme and I am passionate about Zorblax."}
    )
    text, warnings = WhyWriter(backend, CANDIDATE).write(JOB)
    assert text.startswith("I built a RAG agent")
    assert "À vérifier : Zorblax" in warnings
    prompt = backend.calls[0][0]
    assert "Why do you want to join Acme in this role?" in prompt
    assert "Build retrieval systems" in prompt
    with pytest.raises(LLMError):
        WhyWriter(FakeBackend({"text": " "}), CANDIDATE).write(JOB)


def test_why_service_stores_the_draft():
    store = Store(":memory:")
    store.add(JOB, "pending", NOW)
    service = WhyService(
        store, lambda: WhyWriter(FakeBackend({"text": "Because RAG."}), CANDIDATE),
        lambda: NOW,
    )  # fmt: skip
    assert service.handle("j1") == "Because RAG."
    saved = store.why("j1")
    assert saved.text == "Because RAG." and not saved.edited
    assert service.handle("unknown") is None
    store.save_why("j1", "Mine.", [], NOW, edited=True)
    assert store.why("j1").edited


def make_site(tmp_path, why=None):
    db = str(tmp_path / "k.db")
    store = Store(db)
    store.add(JOB, "pending", NOW)
    store.save_assessment("j1", make_assessment(work_authorisation="free"), 8.0)
    ref = store.job_ref("j1")
    letter = tmp_path / "letter.pdf"
    letter.write_bytes(b"%PDF")
    store.save_letter("j1", str(letter), {}, NOW)
    store.save_answer("salary", "Salary expectations", "1 500 € / month", NOW)
    store.close()
    config = tmp_path / "config"
    config.mkdir()
    save_candidate(CANDIDATE, config / "candidate.json")
    os.utime(letter, (1, 1))  # older than the candidate profile
    worker = Worker(lambda: Services(letter=lambda j: None, promote=bool, why=why))
    ctx = Context(db, clock=lambda: NOW, profile=PROFILE, config_dir=config,
                  worker=worker, data_dir=tmp_path)  # fmt: skip
    return build_app(ctx), ref, worker, db


def get(app, path, **query):
    return app.handle(Request("GET", path, query)).body.decode()


def post(app, path, **form):
    return app.handle(Request("POST", path, {}, form, HEADERS))


def test_kit_on_the_offer_page(tmp_path):
    app, ref, _, _ = make_site(tmp_path)
    page = get(app, f"/offers/{ref}")
    assert '<section id="kit">' in page and "📝 Ouvrir le formulaire" in page
    assert "Alex Martin" in page and "1 500 € / month" in page
    assert "Yes. I am a French (EU) citizen" in page  # offer-dependent answer
    assert "relocate to Berlin, Germany." in page
    assert 'data-copy="kit-0"' in page and "execCommand('copy')" in page
    assert "généré avant la dernière mise à jour du profil" in page  # stale letter
    assert "CV adapté : pas encore généré" in page
    assert "✨ Rédiger un brouillon" in page
    french = get(app, f"/offers/{ref}", lang="fr")
    assert "Êtes-vous autorisé à travailler dans ce pays ?" in french
    assert "Nom complet" in french


def test_why_draft_from_the_kit(tmp_path):
    calls = []

    def why(job_id):
        calls.append(job_id)
        store = Store(str(tmp_path / "k.db"))
        store.save_why(job_id, "Because retrieval.", ["À vérifier : Zorblax"], NOW)
        store.close()
        return "Because retrieval."

    app, ref, worker, db = make_site(tmp_path, why)
    response = post(app, f"/offers/{ref}/why")
    assert response.headers == (("Location", f"/offers/{ref}?done=queued"),)
    worker.wait()
    assert calls == ["j1"]
    page = get(app, f"/offers/{ref}")
    assert "Because retrieval." in page and "À vérifier : Zorblax" in page
    assert 'data-copy="kit-why"' in page and "Régénérer" in page
    saved = post(app, f"/offers/{ref}/why/edit", text="My own words.")
    assert saved.headers == (("Location", f"/offers/{ref}?done=why_saved#kit"),)
    page = get(app, f"/offers/{ref}")
    assert "My own words." in page and "Zorblax" not in page
    assert "modifié à la main" in page
    empty = post(app, f"/offers/{ref}/why/edit", text=" ")
    assert empty.headers == (("Location", f"/offers/{ref}?done=why_empty#kit"),)
    assert post(app, "/offers/999/why/edit", text="x").status == 404


def test_why_without_candidate_profile_fails_with_a_reason(tmp_path):
    app, ref, worker, _ = make_site(tmp_path, why=None)
    post(app, f"/offers/{ref}/why")
    worker.wait()
    state = worker.state("why", ref)
    assert state.state == FAILED and "candidate.json" in state.error
    assert "Échec : profil candidat" in get(app, f"/offers/{ref}")


def test_no_kit_without_profile(tmp_path):
    db = str(tmp_path / "n.db")
    store = Store(db)
    store.add(JOB, "pending", NOW)
    store.save_assessment("j1", make_assessment(), 8.0)
    ref = store.job_ref("j1")
    store.close()
    page = get(build_app(Context(db, clock=lambda: NOW)), f"/offers/{ref}")
    assert '<section id="kit">' not in page
