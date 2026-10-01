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


def test_offers_rejected_by_the_listing_rules_skip_the_detail_request():
    from datetime import date

    from intern_radar.prefilter import ListingRules
    from intern_radar.sources.greenhouse import GreenhouseSource

    listing = {
        "jobs": [
            {
                "id": 1,
                "title": "ML Intern",
                "location": {"name": "Paris, France"},
                "absolute_url": "https://x/1",
                "first_published": "2026-09-20T00:00:00Z",
            },
            {
                "id": 2,
                "title": "ML Intern",
                "location": {"name": "London"},
                "absolute_url": "https://x/2",
                "first_published": "2026-09-20T00:00:00Z",
            },
        ]
    }
    base = "https://boards-api.greenhouse.io/v1/boards/acme/jobs"
    client = mock_client(
        {f"GET {base}": listing, f"GET {base}/2": {"content": "Do ML"}}
    )
    rules = ListingRules(window_year=2027, max_age_days=60, today=date(2026, 9, 30))
    company = Company("Acme", "A", "greenhouse", {"board": "acme"})
    jobs = GreenhouseSource(client, rules).fetch(company, set())
    assert [(j.id, j.description) for j in jobs] == [
        ("greenhouse:acme:1", ""),  # France: no detail request (route not mocked)
        ("greenhouse:acme:2", "Do ML"),
    ]
