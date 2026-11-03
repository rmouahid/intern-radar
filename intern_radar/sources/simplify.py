"""Simplify's public internship list (SimplifyJobs repositories on GitHub).

Simplify publishes every internship it tracks as one JSON file, refreshed
several times a day. Entries carry the employer, title, locations, terms
("Summer 2027"), category and a direct link to the employer's ATS, but no
description. Like Adzuna, the source is an aggregator: offers from watched
companies keep their tier, the others are discovery offers ("unlisted").
"""

import re
from collections.abc import Container, Iterable
from datetime import UTC, date, datetime
from typing import Any

import httpx

from intern_radar.models import Company, Job
from intern_radar.prefilter import ListingRules, is_internship_title
from intern_radar.sources.adzuna import Lookup, match_company
from intern_radar.sources.base import collect, get_json

LISTINGS = "https://raw.githubusercontent.com/{repo}/dev/.github/scripts/listings.json"
DEFAULT_REPO = "SimplifyJobs/Summer2027-Internships"
DEFAULT_CATEGORIES = ("AI/ML/Data", "Data Science, AI & Machine Learning")

# Months covered by each academic term (co-op terms in North America).
TERM_MONTHS = {"Winter": (1, 4), "Spring": (1, 5), "Summer": (5, 8), "Fall": (9, 12)}
TERM_RE = re.compile(r"^(Winter|Spring|Summer|Fall) (\d{4})$")

US_STATE_CODES = frozenset(
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE "
    "NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC PR".split()
)
US_STATE_NAMES = frozenset(
    "alabama alaska arizona arkansas california colorado connecticut delaware "
    "florida georgia hawaii idaho illinois indiana iowa kansas kentucky louisiana "
    "maine maryland massachusetts michigan minnesota mississippi missouri montana "
    "nebraska nevada ohio oklahoma oregon pennsylvania tennessee texas utah vermont "
    "virginia washington wisconsin wyoming".split()
) | {
    "new hampshire", "new jersey", "new mexico", "new york", "north carolina",
    "north dakota", "rhode island", "south carolina", "south dakota", "west virginia",
}  # fmt: skip
# Shorthands Simplify uses for US places.
US_PLACES = frozenset(
    {"nyc", "sf", "south sf", "united states", "usa", "remote in usa"}
)
US_PLACE_RE = re.compile(r", ([A-Z]{2})$")


def overlaps_window(term: str, start: date, end: date) -> bool:
    """True when the academic term ("Summer 2027") overlaps [start, end]."""
    match = TERM_RE.match(term.strip())
    if not match:
        return False
    first, last = TERM_MONTHS[match[1]]
    year = int(match[2])
    return date(year, first, 1) <= end and date(year, last, 28) >= start


def _is_us(place: str) -> bool:
    lowered = place.strip().lower()
    if lowered in US_PLACES or lowered in US_STATE_NAMES:
        return True
    code = US_PLACE_RE.search(place.strip())
    return bool(code and code[1] in US_STATE_CODES)


def is_us_only(locations: Iterable[str]) -> bool:
    """True when every place is in the United States, written the Simplify way
    ("Vienna, VA", "NYC", "New Mexico"). The country matcher of the pre-filter
    reads those as Austria or Mexico, so the source decides itself."""
    places = list(locations)
    return bool(places) and all(_is_us(place) for place in places)


def _posted_at(timestamp: Any) -> str | None:
    if not timestamp:
        return None
    return datetime.fromtimestamp(int(timestamp), UTC).date().isoformat()


def _description(item: dict[str, Any]) -> str:
    """Metadata standing in for the description, which Simplify does not carry."""
    lines = [
        "Listing from Simplify's internship list (no description available).",
        f"Terms: {', '.join(item.get('terms') or []) or 'unknown'}",
        f"Category: {item.get('category') or 'unknown'}",
        f"Degrees: {', '.join(item.get('degrees') or []) or 'unknown'}",
        f"Sponsorship: {item.get('sponsorship') or 'unknown'}",
        f"Locations: {'; '.join(item.get('locations') or []) or 'unknown'}",
    ]
    return "\n".join(lines)


class SimplifySource:
    def __init__(
        self,
        client: httpx.Client,
        lookup: Lookup,
        window: tuple[date, date],
        rules: ListingRules | None = None,
    ) -> None:
        self._client = client
        self._lookup = lookup
        self._window = window
        self._rules = rules

    def fetch(self, company: Company, known_ids: Container[str]) -> list[Job]:
        repo = company.params.get("repo", DEFAULT_REPO)
        categories = set(company.params.get("categories", DEFAULT_CATEGORIES))
        listings = get_json(self._client, "GET", LISTINGS.format(repo=repo))

        def convert(item: dict[str, Any]) -> Job | None:
            job_id = f"simplify:{item['id']}"
            title = item["title"].strip()
            if (
                job_id in known_ids
                or not (item.get("active") and item.get("is_visible"))
                or item.get("category") not in categories
                or not any(overlaps_window(t, *self._window) for t in item["terms"])
                or item.get("degrees") == ["PhD"]
                or not is_internship_title(title)
            ):
                return None
            locations = item.get("locations") or []
            location = "; ".join(locations)
            posted = _posted_at(item.get("date_posted"))
            if self._rules and not self._rules.keep(title, location, posted):
                return None
            name, tier = match_company(item["company_name"], self._lookup)
            if tier == "unlisted" and is_us_only(locations):
                return None
            return Job(
                id=job_id,
                company=name,
                tier=tier,
                title=title,
                location=location,
                url=item["url"],
                description=_description(item),
                source="simplify",
                posted_at=posted,
            )

        return collect(company, listings, convert)
