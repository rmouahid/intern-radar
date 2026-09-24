from intern_radar.models import Company, Job
from intern_radar.sources.greenhouse import GreenhouseSource
from tests.factories import mock_client

API = "https://boards-api.greenhouse.io/v1/boards/stripe/jobs"
COMPANY = Company("Stripe", "A", "greenhouse", {"board": "stripe"})

LIST = {
    "jobs": [
        {
            "id": 11,
            "title": "Machine Learning Intern",
            "location": {"name": "Dublin"},
            "absolute_url": "https://stripe.com/jobs/11",
            "first_published": "2026-09-10T09:00:00-04:00",
        },
        {
            "id": 12,
            "title": "Internal Tools Engineer",
            "location": {"name": "Dublin"},
            "absolute_url": "https://stripe.com/jobs/12",
            "first_published": "2026-09-11T09:00:00-04:00",
        },
        {
            "id": 13,
            "title": "Data Science Intern",
            "location": {"name": "Toronto"},
            "absolute_url": "https://stripe.com/jobs/13",
            "first_published": "2026-09-12T09:00:00-04:00",
        },
    ]
}
DETAIL_11 = {
    "id": 11,
    "title": "Machine Learning Intern",
    "location": {"name": "Dublin"},
    "absolute_url": "https://stripe.com/jobs/11",
    "first_published": "2026-09-10T09:00:00-04:00",
    "content": "&lt;p&gt;Train models.&lt;/p&gt;",
}


def test_fetch_returns_new_internship_jobs_with_details():
    client = mock_client({f"GET {API}": LIST, f"GET {API}/11": DETAIL_11})
    jobs = GreenhouseSource(client).fetch(COMPANY, known_ids={"greenhouse:stripe:13"})
    assert jobs == [
        Job(
            id="greenhouse:stripe:11",
            company="Stripe",
            tier="A",
            title="Machine Learning Intern",
            location="Dublin",
            url="https://stripe.com/jobs/11",
            description="Train models.",
            source="greenhouse",
            posted_at="2026-09-10",
        )
    ]
