from intern_radar.models import Company, Job
from intern_radar.sources.workable import WorkableSource
from tests.factories import mock_client

API = "https://apply.workable.com/api/v1/widget/accounts/huggingface"
COMPANY = Company("Hugging Face", "A", "workable", {"account": "huggingface"})

ACCOUNT = {
    "name": "Hugging Face",
    "jobs": [
        {
            "title": "ML Engineering Intern - EMEA Remote",
            "shortcode": "AB12",
            "url": "https://apply.workable.com/j/AB12",
            "published_on": "2026-07-30",
            "city": "",
            "country": "",
            "locations": [
                {"country": "Switzerland", "city": "Bern"},
                {"country": "United Kingdom", "city": "London"},
            ],
            "description": "<p>Open-source ML.</p>",
        },
        {
            "title": "Senior Engineer",
            "shortcode": "CD34",
            "url": "https://apply.workable.com/j/CD34",
            "published_on": "2026-07-30",
            "city": "Paris",
            "country": "France",
            "locations": [],
            "description": "<p>x</p>",
        },
    ],
}


def test_fetch_maps_workable_jobs():
    client = mock_client({f"GET {API}": ACCOUNT})
    assert WorkableSource(client).fetch(COMPANY, known_ids=set()) == [
        Job(
            id="workable:huggingface:AB12",
            company="Hugging Face",
            tier="A",
            title="ML Engineering Intern - EMEA Remote",
            location="Bern, Switzerland; London, United Kingdom",
            url="https://apply.workable.com/j/AB12",
            description="Open-source ML.",
            source="workable",
            posted_at="2026-07-30",
        )
    ]
