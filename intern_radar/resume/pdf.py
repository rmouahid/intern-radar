"""Render a tailored CV following the country conventions (fpdf2, core font).

Single column, real text (ATS-readable), one font, black only, font size
10 pt or more and margins of 1.6 cm. Paper, page limit, section order and
titles, date style, the tabular German-style layout and the local mentions
come from the offer's `Convention`. If the content does not fit, the font
goes from 10.5 to 10 pt, then the least relevant bullets are removed
(projects first, keeping one bullet each, then experiences down to two),
then the last project.
"""

import unicodedata
from dataclasses import replace

from fpdf import FPDF

from intern_radar.candidate import Candidate
from intern_radar.config import Contact
from intern_radar.conventions import (
    CERTIFICATIONS,
    EDUCATION,
    EXPERIENCE,
    LANGUAGES,
    PROJECTS,
    SKILLS,
    SUMMARY,
    Convention,
    format_dates,
    recency,
    section_title,
    work_status_line,
)
from intern_radar.letters.pdf import to_latin1
from intern_radar.resume.writer import Resume

MARGIN = 16  # mm (1.6 cm)
DATE_COLUMN = 32  # mm, tabular layout
SIZES = ((10.5, 5.0), (10, 4.7))  # (font size, line height): never below 10 pt
ONE_PAGE_EDUCATION = 3  # a one-page CV keeps the most recent entries only
MAX_SKILLS_PER_GROUP = 8


