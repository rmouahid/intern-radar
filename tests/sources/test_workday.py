import json

import httpx

from intern_radar.models import Company, Job
from intern_radar.sources.workday import WorkdaySource
from tests.factories import mock_client

HOST = "nvidia.wd5.myworkdayjobs.com"
BASE = f"https://{HOST}/wday/cxs/nvidia/NVIDIAExternalCareerSite"
PUBLIC = f"https://{HOST}/en-US/NVIDIAExternalCareerSite/job/DL-Intern_JR1"
COMPANY = Company(
    "NVIDIA",
    "S",
    "workday",
    {"host": HOST, "tenant": "nvidia", "site": "NVIDIAExternalCareerSite"},
)


def search(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    assert body["searchText"] == "intern" and body["limit"] == 20
    if body["offset"] == 0:
        postings = [
            {"title": f"Other Role {i}", "externalPath": f"/job/x/{i}"}
            for i in range(19)
        ]
        postings.append(
            {
                "title": "Deep Learning Intern - 2027",
                "externalPath": "/job/UK-Reading/DL-Intern_JR1",
            }
        )
        return httpx.Response(200, json={"total": 21, "jobPostings": postings})
    return httpx.Response(
        200,
        json={
            "total": 0,
            "jobPostings": [
                {"externalPath": "/job/x/untitled"},
                {"title": "Hardware Intern", "externalPath": "/job/x/known"},
            ],
        },
    )


DETAIL = {
    "jobPostingInfo": {
        "title": "Deep Learning Intern - 2027",
        "jobReqId": "JR1",
        "location": "UK, Reading",
        "startDate": "2026-09-16",
        "jobDescription": "<p>Train LLMs.</p>",
        "externalUrl": PUBLIC,
    }
}


def test_fetch_pages_with_first_page_total_and_reads_details():
    client = mock_client(
        {
            f"POST {BASE}/jobs": search,
            f"GET {BASE}/job/UK-Reading/DL-Intern_JR1": DETAIL,
        }
    )
    jobs = WorkdaySource(client).fetch(
        COMPANY, known_ids={"workday:nvidia:/job/x/known"}
    )
    assert jobs == [
        Job(
            id="workday:nvidia:/job/UK-Reading/DL-Intern_JR1",
            company="NVIDIA",
            tier="S",
            title="Deep Learning Intern - 2027",
            location="UK, Reading",
            url=PUBLIC,
            description="Train LLMs.",
            source="workday",
            posted_at="2026-09-16",
        )
    ]


def test_multi_location_postings_keep_every_office():
    detail = {
        "jobPostingInfo": {
            **DETAIL["jobPostingInfo"],
            "location": "France, Paris",
            "additionalLocations": ["UK, Reading", "Germany, Munich"],
        }
    }
    client = mock_client(
        {
            f"POST {BASE}/jobs": search,
            f"GET {BASE}/job/UK-Reading/DL-Intern_JR1": detail,
        }
    )
    [job] = WorkdaySource(client).fetch(
        COMPANY, known_ids={"workday:nvidia:/job/x/known"}
    )
    assert job.location == "France, Paris; UK, Reading; Germany, Munich"


def test_a_failing_detail_request_skips_only_that_posting():
    client = mock_client({f"POST {BASE}/jobs": search})  # detail answers 404
    assert WorkdaySource(client).fetch(COMPANY, known_ids=set()) == []
    client = mock_client(
        {
            f"POST {BASE}/jobs": search,
            f"GET {BASE}/job/UK-Reading/DL-Intern_JR1": DETAIL,
        }
    )
    jobs = WorkdaySource(client).fetch(COMPANY, known_ids=set())
    assert [job.title for job in jobs] == ["Deep Learning Intern - 2027"]
