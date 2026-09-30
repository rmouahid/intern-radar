import pytest

from intern_radar.prefilter import (
    is_france_only,
    is_internship_title,
    is_out_of_scope,
    passes,
)
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


@pytest.mark.parametrize(
    "location",
    [
        "Clichy, Ile-de-France, FRA",
        "Paris, FR",
        "Sophia Antipolis, Provence-Alpes-Côte d'Azur, France",
        "Villeurbanne, Auvergne-Rhone-Alpes",
        "Massy, Île-de-France, FRA; Clichy, Ile-de-France, FRA",
    ],
)
def test_country_or_region_marks_the_whole_place_as_french(location):
    assert is_france_only(location)


@pytest.mark.parametrize(
    "location",
    [
        "Clichy, Ile-de-France, FRA; London, England, GBR",
        "Frankfurt, DEU",
        "Frankfurt am Main, Hesse",
        "EMEA",
        "Remote",
        "Paris, France and London, UK",
        "Remote, EU (excluding France)",
    ],
)
def test_places_outside_france_are_not_france_only(location):
    assert not is_france_only(location)


@pytest.mark.parametrize(
    "title",
    [
        "Financial Analyst Intern, Accounting",
        "Operations Human Resources Partner Intern (6 Months) - 2027",
        "Account Representative Intern 6 months - Spanish Speaker",
        "Operations & Logistics Internship Piemonte - Talent Pool",
        "Strategic Finance Intern",
        "Internship in Communication & Media",
        "STAGE 2027 - Stagiaire Qualité Supply Chain (ALL GENDER)",
        "Summer Internship - Tooling & Logistics Engineer",
        "Public Policy Manager Intern - Q3 2027, EU Public Policy team",
        "General Marketing Manager Intern 2027",
        "Recruiting Coordinator Intern",
        "Customer Success Acct Manager - Erada Internship",
        "Legal Intern",
    ],
)
def test_out_of_scope_titles_are_dropped(title):
    assert is_out_of_scope(title)
    assert not passes(make_job(title=title, location="London, UK"))


@pytest.mark.parametrize(
    "title",
    [
        "Machine Learning Intern",
        "Data & AI Intern - Accenture Internship Program",
        "Finance Data Science Intern",
        "ML Operations Intern",
        "Operations Research Intern",
        "Marketing Analytics Machine Learning Intern",
        "Software Engineering Intern, Payments",
        "Intern 2027",
        "SOC Design Team Methodology Intern - 2027",
        "2027 Quantitative Masters Internship Program - Investments",
        "Research Intern",
        "Business Analyst Intern, Amazon University Talent Acquisition",
        "Manufacturing Test Engr Intern, Advanced Manufacturing Engineering",
        "SWQA Test Development Intern, GPU Communications Libraries - 2027",
    ],
)
def test_in_scope_or_ambiguous_titles_are_kept(title):
    assert not is_out_of_scope(title)


def test_extra_excluded_words_extend_the_list():
    assert not is_out_of_scope("Event Coordinator Intern")
    assert is_out_of_scope("Event Coordinator Intern", extra=("event",))
    assert not is_out_of_scope("Event Data Science Intern", extra=("event",))
    job = make_job(title="Event Coordinator Intern")
    assert not passes(job, extra_excluded=("event",))
