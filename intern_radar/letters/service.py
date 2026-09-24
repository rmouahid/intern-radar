"""Handle one cover letter request end to end."""

import hashlib
import html
import logging
import re
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from intern_radar.config import Contact
from intern_radar.letters.cv import CvError
from intern_radar.letters.delivery import DeliveryError, GmailSender
from intern_radar.letters.pdf import file_name, render
from intern_radar.letters.writer import LetterWriter
from intern_radar.models import Job
from intern_radar.notifier import Notifier, format_cap_notice, format_letter_failure
from intern_radar.scorer import LLMError
from intern_radar.store import Store
from intern_radar.telegram import TelegramError

log = logging.getLogger(__name__)

SEPARATOR = "━" * 16
CAP_NOTICE_KEY = "letters_cap_notice_day"
MAX_CAPTION = 1024
LIST_ITEMS = 6
e = html.escape


class DocumentSender(Protocol):
    def send_document(self, content: bytes, filename: str, caption: str) -> None: ...


def _items(values: list[str]) -> str:
    shown = ", ".join(e(v[:40]) for v in values[:LIST_ITEMS])
    return shown + ("…" if len(values) > LIST_ITEMS else "")


def format_letter_caption(job: Job, report: dict[str, Any], email_status: str) -> str:
    """The report card sent with the PDF (HTML, at most 1024 characters)."""
    present = report.get("keywords_present", [])
    missing = report.get("keywords_missing", [])
    if report.get("ats_skipped"):
        ats = "🎯  <b>ATS</b> : description de l'offre absente"
    else:
        total = len(present) + len(missing)
        ats = f"🎯  <b>ATS</b> : {len(present)}/{total} mots-clés"
    sections = [
        f"✍️ <b>Lettre prête · {e(job.company[:60])}</b>\n"
        f"<b>{e(job.title[:150])}</b>\n{SEPARATOR}",
        ats,
    ]
    if report.get("keywords_not_in_cv"):
        sections.append(
            f"🚫  <b>Absents de ton CV</b> :\n{_items(report['keywords_not_in_cv'])}"
        )
    if report.get("keywords_inferred"):
        sections.append(
            "🔎  <b>Déduits de ton CV (à vérifier)</b> :\n"
            + _items(report["keywords_inferred"])
        )
    sections.append(
        f"🧹  <b>Anti-IA</b> : {report.get('ai_changes', 0)} tournures corrigées"
    )
    warnings = []
    flags = [*report.get("unverified", []), *report.get("blacklist_left", [])]
    if flags:
        warnings.append(f"⚠️  <b>À vérifier</b> : {_items(flags)}")
    if report.get("dropped"):
        dropped = e(" ".join(report["dropped"]))
        warnings.append(f"⚠️  <b>Caractères retirés du PDF</b> : {dropped}")
    if report.get("pages", 1) > 1:
        warnings.append(f"⚠️  <b>{report['pages']} pages</b> : à raccourcir")
    if warnings:
        sections.append("\n".join(warnings))
    sections += [e(email_status), SEPARATOR]
    caption = "\n\n".join(sections)
    if len(caption) > MAX_CAPTION:
        # Safety net only: titles and lists are capped above.
        caption = re.sub(r"<[^>]*$", "", caption[: MAX_CAPTION - 1]) + "…"
    return caption


def _plain(caption: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", caption))


class LetterService:
    def __init__(
        self,
        store: Store,
        make_writer: Callable[[], LetterWriter],
        contact: Contact,
        out_dir: Path,
        documents: DocumentSender,
        mail: GmailSender | None,
        notifier: Notifier,
        max_per_day: int,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._make_writer = make_writer
        self._contact = contact
        self._out_dir = out_dir
        self._documents = documents
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
            return self._generate(job, now)
        except Exception as exc:  # the user must hear back, whatever failed
            log.exception("letter for %s failed", job_id)
            self._notify_failure(job, exc)
            return None

    def _generate(self, job: Job, now: datetime) -> Path:
        letter, report = self._make_writer().write(job)
        pdf, dropped, pages = render(letter, job, self._contact, now.date())
        last_name = self._contact.name.split()[-1]
        # One folder per job: two offers can share company and title.
        folder = hashlib.sha1(job.id.encode()).hexdigest()[:10]
        path = self._out_dir / folder / file_name(last_name, job.company, job.title)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pdf)
        data = {
            **asdict(report),
            "dropped": dropped,
            "pages": pages,
            "text": letter.text(),
        }
        self._store.save_letter(job.id, str(path), data, now)
        self._deliver(job, path, data)
        return path

    def _notify_failure(self, job: Job, exc: Exception) -> None:
        reason = str(exc) if isinstance(exc, (LLMError, CvError)) else ""
        reason = reason or type(exc).__name__
        try:
            self._notifier.send(format_letter_failure(job.company, job.title, reason))
        except Exception:
            log.exception("failure notification for %s not sent", job.id)

    def _deliver(self, job: Job, path: Path, report: dict[str, Any]) -> None:
        pdf = path.read_bytes()
        email_status = "📧  E-mail non configuré"
        if self._mail is not None:
            summary = _plain(format_letter_caption(job, report, ""))
            try:
                self._mail.send(
                    subject=f"Lettre — {job.company} · {job.title}",
                    body=f"{summary}\n\n{report.get('text', '')}",
                    pdf=pdf,
                    filename=path.name,
                )
                email_status = "📧  Envoyée par e-mail"
            except DeliveryError as exc:
                email_status = f"📧  E-mail en échec : {exc}"
        try:
            self._documents.send_document(
                pdf, path.name, format_letter_caption(job, report, email_status)
            )
        except TelegramError as exc:
            log.warning("delivery of %s failed: %s", path.name, exc)

    def _cap_notice(self, now: datetime) -> None:
        today = now.date().isoformat()
        if self._store.get_meta(CAP_NOTICE_KEY) == today:
            return
        self._notifier.send(format_cap_notice(self._max_per_day))
        self._store.set_meta(CAP_NOTICE_KEY, today)
