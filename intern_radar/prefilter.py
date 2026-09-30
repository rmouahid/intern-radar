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
# A French country or region names the whole place ("Clichy, Ile-de-France, FRA").
FRENCH_MARKER_RE = re.compile(
    r"\bfrance\b|\bauvergne|\bprovence|\boccitanie\b|\bnouvelle[- ]aquitaine\b"
    r"|\bgrand[- ]est\b|\bbretagne\b|\bbrittany\b|\bnormandie\b|\bnormandy\b"
    r"|\bpays[- ]de[- ]la[- ]loire\b|\bcentre[- ]val[- ]de[- ]loire\b"
    r"|\bbourgogne\b|\bcorse\b",
    re.IGNORECASE,
)
FRENCH_COUNTRY_CODES = {"FR", "FRA"}
COMMA_RE = re.compile(r"\s*,\s*")
PLACE_SEPARATOR_RE = re.compile(r"\s*(?:[;|/&]|\band\b|\bor\b)\s*", re.IGNORECASE)
# Parts that say nothing about the country ("Paris, Île-de-France, France").
NEUTRAL_RE = re.compile(
    r"^(remote|hybrid|on-?site|office|europe|emea|eu|idf|[iî]le-de-france)$",
    re.IGNORECASE,
)


def is_internship_title(title: str) -> bool:
    return bool(TITLE_RE.search(title))


def _excluded(part: str) -> bool:
    return "exclud" in part.lower()


def _is_french(part: str) -> bool:
    return bool(FRANCE_RE.search(part)) and not _excluded(part)


def _names_france(part: str) -> bool:
    return not _excluded(part) and (
        part in FRENCH_COUNTRY_CODES or bool(FRENCH_MARKER_RE.search(part))
    )


def _split(text: str, separator: re.Pattern[str]) -> list[str]:
    return [p.strip() for p in separator.split(text) if p.strip()]


def is_france_only(location: str) -> bool:
    """True when the location names France and no place outside France.

    Places are separated by ";", "|", "/", "&", "and" or "or"; inside a place,
    commas separate city, region and country. A French country or region
    makes the whole place French, whatever its city. Without one, each
    comma-separated part counts on its own ("Paris, London" is two places).
    """
    french = others = 0
    for place in _split(location, PLACE_SEPARATOR_RE):
        parts = _split(place, COMMA_RE)
        if any(_names_france(p) for p in parts):
            french += 1
            continue
        for part in parts:
            if _is_french(part):
                french += 1
            elif not NEUTRAL_RE.match(part):
                others += 1
    return bool(french) and not others


def passes(job: Job) -> bool:
    return is_internship_title(job.title) and not is_france_only(job.location)
