import io
from datetime import UTC, datetime

import pytest
from pypdf import PdfReader

from intern_radar.candidate import parse_candidate
from intern_radar.config import Contact
from intern_radar.resume.pdf import file_name, render
from intern_radar.resume.service import ResumeService, format_resume_caption
from intern_radar.resume.writer import RESUME_SCHEMA, Resume, ResumeWriter
from intern_radar.scorer import LLMError
from intern_radar.store import Store
from intern_radar.telegram import TelegramError
from tests.factories import make_job
from tests.test_candidate import profile_dict

NOW = datetime(2026, 9, 30, tzinfo=UTC)
CONTACT = Contact("Alex Martin", "Paris", "+33 1", "a@x.io", "li/alex", "gh/alex")
CANDIDATE = parse_candidate(profile_dict())


def answer(**overrides):
    data = {
        "headline": "Engineering student building RAG systems",
        "summary": "Engineering student building RAG systems.",
        "items": [
            {"id": "proj-vector", "bullets": ["Implemented IVF search"]},
            {
                "id": "exp-acme",
                "bullets": [
                    "Built a RAG agent with Python and Docker",
                    "Cut answer time by 40%",
                    "Led a team of 12 engineers at Google",
                ],
            },
            {"id": "exp-unknown", "bullets": ["x"]},
        ],
        "skills": [
            {"category": "Languages", "names": ["python", "Rust"]},
            {"category": "Infra", "names": ["Docker"]},
            {"category": "Empty", "names": ["Haskell"]},
        ],
    }
    data.update(overrides)
    return data


class FakeBackend:
    def __init__(self, result):
        self.result, self.calls = result, []

    def complete(self, prompt, schema):
        self.calls.append((prompt, schema))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_writer_keeps_only_sourced_bullets_items_and_skills():
    backend = FakeBackend(answer())
    resume = ResumeWriter(backend, CANDIDATE).write(make_job(description="RAG, Python"))
    prompt, schema = backend.calls[0]
    assert schema is RESUME_SCHEMA and "Never add" in prompt and "exp-acme" in prompt
    assert [item.id for item, _ in resume.items] == ["proj-vector", "exp-acme"]
    assert resume.items[1][1] == (
        "Built a RAG agent with Python and Docker",
        "Cut answer time by 40%",
    )
    assert resume.dropped == ("Led a team of 12 engineers at Google",)
    assert resume.skills == (("Languages", ("Python",)), ("Infra", ("Docker",)))
    assert resume.headline == "Engineering student building RAG systems"


def test_writer_falls_back_on_recorded_facts():
    result = answer(
        headline="Kaggle Grandmaster",
        summary="Worked at OpenAI.",
        items=[{"id": "exp-acme", "bullets": ["Scaled Kubernetes at Meta"]}],
    )
    resume = ResumeWriter(FakeBackend(result), CANDIDATE).write(make_job())
    assert resume.headline == "" and resume.summary == CANDIDATE.summary
    assert resume.items[0][1] == ("Built a RAG agent", "Cut answer time by 40%")
    none = ResumeWriter(FakeBackend(answer(items=[])), CANDIDATE).write(make_job())
    assert [item.id for item, _ in none.items] == ["exp-acme", "proj-vector"]


def test_writer_rejects_invalid_output():
    with pytest.raises(LLMError):
        ResumeWriter(FakeBackend({"items": "?"}), CANDIDATE).write(make_job())


def pdf_text(data):
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(data)).pages)


def test_render_one_page_with_real_text():
    resume = ResumeWriter(FakeBackend(answer()), CANDIDATE).write(make_job())
    data, dropped, pages, removed = render(resume, CANDIDATE, CONTACT)
    text = pdf_text(data)
    assert pages == 1 and removed == 0 and dropped == []
    for expected in ("Alex Martin", "EXPERIENCE", "PROJECTS", "Implemented IVF search"):
        assert expected in text
    assert text.index("PROJECTS") > text.index("EXPERIENCE")


def test_render_trims_bullets_until_one_page():
    long_items = tuple(
        (
            CANDIDATE.experiences[0],
            tuple(f"Built a RAG agent step {i} " * 6 for i in range(4)),
        )
        for _ in range(12)
    )
    resume = Resume("", CANDIDATE.summary, long_items, ())
    data, _, pages, removed = render(resume, CANDIDATE, CONTACT)
    assert pages == 1 and removed > 0


def test_file_name():
    assert file_name("Martin", "Acme AI", "ML Intern (2027)") == (
        "Martin_CV_Acme-AI_ML-Intern-2027.pdf"
    )


class FakeDocuments:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def send_document(self, content, filename, caption, html=True):
        if self.fail:
            raise TelegramError("boom")
        self.sent.append((filename, caption))


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def send(self, message):
        self.sent.append(message.html)


def service(tmp_path, backend, documents=None, max_per_day=10):
    store = Store(":memory:")
    store.add(make_job(id="j1", company="Acme", title="ML Intern"), "pending", NOW)
    notifier = FakeNotifier()
    documents = documents or FakeDocuments()
    svc = ResumeService(
        store,
        lambda: CANDIDATE,
        backend,
        CONTACT,
        tmp_path,
        documents,
        notifier,
        max_per_day,
        clock=lambda: NOW,
    )
    return svc, store, documents, notifier


def test_service_generates_stores_and_resends(tmp_path):
    backend = FakeBackend(answer())
    svc, store, documents, _ = service(tmp_path, backend)
    path = svc.handle("j1")
    assert path.exists() and path.name == "Martin_CV_Acme_ML-Intern.pdf"
    assert svc.handle("j1") == path
    assert len(backend.calls) == 1 and len(documents.sent) == 2
    assert "CV adapté · Acme" in documents.sent[0][1]
    assert "1 puce(s) retirée(s) : non sourcée(s)" in documents.sent[0][1]
    assert store.resume("j1")[1]["items"] == 2


def test_service_failures_are_reported(tmp_path):
    svc, _, _, notifier = service(tmp_path, FakeBackend(LLMError("quota")))
    assert svc.handle("j1") is None and "CV non généré" in notifier.sent[0]
    svc, _, _, notifier = service(
        tmp_path, FakeBackend(answer()), FakeDocuments(fail=True)
    )
    assert svc.handle("j1") is not None and "CV non envoyé" in notifier.sent[0]
    svc, _, _, notifier = service(tmp_path, FakeBackend(answer()), max_per_day=0)
    assert svc.handle("j1") is None and "Limite de CV" in notifier.sent[0]
    assert svc.handle("unknown") is None


def test_caption_fits_telegram():
    report = {"items": 3, "fact_dropped": 0, "fit_removed": 2, "dropped_chars": []}
    caption = format_resume_caption(make_job(company="A" * 900), report)
    assert len(caption) <= 1024 and "pour tenir sur 1 page" in caption
