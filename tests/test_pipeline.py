from datetime import UTC, datetime, timedelta

import pytest

from intern_radar.models import Company
from intern_radar.notifier import NotifyError
from intern_radar.pipeline import Pipeline
from intern_radar.scorer import LLMError
from intern_radar.sources.base import SourceError
from intern_radar.store import Store
from tests.factories import make_assessment, make_job, make_profile

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


class FakeSource:
    def __init__(self, jobs=None, error=None):
        self.jobs = jobs or []
        self.error = error
        self.calls = []

    def fetch(self, company, known_ids):
        self.calls.append((company.name, set(known_ids)))
        if self.error:
            raise self.error
        return [job for job in self.jobs if job.id not in known_ids]


class FakeScorer:
    """Returns the assessment registered per job id; missing ids are skipped."""

    def __init__(self, answers=None, error=None):
        self.answers = answers or {}
        self.error = error
        self.batches = []

    def assess(self, jobs):
        self.batches.append([job.id for job in jobs])
        if self.error:
            raise self.error
        return {job.id: self.answers[job.id] for job in jobs if job.id in self.answers}


class FakeNotifier:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    def send(self, message):
        if self.fail:
            raise NotifyError("ntfy down")
        self.sent.append(message)


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


ACME = Company("Acme", "S", "fake", {})


def build(sources, scorer, notifier=None, companies=(ACME,), **profile):
    store = Store(":memory:")
    clock = Clock()
    pipeline = Pipeline(
        list(companies),
        sources,
        store,
        scorer,
        notifier or FakeNotifier(),
        make_profile(**profile),
        clock,
    )
    return pipeline, store, clock


def test_run_collects_filters_scores_and_notifies():
    jobs = [
        make_job(id="good", tier="S", title="ML Intern", location="London"),
        make_job(id="paris", tier="S", title="ML Intern", location="Paris, France"),
        make_job(id="eng", tier="S", title="ML Engineer", location="London"),
    ]
    scorer = FakeScorer({"good": make_assessment(ai_relevance=9)})
    notifier = FakeNotifier()
    pipeline, store, _ = build({"fake": FakeSource(jobs)}, scorer, notifier)

    report = pipeline.run()

    assert (report.fetched, report.new, report.candidates) == (3, 3, 1)
    assert (report.scored, report.notified, report.errors) == (1, 1, [])
    assert scorer.batches == [["good"]]
    assert [m.title for m in notifier.sent] == ["[S] Acme — ML Intern"]
    assert store.known_ids() == {"good", "paris", "eng"}


def test_second_run_skips_known_jobs_and_does_not_renotify():
    source = FakeSource([make_job(id="good", tier="S")])
    scorer = FakeScorer({"good": make_assessment(ai_relevance=9)})
    notifier = FakeNotifier()
    pipeline, _, _ = build({"fake": source}, scorer, notifier)
    pipeline.run()
    report = pipeline.run()
    assert report.new == 0
    assert source.calls[1][1] == {"good"}
    assert len(notifier.sent) == 1


def test_companies_without_feed_are_skipped_and_unknown_sources_are_errors():
    companies = [Company("Meta", "S", "none", {}), Company("X", "A", "gone", {})]
    pipeline, _, _ = build({}, FakeScorer(), companies=companies)
    report = pipeline.run()
    assert report.errors == ["X: unknown source 'gone'"]


def test_a_failing_source_does_not_stop_the_run():
    companies = [Company("Broken", "A", "broken", {}), ACME]
    sources = {
        "broken": FakeSource(error=SourceError("HTTP 500")),
        "fake": FakeSource([make_job(id="good", tier="S")]),
    }
    scorer = FakeScorer({"good": make_assessment()})
    pipeline, _, _ = build(sources, scorer, companies=companies)
    report = pipeline.run()
    assert report.errors == ["Broken: HTTP 500"]
    assert report.scored == 1


def test_llm_failure_keeps_jobs_pending_without_attempt():
    pipeline, store, _ = build(
        {"fake": FakeSource([make_job(id="good")])},
        FakeScorer(error=LLMError("quota")),
    )
    for _ in range(4):
        report = pipeline.run()
    assert report.errors == ["LLM: quota"]
    assert [job.id for job in store.pending()] == ["good"]


