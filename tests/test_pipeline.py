from datetime import UTC, datetime, timedelta

import pytest

from intern_radar.config import Contact
from intern_radar.models import Company
from intern_radar.notifier import NotifyError
from intern_radar.pipeline import Pipeline
from intern_radar.scorer import LLMError
from intern_radar.sources.base import SourceError
from intern_radar.store import Store
from tests.factories import make_assessment, make_job, make_profile

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


def first_line(message):
    return message.html.split("\n")[0]


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
            raise NotifyError("telegram down")
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
    assert [first_line(m) for m in notifier.sent] == ["🔥 <b>Acme · niveau S</b>"]
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
    assert report.errors == ["telegram down"]
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
    assert [first_line(m) for m in notifier.sent] == ["⚠️ <b>Source en panne : Acme</b>"]


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
    assert [first_line(m) for m in notifier.sent] == [
        "⚠️ <b>Notation LLM indisponible</b>"
    ]


def test_digest_sends_middle_band_once():
    answers = {
        "mid": make_assessment(ai_relevance=6, dates_fit="unknown"),
        "top": make_assessment(ai_relevance=10),
    }
    jobs = [make_job(id="mid", tier="B"), make_job(id="top", tier="S")]
    notifier = FakeNotifier()
    pipeline, _, _ = build({"fake": FakeSource(jobs)}, FakeScorer(answers), notifier)
    pipeline.run()
    notifier.sent.clear()
    assert pipeline.digest() == 1
    assert first_line(notifier.sent[0]) == "📋 <b>Récap du soir — 1 offre</b>"
    assert pipeline.digest() == 0
    assert len(notifier.sent) == 1


def test_digest_failure_raises_and_keeps_offers():
    answers = {"mid": make_assessment(ai_relevance=6, dates_fit="unknown")}
    pipeline, store, _ = build(
        {"fake": FakeSource([make_job(id="mid", tier="B")])},
        FakeScorer(answers),
        FakeNotifier(fail=True),
    )
    pipeline.run()
    with pytest.raises(NotifyError):
        pipeline.digest()
    assert len(store.due_digest(5.5, 7.5)) == 1


def test_low_ai_relevance_offers_are_stored_but_never_notified():
    answers = {"finance": make_assessment(ai_relevance=3)}
    notifier = FakeNotifier()
    pipeline, store, _ = build(
        {"fake": FakeSource([make_job(id="finance", tier="S")])},
        FakeScorer(answers),
        notifier,
    )
    report = pipeline.run()
    assert report.scored == 1
    assert notifier.sent == []
    assert pipeline.digest() == 0


def test_notifications_carry_the_letter_button_when_letters_are_enabled():
    notifier = FakeNotifier()
    pipeline, store, _ = build(
        {"fake": FakeSource([make_job(id="good", tier="S")])},
        FakeScorer({"good": make_assessment(ai_relevance=9)}),
        notifier,
        cv_url="https://cv",
        contact=Contact("A B", "P", "1", "e", "l", "g"),
    )
    pipeline.run()
    button = notifier.sent[0].buttons[0][1]
    assert button.callback == f"L:{store.job_ref('good')}"


class SelectiveNotifier(FakeNotifier):
    """Rejects one offer permanently, like a Telegram HTTP 400."""

    def __init__(self, bad_title):
        super().__init__()
        self.bad_title = bad_title

    def send(self, message):
        if self.bad_title in message.html:
            raise NotifyError("telegram: sendMessage: HTTP 400", permanent=True)
        self.sent.append(message)


def test_a_permanently_rejected_offer_does_not_block_the_others():
    jobs = [
        make_job(id="bad", tier="S", title="Broken Intern"),
        make_job(id="good", tier="A", title="ML Intern"),
    ]
    answers = {job.id: make_assessment(ai_relevance=9) for job in jobs}
    notifier = SelectiveNotifier("Broken Intern")
    pipeline, store, _ = build(
        {"fake": FakeSource(jobs)}, FakeScorer(answers), notifier
    )
    report = pipeline.run()
    assert [first_line(m) for m in notifier.sent] == ["🔥 <b>Acme · niveau A</b>"]
    assert report.notified == 1
    assert store.due_immediate(7.5, limit=10) == []


