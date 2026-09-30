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


def test_get_job(store):
    store.add(make_job(id="a", description="full"), "pending", NOW)
    assert store.get_job("a") == make_job(id="a", description="full")
    assert store.get_job("missing") is None


def test_letters_are_saved_counted_and_replaced(store):
    store.save_letter("a", "/tmp/a.pdf", {"ai_changes": 2}, NOW)
    store.save_letter("b", "/tmp/b.pdf", {}, NOW - timedelta(days=2))
    assert store.letter("a") == ("/tmp/a.pdf", {"ai_changes": 2})
    assert store.letter("zzz") is None
    assert store.letters_since(NOW - timedelta(days=1)) == 1
    store.save_letter("a", "/tmp/a2.pdf", {}, NOW)
    assert store.letter("a") == ("/tmp/a2.pdf", {})


def test_meta_values(store):
    assert store.get_meta("k") is None
    store.set_meta("k", "v1")
    store.set_meta("k", "v2")
    assert store.get_meta("k") == "v2"


def test_job_refs_are_short_and_reversible(store):
    long_id = "workday:nvidia:/job/US-CA-Santa-Clara/" + "x" * 80
    store.add(make_job(id=long_id), "pending", NOW)
    ref = store.job_ref(long_id)
    assert isinstance(ref, int) and len(f"L:{ref}") <= 64
    assert store.job_by_ref(ref).id == long_id
    assert store.job_ref("missing") is None
    assert store.job_by_ref(999999) is None


def test_pending_returns_one_job_per_posting_group(store):
    store.add(make_job(id="de", title="SDE Intern - Germany"), "pending", NOW)
    store.add(make_job(id="uk", title="SDE Intern - UK"), "pending", NOW)
    store.add(make_job(id="ml", title="ML Intern"), "pending", NOW)
    assert sorted(job.id for job in store.pending()) == ["de", "ml"]
    assert len(store.pending(limit=1)) == 1


def test_pending_members_inherit_the_group_assessment_and_state(store):
    store.add(make_job(id="de", title="SDE Intern - Germany"), "pending", NOW)
    store.save_assessment("de", make_assessment(ai_relevance=9), 8.4)
    store.mark_notified("de", NOW)
    store.add(make_job(id="uk", title="SDE Intern - UK"), "pending", NOW)
    store.add(make_job(id="other", title="ML Intern"), "pending", NOW)

    assert store.inherit_group_assessments() == 1
    assert store.inherit_group_assessments() == 0

    assert [job.id for job in store.pending()] == ["other"]
    assert store.due_immediate(7.5) == []  # the group was already notified
    [uk] = [s for s in store.scored(min_score=0) if s.job.id == "uk"]
    assert (uk.score, uk.assessment.ai_relevance) == (8.4, 9)


def test_excluded_groups_are_inherited_too(store):
    store.add(make_job(id="de", title="SDE Intern - Germany"), "pending", NOW)
    store.save_assessment("de", make_assessment(is_internship=False), None)
    store.add(make_job(id="uk", title="SDE Intern - UK"), "pending", NOW)
    assert store.inherit_group_assessments() == 1
    assert store.pending() == []


def test_due_immediate_without_limit_returns_every_member(store):
    for job_id, title in (("de", "SDE Intern - Germany"), ("uk", "SDE Intern - UK")):
        store.add(make_job(id=job_id, title=title), "pending", NOW)
        store.save_assessment(job_id, make_assessment(), 8.0)
    assert len(store.due_immediate(7.5)) == 2


def test_existing_database_gets_group_keys(tmp_path):
    path = tmp_path / "old.db"
    old = Store(str(path))
    old.add(make_job(id="de", title="SDE Intern - Germany"), "pending", NOW)
    old._db.execute("UPDATE jobs SET group_key = NULL")
    old._db.commit()
    old.close()

    reopened = Store(str(path))
    reopened.add(make_job(id="uk", title="SDE Intern - UK"), "pending", NOW)
    assert [job.id for job in reopened.pending()] == ["de"]
    reopened.close()


def test_database_without_group_key_column_is_migrated(tmp_path):
    import sqlite3

    path = tmp_path / "v1.db"
    db = sqlite3.connect(path)
    db.execute(
        "CREATE TABLE jobs (id TEXT PRIMARY KEY, company TEXT NOT NULL,"
        " tier TEXT NOT NULL, title TEXT NOT NULL, location TEXT NOT NULL,"
        " url TEXT NOT NULL, description TEXT NOT NULL, source TEXT NOT NULL,"
        " posted_at TEXT, first_seen TEXT NOT NULL, status TEXT NOT NULL,"
        " attempts INTEGER NOT NULL DEFAULT 0, assessment TEXT, score REAL,"
        " notified_at TEXT, digested_at TEXT)"
    )
    db.execute(
        "INSERT INTO jobs (id, company, tier, title, location, url, description,"
        " source, first_seen, status) VALUES ('de', 'Acme', 'A',"
        " 'SDE Intern - Germany', 'Berlin', 'https://x', 'd', 'greenhouse',"
        " '2026-09-24', 'pending')"
    )
    db.commit()
    db.close()

    store = Store(str(path))
    store.add(make_job(id="uk", title="SDE Intern - UK"), "pending", NOW)
    assert len(store.pending()) == 1  # "de" and "uk" are one posting
    store.close()


def test_assessments_stored_before_work_authorisation_load_as_uncertain(store):
    import json

    store.add(make_job(id="old"), "pending", NOW)
    legacy = {
        "is_internship": True,
        "ai_relevance": 8,
        "dates_fit": "fits",
        "eligibility": "ok",
        "visa_note": "n/a",
        "language_ok": True,
        "summary": "s",
    }
    store._db.execute(
        "UPDATE jobs SET status = 'scored', score = 8, assessment = ? WHERE id = 'old'",
        (json.dumps(legacy),),
    )
    [scored] = store.scored(min_score=0)
    assert scored.assessment.work_authorisation == "uncertain"


def test_rescore_recomputes_every_scored_job_without_resending(store):
    for job_id, score in (("a", 7.0), ("b", 6.0), ("x", None)):
        store.add(make_job(id=job_id), "pending", NOW)
        store.save_assessment(job_id, make_assessment(), score)
    store.mark_digested(["a"], NOW)
    store.add(make_job(id="p"), "pending", NOW)

    changed = store.rescore(lambda job, assessment: 8.0)

    assert changed == 3
    assert {s.job.id: s.score for s in store.scored(0)} == {
        "a": 8.0,
        "b": 8.0,
        "x": 8.0,
    }
    assert store.pending()[0].id == "p"
    # "a" was already in a digest: it is not sent again as an immediate offer.
    assert [s.job.id for s in store.due_immediate(7.5)] == ["b", "x"]
    assert store.rescore(lambda job, assessment: 8.0) == 0


def test_rescore_can_rewrite_assessments_and_chances_can_be_cleared(store):
    from dataclasses import replace

    from intern_radar.chance import Chance

    store.add(make_job(id="ca", location="Toronto"), "pending", NOW)
    store.save_assessment("ca", make_assessment(work_authorisation="unlikely"), 5.0)
    store.save_chance("ca", Chance(3, ((False, "x"),)))
    changed = store.rescore(
        lambda job, a: 7.0 if a.work_authorisation == "self_arranged" else 5.0,
        adjust=lambda job, a: replace(a, work_authorisation="self_arranged"),
    )
    [scored] = store.scored(0)
    assert changed == 1 and scored.score == 7.0
    assert scored.assessment.work_authorisation == "self_arranged"
    assert store.clear_chances() == 1 and store.chance("ca") is None
