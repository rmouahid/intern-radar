"""Render a cover letter as a simple one-page PDF."""

import re
import unicodedata
from datetime import date

from fpdf import FPDF

from intern_radar.config import Contact
from intern_radar.conventions import (
    CONVENTIONS,
    Convention,
    letter_date,
    letter_subject,
)
from intern_radar.letters.writer import Letter
from intern_radar.models import Job

# Characters outside Latin-1 (the core PDF font) with a readable equivalent.
TYPOGRAPHY = str.maketrans(
    {
        "’": "'",
        "‘": "'",
        "“": '"',
        "”": '"',
        "—": "-",
        "–": "-",
        "‑": "-",
        "…": "...",
        " ": " ",
        " ": " ",
        " ": " ",
        "•": "-",
        "œ": "oe",
        "Œ": "OE",
        "€": "EUR",
        "\u2010": "-",
        "\u3010": "[",
        "\u3011": "]",
        "\u300c": '"',
        "\u300d": '"',
    }
)
MARGIN = 16  # mm, same margins as the CV (guide: 1.5 to 2.5 cm)
# (font size, line height) tried in order until the letter fits on one page.
SIZES = ((11, 5.5), (10.5, 5.2), (10, 4.9))


def to_latin1(text: str) -> tuple[str, list[str]]:
    """Latin-1 text for the core PDF font, and the characters dropped."""
    # NFKC turns fullwidth forms (／, ＡＩ) into ASCII; anything left outside
    # Latin-1 becomes a space so that the words around it stay apart.
    text = unicodedata.normalize("NFKC", text).translate(TYPOGRAPHY)
    dropped = sorted({c for c in text if ord(c) > 255})
    kept = "".join(c if ord(c) <= 255 else " " for c in text)
    return re.sub(r" {2,}", " ", kept), dropped


def _fold(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore")
    return ascii_text.decode().strip().lower()


def _slug(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore")
    return re.sub(r"[^A-Za-z0-9]+", "-", ascii_text.decode()).strip("-")


def file_name(name: str, kind: str = "CoverLetter") -> str:
    """`Firstname_Lastname_CoverLetter.pdf`, without accents or spaces."""
    ascii_text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore")
    return f"{'_'.join(ascii_text.decode().split())}_{kind}.pdf"


def render(
    letter: Letter,
    job: Job,
    contact: Contact,
    today: date,
    convention: Convention = CONVENTIONS["international"],
) -> tuple[bytes, list[str], int]:
    """PDF bytes, dropped characters and page count (shrunk to fit one page)."""
    for size, line_height in SIZES:
        data, dropped, pages = _render(
            letter, job, contact, today, convention, size, line_height
        )
        if pages == 1:
            break
    return data, dropped, pages


def _render(
    letter: Letter,
    job: Job,
    contact: Contact,
    today: date,
    convention: Convention,
    size: float,
    line_height: float,
) -> tuple[bytes, list[str], int]:
    pdf = FPDF(format="Letter" if convention.paper == "Letter" else "A4")
    pdf.set_margins(MARGIN, MARGIN, MARGIN)
    pdf.set_auto_page_break(True, MARGIN)
    pdf.set_title(f"{contact.name} - Cover letter")
    pdf.set_author(contact.name)
    pdf.add_page()
    dropped: set[str] = set()

    def write(text: str, style: str = "", gap: float = 0, align: str = "L") -> None:
        clean, lost = to_latin1(text)
        dropped.update(lost)
        pdf.set_font("Helvetica", style=style, size=size)
        pdf.multi_cell(
            0, line_height, clean, align=align, new_x="LMARGIN", new_y="NEXT"
        )
        if gap:
            pdf.ln(gap)

    write(contact.name, "B")
    write(f"{contact.location} · {contact.phone} · {contact.email}")
    write(f"{contact.linkedin} · {contact.github}", gap=8)
    # DIN 5008 (Germany, Austria, Switzerland): the date sits on the right.
    date_align = "R" if convention.letter_date == "de" else "L"
    write(letter_date(convention, letter.language, today), gap=6, align=date_align)
    write(f"{job.company} — Hiring Team")
    write(letter_subject(letter.language, job.title), "B", gap=6)
    write(letter.greeting, gap=3)
    for paragraph in letter.paragraphs:
        write(paragraph, gap=3)
    pdf.ln(2)
    # The LLM sometimes signs the closing itself; the signature is added here.
    closing = [
        line
        for line in letter.closing.splitlines()
        if line.strip() and _fold(line) != _fold(contact.name)
    ]
    for line in closing or [convention.closing_unnamed]:
        write(line)
    write(contact.name)
    return bytes(pdf.output()), sorted(dropped), pdf.page_no()
