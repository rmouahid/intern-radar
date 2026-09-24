from intern_radar.models import Company, Job
from intern_radar.sources.lever import LeverSource
from tests.factories import mock_client

API = "https://api.lever.co/v0/postings/palantir"
COMPANY = Company("Palantir", "A", "lever", {"site": "palantir"})

POSTINGS = [
    {
        "id": "abc",
        "text": "Software Engineer Intern - Singapore",
        "categories": {
            "location": "Singapore, Singapore",
            "allLocations": ["Singapore, Singapore", "London, UK"],
        },
        "hostedUrl": "https://jobs.lever.co/palantir/abc",
        "createdAt": 1786469891368,
        "descriptionPlain": "Build software.",
        "lists": [{"text": "Requirements", "content": "<li>Python</li>"}],
        "additionalPlain": "Visa sponsorship available.",
    },
    {
        "id": "def",
        "text": "Administrative Partner",
        "categories": {"location": "Singapore, Singapore"},
        "hostedUrl": "https://jobs.lever.co/palantir/def",
        "createdAt": 1786469891368,
        "descriptionPlain": "",
    },
]


def test_fetch_maps_lever_postings():
    client = mock_client({f"GET {API}": POSTINGS})
    assert LeverSource(client).fetch(COMPANY, known_ids=set()) == [
        Job(
            id="lever:palantir:abc",
            company="Palantir",
            tier="A",
            title="Software Engineer Intern - Singapore",
            location="Singapore, Singapore; London, UK",
            url="https://jobs.lever.co/palantir/abc",
            description="Build software.\nRequirements\nPython\n"
            "Visa sponsorship available.",
            source="lever",
            posted_at="2026-08-11",
        )
    ]


def test_a_malformed_posting_is_skipped_not_fatal():
    broken = {"id": "zzz", "text": "Research Intern", "categories": {}}
    client = mock_client({f"GET {API}": [broken, *POSTINGS]})
    jobs = LeverSource(client).fetch(COMPANY, known_ids=set())
    assert [job.id for job in jobs] == ["lever:palantir:abc"]
