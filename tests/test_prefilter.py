import pytest

from intern_radar.prefilter import is_france_only, is_internship_title, passes
from tests.factories import make_job


@pytest.mark.parametrize(
    "title",
    [
        "Machine Learning Intern",
        "Software Engineering Interns",
        "Research Internship (Summer 2027)",
        "ML Intern/Co-op (Winter 2027)",
        "AI Coop",
        "Stagiaire Data Science",
        "Graduate Trainee - AI",
        "Industrial Placement, Machine Learning",
        "2027 Intern - Machine Learning Engineer",
    ],
)
def test_internship_titles_match(title):
    assert is_internship_title(title)


@pytest.mark.parametrize(
    "title",
    [
        "Senior Full-Stack Engineer, Internal Applications",
        "Director, US International Tax",
        "Internal Communications Manager",
        "Machine Learning Engineer",
        "",
    ],
)
def test_other_titles_do_not_match(title):
    assert not is_internship_title(title)


@pytest.mark.parametrize(
    "location, expected",
    [
        ("Paris, France", True),
        ("Remote - France", True),
        ("Sophia Antipolis", True),
        ("London, UK", False),
        ("", False),
        ("Remote", False),
        ("Toronto, Ontario", False),
    ],
)
def test_is_france_only(location, expected):
    assert is_france_only(location) is expected


def test_multi_location_with_non_french_office_passes():
    assert not is_france_only("Paris, France; London, UK")
    assert not is_france_only("Paris, France | Zurich, Switzerland")
    assert not is_france_only("Paris or Dublin")
    assert is_france_only("Paris, France; Lyon, France")


def test_passes_combines_title_and_location():
    assert passes(make_job(title="AI Intern", location="London, UK"))
    assert not passes(make_job(title="AI Intern", location="Paris, France"))
    assert not passes(make_job(title="AI Engineer", location="London, UK"))


@pytest.mark.parametrize(
    "location",
    [
        "Paris, London",
        "Paris, France and London, UK",
        "Paris & London",
        "Remote, EU (excluding France)",
    ],
)
def test_locations_mixing_france_with_other_places_pass(location):
    assert not is_france_only(location)


def test_french_city_with_region_or_remote_is_still_france_only():
    assert is_france_only("Paris, Île-de-France, France")
    assert is_france_only("Remote, France")