def test_jobs_missing_from_the_answer_are_retried_three_times():
    scorer = FakeScorer({})
    pipeline, store, _ = build({"fake": FakeSource([make_job(id="odd")])}, scorer)
    for _ in range(4):
        pipeline.run()
    assert scorer.batches == [["odd"], ["odd"], ["odd"]]
    assert store.pending() == []


def test_caps_llm_batches_and_immediate_notifications():
    jobs = [make_job(id=f"j{i:02d}", tier="S") for i in range(25)]
    answers = {job.id: make_assessment(ai_relevance=9) for job in jobs}
    scorer = FakeScorer(answers)
    notifier = FakeNotifier()
    pipeline, _, _ = build(
        {"fake": FakeSource(jobs)},
        scorer,
        notifier,
        max_llm_batches_per_run=2,
        max_immediate_per_run=5,
    )
    report = pipeline.run()
    assert [len(batch) for batch in scorer.batches] == [10, 10]
    assert (report.scored, report.notified) == (20, 5)
    pipeline.run()
    assert [len(batch) for batch in scorer.batches] == [10, 10, 5]
    assert len(notifier.sent) == 10


def test_notification_failure_leaves_offers_for_the_next_run():
    scorer = FakeScorer({"good": make_assessment(ai_relevance=9)})
    failing = FakeNotifier(fail=True)
    pipeline, store, _ = build(
        {"fake": FakeSource([make_job(id="good", tier="S")])}, scorer, failing
    )
    report = pipeline.run()
    assert report.notified == 0
    assert report.errors == ["ntfy down"]
    assert [s.job.id for s in store.due_immediate(7.5, limit=10)] == ["good"]


def test_adzuna_duplicates_of_ats_jobs_are_not_scored():
    companies = [ACME, Company("Adzuna", "unlisted", "adzuna", {})]
    sources = {
        "fake": FakeSource([make_job(id="gh:1", company="Acme", title="ML Intern")]),
        "adzuna": FakeSource(
            [
                make_job(
                    id="adzuna:1", company="Acme", title="ML intern", source="adzuna"
                )
            ]
        ),
    }
    scorer = FakeScorer({"gh:1": make_assessment()})
    pipeline, _, _ = build(sources, scorer, companies=companies)
    report = pipeline.run()
    assert report.candidates == 1
    assert scorer.batches == [["gh:1"]]


def test_source_alert_after_three_days():
    source = FakeSource(error=SourceError("HTTP 500"))
    notifier = FakeNotifier()
    pipeline, _, clock = build({"fake": source}, FakeScorer(), notifier)
    pipeline.run()
    clock.now = NOW + timedelta(days=3)
    pipeline.run()
    pipeline.run()
    assert [m.title for m in notifier.sent] == ["Source broken: Acme"]


def test_llm_alert_after_a_day():
    notifier = FakeNotifier()
    pipeline, _, clock = build(
        {"fake": FakeSource([make_job(id="good")])},
        FakeScorer(error=LLMError("quota")),
        notifier,
    )
    pipeline.run()
    clock.now = NOW + timedelta(days=1)
    pipeline.run()
    assert [m.title for m in notifier.sent] == ["LLM scoring unavailable"]


def test_digest_sends_middle_band_once():
    answers = {
        "mid": make_assessment(ai_relevance=5, dates_fit="unknown"),
        "top": make_assessment(ai_relevance=10),
    }
    jobs = [make_job(id="mid", tier="B"), make_job(id="top", tier="S")]
    notifier = FakeNotifier()
    pipeline, _, _ = build({"fake": FakeSource(jobs)}, FakeScorer(answers), notifier)
    pipeline.run()
    notifier.sent.clear()
    assert pipeline.digest() == 1
    assert notifier.sent[0].title == "Digest — 1 offer"
    assert pipeline.digest() == 0
    assert len(notifier.sent) == 1


def test_digest_failure_raises_and_keeps_offers():
    answers = {"mid": make_assessment(ai_relevance=5, dates_fit="unknown")}
    pipeline, store, _ = build(
        {"fake": FakeSource([make_job(id="mid", tier="B")])},
        FakeScorer(answers),
        FakeNotifier(fail=True),
    )
    pipeline.run()
    with pytest.raises(NotifyError):
        pipeline.digest()
    assert len(store.due_digest(5.5, 7.5)) == 1
