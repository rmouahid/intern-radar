"""Adzuna job search API, a catch-all for companies without a usable feed."""

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

API = "https://api.adzuna.com/v1/api/jobs/{country}/search/1"
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
)

Lookup = dict[str, tuple[str, Tier]]


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
    ) -> None:
        self._client = client
        self._app_id = app_id
        self._app_key = app_key
        self._lookup = lookup

    def fetch(self, company: Company, known_ids: Container[str]) -> list[Job]:
        if not (self._app_id and self._app_key):
            raise SourceError("adzuna_app_id / adzuna_app_key missing in profile.yaml")

        def convert(item: dict[str, Any]) -> Job | None:
            job_id = f"adzuna:{item['id']}"
            title = html_to_text(item.get("title", ""))
            if job_id in known_ids or not is_internship_title(title):
                return None
            employer = (item.get("company") or {}).get("display_name", "")
            name, tier = match_company(employer, self._lookup)
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

        jobs: list[Job] = []
        for country in company.params.get("countries", DEFAULT_COUNTRIES):
            data = get_json(
                self._client,
                "GET",
                API.format(country=country),
                params={
                    "app_id": self._app_id,
                    "app_key": self._app_key,
                    "results_per_page": 50,
                    "what": "intern",
                    "what_or": "machine learning ai data llm",
                    "max_days_old": 7,
                    "sort_by": "date",
                    "content-type": "application/json",
                },
            )
            jobs.extend(collect(company, data.get("results", []), convert))
        return jobs
