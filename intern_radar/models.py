"""Domain objects shared by every module."""

from dataclasses import dataclass, field
from typing import Any, Literal

Tier = Literal["S", "A", "B", "unlisted"]
DatesFit = Literal["fits", "too_short_extendable", "incompatible", "unknown"]
Eligibility = Literal[
    "ok", "phd_only", "undergrad_only", "local_students_only", "unknown"
]
WorkAuthorisation = Literal[
    "free",
    "self_arranged",
    "programme",
    "sponsorship_stated",
    "uncertain",
    "unlikely",
]

TIERS: tuple[str, ...] = ("S", "A", "B", "unlisted")
DATES_FIT_VALUES: tuple[str, ...] = (
    "fits",
    "too_short_extendable",
    "incompatible",
    "unknown",
)
ELIGIBILITY_VALUES: tuple[str, ...] = (
    "ok",
    "phd_only",
    "undergrad_only",
    "local_students_only",
    "unknown",
)

WORK_AUTHORISATION_VALUES: tuple[str, ...] = (
    "free",
    "self_arranged",
    "programme",
    "sponsorship_stated",
    "uncertain",
    "unlikely",
)


@dataclass(frozen=True)
class Company:
    """A watched company and how to reach its job feed."""

    name: str
    tier: Tier
    source: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Job:
    """A job posting normalized across every source."""

    id: str
    company: str
    tier: Tier
    title: str
    location: str
    url: str
    description: str
    source: str
    posted_at: str | None = None


@dataclass(frozen=True)
class Assessment:
    """What the LLM says about one job."""

    is_internship: bool
    ai_relevance: int
    dates_fit: DatesFit
    eligibility: Eligibility
    visa_note: str
    language_ok: bool
    summary: str
    # Assessments stored before this field existed load as "uncertain".
    work_authorisation: WorkAuthorisation = "uncertain"


@dataclass(frozen=True)
class ScoredJob:
    """A job with its assessment; `score` is None when the job is excluded."""

    job: Job
    assessment: Assessment
    score: float | None
