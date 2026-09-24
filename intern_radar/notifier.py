"""ntfy notifications and their formatting."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from intern_radar.models import ScoredJob

MAX_DIGEST_LINES = 20
SEPARATOR = "━" * 16
DATES_LABELS = {
    "fits": "Dates compatibles",
    "too_short_extendable": "Trop court, demander une prolongation",
    "unknown": "Dates non précisées",
    "incompatible": "Dates incompatibles",
}


class NotifyError(Exception):
    """A notification could not be delivered."""


@dataclass(frozen=True)
class Message:
    title: str
    body: str
    priority: int = 3
    tags: tuple[str, ...] = ()
    click: str | None = None
    actions: tuple[tuple[str, str], ...] = ()


class Notifier(Protocol):
    def send(self, message: Message) -> None: ...


class NtfyNotifier:
    def __init__(self, server: str, topic: str, client: httpx.Client) -> None:
        self._server = server.rstrip("/") + "/"
        self._topic = topic
        self._client = client

    def send(self, message: Message) -> None:
        payload: dict[str, Any] = {
            "topic": self._topic,
            "title": message.title,
            "message": message.body,
            "priority": message.priority,
            "tags": list(message.tags),
        }
        if message.click:
            payload["click"] = message.click
        if message.actions:
            payload["actions"] = [
                {"action": "view", "label": label, "url": url}
                for label, url in message.actions
            ]
        try:
            response = self._client.post(self._server, json=payload)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise NotifyError(f"ntfy: {exc}") from exc


class ConsoleNotifier:
    """Prints messages instead of sending them (dry runs)."""

    def __init__(self, write: Callable[[str], Any] = print) -> None:
        self._write = write

    def send(self, message: Message) -> None:
        self._write(f"[priority {message.priority}] {message.title}\n{message.body}\n")


def format_immediate(scored: ScoredJob) -> Message:
    job, assessment = scored.job, scored.assessment
    body = "\n".join(
        [
            job.title,
            SEPARATOR,
            f"📍  {job.location or 'Lieu non précisé'}",
            f"⭐  {scored.score:.1f} / 10",
            f"📅  {DATES_LABELS[assessment.dates_fit]}",
            f"🛂  {assessment.visa_note}",
            SEPARATOR,
            assessment.summary,
        ]
    )
    return Message(
        title=f"{job.company} · niveau {job.tier}",
        body=body,
        priority=4,
        tags=("fire",),
        click=job.url,
        actions=(("Voir l'offre", job.url),),
    )


def format_digest(jobs: list[ScoredJob]) -> Message:
    lines = [
        f"• [{s.job.tier}] {s.job.company} — {s.job.title[:80]}"
        f" · {s.job.location[:40]} · {s.score:.1f}"
        for s in jobs[:MAX_DIGEST_LINES]
    ]
    if len(jobs) > MAX_DIGEST_LINES:
        lines.append(f"… et {len(jobs) - MAX_DIGEST_LINES} autres (intern-radar list)")
    noun = "offre" if len(jobs) == 1 else "offres"
    return Message(
        title=f"Récap du soir — {len(jobs)} {noun}",
        body="\n".join(lines),
        priority=3,
        tags=("clipboard",),
    )


def format_source_alert(company: str, error: str) -> Message:
    return Message(
        title=f"Source en panne : {company}",
        body=f"En échec depuis 3 jours. Dernière erreur : {error[:300]}",
        priority=2,
        tags=("warning",),
    )


def format_llm_alert() -> Message:
    return Message(
        title="Notation LLM indisponible",
        body="La notation échoue depuis un jour ; des offres attendent d'être notées.",
        priority=2,
        tags=("warning",),
    )
