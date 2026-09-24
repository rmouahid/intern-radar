"""amazon.jobs search API."""

from collections.abc import Container
from datetime import datetime

import httpx

from intern_radar.models import Company, Job
from intern_radar.prefilter import is_internship_title
from intern_radar.sources.base import get_json, html_to_text

API = "https://www.amazon.jobs/en/search.json"
PAGE_SIZE = 100
MAX_PAGES = 5


def _posted(value: str | None) -> str | None:
    try:
        return datetime.strptime(value or "", "%B %d, %Y").date().isoformat()
    except ValueError:
        return None


class AmazonSource:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def fetch(self, company: Company, known_ids: Container[str]) -> list[Job]:
        jobs: list[Job] = []
        for page in range(MAX_PAGES):
            offset = page * PAGE_SIZE
            data = get_json(
                self._client,
                "GET",
                API,
                params={
                    "base_query": "intern",
                    "result_limit": PAGE_SIZE,
                    "offset": offset,
                    "sort": "recent",
                },
            )
            items = data.get("jobs", [])
            for item in items:
                job_id = f"amazon:{item['id_icims']}"
                if job_id in known_ids or not is_internship_title(item["title"]):
                    continue
                parts = (
                    item.get("description", ""),
                    item.get("basic_qualifications", ""),
                    item.get("preferred_qualifications", ""),
                )
                jobs.append(
                    Job(
                        id=job_id,
                        company=company.name,
                        tier=company.tier,
                        title=item["title"].strip(),
                        location=item.get("normalized_location")
                        or item.get("location", ""),
                        url=f"https://www.amazon.jobs{item['job_path']}",
                        description=html_to_text("<br/>".join(p for p in parts if p)),
                        source="amazon",
                        posted_at=_posted(item.get("posted_date")),
                    )
                )
            if len(items) < PAGE_SIZE or offset + PAGE_SIZE >= data.get("hits", 0):
                break
        return jobs
