"""Deterministic final score computed from the LLM assessment."""

from intern_radar.config import Weights
from intern_radar.models import Assessment, Tier

TIER_POINTS = {"S": 10, "A": 8, "B": 6, "unlisted": 4}
DATES_POINTS = {"fits": 10, "unknown": 6, "too_short_extendable": 4}
LOCAL_STUDENTS_PENALTY = 2


def is_excluded(assessment: Assessment) -> bool:
    return (
        not assessment.is_internship
        or assessment.dates_fit == "incompatible"
        or assessment.eligibility == "phd_only"
        or not assessment.language_ok
    )


def final_score(
    tier: Tier, assessment: Assessment, weights: Weights, min_relevance: int = 0
) -> float | None:
    """Score out of 10, or None when the offer must never be notified.

    `min_relevance` keeps non-AI internships at top companies (finance,
    design…) from outranking AI ones on company tier alone.
    """
    if is_excluded(assessment) or assessment.ai_relevance < min_relevance:
        return None
    score = (
        weights.tier * TIER_POINTS[tier]
        + weights.relevance * assessment.ai_relevance
        + weights.dates * DATES_POINTS[assessment.dates_fit]
    )
    if assessment.eligibility == "local_students_only":
        score -= LOCAL_STUDENTS_PENALTY
    return round(max(score, 0.0), 1)
