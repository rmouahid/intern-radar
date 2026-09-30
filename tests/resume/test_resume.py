import io
from datetime import UTC, datetime

import pytest
from pypdf import PdfReader

from intern_radar.candidate import parse_candidate
from intern_radar.config import Contact
from intern_radar.conventions import CONVENTIONS
from intern_radar.resume.pdf import file_name, render
from intern_radar.resume.service import ResumeService, format_resume_caption
from intern_radar.resume.writer import RESUME_SCHEMA, Resume, ResumeWriter
from intern_radar.scorer import LLMError
from intern_radar.store import Store
from intern_radar.telegram import TelegramError
from tests.factories import make_assessment, make_job
from tests.test_candidate import profile_dict

NOW = datetime(2026, 9, 30, tzinfo=UTC)
CONTACT = Contact("Alex Martîn", "Paris", "+33 1", "a@x.io", "li/alex", "gh/alex")
CANDIDATE = parse_candidate(profile_dict())
US, UK, DACH = CONVENTIONS["us"], CONVENTIONS["uk"], CONVENTIONS["dach"]


def answer(**overrides):
    data = {
        "language": "en",
        "headline": "Engineering student building RAG systems",
        "summary": "Engineering student building RAG systems.",
        "experiences": [
            {
                "id": "exp-acme",
                "bullets": [
                    "Built a RAG agent with Python and Docker",
                    "Cut answer time by 40%",
                    "Led a team of 12 engineers at Google",
                ],
            },
            {"id": "proj-vector", "bullets": ["not an experience"]},
        ],
        "projects": [
            {"id": "proj-vector", "bullets": ["Implemented IVF search"]},
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


def write(result, convention=US):
    return ResumeWriter(FakeBackend(result), CANDIDATE, convention).write(make_job())


def test_writer_follows_the_convention_and_keeps_only_sourced_content():
    backend = FakeBackend(answer())
    resume = ResumeWriter(backend, CANDIDATE, UK).write(make_job(description="RAG"))
    prompt, schema = backend.calls[0]
    assert schema is RESUME_SCHEMA and "Never add" in prompt
    assert "British English" in prompt and "Personal statement: 3 to 4" in prompt
    assert 'never "I"' in prompt and "past" in prompt
    assert [item.id for item, _ in resume.experiences] == ["exp-acme"]
    assert [item.id for item, _ in resume.projects] == ["proj-vector"]
    assert resume.experiences[0][1] == (
        "Built a RAG agent with Python and Docker",
        "Cut answer time by 40%",
    )
    assert resume.dropped == ("Led a team of 12 engineers at Google",)
    assert resume.skills == (("Languages", ("Python",)), ("Infra", ("Docker",)))
    assert resume.language == "en"


def test_writer_falls_back_on_recorded_facts():
    result = answer(
        headline="Kaggle Grandmaster",
        summary="Worked at OpenAI.",
        language="xx",
        experiences=[{"id": "exp-acme", "bullets": ["Scaled Kubernetes at Meta"]}],
        projects=[],
    )
    resume = write(result)
    assert resume.headline == "" and resume.summary == CANDIDATE.summary
    assert resume.language == "en"
    assert resume.experiences[0][1] == ("Built a RAG agent", "Cut answer time by 40%")
    empty = write(answer(experiences=[], projects=[]))
    assert [item.id for item, _ in empty.experiences] == ["exp-acme"]


def test_writer_rejects_invalid_output():
    with pytest.raises(LLMError):
        write({"experiences": "?"})


def pdf_text(data):
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(data)).pages)


def test_render_us_letter_one_page_with_metadata_and_status():
    data, dropped, pages, removed = render(
        write(answer()), CANDIDATE, CONTACT, US, "unlikely"
    )
    reader = PdfReader(io.BytesIO(data))
    assert pages == 1 and removed == 0 and dropped == []
    assert round(float(reader.pages[0].mediabox.width)) == 612  # US Letter
    assert reader.metadata.title == "Alex Martîn - CV"
    assert reader.metadata.author == "Alex Martîn"
    text = pdf_text(data)
    assert "requires visa sponsorship" in text and "SUMMARY" in text
    # Students in North America: education before experience.
    assert text.index("EDUCATION") < text.index("EXPERIENCE") < text.index("PROJECTS")
    assert "Jul-Aug 2025" not in text and "Aug 2025" in text


def test_render_dach_is_a4_tabular_without_status():
    data, _, pages, _ = render(write(answer()), CANDIDATE, CONTACT, DACH, "free")
    reader = PdfReader(io.BytesIO(data))
    assert round(float(reader.pages[0].mediabox.width)) == 595  # A4
    text = pdf_text(data)
    assert "sponsorship" not in text and "EU citizen" not in text
    assert text.index("EXPERIENCE") < text.index("EDUCATION")


def test_local_mentions():
    resume = write(answer())
    au = pdf_text(
        render(resume, CANDIDATE, CONTACT, CONVENTIONS["australia"], "self_arranged")[0]
    )
    assert "Referees available on request." in au and "Working Holiday" in au
    pl = pdf_text(render(resume, CANDIDATE, CONTACT, CONVENTIONS["poland"], "free")[0])
    assert "RODO" in pl
    ch = pdf_text(
        render(resume, CANDIDATE, CONTACT, CONVENTIONS["switzerland"], "free")[0]
    )
    assert "Nationality: French" in ch


def test_render_trims_bullets_until_the_page_limit():
    long_items = tuple(
        (
            CANDIDATE.projects[0],
            tuple(f"Implemented IVF search step {i} " * 6 for i in range(3)),
        )
        for _ in range(12)
    )
    resume = Resume("en", "", CANDIDATE.summary, (), long_items, ())
    _, _, pages, removed = render(resume, CANDIDATE, CONTACT, US, "free")
    assert pages == 1 and removed > 0


def test_file_name():
    assert file_name("Rayân Mouahid") == "Rayan_Mouahid_CV.pdf"
    assert file_name("Rayân Mouahid", "CoverLetter") == "Rayan_Mouahid_CoverLetter.pdf"


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
    store.add(
        make_job(id="j1", company="Acme", title="ML Intern", location="London, UK"),
        "pending",
        NOW,
    )
    store.save_assessment("j1", make_assessment(work_authorisation="unlikely"), 8.0)
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
    assert path.exists() and path.name == "Alex_Martin_CV.pdf"
    assert svc.handle("j1") == path
    assert len(backend.calls) == 1 and len(documents.sent) == 2
    caption = documents.sent[0][1]
    assert "CV adapté · Acme" in caption and "United Kingdom (A4" in caption
    assert "1 puce(s) retirée(s) : non sourcée(s)" in caption
    assert "British English" in backend.calls[0][0]
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
