"""Cheap rule-based filter applied before any LLM call."""

import re

from intern_radar.models import Job

TITLE_RE = re.compile(
    r"\b(interns?|internships?|co-?ops?|stagiaires?|trainees?|placements?)\b",
    re.IGNORECASE,
)
FRANCE_RE = re.compile(
    r"\b(france|paris|lyon|marseille|toulouse|nice|nantes|strasbourg|montpellier"
    r"|bordeaux|lille|rennes|grenoble|sophia[- ]antipolis)\b",
    re.IGNORECASE,
)
LOCATION_SEPARATOR_RE = re.compile(r"\s*(?:[;,|/&]|\band\b|\bor\b)\s*", re.IGNORECASE)
# Parts that say nothing about the country ("Paris, Île-de-France, France").
NEUTRAL_RE = re.compile(
    r"^(remote|hybrid|on-?site|office|europe|emea|eu|idf|[iî]le-de-france)$",
    re.IGNORECASE,
)


def is_internship_title(title: str) -> bool:
    return bool(TITLE_RE.search(title))


def _is_french(part: str) -> bool:
    return bool(FRANCE_RE.search(part)) and "exclud" not in part.lower()


def is_france_only(location: str) -> bool:
    """True when the location names France and no place outside France."""
    parts = [p.strip() for p in LOCATION_SEPARATOR_RE.split(location) if p.strip()]
    french = [p for p in parts if _is_french(p)]
    others = [p for p in parts if not _is_french(p) and not NEUTRAL_RE.match(p)]
    return bool(french) and not others


def passes(job: Job) -> bool:
    return is_internship_title(job.title) and not is_france_only(job.location)
