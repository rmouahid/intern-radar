from datetime import UTC, datetime, timedelta

import pytest

from intern_radar.store import Store
from tests.factories import make_assessment, make_job

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def test_add_and_known_ids(store):
    store.add(make_job(id="a"), "pending", NOW)
    store.add(make_job(id="b"), "rejected", NOW)
    assert store.known_ids() == {"a", "b"}


def test_add_is_idempotent(store):
    store.add(make_job(id="a", title="First"), "pending", NOW)
    store.add(make_job(id="a", title="Second"), "pending", NOW)
    assert [job.title for job in store.pending()] == ["First"]


def test_pending_returns_only_pending_jobs_with_description(store):
    store.add(make_job(id="a", description="full text"), "pending", NOW)
    store.add(make_job(id="b"), "rejected", NOW)
    assert store.pending() == [make_job(id="a", description="full text")]


def test_rejected_jobs_do_not_keep_their_description(store):
    store.add(make_job(id="b", description="long"), "rejected", NOW)
    row = store._db.execute("SELECT description FROM jobs WHERE id='b'").fetchone()
    assert row["description"] == ""


def test_pending_respects_limit_and_attempts(store):
    for job_id in ("a", "b", "c"):
        store.add(make_job(id=job_id), "pending", NOW)
    for _ in range(3):
        store.record_attempt(["a"])
    assert [job.id for job in store.pending()] == ["b", "c"]
    assert [job.id for job in store.pending(limit=1)] == ["b"]


def test_has_similar_ignores_case_and_adzuna_jobs(store):
    store.add(make_job(id="gh:1", company="Stripe", title="ML Intern"), "pending", NOW)
    store.add(
        make_job(id="adzuna:9", company="Google", title="AI Intern", source="adzuna"),
        "pending",
        NOW,
    )
    assert store.has_similar("Stripe", "ml intern")
    assert not store.has_similar("Stripe", "Data Intern")
    assert not store.has_similar("Google", "AI Intern")


def test_scored_jobs_flow_through_immediate_and_digest(store):
    for job_id, score in (("hi", 9.0), ("mid", 6.0), ("low", 4.0), ("ex", None)):
        store.add(make_job(id=job_id), "pending", NOW)
        store.save_assessment(job_id, make_assessment(), score)

    assert store.pending() == []
    assert [s.job.id for s in store.due_immediate(7.5, limit=10)] == ["hi"]
    store.mark_notified("hi", NOW)
    assert store.due_immediate(7.5, limit=10) == []

    digest = store.due_digest(5.5, 7.5)
    assert [(s.job.id, s.score) for s in digest] == [("mid", 6.0)]
    assert digest[0].assessment == make_assessment()
    store.mark_digested(["mid"], NOW)
    assert store.due_digest(5.5, 7.5) == []

    assert [s.job.id for s in store.scored(min_score=5)] == ["hi", "mid"]


def test_due_immediate_orders_by_score_and_limits(store):
    for job_id, score in (("a", 8.0), ("b", 9.5), ("c", 7.6)):
        store.add(make_job(id=job_id), "pending", NOW)
        store.save_assessment(job_id, make_assessment(), score)
    assert [s.job.id for s in store.due_immediate(7.5, limit=2)] == ["b", "a"]


def test_source_alert_after_three_days_of_failures(store):
    store.record_source_result("Acme", "HTTP 500", NOW)
    store.record_source_result("Acme", "HTTP 503", NOW + timedelta(days=2))
    assert store.sources_to_alert(NOW + timedelta(days=2), timedelta(days=3)) == []
    later = NOW + timedelta(days=3)
    assert store.sources_to_alert(later, timedelta(days=3)) == [("Acme", "HTTP 503")]
    store.mark_source_alerted("Acme")
    assert store.sources_to_alert(later, timedelta(days=3)) == []


def test_source_success_resets_the_failure_streak(store):
    store.record_source_result("Acme", "HTTP 500", NOW)
    store.record_source_result("Acme", None, NOW + timedelta(days=1))
    store.record_source_result("Acme", "HTTP 500", NOW + timedelta(days=2))
    assert store.sources_to_alert(NOW + timedelta(days=4), timedelta(days=3)) == []


def test_llm_alert_after_a_day_of_failures(store):
    store.record_llm_result(False, NOW)
    assert not store.llm_alert_due(NOW + timedelta(hours=23), timedelta(days=1))
    assert store.llm_alert_due(NOW + timedelta(days=1), timedelta(days=1))
    store.mark_llm_alerted()
    assert not store.llm_alert_due(NOW + timedelta(days=2), timedelta(days=1))
    store.record_llm_result(True, NOW + timedelta(days=2))
    store.record_llm_result(False, NOW + timedelta(days=3))
    assert not store.llm_alert_due(NOW + timedelta(days=3), timedelta(days=1))


def test_pending_scores_top_tiers_and_newest_offers_first(store):
    store.add(make_job(id="adzuna:1", tier="unlisted"), "pending", NOW)
    store.add(make_job(id="workday:old", tier="S"), "pending", NOW)
    store.add(make_job(id="ashby:1", tier="B"), "pending", NOW)
    store.add(make_job(id="workday:new", tier="S"), "pending", NOW + timedelta(hours=2))
    store.add(make_job(id="greenhouse:1", tier="A"), "pending", NOW)
    assert [job.id for job in store.pending()] == [
        "workday:new",
        "workday:old",
        "greenhouse:1",
        "ashby:1",
        "adzuna:1",
    ]
