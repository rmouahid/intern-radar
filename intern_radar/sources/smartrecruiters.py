"""SmartRecruiters public postings API."""

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

API = "https://api.smartrecruiters.com/v1/companies/{company_id}/postings"
PAGE_SIZE = 100
MAX_PAGES = 3


class SmartRecruitersSource:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def fetch(self, company: Company, known_ids: Container[str]) -> list[Job]:
        company_id = require_param(company, "company_id")
        url = API.format(company_id=company_id)

        def convert(item: dict[str, Any]) -> Job | None:
            job_id = f"smartrecruiters:{company_id}:{item['id']}"
            if job_id in known_ids or not is_internship_title(item["name"]):
                return None
            detail = get_json(self._client, "GET", f"{url}/{item['id']}")
            sections = (detail.get("jobAd") or {}).get("sections") or {}
            description = "\n".join(
                html_to_text(section.get("text", ""))
                for key, section in sections.items()
                if key != "companyDescription"
            )
            return Job(
                id=job_id,
                company=company.name,
                tier=company.tier,
                title=item["name"].strip(),
                location=(item.get("location") or {}).get("fullLocation", ""),
                url=detail.get("postingUrl")
                or f"https://jobs.smartrecruiters.com/{company_id}/{item['id']}",
                description=description,
                source="smartrecruiters",
                posted_at=iso_date(item.get("releasedDate")),
            )

        jobs: list[Job] = []
        for page in range(MAX_PAGES):
            data = get_json(
                self._client,
                "GET",
                url,
                params={"q": "intern", "limit": PAGE_SIZE, "offset": page * PAGE_SIZE},
            )
            items = data.get("content", [])
            jobs.extend(collect(company, items, convert))
            if len(items) < PAGE_SIZE:
                break
        return jobs
