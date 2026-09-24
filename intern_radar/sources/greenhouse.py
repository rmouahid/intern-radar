"""Greenhouse job boards (boards-api.greenhouse.io)."""

from collections.abc import Container
from typing import Any

import httpx

from intern_radar.models import Company, Job
from intern_radar.prefilter import is_internship_title
from intern_radar.sources.base import (
    collect,
    get_json,
    html_to_text,
    iso_date,
    require_param,
)

API = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs"


class GreenhouseSource:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def fetch(self, company: Company, known_ids: Container[str]) -> list[Job]:
        board = require_param(company, "board")
        url = API.format(board=board)
        listing = get_json(self._client, "GET", url)

        def convert(item: dict[str, Any]) -> Job | None:
            job_id = f"greenhouse:{board}:{item['id']}"
            if job_id in known_ids or not is_internship_title(item["title"]):
                return None
            detail = get_json(self._client, "GET", f"{url}/{item['id']}")
            return Job(
                id=job_id,
                company=company.name,
                tier=company.tier,
                title=item["title"].strip(),
                location=(item.get("location") or {}).get("name", ""),
                url=item["absolute_url"],
                description=html_to_text(detail.get("content") or ""),
                source="greenhouse",
                posted_at=iso_date(
                    item.get("first_published") or item.get("updated_at")
                ),
            )

        return collect(company, listing.get("jobs", []), convert)
