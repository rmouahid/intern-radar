"""Workday career sites (the cxs JSON API behind *.myworkdayjobs.com)."""

from collections.abc import Container
from typing import Any

import httpx

from intern_radar.models import Company, Job
from intern_radar.prefilter import is_internship_title
from intern_radar.sources.base import collect, get_json, html_to_text, require_param

PAGE_SIZE = 20
MAX_PAGES = 5  # results are relevance-sorted; internships come first


class WorkdaySource:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def fetch(self, company: Company, known_ids: Container[str]) -> list[Job]:
        host = require_param(company, "host")
        tenant = require_param(company, "tenant")
        site = require_param(company, "site")
        base = f"https://{host}/wday/cxs/{tenant}/{site}"

        def convert(posting: dict[str, Any]) -> Job | None:
            title = posting.get("title")
            path = posting.get("externalPath")
            if not title or not path or not is_internship_title(title):
                return None
            job_id = f"workday:{tenant}:{path}"
            if job_id in known_ids:
                return None
            info = get_json(self._client, "GET", f"{base}{path}")["jobPostingInfo"]
            offices = [info.get("location"), *(info.get("additionalLocations") or [])]
            return Job(
                id=job_id,
                company=company.name,
                tier=company.tier,
                title=title.strip(),
                location="; ".join(o for o in offices if o)
                or posting.get("locationsText", ""),
                url=info.get("externalUrl") or f"https://{host}/{site}{path}",
                description=html_to_text(info.get("jobDescription") or ""),
                source="workday",
                posted_at=info.get("startDate"),
            )

        jobs: list[Job] = []
        total = 0
        for page in range(MAX_PAGES):
            data = get_json(
                self._client,
                "POST",
                f"{base}/jobs",
                json={
                    "appliedFacets": {},
                    "limit": PAGE_SIZE,
                    "offset": page * PAGE_SIZE,
                    "searchText": "intern",
                },
            )
            if page == 0:  # Workday only reports the total on the first page
                total = data.get("total", 0)
            postings = data.get("jobPostings", [])
            jobs.extend(collect(company, postings, convert))
            if len(postings) < PAGE_SIZE or (page + 1) * PAGE_SIZE >= total:
                break
        return jobs
