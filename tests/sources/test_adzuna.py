import httpx
import pytest

from intern_radar.models import Company, Job
from intern_radar.sources.adzuna import AdzunaSource, company_lookup, match_company
from intern_radar.sources.base import SourceError
from tests.factories import mock_client

COMPANIES = [
    Company("Google", "S", "none", {"aliases": ["DeepMind"]}),
    Company("Apple", "S", "none", {}),
    Company("Adzuna", "unlisted", "adzuna", {"countries": ["gb"]}),
]
LOOKUP = company_lookup(COMPANIES)
API = "https://api.adzuna.com/v1/api/jobs/gb/search/1"


@pytest.mark.parametrize(
    "employer, expected",
    [
        ("Google UK Ltd", ("Google", "S")),
        ("DeepMind Technologies", ("Google", "S")),
        ("Applebee's", ("Applebee's", "unlisted")),
        ("", ("Unknown employer", "unlisted")),
    ],
)
def test_match_company(employer, expected):
    assert match_company(employer, LOOKUP) == expected


def search(request: httpx.Request) -> httpx.Response:
    params = request.url.params
    assert (params["app_id"], params["app_key"]) == ("id", "key")
    assert params["what"] == "intern"
    return httpx.Response(
        200,
        json={
            "results": [
                {
                    "id": "555",
                    "title": "<strong>AI</strong> Research Intern",
                    "company": {"display_name": "Google UK Ltd"},
                    "location": {"display_name": "London, UK"},
                    "redirect_url": "https://www.adzuna.co.uk/jobs/land/ad/555",
                    "description": "Gemini research...",
                    "created": "2026-09-20T10:00:00Z",
                },
                {
                    "id": "556",
                    "title": "Sales Manager",
                    "company": {"display_name": "X"},
                    "location": {"display_name": "London"},
                    "redirect_url": "https://a/556",
                    "description": "",
                    "created": None,
                },
            ]
        },
    )


def test_fetch_maps_results_and_attributes_listed_companies():
    source = AdzunaSource(mock_client({f"GET {API}": search}), "id", "key", LOOKUP)
    assert source.fetch(COMPANIES[2], set()) == [
        Job(
            id="adzuna:555",
            company="Google",
            tier="S",
            title="AI Research Intern",
            location="London, UK",
            url="https://www.adzuna.co.uk/jobs/land/ad/555",
            description="Gemini research...",
            source="adzuna",
            posted_at="2026-09-20",
        )
    ]


def test_fetch_requires_keys():
    source = AdzunaSource(mock_client({}), None, None, LOOKUP)
    with pytest.raises(SourceError, match="adzuna_app_id"):
        source.fetch(COMPANIES[2], set())
