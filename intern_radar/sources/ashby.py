"""Ashby job boards (api.ashbyhq.com)."""

from collections.abc import Container

import httpx

from intern_radar.models import Company, Job
from intern_radar.prefilter import is_internship_title
from intern_radar.sources.base import get_json, iso_date, require_param

API = "https://api.ashbyhq.com/posting-api/job-board/{org}"


class AshbySource:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def fetch(self, company: Company, known_ids: Container[str]) -> list[Job]:
        org = require_param(company, "org")
        board = get_json(self._client, "GET", API.format(org=org))
        jobs = []
        for item in board.get("jobs", []):
            job_id = f"ashby:{org}:{item['id']}"
            if (
                job_id in known_ids
                or not item.get("isListed", True)
                or not is_internship_title(item["title"])
            ):
                continue
            locations = [item.get("location", "")] + [
                loc.get("location", "") for loc in item.get("secondaryLocations") or []
            ]
            jobs.append(
                Job(
                    id=job_id,
                    company=company.name,
                    tier=company.tier,
                    title=item["title"].strip(),
                    location="; ".join(loc for loc in locations if loc),
                    url=item["jobUrl"],
                    description=item.get("descriptionPlain") or "",
                    source="ashby",
                    posted_at=iso_date(item.get("publishedAt")),
                )
            )
        return jobs
