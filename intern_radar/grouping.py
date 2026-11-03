"""Posting groups: one internship that a company publishes once per country.

Amazon, NVIDIA or Microsoft post the same internship several times
("… Intern - Germany", "… Intern - UK"). Members of a group share one LLM
assessment and one notification.
"""

import re
from collections.abc import Iterable

from intern_radar.models import ScoredJob

PLACES = (
    "remote|hybrid|emea|apac|latam|europe|eu|uk|us|usa|united states|united kingdom"
    "|canada|mexico|brazil|argentina|chile|colombia|ireland|germany|france|spain"
    "|italy|portugal|netherlands|belgium|luxembourg|switzerland|austria|poland"
    "|czech republic|czechia|romania|hungary|greece|sweden|norway|denmark|finland"
    "|estonia|israel|turkey|uae|united arab emirates|saudi arabia|egypt|morocco"
    "|south africa|nigeria|kenya|india|china|hong kong|taiwan|japan|korea"
    "|south korea|singapore|malaysia|vietnam|thailand|indonesia|philippines"
    "|australia|new zealand"
)
# A trailing "- Germany", ", Singapore" or "(Remote)" names where, not what.
PLACE_SUFFIX_RE = re.compile(
    rf"(?:\s*[-,|/]\s*(?:{PLACES})|\s*\((?:{PLACES})\))\s*$", re.IGNORECASE
)
DASHES_RE = re.compile(r"[‐-―]")
NON_WORD_RE = re.compile(r"[^0-9a-z]+")

# Identifiers of one posting in its ATS URL, whatever the domain in front:
# Ashby and Lever UUIDs, Workday requisitions ("..._JR2004567", "..._R-12345"),
# Greenhouse and other numeric ids ("/jobs/7311111", "?gh_jid=7311111").
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
WORKDAY_REQ_RE = re.compile(r"_([A-Z]{1,4}-?\d{4,}(?:-\d+)?)(?=[/?#]|$)")
NUMERIC_ID_RE = re.compile(r"(?<![\d.])(\d{7,})(?![\d.])")


def group_key(company: str, title: str) -> str:
    text = DASHES_RE.sub("-", title.lower()).strip()
    while (stripped := PLACE_SUFFIX_RE.sub("", text)) != text:
        text = stripped
    words = NON_WORD_RE.sub(" ", text).strip()
    return f"{company.lower()}|{words}"


def posting_key(url: str) -> str | None:
    """The posting identifier found in an offer URL, or None.

    Aggregators (Adzuna, Simplify) rewrite titles but often link to the
    employer's ATS: the same identifier then names the same offer.
    """
    if match := UUID_RE.search(url.lower()):
        return match[0]
    if match := WORKDAY_REQ_RE.search(url):
        return match[1].lower()
    if match := NUMERIC_ID_RE.search(url):
        return match[1]
    return None


def group_scored(jobs: Iterable[ScoredJob]) -> list[list[ScoredJob]]:
    """Groups in order of their first member, members in input order."""
    groups: dict[str, list[ScoredJob]] = {}
    for scored in jobs:
        groups.setdefault(group_key(scored.job.company, scored.job.title), []).append(
            scored
        )
    return list(groups.values())
