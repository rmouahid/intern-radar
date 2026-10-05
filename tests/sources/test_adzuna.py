import httpx
import pytest

from intern_radar.models import Company, Job
from intern_radar.sources.adzuna import (
    AdzunaSource,
    company_lookup,
    match_company,
    search_terms,
)
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
    assert params["what_or"] == "google deepmind apple"
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
                    "id": "557",
                    "title": "Data Intern",
                    "company": {"display_name": "Unwatched Bank"},
                    "location": {"display_name": "London"},
                    "redirect_url": "https://a/557",
                    "description": "",
                    "created": None,
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
    source = AdzunaSource(
        mock_client({f"GET {API}": search}),
        "id",
        "key",
        LOOKUP,
        search_terms(COMPANIES),
    )
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
    source = AdzunaSource(mock_client({}), None, None, LOOKUP, "")
    with pytest.raises(SourceError, match="adzuna_app_id"):
        source.fetch(COMPANIES[2], set())


def test_search_terms_cover_companies_without_feed_only():
    companies = [
        Company("Goldman Sachs", "A", "none", {"aliases": ["GS", "GS Group"]}),
        Company("Stripe", "A", "greenhouse", {}),
        Company("Meta", "S", "none", {"aliases": ["Facebook"]}),
        Company("G-Research", "A", "none", {"aliases": ["G Research"]}),
        Company("Arm", "A", "none", {"aliases": ["Arm Holdings"]}),
    ]
    assert search_terms(companies) == ("goldman sachs meta facebook g-research arm")


def test_discovery_query_keeps_only_employers_outside_the_watch_list():
    calls = []

    def search_both(request):
        what_or = request.url.params["what_or"]
        calls.append(what_or)
        employer = "Google UK Ltd" if "google" in what_or else "Tiny AI Startup"
        twin = "Google UK Ltd" if "google" not in what_or else "Tiny AI Startup"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": f"{len(calls)}{n}",
                        "title": "ML Intern",
                        "company": {"display_name": name},
                        "location": {"display_name": "Berlin"},
                        "redirect_url": "https://a",
                        "description": "",
                        "created": None,
                    }
                    for n, name in enumerate((employer, twin))
                ]
            },
        )

    source = AdzunaSource(
        mock_client({f"GET {API}": search_both}), "id", "key", LOOKUP,
        search_terms(COMPANIES), discovery=True,
    )  # fmt: skip
    jobs = source.fetch(COMPANIES[2], set())
    assert len(calls) == 2 and "machine learning" in calls[1]
    assert sorted((j.company, j.tier) for j in jobs) == [
        ("Google", "S"),
        ("Tiny AI Startup", "unlisted"),
    ]


def test_a_failing_country_does_not_fail_the_source(monkeypatch):
    from intern_radar.sources import base

    monkeypatch.setattr(base, "retry_sleep", lambda seconds: None)
    adzuna = Company("Adzuna", "unlisted", "adzuna", {"countries": ["gb", "de"]})
    routes = {
        f"GET {API}": search,
        "GET https://api.adzuna.com/v1/api/jobs/de/search/1": 503,
    }
    source = AdzunaSource(
        mock_client(routes), "id", "key", LOOKUP, search_terms(COMPANIES)
    )
    assert [job.id for job in source.fetch(adzuna, set())] == ["adzuna:555"]


def test_the_source_fails_when_every_country_fails(monkeypatch):
    from intern_radar.sources import base

    monkeypatch.setattr(base, "retry_sleep", lambda seconds: None)
    adzuna = Company("Adzuna", "unlisted", "adzuna", {"countries": ["gb", "de"]})
    source = AdzunaSource(mock_client({f"GET {API}": 503}), "id", "key", LOOKUP, "x")
    with pytest.raises(SourceError, match="503"):
        source.fetch(adzuna, set())
