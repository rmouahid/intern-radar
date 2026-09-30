"""Orchestrates one watch run and the evening digest."""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from intern_radar import prefilter, ranking
from intern_radar.chance import Chance
from intern_radar.config import Profile
from intern_radar.grouping import group_scored
from intern_radar.models import Company, ScoredJob
from intern_radar.notifier import (
    Message,
    Notifier,
    NotifyError,
    format_digest,
    format_immediate,
    format_llm_alert,
    format_source_alert,
)
from intern_radar.scorer import LLMError, Scorer
from intern_radar.sources.base import Source
from intern_radar.store import Store

log = logging.getLogger(__name__)

BATCH_SIZE = 10
SOURCE_ALERT_AFTER = timedelta(days=3)
LLM_ALERT_AFTER = timedelta(days=1)
SENT, REJECTED, FAILED = "sent", "rejected", "failed"


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class RunReport:
    fetched: int = 0
    new: int = 0
    candidates: int = 0
    out_of_scope: int = 0  # internship titles dropped by the field filter
    scored: int = 0
    notified: int = 0
    grouped: int = 0  # jobs that reused the result of their posting group
    errors: list[str] = field(default_factory=list)


class Pipeline:
    def __init__(
        self,
        companies: list[Company],
        sources: Mapping[str, Source],
        store: Store,
        scorer: Scorer,
        notifier: Notifier,
        profile: Profile,
        clock: Callable[[], datetime] = utcnow,
        chance: Callable[[ScoredJob], Chance | None] | None = None,
        resumes: bool = False,
    ) -> None:
        self._companies = companies
        self._sources = sources
        self._store = store
        self._scorer = scorer
        self._notifier = notifier
        self._profile = profile
        self._clock = clock
        self._chance = chance
        self._resumes = resumes

    def run(self) -> RunReport:
        report = RunReport()
        self._collect(report)
        self._score(report)
        if self._notify(report):
            self._alert(report)
        return report

    def digest(self) -> int:
        thresholds = self._profile.thresholds
        jobs = self._store.due_digest(thresholds.digest, thresholds.immediate)
        if not jobs:
            return 0
        refs = None
        if self._profile.cv_url and self._profile.contact:  # the listener runs
            refs = {s.job.id: self._store.job_ref(s.job.id) for s in jobs}
        self._notifier.send(format_digest(jobs, refs))
        self._store.mark_digested([s.job.id for s in jobs], self._clock())
        return len(jobs)

    def _collect(self, report: RunReport) -> None:
        now = self._clock()
        known = self._store.known_ids()
        extra = self._profile.extra_excluded_title_words
        for company in self._companies:
            if company.source == "none":
                continue
            source = self._sources.get(company.source)
            try:
                if source is None:
                    raise LookupError(f"unknown source '{company.source}'")
                jobs = source.fetch(company, known)
            except Exception as exc:  # one broken source must not stop the run
                log.warning("%s: %s", company.name, exc)
                report.errors.append(f"{company.name}: {exc}")
                self._store.record_source_result(company.name, str(exc), now)
                continue
            self._store.record_source_result(company.name, None, now)
            report.fetched += len(jobs)
            for job in jobs:
                if job.id in known:
                    continue
                known.add(job.id)
                if not prefilter.passes(job, extra, self._profile.window_start.year):
                    status = "rejected"
                    report.out_of_scope += prefilter.is_internship_title(
                        job.title
                    ) and prefilter.is_out_of_scope(job.title, extra)
                elif job.source == "adzuna" and self._store.has_similar(
                    job.company, job.title
                ):
                    status = "duplicate"
                else:
                    status = "pending"
                self._store.add(job, status, now)
                report.new += 1
                report.candidates += status == "pending"

    def _score(self, report: RunReport) -> None:
        now = self._clock()
        report.grouped += self._store.inherit_group_assessments()
        limit = BATCH_SIZE * self._profile.max_llm_batches_per_run
        pending = self._store.pending(limit=limit)
        for start in range(0, len(pending), BATCH_SIZE):
            batch = pending[start : start + BATCH_SIZE]
            try:
                assessments = self._scorer.assess(batch)
            except LLMError as exc:
                log.warning("LLM unavailable: %s", exc)
                report.errors.append(f"LLM: {exc}")
                self._store.record_llm_result(False, now)
                return
            self._store.record_llm_result(True, now)
            missing = [job.id for job in batch if job.id not in assessments]
            self._store.record_attempt(missing)
            for job in batch:
                assessment = assessments.get(job.id)
                if assessment is None:
                    continue
                score = ranking.final_score(
                    job.tier,
                    assessment,
                    self._profile.weights,
                    self._profile.thresholds.min_relevance,
                    self._profile.visa_penalties,
                )
                self._store.save_assessment(job.id, assessment, score)
                report.scored += 1
        report.grouped += self._store.inherit_group_assessments()

    def _notify(self, report: RunReport) -> bool:
        now = self._clock()
        due = self._store.due_immediate(self._profile.thresholds.immediate)
        groups = group_scored(due)[: self._profile.max_immediate_per_run]
        letters = bool(self._profile.cv_url and self._profile.contact)
        for lead, *siblings in groups:
            ref = self._store.job_ref(lead.job.id) if letters else None
            callback = f"L:{ref}" if ref is not None else None
            chance = self._chance(lead) if self._chance else None
            cv = f"C:{ref}" if ref is not None and self._resumes else None
            message = format_immediate(lead, callback, siblings, chance, cv)
            outcome = self._send(message, report)
            if outcome == FAILED:
                return False
            # A rejected offer is marked too: it would block every later run.
            for member in (lead, *siblings):
                self._store.mark_notified(member.job.id, now)
            report.notified += outcome == SENT
        return True

    def _alert(self, report: RunReport) -> None:
        now = self._clock()
        for company, error in self._store.sources_to_alert(now, SOURCE_ALERT_AFTER):
            if self._send(format_source_alert(company, error), report) == FAILED:
                return
            self._store.mark_source_alerted(company)
        if self._store.llm_alert_due(now, LLM_ALERT_AFTER):
            if self._send(format_llm_alert(), report) != FAILED:
                self._store.mark_llm_alerted()

    def _send(self, message: Message, report: RunReport) -> str:
        """SENT, REJECTED (Telegram refuses this message for good) or FAILED."""
        try:
            self._notifier.send(message)
        except NotifyError as exc:
            log.warning("%s", exc)
            report.errors.append(str(exc))
            return REJECTED if exc.permanent else FAILED
        return SENT
