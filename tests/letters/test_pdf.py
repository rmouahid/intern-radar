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
    assert file_name("Rayân Mouahid") == "Rayan_Mouahid_CoverLetter.pdf"


def test_country_conventions_shape_the_letter():
    import io

    from pypdf import PdfReader

    from intern_radar.conventions import CONVENTIONS

    us = make_job(company="Acme", title="ML Intern", location="Austin, TX")
    data, _, _ = render(LETTER, us, CONTACT, date(2026, 9, 30), CONVENTIONS["us"])
    reader = PdfReader(io.BytesIO(data))
    assert round(float(reader.pages[0].mediabox.width)) == 612
    assert reader.metadata.title == "Rayân Mouahid - Cover letter"
    assert "September 30, 2026" in text_of(data)
    assert "Application for ML Intern" in text_of(data)
    uk = render(LETTER, us, CONTACT, date(2026, 9, 30), CONVENTIONS["uk"])[0]
    assert "30 September 2026" in text_of(uk)
    german = Letter(
        "de",
        "Sehr geehrte Damen und Herren,",
        ("a", "b", "c", "d"),
        "Mit freundlichen Grüßen",
    )
    de = render(german, us, CONTACT, date(2026, 9, 30), CONVENTIONS["dach"])[0]
    assert "30.09.2026" in text_of(de) and "Bewerbung als ML Intern" in text_of(de)


def test_render_contains_header_body_and_signature():
    job = make_job(company="Acme", title="ML Intern", location="London, UK")
    data, dropped, pages = render(LETTER, job, CONTACT, date(2026, 9, 24))
    text = text_of(data)
    assert data.startswith(b"%PDF")
    assert dropped == []
    for expected in (
        "Rayân Mouahid",
        "me@example.com",
        "24 September 2026",
        "Acme - Hiring Team",
        "Application for ML Intern",
        "Second paragraph.",
        "Sincerely,",
    ):
        assert expected in text


def test_render_normalises_typography_and_reports_dropped():
    letter = Letter("en", "Dear Team,", ("It’s great — 🚀", "b", "c"), "Best,")
    data, dropped, _ = render(letter, make_job(), CONTACT, date(2026, 9, 24))
    assert "It's great -" in text_of(data)
    assert dropped == ["🚀"]


def test_to_latin1_keeps_french_ligatures_and_symbols():
    assert to_latin1("cœur, Œuvre, 5 € ‑ ok") == ("coeur, OEuvre, 5 EUR - ok", [])


def test_long_letters_are_shrunk_to_fit_one_page():
    paragraph = "I built retrieval systems in Python for search. " * 55
    letter = Letter("en", "Dear Team,", (paragraph, "b", "c"), "Best,")
    data, _, pages = render(letter, make_job(), CONTACT, date(2026, 9, 24))
    assert pages == 1
    assert len(PdfReader(io.BytesIO(data)).pages) == 1


def test_letters_too_long_for_one_page_report_their_page_count():
    paragraph = "I built retrieval systems in Python for search. " * 120
    letter = Letter("en", "Dear Team,", (paragraph, "b", "c"), "Best,")
    _, _, pages = render(letter, make_job(), CONTACT, date(2026, 9, 24))
    assert pages == 2


def test_fullwidth_and_unknown_characters_never_glue_words_together():
    text, dropped = to_latin1("【Class of 2029／Internship】Applied Scientists")
    assert text == "[Class of 2029/Internship]Applied Scientists"
    assert dropped == []
    assert to_latin1("AI ⟶ ML") == ("AI ML", ["⟶"])


def test_signature_is_not_duplicated_when_the_closing_contains_the_name():
    letter = Letter("en", "Dear Team,", ("a", "b", "c"), "Sincerely,\nRayan Mouahid")
    data, _, _ = render(letter, make_job(), CONTACT, date(2026, 9, 24))
    assert text_of(data).count("Mouahid") == 2  # header + one signature
