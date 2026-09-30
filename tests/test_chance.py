from datetime import date

import pytest

from intern_radar.candidate import parse_candidate
from intern_radar.chance import (
    CHANCE_SCHEMA,
    CachedChance,
    Chance,
    ChanceEstimator,
    parse_chance,
)
from intern_radar.models import ScoredJob
from intern_radar.notifier import format_immediate
from intern_radar.scorer import LLMError
from intern_radar.store import Store
from tests.factories import make_assessment, make_job
from tests.test_candidate import profile_dict

ANSWER = {
    "percent": 12,
    "reasons": [
        {"positive": True, "text": "Expérience RAG en production"},
        {"positive": False, "text": "Visa US requis"},
    ],
}


class FakeBackend:
    def __init__(self, answer=ANSWER, error=None):
        self.answer, self.error, self.calls = answer, error, []

    def complete(self, prompt, schema):
        self.calls.append((prompt, schema))
        if self.error:
            raise self.error
        return self.answer


def scored(**job):
    return ScoredJob(
        make_job(posted_at="2026-09-20", **job),
        make_assessment(work_authorisation="programme"),
        8.0,
    )


def estimator(backend):
    return ChanceEstimator(
        backend,
        parse_candidate(profile_dict()),
        "4+ months between March 2027 and August 2027",
        today=lambda: date(2026, 9, 30),
    )


def test_estimate_prompt_carries_profile_offer_and_assessment():
    backend = FakeBackend()
    chance = estimator(backend)(scored(description="About us\nWe grow.\nThe role\nRAG"))
    prompt, schema = backend.calls[0]
    assert schema is CHANCE_SCHEMA
    assert "Built a RAG agent" in prompt and "Offer age: 10 days" in prompt
    assert 'work authorisation "programme"' in prompt
    assert "We grow." not in prompt  # cleaned description
    assert chance == Chance(
        12, ((True, "Expérience RAG en production"), (False, "Visa US requis"))
    )


@pytest.mark.parametrize(
    "answer",
    [
        {"percent": "12", "reasons": [{"positive": True, "text": "x"}]},
        {"percent": 12, "reasons": []},
        {"percent": 12, "reasons": [{"positive": True}]},
        [],
    ],
)
def test_invalid_answers_raise(answer):
    with pytest.raises(LLMError):
        parse_chance(answer)


def test_percent_is_clamped_and_reasons_capped():
    answer = {
        "percent": 140,
        "reasons": [{"positive": True, "text": str(i)} for i in range(5)],
    }
    chance = parse_chance(answer)
    assert chance.percent == 100 and len(chance.reasons) == 3


def test_cache_stores_once_and_failures_return_none():
    store = Store(":memory:")
    backend = FakeBackend()
    cached = CachedChance(store, estimator(backend))
    job = scored()
    assert cached(job).percent == 12
    assert cached(job).percent == 12
    assert len(backend.calls) == 1
    assert store.chance(job.job.id) == cached(job)

    failing = CachedChance(store, estimator(FakeBackend(error=LLMError("quota"))))
    assert failing(scored(id="other")) is None
    assert store.chance("other") is None


def test_notification_shows_the_chance_and_its_reasons():
    chance = Chance(12, ((True, "RAG <prod>"), (False, "Visa")))
    html = format_immediate(scored(), chance=chance).html
    assert "🎯  <b>Chance d'entretien : 12 %</b>" in html
    assert "  ✅ RAG &lt;prod&gt;\n  ⚠️ Visa" in html
    assert "🎯" not in format_immediate(scored()).html
