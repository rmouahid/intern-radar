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


def group_key(company: str, title: str) -> str:
    text = DASHES_RE.sub("-", title.lower()).strip()
    while (stripped := PLACE_SUFFIX_RE.sub("", text)) != text:
        text = stripped
    words = NON_WORD_RE.sub(" ", text).strip()
    return f"{company.lower()}|{words}"


def group_scored(jobs: Iterable[ScoredJob]) -> list[list[ScoredJob]]:
    """Groups in order of their first member, members in input order."""
    groups: dict[str, list[ScoredJob]] = {}
    for scored in jobs:
        groups.setdefault(group_key(scored.job.company, scored.job.title), []).append(
            scored
        )
    return list(groups.values())
