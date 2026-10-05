"""Adzuna job search API, a catch-all for companies without a usable feed.

The search targets the watched companies that have no public feed: it asks
for "intern" offers mentioning their names or aliases, then keeps only the
offers whose employer is a watched company. Generic results (thousands of
employers outside the watch list) would only cost LLM scoring.
"""

import logging
import re
from collections.abc import Container
from typing import Any

import httpx

from intern_radar.models import Company, Job, Tier
from intern_radar.prefilter import is_internship_title
from intern_radar.sources.base import (
    SourceError,
    collect,
    get_json,
    html_to_text,
    iso_date,
)

log = logging.getLogger(__name__)

API = "https://api.adzuna.com/v1/api/jobs/{country}/search/1"
DISCOVERY_TERMS = "machine learning ai llm nlp genai data scientist deep learning"
DEFAULT_COUNTRIES = (
    "gb",
    "us",
    "ca",
    "sg",
    "de",
    "nl",
    "ch",
    "es",
    "it",
    "at",
    "be",
    "pl",
    "au",
    "nz",
)

Lookup = dict[str, tuple[str, Tier]]
MAX_DAYS_OLD = 14
# Words of company names that match far too many offers on their own.
GENERIC_WORDS = {
    "ai",
    "group",
    "consulting",
    "securities",
    "chase",
    "labs",
    "limited",
    "holdings",
    "international",
    "research",
    "advanced",
    "micro",
    "devices",
    "black",
    "forest",
    "two",
}


def search_terms(companies: list[Company]) -> str:
    """Words of the names and aliases of companies without a feed."""
    words: dict[str, None] = {}
    for company in companies:
        if company.source != "none":
            continue
        for name in [company.name, *company.params.get("aliases", [])]:
            for word in re.findall(r"[\w&.-]+", name.lower()):
                if len(word) > 2 and word not in GENERIC_WORDS:
                    words.setdefault(word)
    return " ".join(words)


def company_lookup(companies: list[Company]) -> Lookup:
    lookup: Lookup = {}
    for company in companies:
        if company.tier == "unlisted":
            continue
        for name in [company.name, *company.params.get("aliases", [])]:
            lookup[name.lower()] = (company.name, company.tier)
    return lookup


def match_company(employer: str, lookup: Lookup) -> tuple[str, Tier]:
    lowered = employer.lower()
    for name, match in lookup.items():
        if re.search(rf"\b{re.escape(name)}\b", lowered):
            return match
    return (employer or "Unknown employer", "unlisted")


class AdzunaSource:
    def __init__(
        self,
        client: httpx.Client,
        app_id: str | None,
        app_key: str | None,
        lookup: Lookup,
        terms: str,
        discovery: bool = False,
    ) -> None:
        """`discovery` adds, per country, a generic AI query whose offers from
        employers outside the watch list are kept as tier "unlisted"."""
        self._client = client
        self._app_id = app_id
        self._app_key = app_key
        self._lookup = lookup
        self._terms = terms
        self._discovery = discovery

    def fetch(self, company: Company, known_ids: Container[str]) -> list[Job]:
        if not (self._app_id and self._app_key):
            raise SourceError("adzuna_app_id / adzuna_app_key missing in profile.yaml")

        def converter(keep_unlisted: bool):
            def convert(item: dict[str, Any]) -> Job | None:
                return self._convert(item, known_ids, keep_unlisted)

            return convert

        jobs: list[Job] = []
        seen: set[str] = set()
        queries = [(self._terms or DISCOVERY_TERMS, False)]
        if self._discovery:
            queries.append((DISCOVERY_TERMS, True))
        errors: list[SourceError] = []
        attempts = 0
        for country in company.params.get("countries", DEFAULT_COUNTRIES):
            for terms, keep_unlisted in queries:
                attempts += 1
                try:
                    data = self._search(country, terms)
                except SourceError as exc:
                    # One country down must not cost every other country.
                    log.warning("Adzuna %s skipped: %s", country, exc)
                    errors.append(exc)
                    continue
                for job in collect(
                    company, data.get("results", []), converter(keep_unlisted)
                ):
                    if job.id not in seen:
                        seen.add(job.id)
                        jobs.append(job)
        if errors and len(errors) == attempts:
            raise errors[0]
        return jobs

    def _search(self, country: str, terms: str) -> dict[str, Any]:
        return get_json(
            self._client,
            "GET",
            API.format(country=country),
            params={
                "app_id": self._app_id,
                "app_key": self._app_key,
                "results_per_page": 50,
                "what": "intern",
                "what_or": terms,
                "max_days_old": MAX_DAYS_OLD,
                "content-type": "application/json",
            },
        )

    def _convert(
        self, item: dict[str, Any], known_ids: Container[str], keep_unlisted: bool
    ) -> Job | None:
        """Watched employers from the targeted query; employers outside the
        watch list only from the discovery query."""
        job_id = f"adzuna:{item['id']}"
        title = html_to_text(item.get("title", ""))
        if job_id in known_ids or not is_internship_title(title):
            return None
        employer = (item.get("company") or {}).get("display_name", "")
        name, tier = match_company(employer, self._lookup)
        if (tier == "unlisted") != keep_unlisted:
            return None
        return Job(
            id=job_id,
            company=name,
            tier=tier,
            title=title,
            location=(item.get("location") or {}).get("display_name", ""),
            url=item["redirect_url"],
            description=html_to_text(item.get("description", "")),
            source="adzuna",
            posted_at=iso_date(item.get("created")),
        )
