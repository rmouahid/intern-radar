import pytest

from intern_radar.grouping import group_key, group_scored
from intern_radar.models import ScoredJob
from tests.factories import make_assessment, make_job


@pytest.mark.parametrize(
    "a, b",
    [
        (
            "2026 Software Dev Engineer Intern - Germany",
            "2026 Software Dev Engineer Intern - UK",
        ),
        (
            "2027 Software Dev Engineer Intern - Italy",
            "2027 software dev engineer intern – Spain",
        ),
        ("ML Intern (Remote)", "ML Intern"),
        ("Research Intern, Singapore", "Research Intern, Japan"),
        ("Data Science INTERN", "data science intern"),
        (
            "Software Engineering Intern, Test Development - 2027",
            "Software Engineering Intern, Test Development – 2027",
        ),
    ],
)
def test_same_posting_in_other_countries_shares_a_key(a, b):
    assert group_key("Acme", a) == group_key("Acme", b)


@pytest.mark.parametrize(
    "a, b",
    [
        ("Software Engineering Intern - 2027", "Software Engineering Intern - 2028"),
        ("ML Intern, Search", "ML Intern, Ads"),
        ("Applied Scientist Intern", "Applied Science Intern"),
    ],
)
def test_different_postings_keep_different_keys(a, b):
    assert group_key("Acme", a) != group_key("Acme", b)


def test_companies_are_never_grouped_together():
    assert group_key("Acme", "ML Intern") != group_key("Globex", "ML Intern")


def scored(job_id, title, location, score=8.0):
    job = make_job(id=job_id, title=title, location=location)
    return ScoredJob(job, make_assessment(), score)


def test_group_scored_keeps_first_seen_order_and_members():
    a = scored("1", "ML Intern - Germany", "Berlin")
    b = scored("2", "Data Intern", "London")
    c = scored("3", "ML Intern - Spain", "Barcelona")
    groups = group_scored([a, b, c])
    assert groups == [[a, c], [b]]


def test_group_scored_of_nothing_is_empty():
    assert group_scored([]) == []
