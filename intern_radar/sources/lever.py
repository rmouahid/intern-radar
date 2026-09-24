"""Lever job sites (api.lever.co)."""

from collections.abc import Container
from datetime import UTC, datetime

import httpx

from intern_radar.models import Company, Job
from intern_radar.prefilter import is_internship_title
from intern_radar.sources.base import get_json, html_to_text, require_param

API = "https://api.lever.co/v0/postings/{site}"


def _description(item: dict) -> str:
    parts = [item.get("descriptionPlain") or ""]
    for block in item.get("lists") or []:
        parts.append(block.get("text", ""))
        parts.append(html_to_text(block.get("content", "")))
    parts.append(item.get("additionalPlain") or "")
    return "\n".join(part.strip() for part in parts if part.strip())


class LeverSource:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def fetch(self, company: Company, known_ids: Container[str]) -> list[Job]:
        site = require_param(company, "site")
        postings = get_json(
            self._client, "GET", API.format(site=site), params={"mode": "json"}
        )
        jobs = []
        for item in postings:
            job_id = f"lever:{site}:{item['id']}"
            if job_id in known_ids or not is_internship_title(item["text"]):
                continue
            categories = item.get("categories") or {}
            locations = categories.get("allLocations") or [
                categories.get("location", "")
            ]
            created = item.get("createdAt")
            jobs.append(
                Job(
                    id=job_id,
                    company=company.name,
                    tier=company.tier,
                    title=item["text"].strip(),
                    location="; ".join(loc for loc in locations if loc),
                    url=item["hostedUrl"],
                    description=_description(item),
                    source="lever",
                    posted_at=(
                        datetime.fromtimestamp(created / 1000, UTC).date().isoformat()
                        if created
                        else None
                    ),
                )
            )
        return jobs
