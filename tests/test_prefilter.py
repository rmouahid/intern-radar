import pytest

from intern_radar.prefilter import (
    is_france_only,
    is_internship_title,
    is_out_of_scope,
    is_past_cycle,
    is_stale,
    is_undergrad_only_title,
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


@pytest.mark.parametrize(
    "title, past",
    [
        ("2026 Software Dev Engineer Intern - UK", True),
        ("2026 Applied Scientist Intern, Amazon University Talent Acquisition", True),
        ("Summer 2025 / 2026 ML Intern", True),
        ("2026-2027 Research Intern", False),
        ("ML Intern (Summer 2027)", False),
        ("【Class of 2029／Internship】Applied Scientists", False),
        ("Machine Learning Intern", False),
        ("Intern, Model 2026X team", False),
    ],
)
def test_past_recruiting_cycles_are_detected(title, past):
    assert is_past_cycle(title, 2027) is past


def test_passes_drops_past_cycles_only_with_a_window_year():
    job = make_job(title="2026 ML Intern")
    assert passes(job)
    assert not passes(job, window_year=2027)
    assert passes(make_job(title="2027 ML Intern"), window_year=2027)


@pytest.mark.parametrize(
    "title, undergrad",
    [
        ("Software Engineering - Intern, Bachelor’s", True),
        ("Undergrad Intern Sales and Marketing", True),
        ("Undergraduate Intern Technical (OpenVINO)", True),
        (
            "2027 Applied Science Internship - Undergrad Student Science Recruiting",
            True,
        ),
        ("Intern, Bachelor's or Master's", False),
        (
            "2027 Applied Science Internship - Master's Student Science Recruiting",
            False,
        ),
        ("Research Intern (MS/PhD)", False),
        ("Graduate Trainee - AI", False),
        ("ML Intern", False),
    ],
)
def test_undergrad_only_titles(title, undergrad):
    assert is_undergrad_only_title(title) is undergrad
    if undergrad:
        assert not passes(make_job(title=title))


@pytest.mark.parametrize(
    "posted_at, stale",
    [
        ("2026-08-01", False),  # 60 days before today: kept
        ("2026-07-31", True),  # 61 days
        ("2025-06-01T10:00:00Z", True),
        (None, False),
        ("not a date", False),
    ],
)
def test_is_stale(posted_at, stale):
    from datetime import date

    assert is_stale(posted_at, date(2026, 9, 30), 60) is stale
    assert is_stale(posted_at, date(2026, 9, 30), 0) is False
