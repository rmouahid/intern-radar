from intern_radar.models import Company, Job
from intern_radar.sources.ashby import AshbySource
from tests.factories import mock_client

API = "https://api.ashbyhq.com/posting-api/job-board/cohere"
COMPANY = Company("Cohere", "A", "ashby", {"org": "cohere"})

BOARD = {
    "jobs": [
        {
            "id": "u1",
            "title": "Machine Learning Intern/Co-op (Winter 2027)",
            "location": "Toronto",
            "secondaryLocations": [{"location": "London"}],
            "publishedAt": "2026-09-15T18:21:37.401+00:00",
            "isListed": True,
            "jobUrl": "https://jobs.ashbyhq.com/cohere/u1",
            "descriptionPlain": "Work on LLMs.",
        },
        {
            "id": "u2",
            "title": "Research Intern",
            "location": "Toronto",
            "secondaryLocations": [],
            "publishedAt": "2026-09-15T00:00:00+00:00",
            "isListed": False,
            "jobUrl": "https://jobs.ashbyhq.com/cohere/u2",
            "descriptionPlain": "Hidden.",
        },
    ]
}


def test_fetch_keeps_listed_internships():
    client = mock_client({f"GET {API}": BOARD})
    assert AshbySource(client).fetch(COMPANY, known_ids=set()) == [
        Job(
            id="ashby:cohere:u1",
            company="Cohere",
            tier="A",
            title="Machine Learning Intern/Co-op (Winter 2027)",
            location="Toronto; London",
            url="https://jobs.ashbyhq.com/cohere/u1",
            description="Work on LLMs.",
            source="ashby",
            posted_at="2026-09-15",
        )
    ]
