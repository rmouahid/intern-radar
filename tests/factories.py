"""Builders for test objects with sensible defaults."""

from datetime import date
from typing import Any

from intern_radar.config import Profile
from intern_radar.models import Assessment, Job


def make_job(**overrides: Any) -> Job:
    values: dict[str, Any] = {
        "id": "greenhouse:acme:1",
        "company": "Acme",
        "tier": "A",
        "title": "Machine Learning Intern",
        "location": "London, UK",
        "url": "https://example.com/jobs/1",
        "description": "Build ML systems.",
        "source": "greenhouse",
        "posted_at": "2026-09-20",
    }
    values.update(overrides)
    return Job(**values)


def make_assessment(**overrides: Any) -> Assessment:
    values: dict[str, Any] = {
        "is_internship": True,
        "ai_relevance": 8,
        "dates_fit": "fits",
        "eligibility": "ok",
        "visa_note": "UK: GAE scheme via a sponsor",
        "language_ok": True,
        "summary": "Applied ML on LLM agents.",
    }
    values.update(overrides)
    return Assessment(**values)


def make_profile(**overrides: Any) -> Profile:
    values: dict[str, Any] = {
        "candidate_summary": "Engineering student, RAG and LLM projects.",
        "window_start": date(2027, 3, 8),
        "window_end": date(2027, 8, 31),
        "min_months": 4,
        "ntfy_topic": "test-topic",
    }
    values.update(overrides)
    return Profile(**values)
