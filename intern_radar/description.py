"""Removes boilerplate from job descriptions before they are sent to the LLM.

Descriptions are truncated (3,000 characters for scoring), and many start
with the company presentation and end with benefits and legal notices, so
the responsibilities, requirements and dates were often cut off. Sections
are recognised by short heading lines; unknown headings never end a
section, and everything not recognised as boilerplate is kept.
"""

import re

MAX_HEADING_LENGTH = 70
# Headings of sections that say nothing about the role itself.
BOILERPLATE_HEADING_RE = re.compile(
    r"^(company description|about (us|the (company|team))|about [\w&.' -]{1,30}"
    r"|who (we are|are we)|a world-changing company|our (company|mission|story"
    r"|culture|values)|life at [\w&.' -]{1,30}|why join( us)?"
    r"|benefits|perks|what we offer|what( i)?s in it for you|compensation"
    r"|expected pay range|pay (range|transparency)|salary( range)?|hourly rate"
    r"|usd|equal (employment )?opportunity|eeo|diversity|inclusion"
    r"|accommodations?|privacy( notice)?|disclaimer|posting statement"
    r"|state ?specific notices|ai use guidelines( for interviews)?"
    r"|our recruitment process|(how )?to apply|work likeabosch includes"
    r"|legal notice)\b",
)
# Lines that are boilerplate wherever they appear.
BOILERPLATE_LINE_RE = re.compile(
    r"equal (employment )?opportunit(y|ies) employer|without regard to (race|age|sex)"
    r"|if you have a disability|our inclusive culture empowers"
    r"|reasonable accommodations?|applicant privacy|by submitting your (resume"
    r"|application)|e-verify|base (salary|pay) range|pay range for this"
    r"|salary range for this|protected veteran|sexual orientation",
    re.IGNORECASE,
)
# Opening lines shared by every posting of a company, followed by boilerplate.
INTRO_RE = re.compile(r"^there['’]s a universe of opportunity at ", re.IGNORECASE)
# Duration and period mentions are kept even inside a dropped section.
DATES_RE = re.compile(
    r"\b(\d+[- ]?(weeks?|months?)|summer|spring|autumn|fall|winter|start date"
    r"|starting|duration|january|february|march|april|june|july|august"
    r"|september|october|november|december)\b",
    re.IGNORECASE,
)
DECORATION_RE = re.compile(r"^[^\w]+|[\s:?.!]+$")
PUNCTUATION_RE = re.compile(r"[^\w& ?'.-]")


def _heading(line: str) -> str | None:
    """Normalised heading text, or None when the line is not heading-like."""
    text = line.strip()
    if not text or len(text) > MAX_HEADING_LENGTH or text.endswith((".", ",", ";")):
        return None
    text = DECORATION_RE.sub("", text).replace("’", "'").lower()
    text = PUNCTUATION_RE.sub("", text).replace("'", "").strip()
    return text or None


# Headings of sections about the role: they end a boilerplate section.
ROLE_HEADING_RE = re.compile(
    r"^(job description|the role|role overview|(the |your )?(key )?(job )?"
    r"responsibilities|what (you will|youll|you ll) (do|be doing)|you will"
    r"|what we need to see|what (we are|were) looking for|requirements"
    r"|(minimum |preferred |basic )?qualifications|you have|we prefer"
    r"|required skills|your (skills|profile|contribution|core responsibilities)"
    r"|ways to stand out|bonus points|nice to have|the work|job details"
    r"|duration|start date|internship (start dates|details|dates)|location"
    r"|eligibility|who you are|what distinguishes you|your tasks"
    r"|key job responsibilities|basic qualifications|preferred qualifications"
    r"|about (the |this |our )?[\w&.' -]{0,40}(internship|program|programme|role"
    r"|team|position|job|opportunity)|why this role)\b",
)


def _section(line: str) -> str | None:
    """ "role" or "boilerplate" for a recognised heading line, else None."""
    if INTRO_RE.match(line.strip()):
        return "boilerplate"
    heading = _heading(line)
    if heading is None:
        return None
    if ROLE_HEADING_RE.match(heading):  # before "about <company>"
        return "role"
    if BOILERPLATE_HEADING_RE.match(heading):
        return "boilerplate"
    return None


def clean_description(text: str) -> str:
    """Description without boilerplate sections and lines; never empty."""
    kept: list[str] = []
    skipping = False
    for line in text.splitlines():
        section = _section(line)
        if section is not None:
            skipping = section == "boilerplate"
        if BOILERPLATE_LINE_RE.search(line):
            continue
        if skipping and (section is not None or not DATES_RE.search(line)):
            continue
        stripped = line.strip()
        if stripped and (not kept or kept[-1] != stripped):
            kept.append(stripped)
    cleaned = "\n".join(kept)
    return cleaned or text.strip()
