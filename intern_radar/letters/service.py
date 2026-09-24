"""Handle one cover letter request end to end."""

import logging
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from intern_radar.config import Contact
from intern_radar.letters.cv import CvError
from intern_radar.letters.delivery import (
    DeliveryError,
    GmailSender,
    NtfyAttachmentSender,
)
from intern_radar.letters.pdf import file_name, render
from intern_radar.letters.writer import LetterWriter
from intern_radar.models import Job
from intern_radar.notifier import Message, Notifier
from intern_radar.scorer import LLMError
from intern_radar.store import Store

log = logging.getLogger(__name__)

SEPARATOR = "━" * 16
CAP_NOTICE_KEY = "letters_cap_notice_day"


def format_letter_card(
    job: Job, report: dict[str, Any], filename: str, email_status: str
) -> str:
    present = report.get("keywords_present", [])
    missing = report.get("keywords_missing", [])
    lines = [
        job.title,
        SEPARATOR,
        f"🎯  ATS : {len(present)}/{len(present) + len(missing)} mots-clés",
    ]
    not_in_cv = report.get("keywords_not_in_cv", [])
    if not_in_cv:
        lines.append(f"🚫  Absents de ton CV : {', '.join(not_in_cv)}")
    lines.append(f"🧹  Anti-IA : {report.get('ai_changes', 0)} tournures corrigées")
    flags = [*report.get("unverified", []), *report.get("blacklist_left", [])]
    if flags:
        lines.append(f"⚠️  À vérifier : {', '.join(flags)}")
    lines += [email_status, SEPARATOR, f"📎 {filename}"]
    return "\n".join(lines)


class LetterService:
    def __init__(
        self,
        store: Store,
        make_writer: Callable[[], LetterWriter],
        contact: Contact,
        out_dir: Path,
        attachments: NtfyAttachmentSender,
        mail: GmailSender | None,
        notifier: Notifier,
        max_per_day: int,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._make_writer = make_writer
        self._contact = contact
        self._out_dir = out_dir
        self._attachments = attachments
        self._mail = mail
        self._notifier = notifier
        self._max_per_day = max_per_day
        self._clock = clock

    def handle(self, job_id: str) -> Path | None:
        job_id = job_id.strip()
        job = self._store.get_job(job_id)
        if job is None:
            log.warning("letter request for unknown job %r", job_id[:80])
            return None
        stored = self._store.letter(job_id)
        if stored and Path(stored[0]).exists():
            path = Path(stored[0])
            self._deliver(job, path, stored[1])
            return path
        now = self._clock()
        if self._store.letters_since(now - timedelta(days=1)) >= self._max_per_day:
            self._cap_notice(now)
            return None
        try:
            letter, report = self._make_writer().write(job)
        except (LLMError, CvError) as exc:
            log.warning("letter for %s failed: %s", job_id, exc)
            self._notifier.send(
                Message(
                    title=f"❌ Lettre non générée · {job.company}",
                    body=f"{job.title}\n{str(exc)[:300]}",
                    priority=3,
                    tags=("x",),
                )
            )
            return None
        pdf, dropped = render(letter, job, self._contact, now.date())
        last_name = self._contact.name.split()[-1]
        path = self._out_dir / file_name(last_name, job.company, job.title)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pdf)
        data = {**asdict(report), "dropped": dropped, "text": letter.text()}
        self._store.save_letter(job_id, str(path), data, now)
        self._deliver(job, path, data)
        return path

    def _deliver(self, job: Job, path: Path, report: dict[str, Any]) -> None:
        pdf = path.read_bytes()
        email_status = "📧  E-mail non configuré"
        if self._mail is not None:
            card = format_letter_card(job, report, path.name, "")
            try:
                self._mail.send(
                    subject=f"Lettre — {job.company} · {job.title}",
                    body=f"{card}\n\n{report.get('text', '')}",
                    pdf=pdf,
                    filename=path.name,
                )
                email_status = "📧  Envoyée par e-mail"
            except DeliveryError as exc:
                email_status = f"📧  E-mail en échec : {exc}"
        try:
            self._attachments.send(
                pdf,
                path.name,
                f"✍️ Lettre prête · {job.company}",
                format_letter_card(job, report, path.name, email_status),
            )
        except DeliveryError as exc:
            log.warning("ntfy delivery of %s failed: %s", path.name, exc)

    def _cap_notice(self, now: datetime) -> None:
        today = now.date().isoformat()
        if self._store.get_meta(CAP_NOTICE_KEY) == today:
            return
        self._notifier.send(
            Message(
                title="Limite de lettres atteinte",
                body=f"{self._max_per_day} lettres sur les dernières 24 h. "
                "Réessaie plus tard.",
                priority=2,
                tags=("warning",),
            )
        )
        self._store.set_meta(CAP_NOTICE_KEY, today)
