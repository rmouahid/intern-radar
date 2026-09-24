import io
from datetime import date

from pypdf import PdfReader

from intern_radar.config import Contact
from intern_radar.letters.pdf import file_name, render, to_latin1
from intern_radar.letters.writer import Letter
from tests.factories import make_job

CONTACT = Contact(
    "Rayân Mouahid",
    "Paris, France",
    "+33 7 00",
    "me@example.com",
    "linkedin.com/in/me",
    "github.com/me",
)
LETTER = Letter(
    "en",
    "Dear Hiring Team,",
    ("First paragraph.", "Second paragraph.", "Third paragraph."),
    "Sincerely,",
)


def text_of(data: bytes) -> str:
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(data)).pages)


def test_to_latin1():
    assert to_latin1("It’s “good” — really…") == ('It\'s "good" - really...', [])
    assert to_latin1("Rayân café 🚀") == ("Rayân café ", ["🚀"])


def test_file_name():
    assert file_name("Mouahid", "Hugging Face", "ML Intern (2027)") == (
        "Mouahid_CoverLetter_Hugging-Face_ML-Intern-2027.pdf"
    )
    long_name = file_name("Mouahid", "Amazon", "Robotics " * 30)
    assert len(long_name) <= 80 and long_name.endswith(".pdf")


def test_render_contains_header_body_and_signature():
    job = make_job(company="Acme", title="ML Intern", location="London, UK")
    data, dropped = render(LETTER, job, CONTACT, date(2026, 9, 24))
    text = text_of(data)
    assert data.startswith(b"%PDF")
    assert dropped == []
    for expected in (
        "Rayân Mouahid",
        "me@example.com",
        "September 24, 2026",
        "Acme - Hiring Team",
        "Re: ML Intern (London, UK)",
        "Second paragraph.",
        "Sincerely,",
    ):
        assert expected in text


def test_render_normalises_typography_and_reports_dropped():
    letter = Letter("en", "Dear Team,", ("It’s great — 🚀", "b", "c"), "Best,")
    data, dropped = render(letter, make_job(), CONTACT, date(2026, 9, 24))
    assert "It's great -" in text_of(data)
    assert dropped == ["🚀"]
