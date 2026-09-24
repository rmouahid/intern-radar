"""Workable accounts (apply.workable.com widget API)."""

from collections.abc import Container

import httpx

from intern_radar.models import Company, Job
from intern_radar.prefilter import is_internship_title
from intern_radar.sources.base import get_json, html_to_text, require_param

API = "https://apply.workable.com/api/v1/widget/accounts/{account}"


def _place(city: str, country: str) -> str:
    return ", ".join(part for part in (city, country) if part)


class WorkableSource:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def fetch(self, company: Company, known_ids: Container[str]) -> list[Job]:
        account = require_param(company, "account")
        data = get_json(
            self._client,
            "GET",
            API.format(account=account),
            params={"details": "true"},
        )
        jobs = []
        for item in data.get("jobs", []):
            job_id = f"workable:{account}:{item['shortcode']}"
            if job_id in known_ids or not is_internship_title(item["title"]):
                continue
            places = [
                _place(loc.get("city", ""), loc.get("country", ""))
                for loc in item.get("locations") or []
            ] or [_place(item.get("city", ""), item.get("country", ""))]
            jobs.append(
                Job(
                    id=job_id,
                    company=company.name,
                    tier=company.tier,
                    title=item["title"].strip(),
                    location="; ".join(place for place in places if place),
                    url=item["url"],
                    description=html_to_text(item.get("description") or ""),
                    source="workable",
                    posted_at=item.get("published_on"),
                )
            )
        return jobs
