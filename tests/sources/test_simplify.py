from datetime import UTC, date, datetime

import pytest

from intern_radar.models import Company
from intern_radar.prefilter import ListingRules
from intern_radar.sources.base import SourceError
from intern_radar.sources.simplify import (
    LISTINGS,
    SimplifySource,
    is_us_only,
    overlaps_window,
)
from tests.factories import mock_client

URL = LISTINGS.format(repo="SimplifyJobs/Summer2027-Internships")
COMPANY = Company("Simplify", "unlisted", "simplify", {"min_interval_hours": 6})
LOOKUP = {"stripe": ("Stripe", "A"), "tesla": ("Tesla", "A")}
WINDOW = (date(2027, 3, 8), date(2027, 8, 31))
POSTED = int(datetime(2026, 10, 20, 15, tzinfo=UTC).timestamp())


def listing(**overrides):
    values = {
        "id": "uuid-1",
        "company_name": "Stripe",
        "title": "Machine Learning Engineer Intern",
        "category": "AI/ML/Data",
        "terms": ["Summer 2027"],
        "degrees": ["Master's", "PhD"],
        "sponsorship": "Other",
        "locations": ["Toronto, ON, Canada"],
        "url": "https://stripe.com/jobs/listing/ml-intern/7311111",
        "company_url": "https://simplify.jobs/c/Stripe",
        "date_posted": POSTED,
        "active": True,
        "is_visible": True,
    }
    values.update(overrides)
    return values


def fetch(listings, known=(), rules=None, company=COMPANY):
    client = mock_client({f"GET {URL}": listings})
    source = SimplifySource(client, LOOKUP, WINDOW, rules)
    return source.fetch(company, known_ids=set(known))


def test_watched_employer_keeps_its_tier_and_metadata():
    [job] = fetch([listing()])
    assert job.id == "simplify:uuid-1"
    assert (job.company, job.tier) == ("Stripe", "A")
    assert job.title == "Machine Learning Engineer Intern"
    assert job.location == "Toronto, ON, Canada"
    assert job.url == "https://stripe.com/jobs/listing/ml-intern/7311111"
    assert job.source == "simplify"
    assert job.posted_at == "2026-10-20"
    assert "Terms: Summer 2027" in job.description
    assert "Degrees: Master's, PhD" in job.description
    assert "no description" in job.description


def test_unknown_employer_is_discovery():
    [job] = fetch(
        [listing(company_name="Apera AI", locations=["Vancouver, BC, Canada"])]
    )
    assert (job.company, job.tier) == ("Apera AI", "unlisted")


@pytest.mark.parametrize(
    "change",
    [
        {"active": False},
        {"is_visible": False},
        {"category": "Hardware"},
        {"terms": ["Fall 2027"]},
        {"terms": ["N/A"]},
        {"degrees": ["PhD"]},
        {"title": "Machine Learning Engineer"},
    ],
)
def test_listings_outside_the_search_are_skipped(change):
    assert fetch([listing(**change)]) == []


def test_known_ids_are_skipped():
    assert fetch([listing()], known={"simplify:uuid-1"}) == []


def test_categories_can_be_widened_in_companies_yaml():
    company = Company("Simplify", "unlisted", "simplify", {"categories": ["Quant"]})
    assert fetch([listing(category="Quant")], company=company)
    assert fetch([listing()], company=company) == []


def test_us_only_discovery_offers_are_dropped():
    # "Vienna, VA" would otherwise pass for Austria, "New Mexico" for Mexico.
    us = listing(company_name="Navy Federal", locations=["Vienna, VA", "New Mexico"])
    abroad = listing(
        id="uuid-2", company_name="Johnson & Johnson",
        locations=["Boston, MA", "Barcelona, Spain"],
    )  # fmt: skip
    assert [job.id for job in fetch([us, abroad])] == ["simplify:uuid-2"]


def test_watched_employers_keep_their_us_offers():
    [job] = fetch([listing(company_name="Tesla", locations=["Palo Alto, CA"])])
    assert job.tier == "A"


def test_listing_rules_are_checked_before_building_the_job():
    rules = ListingRules(window_year=2027, max_age_days=10, today=date(2026, 11, 2))
    assert fetch([listing()], rules=rules) == []


def test_one_broken_listing_does_not_hide_the_others():
    broken = listing(id="uuid-0")
    del broken["url"]
    assert [job.id for job in fetch([broken, listing()])] == ["simplify:uuid-1"]


def test_repo_can_be_changed_for_the_next_cycle():
    company = Company(
        "Simplify",
        "unlisted",
        "simplify",
        {"repo": "SimplifyJobs/Summer2028-Internships"},
    )
    other = LISTINGS.format(repo="SimplifyJobs/Summer2028-Internships")
    client = mock_client({f"GET {other}": [listing()]})
    assert SimplifySource(client, LOOKUP, WINDOW).fetch(company, set())


def test_http_errors_are_source_errors():
    with pytest.raises(SourceError, match="404"):
        SimplifySource(mock_client({}), LOOKUP, WINDOW).fetch(COMPANY, set())


@pytest.mark.parametrize(
    ("term", "expected"),
    [
        ("Summer 2027", True),
        ("Spring 2027", True),
        ("Winter 2027", True),
        ("Fall 2027", False),
        ("Summer 2026", False),
        ("Spring 2028", False),
        ("N/A", False),
    ],
)
def test_terms_overlapping_the_window(term, expected):
    assert overlaps_window(term, *WINDOW) is expected


@pytest.mark.parametrize(
    ("locations", "expected"),
    [
        (["Vienna, VA"], True),
        (["NYC", "SF"], True),
        (["Remote in USA"], True),
        (["New Mexico", "Washington"], True),
        (["Toronto, ON, Canada"], False),
        (["London, UK"], False),
        (["Boston, MA", "Barcelona, Spain"], False),
        ([], False),
    ],
)
def test_us_only_locations(locations, expected):
    assert is_us_only(locations) is expected
