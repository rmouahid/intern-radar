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
LOCATION_SEPARATOR_RE = re.compile(r"\s*(?:;|\||/|\bor\b)\s*", re.IGNORECASE)


def is_internship_title(title: str) -> bool:
    return bool(TITLE_RE.search(title))


def is_france_only(location: str) -> bool:
    """True when every listed location is in France."""
    segments = [s for s in LOCATION_SEPARATOR_RE.split(location) if s.strip()]
    return bool(segments) and all(FRANCE_RE.search(s) for s in segments)


def passes(job: Job) -> bool:
    return is_internship_title(job.title) and not is_france_only(job.location)