def test_out_of_scope_titles_are_rejected_and_counted():
    jobs = [
        make_job(id="fin", tier="S", title="Financial Analyst Intern"),
        make_job(id="evt", tier="S", title="Event Coordinator Intern"),
        make_job(id="ml", tier="S", title="ML Intern"),
    ]
    scorer = FakeScorer({"ml": make_assessment()})
    pipeline, _, _ = build(
        {"fake": FakeSource(jobs)}, scorer, extra_excluded_title_words=("event",)
    )
    report = pipeline.run()
    assert (report.candidates, report.out_of_scope) == (1, 2)
    assert scorer.batches == [["ml"]]


def test_posting_group_is_scored_once_and_notified_once():
    jobs = [
        make_job(id="de", tier="S", title="SDE Intern - Germany", location="Berlin"),
        make_job(id="uk", tier="S", title="SDE Intern - UK", location="London"),
    ]
    scorer = FakeScorer({"de": make_assessment(ai_relevance=9)})
    notifier = FakeNotifier()
    pipeline, store, _ = build({"fake": FakeSource(jobs)}, scorer, notifier)

    report = pipeline.run()

    assert scorer.batches == [["de"]]
    assert (report.scored, report.grouped, report.notified) == (1, 1, 1)
    assert "Berlin" in notifier.sent[0].html and "London" in notifier.sent[0].html
    assert store.due_immediate(0) == []


def test_new_country_of_a_notified_posting_is_not_notified_again():
    de = make_job(id="de", tier="S", title="SDE Intern - Germany", location="Berlin")
    source = FakeSource([de])
    scorer = FakeScorer({"de": make_assessment(ai_relevance=9)})
    notifier = FakeNotifier()
    pipeline, _, _ = build({"fake": source}, scorer, notifier)
    pipeline.run()

    source.jobs.append(
        make_job(id="uk", tier="S", title="SDE Intern - UK", location="London")
    )
    report = pipeline.run()

    assert (report.scored, report.grouped, report.notified) == (0, 1, 0)
    assert len(notifier.sent) == 1 and scorer.batches == [["de"]]


def test_immediate_cap_counts_posting_groups():
    jobs = [
        make_job(id=f"{c}{i}", tier="S", title=f"Intern {c} - {country}")
        for c in "ab"
        for i, country in enumerate(("Germany", "UK"))
    ]
    scorer = FakeScorer({job.id: make_assessment(ai_relevance=9) for job in jobs})
    notifier = FakeNotifier()
    pipeline, store, _ = build(
        {"fake": FakeSource(jobs)}, scorer, notifier, max_immediate_per_run=1
    )
    pipeline.run()
    assert len(notifier.sent) == 1
    assert len(store.due_immediate(0)) == 2  # the other group waits for next run


def test_digest_carries_promotion_buttons_when_the_listener_runs():
    def digest_with(**profile):
        scorer = FakeScorer(
            {"mid": make_assessment(ai_relevance=7, dates_fit="unknown")}
        )
        notifier = FakeNotifier()
        pipeline, store, _ = build(
            {"fake": FakeSource([make_job(id="mid", tier="B")])},
            scorer,
            notifier,
            **profile,
        )
        pipeline.run()
        pipeline.digest()
        return notifier.sent[-1], store

    plain, _ = digest_with()
    assert plain.buttons == ()
    message, store = digest_with(
        cv_url="https://cv", contact=Contact("A B", "P", "1", "e", "l", "g")
    )
    assert message.buttons[0][0].callback == f"P:{store.job_ref('mid')}"


def test_immediate_notifications_carry_the_interview_chance():
    from intern_radar.chance import Chance

    asked = []

    def chance(scored):
        asked.append(scored.job.id)
        return Chance(15, ((True, "Profil RAG"),))

    scorer = FakeScorer({"good": make_assessment(ai_relevance=9)})
    notifier = FakeNotifier()
    store = Store(":memory:")
    pipeline = Pipeline(
        [ACME],
        {"fake": FakeSource([make_job(id="good", tier="S")])},
        store,
        scorer,
        notifier,
        make_profile(),
        Clock(),
        chance=chance,
    )
    pipeline.run()
    assert asked == ["good"]
    assert "Chance d'entretien : 15 %" in notifier.sent[0].html


