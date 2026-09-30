import pytest

from intern_radar.config import Weights
from intern_radar.countries import mentions_any
from intern_radar.ranking import final_score, with_rule_based_visa
from tests.factories import make_assessment

PVT = ("Canada", "Japan", "Australia", "South Korea")


@pytest.mark.parametrize(
    "location, expected",
    [
        ("Toronto, Ontario, CAN", True),
        ("Montréal, QC", True),
        ("Tokyo, JPN", True),
        ("Sydney NSW", True),
        ("Seoul, South Korea", True),
        ("US, CA, Santa Clara", False),  # CA is California
        ("San Francisco, CA", False),
        ("London, UK", False),
        ("", False),
        ("Paris, France; Vancouver, Canada", True),
    ],
)
def test_mentions_any(location, expected):
    assert mentions_any(location, PVT) is expected


def test_unknown_country_names_match_by_name():
    assert mentions_any("Casablanca, Morocco", ("Morocco",))


def test_self_arranged_visa_override():
    uncertain = make_assessment(work_authorisation="unlikely")
    moved = with_rule_based_visa(uncertain, "Toronto, Ontario, CAN", PVT)
    assert moved.work_authorisation == "self_arranged"
    assert with_rule_based_visa(uncertain, "London, UK", PVT) == uncertain
    assert with_rule_based_visa(uncertain, "Toronto", ()) == uncertain
    free = make_assessment(work_authorisation="free")
    assert with_rule_based_visa(free, "Tokyo", PVT) == free
    w = Weights()
    assert final_score("A", moved, w) == final_score("A", free, w)
    assert final_score("A", moved, w) > final_score("A", uncertain, w)


@pytest.mark.parametrize(
    "location", ["Berlin", "Manching", "Leixlip, Ireland", "Zürich", "Madrid, ESP"]
)
def test_eu_eea_and_swiss_offers_are_free(location):
    legacy = make_assessment(work_authorisation="uncertain")
    assert with_rule_based_visa(legacy, location, ()).work_authorisation == "free"


def test_non_european_offers_keep_their_assessment():
    unlikely = make_assessment(work_authorisation="unlikely")
    assert with_rule_based_visa(unlikely, "New York", ()) == unlikely
