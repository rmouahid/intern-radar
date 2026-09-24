import pytest

from intern_radar.config import Weights
from intern_radar.ranking import final_score, is_excluded
from tests.factories import make_assessment

W = Weights()


@pytest.mark.parametrize(
    "overrides",
    [
        {"is_internship": False},
        {"dates_fit": "incompatible"},
        {"eligibility": "phd_only"},
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
    assert final_score("S", google, W) == pytest.approx(9.7)
    assert final_score("A", stripe, W) == pytest.approx(6.4)
    assert final_score("unlisted", unlisted, W) == pytest.approx(5.9)


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
