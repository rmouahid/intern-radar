"""Telegram notifications and their HTML formatting."""

import html
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from intern_radar.models import ScoredJob
from intern_radar.telegram import Button, TelegramClient, TelegramError

MAX_DIGEST_LINES = 15
SEPARATOR = "━" * 16
DATES_LABELS = {
    "fits": "Dates compatibles",
    "too_short_extendable": "Trop court, demander une prolongation",
    "unknown": "Dates non précisées",
    "incompatible": "Dates incompatibles",
}
e = html.escape


class NotifyError(Exception):
    """A notification could not be delivered."""


@dataclass(frozen=True)
class Message:
    html: str
    buttons: tuple[tuple[Button, ...], ...] = ()
    silent: bool = False


class Notifier(Protocol):
    def send(self, message: Message) -> None: ...


class TelegramNotifier:
    def __init__(self, telegram: TelegramClient) -> None:
        self._telegram = telegram

    def send(self, message: Message) -> None:
        try:
            self._telegram.send_message(message.html, message.buttons, message.silent)
        except TelegramError as exc:
            raise NotifyError(f"telegram: {exc}") from None


class ConsoleNotifier:
    """Prints messages instead of sending them (dry runs)."""

    def __init__(self, write: Callable[[str], Any] = print) -> None:
        self._write = write

    def send(self, message: Message) -> None:
        labels = " ".join(f"[{b.label}]" for row in message.buttons for b in row)
        self._write(f"{message.html}\n{labels}\n")


def format_immediate(scored: ScoredJob, letter_callback: str | None = None) -> Message:
    job, assessment = scored.job, scored.assessment
    lines = [
        f"🔥 <b>{e(job.company)} · niveau {job.tier}</b>",
        f"<b>{e(job.title)}</b>",
        SEPARATOR,
        f"📍  {e(job.location or 'Lieu non précisé')}",
        f"⭐  {scored.score:.1f} / 10",
        f"📅  {DATES_LABELS[assessment.dates_fit]}",
        f"🛂  {e(assessment.visa_note)}",
        SEPARATOR,
        f"<i>{e(assessment.summary)}</i>",
    ]
    buttons = [Button("🔗 Voir l'offre", url=job.url)]
    if letter_callback:
        buttons.append(Button("✍️ Lettre de motivation", callback=letter_callback))
    return Message("\n".join(lines), (tuple(buttons),))


def format_digest(jobs: list[ScoredJob]) -> Message:
    blocks = [
        f"<b>{e(s.job.company)}</b> · niveau {s.job.tier}\n"
        f'<a href="{e(s.job.url)}">{e(s.job.title[:80])}</a>\n'
        f"📍 {e(s.job.location[:40] or 'Lieu non précisé')}   ⭐ {s.score:.1f} / 10"
        for s in jobs[:MAX_DIGEST_LINES]
    ]
    if len(jobs) > MAX_DIGEST_LINES:
        blocks.append(f"… et {len(jobs) - MAX_DIGEST_LINES} autres (intern-radar list)")
    noun = "offre" if len(jobs) == 1 else "offres"
    header = f"📋 <b>Récap du soir — {len(jobs)} {noun}</b>\n{SEPARATOR}"
    body = "\n\n".join(blocks)
    return Message(f"{header}\n\n{body}\n\n{SEPARATOR}", silent=True)


def format_source_alert(company: str, error: str) -> Message:
    return Message(
        f"⚠️ <b>Source en panne : {e(company)}</b>\n"
        f"En échec depuis 3 jours. Dernière erreur : {e(error[:300])}",
        silent=True,
    )


def format_llm_alert() -> Message:
    return Message(
        "⚠️ <b>Notation LLM indisponible</b>\n"
        "La notation échoue depuis un jour ; des offres attendent d'être notées.",
        silent=True,
    )


def format_letter_failure(company: str, title: str, reason: str) -> Message:
    return Message(
        f"❌ <b>Lettre non générée · {e(company)}</b>\n{e(title)}\n{e(reason[:300])}"
    )


def format_cap_notice(limit: int) -> Message:
    return Message(
        "⚠️ <b>Limite de lettres atteinte</b>\n"
        f"{limit} lettres sur les dernières 24 h. Réessaie plus tard.",
        silent=True,
    )
