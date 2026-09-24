import httpx

from intern_radar.models import Company, Job
from intern_radar.sources.smartrecruiters import SmartRecruitersSource
from tests.factories import mock_client

API = "https://api.smartrecruiters.com/v1/companies/BoschGroup/postings"
COMPANY = Company("Bosch", "B", "smartrecruiters", {"company_id": "BoschGroup"})


def listing(request: httpx.Request) -> httpx.Response:
    offset = int(request.url.params["offset"])
    assert request.url.params["q"] == "intern"
    pages = {
        0: [
            {
                "id": "1",
                "name": "AI Research Intern",
                "location": {"fullLocation": "Renningen, BW, Germany"},
                "releasedDate": "2026-09-24T14:50:48.550Z",
            },
            {
                "id": "2",
                "name": "System Architect",
                "location": {"fullLocation": "Stuttgart, Germany"},
                "releasedDate": "2026-09-24T14:50:48.550Z",
            },
        ],
    }
    content = pages.get(offset, [])
    return httpx.Response(
        200,
        json={"offset": offset, "limit": 100, "totalFound": 2, "content": content},
    )


DETAIL = {
    "id": "1",
    "postingUrl": "https://jobs.smartrecruiters.com/BoschGroup/1-ai-research-intern",
    "jobAd": {
        "sections": {
            "jobDescription": {
                "title": "Job Description",
                "text": "<p>LLM research.</p>",
            },
            "qualifications": {
                "title": "Qualifications",
                "text": "<ul><li>Python</li></ul>",
            },
        }
    },
}


def test_fetch_lists_then_reads_internship_details():
    client = mock_client({f"GET {API}": listing, f"GET {API}/1": DETAIL})
    assert SmartRecruitersSource(client).fetch(COMPANY, known_ids=set()) == [
        Job(
            id="smartrecruiters:BoschGroup:1",
            company="Bosch",
            tier="B",
            title="AI Research Intern",
            location="Renningen, BW, Germany",
            url="https://jobs.smartrecruiters.com/BoschGroup/1-ai-research-intern",
            description="LLM research.\nPython",
            source="smartrecruiters",
            posted_at="2026-09-24",
        )
    ]
