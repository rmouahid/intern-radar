import httpx

from intern_radar.models import Company, Job
from intern_radar.sources.amazon import AmazonSource
from tests.factories import mock_client

API = "https://www.amazon.jobs/en/search.json"
COMPANY = Company("Amazon", "S", "amazon", {})


def search(request: httpx.Request) -> httpx.Response:
    assert request.url.params["base_query"] == "intern"
    offset = int(request.url.params["offset"])
    jobs = (
        []
        if offset
        else [
            {
                "id_icims": "10512549",
                "title": "Applied Scientist Intern",
                "normalized_location": "London, GBR",
                "job_path": "/en/jobs/10512549/applied-scientist-intern",
                "posted_date": "August 24, 2026",
                "description": "Research on LLMs.<br/>6 months.",
                "basic_qualifications": "- Enrolled in a Master's degree",
                "preferred_qualifications": "",
            },
            {
                "id_icims": "2",
                "title": "Area Manager",
                "normalized_location": "X",
                "job_path": "/en/jobs/2/area-manager",
                "posted_date": "bad date",
                "description": "",
                "basic_qualifications": "",
                "preferred_qualifications": "",
            },
        ]
    )
    return httpx.Response(200, json={"hits": 2, "jobs": jobs})


def test_fetch_maps_amazon_jobs():
    jobs = AmazonSource(mock_client({f"GET {API}": search})).fetch(COMPANY, set())
    assert jobs == [
        Job(
            id="amazon:10512549",
            company="Amazon",
            tier="S",
            title="Applied Scientist Intern",
            location="London, GBR",
            url="https://www.amazon.jobs/en/jobs/10512549/applied-scientist-intern",
            description="Research on LLMs.\n6 months.\n- Enrolled in a Master's degree",
            source="amazon",
            posted_at="2026-08-24",
        )
    ]
