"""Workday career sites (the cxs JSON API behind *.myworkdayjobs.com)."""

from collections.abc import Container

import httpx

from intern_radar.models import Company, Job
from intern_radar.prefilter import is_internship_title
from intern_radar.sources.base import get_json, html_to_text, require_param

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
            for posting in postings:
                title = posting.get("title")
                path = posting.get("externalPath")
                if not title or not path or not is_internship_title(title):
                    continue
                job_id = f"workday:{tenant}:{path}"
                if job_id in known_ids:
                    continue
                info = get_json(self._client, "GET", f"{base}{path}")["jobPostingInfo"]
                jobs.append(
                    Job(
                        id=job_id,
                        company=company.name,
                        tier=company.tier,
                        title=title.strip(),
                        location=info.get("location")
                        or posting.get("locationsText", ""),
                        url=info.get("externalUrl") or f"https://{host}/{site}{path}",
                        description=html_to_text(info.get("jobDescription") or ""),
                        source="workday",
                        posted_at=info.get("startDate"),
                    )
                )
            if len(postings) < PAGE_SIZE or (page + 1) * PAGE_SIZE >= total:
                break
        return jobs
