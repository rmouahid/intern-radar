"""Telegram notifications and their HTML formatting."""

import html
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from intern_radar.grouping import group_scored
from intern_radar.models import ScoredJob
from intern_radar.telegram import Button, TelegramClient, TelegramError

MAX_DIGEST_LINES = 15
MAX_GROUP_LOCATIONS = 5
BUTTONS_PER_ROW = 5
SEPARATOR = "━" * 16
DATES_LABELS = {
    "fits": "Dates compatibles",
    "too_short_extendable": "Trop court, demander une prolongation",
    "unknown": "Dates non précisées",
    "incompatible": "Dates incompatibles",
}
WORK_AUTHORISATION_LABELS = {
    "free": "Pas de visa (UE/EEE/Suisse)",
    "programme": "Visa stagiaire standard",
    "sponsorship_stated": "Sponsoring annoncé",
    "uncertain": "Visa incertain",
    "unlikely": "Visa peu probable",
}
e = html.escape


class NotifyError(Exception):
    """A notification could not be delivered.

    `permanent` means Telegram rejected this message itself (HTTP 4xx other
    than 429): sending it again would fail again.
    """

    def __init__(self, message: str, permanent: bool = False) -> None:
        super().__init__(message)
        self.permanent = permanent


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
            permanent = exc.status is not None and 400 <= exc.status < 500
            permanent = permanent and exc.status != 429
            raise NotifyError(f"telegram: {exc}", permanent=permanent) from None


class ConsoleNotifier:
    """Prints messages instead of sending them (dry runs)."""

    def __init__(self, write: Callable[[str], Any] = print) -> None:
        self._write = write

    def send(self, message: Message) -> None:
        labels = " ".join(f"[{b.label}]" for row in message.buttons for b in row)
        self._write(f"{message.html}\n{labels}\n")


def _locations(members: Sequence[ScoredJob], width: int) -> str:
    """Distinct locations of a posting group, each linked to its own offer."""
    urls: dict[str, str] = {}
    for member in members:
        urls.setdefault(
            member.job.location[:width] or "Lieu non précisé", member.job.url
        )
    link = len(set(urls.values())) > 1
    parts = [
        f'<a href="{e(url)}">{e(location)}</a>'
        if link and url.startswith(("https://", "http://"))
        else e(location)
        for location, url in list(urls.items())[:MAX_GROUP_LOCATIONS]
    ]
    if len(urls) > MAX_GROUP_LOCATIONS:
        parts.append(f"+{len(urls) - MAX_GROUP_LOCATIONS}")
    return " · ".join(parts)


def format_immediate(
    scored: ScoredJob,
    letter_callback: str | None = None,
    siblings: Sequence[ScoredJob] = (),
) -> Message:
    """Notification for one posting; `siblings` are its copies in other places."""
    job, assessment = scored.job, scored.assessment
    width = 60 if siblings else 100
    # Source and LLM fields are unbounded; Telegram rejects texts over 4096.
    lines = [
        f"🔥 <b>{e(job.company[:80])} · niveau {job.tier}</b>",
        f"<b>{e(job.title[:200])}</b>",
        SEPARATOR,
        f"📍  {_locations([scored, *siblings], width)}",
        f"⭐  {scored.score:.1f} / 10",
        f"📅  {DATES_LABELS[assessment.dates_fit]}",
        f"🛂  <b>{WORK_AUTHORISATION_LABELS[assessment.work_authorisation]}</b>"
        f" · {e(assessment.visa_note[:300])}",
        SEPARATOR,
        f"<i>{e(assessment.summary[:500])}</i>",
    ]
    buttons = []
    if job.url.startswith(("https://", "http://")):
        buttons.append(Button("🔗 Voir l'offre", url=job.url))
    if letter_callback:
        buttons.append(Button("✍️ Lettre de motivation", callback=letter_callback))
    return Message("\n".join(lines), (tuple(buttons),) if buttons else ())


def format_digest(
    jobs: list[ScoredJob], refs: Mapping[str, int] | None = None
) -> Message:
    """Evening digest; with `refs` (job id → store ref) entries are numbered
    and a "🔔 n" button per entry promotes it to a full notification."""
    groups = group_scored(jobs)
    shown = groups[:MAX_DIGEST_LINES]
    number = (lambda n: f"{n}. ") if refs else (lambda n: "")
    blocks = [
        f"<b>{number(n)}{e(s.job.company)}</b> · niveau {s.job.tier}\n"
        f'<a href="{e(s.job.url)}">{e(s.job.title[:80])}</a>\n'
        f"📍 {_locations(group, 40)}   ⭐ {s.score:.1f} / 10"
        for n, (s, group) in enumerate(((g[0], g) for g in shown), start=1)
    ]
    if len(groups) > MAX_DIGEST_LINES:
        extra = len(groups) - MAX_DIGEST_LINES
        blocks.append(f"… et {extra} autres (intern-radar list)")
    noun = "offre" if len(groups) == 1 else "offres"
    header = f"📋 <b>Récap du soir — {len(groups)} {noun}</b>\n{SEPARATOR}"
    body = "\n\n".join(blocks)
    buttons: tuple[tuple[Button, ...], ...] = ()
    if refs:
        tap = [
            Button(f"🔔 {n}", callback=f"P:{refs[group[0].job.id]}")
            for n, group in enumerate(shown, start=1)
        ]
        buttons = tuple(
            tuple(tap[i : i + BUTTONS_PER_ROW])
            for i in range(0, len(tap), BUTTONS_PER_ROW)
        )
    return Message(f"{header}\n\n{body}\n\n{SEPARATOR}", buttons, silent=True)


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


def format_letter_undelivered(company: str, title: str, reason: str) -> Message:
    return Message(
        f"❌ <b>Lettre non envoyée · {e(company)}</b>\n{e(title)}\n"
        f"Le PDF est sur le VPS. Erreur : {e(reason[:300])}"
    )
