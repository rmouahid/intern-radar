import pytest

from intern_radar.conventions import (
    CONVENTIONS,
    convention_for,
    format_dates,
    recency,
    section_title,
    work_status_line,
)


@pytest.mark.parametrize(
    "location, region",
    [
        ("US, CA, Santa Clara", "us"),
        ("Austin, TX", "us"),
        ("Seattle, Washington, USA", "us"),
        ("Toronto, Ontario, CAN", "canada"),
        ("Montreal", "quebec"),
        ("London, UK", "uk"),
        ("Dublin", "ireland"),
        ("Berlin", "dach"),
        ("Zürich", "switzerland"),
        ("Amsterdam", "benelux"),
        ("Stockholm", "nordics"),
        ("Oslo", "norway"),
        ("Warsaw", "poland"),
        ("Milan", "italy"),
        ("Madrid, ESP", "south_europe"),
        ("Sydney NSW", "australia"),
        ("Singapore", "singapore"),
        ("Bengaluru", "india"),
        ("Tokyo, JPN", "japan"),
        ("Shanghai", "china"),
        ("Dubai", "gulf"),
        ("Paris, FR", "international"),
        ("Remote", "international"),
    ],
)
def test_convention_for(location, region):
    assert convention_for(location) is CONVENTIONS[region]


@pytest.mark.parametrize(
    "text, english, german",
    [
        ("Sept. 2024 – Sept. 2028", "Sep 2024 – Sep 2028", "09/2024 – 09/2028"),
        ("July 2025 – August 2025", "Jul 2025 – Aug 2025", "07/2025 – 08/2025"),
        ("2020 – 2023", "2020 – 2023", "2020 – 2023"),
        ("June 2020", "Jun 2020", "06/2020"),
        ("started Aug. 2026, ongoing", "Aug 2026 – Present", "08/2026 – heute"),
        ("unknown", "unknown", "unknown"),
    ],
)
def test_format_dates(text, english, german):
    assert format_dates(text, CONVENTIONS["us"]) == english
    assert format_dates(text, CONVENTIONS["dach"], "de") == german


def test_section_titles_follow_region_and_language():
    assert section_title(CONVENTIONS["uk"], "summary", "en") == "Personal statement"
    assert section_title(CONVENTIONS["us"], "summary", "en") == "Summary"
    assert section_title(CONVENTIONS["dach"], "experience", "de") == "Berufserfahrung"
    assert section_title(CONVENTIONS["quebec"], "skills", "fr") == (
        "Compétences techniques"
    )


def test_work_status_lines():
    assert work_status_line(CONVENTIONS["us"], "unlikely") == (
        "French citizen: requires visa sponsorship"
    )
    assert "Working Holiday" in work_status_line(CONVENTIONS["canada"], "self_arranged")
    assert work_status_line(CONVENTIONS["dach"], "free") == ""
    assert work_status_line(CONVENTIONS["switzerland"], "free").startswith(
        "Nationality: French"
    )


def test_student_order_and_page_limits():
    assert CONVENTIONS["us"].sections.index("education") < CONVENTIONS[
        "us"
    ].sections.index("experience")
    assert CONVENTIONS["us"].paper == "Letter" and CONVENTIONS["uk"].paper == "A4"
    assert CONVENTIONS["us"].cv_pages == 1 and CONVENTIONS["dach"].cv_pages == 2


def test_recency_sorts_most_recent_first():
    dates = [
        "2020 – 2023",
        "Sept. 2024 – Sept. 2028",
        "2023 – 2024",
        "June 2020",
        "Aug 2026 – present",
    ]
    assert sorted(dates, key=recency) == [
        "Aug 2026 – present",
        "Sept. 2024 – Sept. 2028",
        "2023 – 2024",
        "2020 – 2023",
        "June 2020",
    ]
