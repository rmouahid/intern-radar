"""Microsoft careers search API (apply.careers.microsoft.com)."""

from collections.abc import Container
from datetime import UTC, datetime

import httpx

from intern_radar.models import Company, Job
from intern_radar.prefilter import is_internship_title
from intern_radar.sources.base import get_json

API = "https://apply.careers.microsoft.com/api/pcsx/search"
SITE = "https://apply.careers.microsoft.com"
MAX_PAGES = 10


class MicrosoftSource:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def fetch(self, company: Company, known_ids: Container[str]) -> list[Job]:
        jobs: list[Job] = []
        start = 0
        for _ in range(MAX_PAGES):
            data = get_json(
                self._client,
                "GET",
                API,
                params={"domain": "microsoft.com", "query": "intern", "start": start},
            )
            positions = (data.get("data") or {}).get("positions", [])
            if not positions:
                break
            for item in positions:
                job_id = f"microsoft:{item['id']}"
                if job_id in known_ids or not is_internship_title(item["name"]):
                    continue
                posted = item.get("postedTs")
                jobs.append(
                    Job(
                        id=job_id,
                        company=company.name,
                        tier=company.tier,
                        title=item["name"].strip(),
                        location="; ".join(item.get("locations") or []),
                        url=f"{SITE}{item['positionUrl']}",
                        description="",
                        source="microsoft",
                        posted_at=(
                            datetime.fromtimestamp(posted, UTC).date().isoformat()
                            if posted
                            else None
                        ),
                    )
                )
            start += len(positions)
        return jobs