def test_tracking_buttons_and_reminders():
    scorer = FakeScorer({"good": make_assessment(ai_relevance=9)})
    notifier = FakeNotifier()
    store = Store(":memory:")
    clock = Clock()
    pipeline = Pipeline(
        [ACME],
        {"fake": FakeSource([make_job(id="good", tier="S")])},
        store,
        scorer,
        notifier,
        make_profile(),
        clock,
        tracking=True,
    )
    pipeline.run()
    ref = store.job_ref("good")
    assert [b.callback for b in notifier.sent[0].buttons[-1]] == [
        f"A:{ref}",
        f"D:{ref}",
    ]

    store.set_application("good", "applied", clock.now)
    assert pipeline.remind(14) == 0
    clock.now += timedelta(days=15)
    assert pipeline.remind(14) == 1
    reminder = notifier.sent[-1]
    assert reminder.html.startswith("⏰ <b>Relance · Acme</b>")
    assert "il y a 15 jours" in reminder.html
    assert [b.callback for b in reminder.buttons[0]] == [
        f"I:{ref}",
        f"R:{ref}",
        f"N:{ref}",
    ]
    assert pipeline.remind(14) == 0


def test_min_interval_hours_spaces_out_quota_limited_sources():
    source = FakeSource([make_job(id="a")])
    company = Company("Quota", "unlisted", "fake", {"min_interval_hours": 6})
    pipeline, _, clock = build({"fake": source}, FakeScorer(), companies=(company,))
    pipeline.run()
    clock.now += timedelta(hours=2)
    pipeline.run()
    clock.now += timedelta(hours=5)
    pipeline.run()
    assert len(source.calls) == 2


def test_stale_offers_are_rejected_and_old_stored_ones_not_sent():
    jobs = [
        make_job(id="new", tier="S", title="ML Intern A", posted_at="2026-09-20"),
        make_job(id="old", tier="S", title="ML Intern B", posted_at="2026-05-01"),
    ]
    scorer = FakeScorer({"new": make_assessment(ai_relevance=9)})
    notifier = FakeNotifier()
    pipeline, store, _ = build({"fake": FakeSource(jobs)}, scorer, notifier)
    report = pipeline.run()
    assert (report.stale, report.candidates) == (1, 1)
    assert scorer.batches == [["new"]]

    # Offers stored before the rule existed are no longer sent either.
    store.add(
        make_job(id="legacy", title="ML Intern C", posted_at="2026-03-01"),
        "pending",
        NOW,
    )
    store.save_assessment("legacy", make_assessment(ai_relevance=9), 9.0)
    store.add(
        make_job(id="mid", title="ML Intern D", posted_at="2026-03-01"), "pending", NOW
    )
    store.save_assessment("mid", make_assessment(), 6.0)
    pipeline.run()
    assert pipeline.digest() == 0
    sent = " ".join(m.html for m in notifier.sent)
    assert "ML Intern C" not in sent and "ML Intern D" not in sent


def test_offer_age_limit_can_be_disabled():
    job = make_job(id="old", tier="S", posted_at="2020-01-01")
    scorer = FakeScorer({"old": make_assessment(ai_relevance=9)})
    pipeline, _, _ = build({"fake": FakeSource([job])}, scorer, max_offer_age_days=0)
    assert pipeline.run().stale == 0 and scorer.batches == [["old"]]


def test_offers_in_self_sponsored_countries_are_not_penalised():
    job = make_job(id="ca", tier="A", title="ML Intern", location="Toronto, CAN")
    scorer = FakeScorer({"ca": make_assessment(work_authorisation="unlikely")})
    pipeline, store, _ = build(
        {"fake": FakeSource([job])}, scorer, self_sponsored_countries=("Canada",)
    )
    pipeline.run()
    [scored] = store.scored(0)
    assert scored.assessment.work_authorisation == "self_arranged"
