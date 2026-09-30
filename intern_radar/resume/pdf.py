"""Render a tailored CV on exactly one A4 page (fpdf2, core font).

Text stays real text (ATS-readable). If the content does not fit, the font
shrinks first, then the least relevant bullets are removed (last item
first, keeping at least one bullet per item), then the last items.
"""

from dataclasses import replace

from fpdf import FPDF

from intern_radar.candidate import Candidate
from intern_radar.config import Contact
from intern_radar.letters.pdf import _slug, to_latin1
from intern_radar.resume.writer import Resume

MARGIN = 14
# (font size, line height) tried in order until the CV fits on one page.
SIZES = ((10, 4.6), (9.5, 4.3), (9, 4.1))


def file_name(last_name: str, company: str, title: str) -> str:
    base = f"{_slug(last_name)}_CV_{_slug(company)}_{_slug(title)}"
    return base[:76].rstrip("-_") + ".pdf"


def _dated(text: str, dates: str) -> str:
    return f"{text}  ({dates})" if dates.strip() else text


def _trim(resume: Resume) -> Resume | None:
    """The resume with one bullet (or, at the end, one item) less."""
    items = list(resume.items)
    for index in range(len(items) - 1, -1, -1):
        item, bullets = items[index]
        if len(bullets) > 1:
            items[index] = (item, bullets[:-1])
            return replace(resume, items=tuple(items))
    if len(items) > 1:
        return replace(resume, items=tuple(items[:-1]))
    return None


def render(
    resume: Resume, candidate: Candidate, contact: Contact
) -> tuple[bytes, list[str], int, int]:
    """PDF bytes, dropped characters, page count and bullets removed to fit."""
    removed = 0
    data, dropped, pages = _render(resume, candidate, contact, *SIZES[0])
    current: Resume | None = resume
    while current is not None:
        for size, line_height in SIZES:
            data, dropped, pages = _render(
                current, candidate, contact, size, line_height
            )
            if pages == 1:
                return data, dropped, pages, removed
        current = _trim(current)
        removed += 1
    return data, dropped, pages, removed


def _render(
    resume: Resume,
    candidate: Candidate,
    contact: Contact,
    size: float,
    line_height: float,
) -> tuple[bytes, list[str], int]:
    pdf = FPDF(format="A4")
    pdf.set_margins(MARGIN, MARGIN, MARGIN)
    pdf.set_auto_page_break(True, MARGIN)
    pdf.add_page()
    dropped: set[str] = set()

    def write(text: str, style: str = "", scale: float = 1, indent: float = 0) -> None:
        clean, lost = to_latin1(text)
        dropped.update(lost)
        pdf.set_font("Helvetica", style=style, size=size * scale)
        pdf.set_x(MARGIN + indent)
        pdf.multi_cell(
            0, line_height * scale, clean, align="L", new_x="LMARGIN", new_y="NEXT"
        )

    def heading(text: str) -> None:
        pdf.ln(1.5)
        write(text.upper(), "B", 1.05)
        y = pdf.get_y()
        pdf.line(MARGIN, y, pdf.w - MARGIN, y)
        pdf.ln(1)

    write(contact.name, "B", 1.6)
    write(
        " | ".join(
            part
            for part in (
                contact.location,
                contact.phone,
                contact.email,
                contact.linkedin,
                contact.github,
            )
            if part
        )
    )
    if resume.headline:
        write(resume.headline, "I")
    heading("Summary")
    write(resume.summary)
    if candidate.education:
        heading("Education")
        for education in candidate.education:
            write(
                _dated(f"{education.degree} — {education.school}", education.dates), "B"
            )
            for detail in education.details[:2]:
                write(f"- {detail}", indent=3)
    experience_ids = {item.id for item in candidate.experiences}
    for title, wanted in (("Experience", True), ("Projects", False)):
        chosen = [(i, b) for i, b in resume.items if (i.id in experience_ids) == wanted]
        if not chosen:
            continue
        heading(title)
        for item, bullets in chosen:
            write(_dated(f"{item.title} — {item.organisation}", item.dates), "B")
            for bullet in bullets:
                write(f"- {bullet}", indent=3)
    if resume.skills:
        heading("Skills")
        for category, names in resume.skills:
            write(f"{category}: {', '.join(names)}")
    if candidate.languages:
        heading("Languages")
        write(
            ", ".join(f"{lang.language} ({lang.level})" for lang in candidate.languages)
        )
    return bytes(pdf.output()), sorted(dropped), pdf.page_no()
