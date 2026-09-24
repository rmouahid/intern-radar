import httpx

from intern_radar.models import Company, Job
from intern_radar.sources.microsoft import MicrosoftSource
from tests.factories import mock_client

API = "https://apply.careers.microsoft.com/api/pcsx/search"
COMPANY = Company("Microsoft", "S", "microsoft", {})


def search(request: httpx.Request) -> httpx.Response:
    start = int(request.url.params["start"])
    positions = (
        []
        if start
        else [
            {
                "id": 1970393556917520,
                "name": "Data Science INTERN",
                "locations": ["United Kingdom, London", "Ireland, Dublin"],
                "postedTs": 1789031303,
                "positionUrl": "/careers/job/1970393556917520",
            },
            {
                "id": 7,
                "name": "Account Executive",
                "locations": ["US"],
                "postedTs": 1789031303,
                "positionUrl": "/careers/job/7",
            },
        ]
    )
    return httpx.Response(200, json={"status": 200, "data": {"positions": positions}})


def test_fetch_maps_microsoft_positions():
    jobs = MicrosoftSource(mock_client({f"GET {API}": search})).fetch(COMPANY, set())
    assert jobs == [
        Job(
            id="microsoft:1970393556917520",
            company="Microsoft",
            tier="S",
            title="Data Science INTERN",
            location="United Kingdom, London; Ireland, Dublin",
            url="https://apply.careers.microsoft.com/careers/job/1970393556917520",
            description="",
            source="microsoft",
            posted_at="2026-09-10",
        )
    ]
