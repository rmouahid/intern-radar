"""Handle one tailored-CV request end to end."""

import hashlib
import html
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from intern_radar.candidate import Candidate
from intern_radar.config import Contact
from intern_radar.conventions import convention_for
from intern_radar.editing import resume_to_dict
from intern_radar.models import Job
from intern_radar.notifier import Message, Notifier
from intern_radar.resume.pdf import file_name, render
from intern_radar.resume.writer import ResumeWriter
from intern_radar.scorer import LLMError
from intern_radar.store import Store
from intern_radar.telegram import TelegramError

log = logging.getLogger(__name__)
e = html.escape


def format_resume_caption(job: Job, report: dict[str, Any]) -> str:
    lines = [
        f"📄 <b>CV adapté · {e(job.company[:80])}</b>",
        e(job.title[:200]),
        f"🧩  {report['items']} éléments mis en avant",
        f"🌍  Format : {e(report.get('format', ''))}",
    ]
    if report.get("fact_dropped"):
        lines.append(
            f"🔎  {report['fact_dropped']} puce(s) retirée(s) : non sourcée(s)"
        )
    if report.get("fit_removed"):
        lines.append(
            f"✂️  {report['fit_removed']} puce(s) retirée(s) pour tenir sur 1 page"
        )
    if report.get("dropped_chars"):
        lines.append(
            f"⚠️  Caractères non rendus : {e(' '.join(report['dropped_chars']))}"
        )
    return "\n".join(lines)[:1024]


class ResumeService:
    def __init__(
        self,
        store: Store,
        candidate: Callable[[], Candidate],
        backend: Any,
        contact: Contact,
        out_dir: Path,
        documents: Any,
        notifier: Notifier,
        max_per_day: int,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._candidate = candidate
        self._backend = backend
        self._contact = contact
        self._out_dir = out_dir
        self._documents = documents
        self._notifier = notifier
        self._max_per_day = max_per_day
        self._clock = clock

    def handle(self, job_id: str) -> Path | None:
        job = self._store.get_job(job_id)
        if job is None:
            log.warning("CV request for unknown job %r", job_id[:80])
            return None
        stored = self._store.resume(job_id)
        if stored and Path(stored[0]).exists():
            self._send(job, Path(stored[0]), stored[1])
            return Path(stored[0])
        now = self._clock()
        if self._store.resumes_since(now - timedelta(days=1)) >= self._max_per_day:
            self._notify(
                "⚠️ <b>Limite de CV atteinte</b>\n"
                f"{self._max_per_day} CV sur les dernières 24 h."
            )
            return None
        try:
            return self._generate(job, now)
        except Exception as exc:  # the user must hear back, whatever failed
            log.exception("CV for %s failed", job_id)
            reason = str(exc) if isinstance(exc, LLMError) else type(exc).__name__
            self._notify(
                f"❌ <b>CV non généré · {e(job.company)}</b>\n{e(job.title)}\n"
                f"{e(reason[:300])}"
            )
            return None

    def _generate(self, job: Job, now: datetime) -> Path:
        candidate = self._candidate()
        convention = convention_for(job.location)
        scored = self._store.scored_job(job.id)
        visa = scored.assessment.work_authorisation if scored else "uncertain"
        resume = ResumeWriter(self._backend, candidate, convention).write(job)
        pdf, dropped_chars, pages, removed = render(
            resume, candidate, self._contact, convention, visa
        )
        folder = hashlib.sha1(job.id.encode()).hexdigest()[:10]
        path = self._out_dir / folder / file_name(self._contact.name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pdf)
        report = {
            "items": len(resume.items),
            "fact_dropped": len(resume.dropped),
            "dropped_bullets": list(resume.dropped),
            "fit_removed": removed,
            "dropped_chars": dropped_chars,
            "pages": pages,
            "format": f"{convention.region} ({convention.paper}, "
            f"{pages}/{convention.cv_pages} page(s), {resume.language})",
            "resume": resume_to_dict(resume),
        }
        self._store.save_resume(job.id, str(path), report, now)
        self._send(job, path, report)
        return path

    def _send(self, job: Job, path: Path, report: dict[str, Any]) -> None:
        try:
            self._documents.send_document(
                path.read_bytes(), path.name, format_resume_caption(job, report)
            )
        except TelegramError as exc:
            log.warning("delivery of %s failed: %s", path.name, exc)
            self._notify(
                f"❌ <b>CV non envoyé · {e(job.company)}</b>\n"
                f"Le PDF est sur le VPS. Erreur : {e(str(exc)[:300])}"
            )

    def _notify(self, text: str) -> None:
        try:
            self._notifier.send(Message(text))
        except Exception:
            log.exception("CV notice not sent")
