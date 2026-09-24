"""Render a cover letter as a simple one-page PDF."""

import re
import unicodedata
from datetime import date

from fpdf import FPDF

from intern_radar.config import Contact
from intern_radar.letters.writer import Letter
from intern_radar.models import Job

TYPOGRAPHY = str.maketrans(
    {
        "’": "'",
        "‘": "'",
        "“": '"',
        "”": '"',
        "—": "-",
        "–": "-",
        "…": "...",
        " ": " ",
        " ": " ",
        "•": "-",
    }
)
LINE_HEIGHT = 5.5
MARGIN = 25


def to_latin1(text: str) -> tuple[str, list[str]]:
    """Latin-1 text for the core PDF font, and the characters dropped."""
    text = text.translate(TYPOGRAPHY)
    dropped = sorted({c for c in text if ord(c) > 255})
    return "".join(c for c in text if ord(c) <= 255), dropped


def _slug(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore")
    return re.sub(r"[^A-Za-z0-9]+", "-", ascii_text.decode()).strip("-")


def file_name(last_name: str, company: str, title: str) -> str:
    base = f"{_slug(last_name)}_CoverLetter_{_slug(company)}_{_slug(title)}"
    return base[:76].rstrip("-_") + ".pdf"


def render(
    letter: Letter, job: Job, contact: Contact, today: date
) -> tuple[bytes, list[str]]:
    pdf = FPDF(format="A4")
    pdf.set_margins(MARGIN, MARGIN, MARGIN)
    pdf.set_auto_page_break(True, MARGIN)
    pdf.add_page()
    dropped: set[str] = set()

    def write(text: str, style: str = "", gap: float = 0) -> None:
        clean, lost = to_latin1(text)
        dropped.update(lost)
        pdf.set_font("Helvetica", style=style, size=11)
        pdf.multi_cell(0, LINE_HEIGHT, clean, new_x="LMARGIN", new_y="NEXT")
        if gap:
            pdf.ln(gap)

    write(contact.name, "B")
    write(f"{contact.location} · {contact.phone} · {contact.email}")
    write(f"{contact.linkedin} · {contact.github}", gap=8)
    write(f"{today:%B} {today.day}, {today.year}", gap=6)
    write(f"{job.company} — Hiring Team")
    location = f" ({job.location})" if job.location else ""
    write(f"Re: {job.title}{location}", "B", gap=6)
    write(letter.greeting, gap=3)
    for paragraph in letter.paragraphs:
        write(paragraph, gap=3)
    pdf.ln(2)
    write(letter.closing)
    write(contact.name)
    return bytes(pdf.output()), sorted(dropped)
