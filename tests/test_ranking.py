import pytest

from intern_radar.config import VisaPenalties, Weights
from intern_radar.ranking import final_score, is_excluded
from tests.factories import make_assessment

W = Weights()


@pytest.mark.parametrize(
    "overrides",
    [
        {"is_internship": False},
        {"dates_fit": "incompatible"},
        {"eligibility": "phd_only"},
        {"eligibility": "undergrad_only"},
        {"language_ok": False},
    ],
)
def test_hard_exclusions(overrides):
    assessment = make_assessment(**overrides)
    assert is_excluded(assessment)
    assert final_score("S", assessment, W) is None


def test_spec_examples():
    google = make_assessment(ai_relevance=9, dates_fit="fits")
    stripe = make_assessment(ai_relevance=4, dates_fit="unknown")
    unlisted = make_assessment(ai_relevance=9, dates_fit="unknown")
    assert final_score("S", google, W) == pytest.approx(9.5)
    assert final_score("A", stripe, W) == pytest.approx(5.6)
    assert final_score("unlisted", unlisted, W) == pytest.approx(6.9)


def test_relevant_tier_b_offer_with_unknown_dates_reaches_immediate():
    # Snowflake "Software Engineer Intern (AI / ML)": 6.9 with the old weights.
    snowflake = make_assessment(ai_relevance=9, dates_fit="unknown")
    assert final_score("B", snowflake, W) == pytest.approx(7.5)
    # A tier-S offer with a middling relevance no longer passes on tier alone.
    middling = make_assessment(ai_relevance=6, dates_fit="unknown")
    assert final_score("S", middling, W) < 7.5


def test_short_internship_and_local_students_penalty():
    short = make_assessment(ai_relevance=10, dates_fit="too_short_extendable")
    assert final_score("S", short, W) == pytest.approx(8.8)
    local = make_assessment(ai_relevance=10, eligibility="local_students_only")
    assert final_score("S", local, W) == pytest.approx(8.0)


def test_score_never_goes_below_zero():
    weak = make_assessment(
        ai_relevance=0,
        dates_fit="too_short_extendable",
        eligibility="local_students_only",
    )
    assert final_score("unlisted", weak, Weights(0, 0, 0)) == 0.0


def test_custom_weights():
    assessment = make_assessment(ai_relevance=5, dates_fit="fits")
    assert final_score("B", assessment, Weights(1, 0, 0)) == pytest.approx(6.0)


def test_offers_below_the_minimum_ai_relevance_are_excluded():
    finance = make_assessment(ai_relevance=5)
    ml = make_assessment(ai_relevance=6)
    assert final_score("S", finance, W, min_relevance=6) is None
    assert final_score("S", ml, W, min_relevance=6) == pytest.approx(8.0)
    assert final_score("S", finance, W) is not None


@pytest.mark.parametrize(
    "authorisation, penalty",
    [
        ("free", 0),
        ("programme", 0.5),
        ("sponsorship_stated", 0),
        ("uncertain", 1),
        ("unlikely", 3),
    ],
)
def test_work_authorisation_penalties(authorisation, penalty):
    base = final_score("S", make_assessment(work_authorisation="free"), W)
    score = final_score("S", make_assessment(work_authorisation=authorisation), W)
    assert score == pytest.approx(base - penalty)


def test_visa_penalties_are_configurable_and_never_exclude():
    unlikely = make_assessment(work_authorisation="unlikely")
    assert final_score("S", unlikely, W, visa=VisaPenalties(unlikely=0)) == (
        final_score("S", make_assessment(), W)
    )
    assert final_score("S", unlikely, W) is not None