def slug(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore")
    return "_".join(ascii_text.decode().split())


def file_name(name: str, kind: str = "CV") -> str:
    """`Firstname_Lastname_CV.pdf`, without accents or spaces."""
    return f"{slug(name)}_{kind}.pdf"


def _fewer_bullets(entries, keep: int):
    """Entries with one bullet less on the last one above `keep`, or None."""
    entries = list(entries)
    for index in range(len(entries) - 1, -1, -1):
        item, bullets = entries[index]
        if len(bullets) > keep:
            entries[index] = (item, bullets[:-1])
            return tuple(entries)
    return None


def _trim(resume: Resume) -> Resume | None:
    """The resume with a little less content, least relevant first.

    Order: project bullets down to one; projects down to two; experience
    bullets down to three (the guide's minimum); projects down to one;
    experience bullets down to two; the last project.
    """
    projects, experiences = resume.projects, resume.experiences
    if shorter := _fewer_bullets(projects, 1):
        return replace(resume, projects=shorter)
    if len(projects) > 2:
        return replace(resume, projects=projects[:-1])
    if shorter := _fewer_bullets(experiences, 3):
        return replace(resume, experiences=shorter)
    if len(projects) > 1:
        return replace(resume, projects=projects[:-1])
    if shorter := _fewer_bullets(experiences, 2):
        return replace(resume, experiences=shorter)
    if projects:
        return replace(resume, projects=projects[:-1])
    return None


def render(
    resume: Resume,
    candidate: Candidate,
    contact: Contact,
    convention: Convention,
    work_authorisation: str,
) -> tuple[bytes, list[str], int, int]:
    """PDF bytes, dropped characters, page count and bullets removed to fit."""
    removed = 0
    current: Resume | None = resume
    data, dropped, pages = b"", [], 0
    while current is not None:
        for size, line_height in SIZES:
            data, dropped, pages = _render(
                current, candidate, contact, convention, work_authorisation,
                size, line_height,
            )  # fmt: skip
            if pages <= convention.cv_pages:
                return data, dropped, pages, removed
        current = _trim(current)
        removed += 1
    return data, dropped, pages, removed


def _render(
    resume: Resume,
    candidate: Candidate,
    contact: Contact,
    convention: Convention,
    work_authorisation: str,
    size: float,
    line_height: float,
) -> tuple[bytes, list[str], int]:
    pdf = FPDF(format="Letter" if convention.paper == "Letter" else "A4")
    pdf.set_margins(MARGIN, MARGIN, MARGIN)
    pdf.set_auto_page_break(True, MARGIN)
    pdf.set_title(f"{contact.name} - CV")
    pdf.set_author(contact.name)
    pdf.add_page()
    dropped: set[str] = set()
    language = resume.language

    def text(value: str) -> str:
        clean, lost = to_latin1(value)
        dropped.update(lost)
        return clean

    def write(value: str, style: str = "", scale: float = 1, indent: float = 0):
        pdf.set_font("Helvetica", style=style, size=size * scale)
        pdf.set_x(MARGIN + indent)
        pdf.multi_cell(
            0, line_height * scale, text(value), align="L",
            new_x="LMARGIN", new_y="NEXT",
        )  # fmt: skip

    def heading(key: str) -> None:
        pdf.ln(1.8)
        write(section_title(convention, key, language).upper(), "B", 1.1)
        y = pdf.get_y()
        pdf.line(MARGIN, y, pdf.w - MARGIN, y)
        pdf.ln(1.2)

    def entry(title: str, dates: str, bullets: tuple[str, ...], extra: str = ""):
        dates = format_dates(dates, convention, language) if dates else ""
        if convention.tabular:
            pdf.set_font("Helvetica", size=size)
            y = pdf.get_y()
            pdf.set_x(MARGIN)
            pdf.cell(DATE_COLUMN, line_height, text(dates))
            pdf.set_y(y)
            indent = DATE_COLUMN
        else:
            title = f"{title}  |  {dates}" if dates else title
            indent = 0
        write(title, "B", indent=indent)
        if extra:
            write(extra, "I", 0.95, indent=indent)
        for bullet in bullets:
            write(f"- {bullet}", indent=indent + 3)
        pdf.ln(0.8)

    # Header
    write(contact.name, "B", 1.55)
    contacts = (
        contact.location,
        contact.phone,
        contact.email,
        contact.linkedin,
        contact.github,
    )
    write(" | ".join(p for p in contacts if p), scale=0.95)
    status = work_status_line(convention, work_authorisation)
    if status:
        write(status, scale=0.95)
    if resume.headline:
        write(resume.headline, "I")

    certifications = "; ".join(candidate.certifications)
    # Reverse chronological order, whatever the order of the profile.
    education = tuple(sorted(candidate.education, key=lambda e: recency(e.dates)))
    experiences = tuple(sorted(resume.experiences, key=lambda e: recency(e[0].dates)))
    if convention.cv_pages == 1:
        education = education[:ONE_PAGE_EDUCATION]
    for key in convention.sections:
        if key == SUMMARY and resume.summary:
            heading(SUMMARY)
            write(resume.summary)
        elif key == EDUCATION and education:
            heading(EDUCATION)
            for school in education:
                entry(
                    f"{school.degree} - {school.school}",
                    school.dates,
                    school.details[:1],
                )
        elif key == SKILLS and resume.skills:
            heading(SKILLS)
            for category, names in resume.skills:
                write(f"{category}: {', '.join(names[:MAX_SKILLS_PER_GROUP])}")
        elif key == EXPERIENCE and experiences:
            heading(EXPERIENCE)
            for item, bullets in experiences:
                entry(f"{item.title} - {item.organisation}", item.dates, bullets)
        elif key == PROJECTS and resume.projects:
            heading(PROJECTS)
            for item, bullets in resume.projects:
                stack = ", ".join(item.skills[:8])
                extra = " | ".join(p for p in (item.link, stack) if p)
                entry(item.title, item.dates, bullets, extra)
        elif key == CERTIFICATIONS and certifications:
            heading(CERTIFICATIONS)
            write(certifications)
        elif key == LANGUAGES and candidate.languages:
            heading(LANGUAGES)
            write(", ".join(f"{x.language} ({x.level})" for x in candidate.languages))
    if convention.referees:
        pdf.ln(1.5)
        write("Referees available on request.", "I", 0.95)
    if convention.gdpr_clause:
        pdf.ln(2)
        write(convention.gdpr_clause, scale=0.9)
    return bytes(pdf.output()), sorted(dropped), pdf.page_no()
