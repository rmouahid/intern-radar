"""ntfy notifications and their formatting."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from intern_radar.models import ScoredJob

MAX_DIGEST_LINES = 20
DATES_LABELS = {
    "fits": "dates OK",
    "too_short_extendable": "too short, ask to extend",
    "unknown": "dates not stated",
    "incompatible": "dates incompatible",
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
            f"📍 {job.location or 'location not stated'} · score {scored.score:.1f}",
            f"📅 {DATES_LABELS[assessment.dates_fit]} · 🛂 {assessment.visa_note}",
            assessment.summary,
        ]
    )
    return Message(
        title=f"[{job.tier}] {job.company} — {job.title}",
        body=body,
        priority=4,
        tags=("fire",),
        click=job.url,
        actions=(("View offer", job.url),),
    )


def format_digest(jobs: list[ScoredJob]) -> Message:
    lines = [
        f"• [{s.job.tier}] {s.job.company} — {s.job.title[:80]}"
        f" · {s.job.location[:40]} · {s.score:.1f}"
        for s in jobs[:MAX_DIGEST_LINES]
    ]
    if len(jobs) > MAX_DIGEST_LINES:
        lines.append(f"… and {len(jobs) - MAX_DIGEST_LINES} more (intern-radar list)")
    noun = "offer" if len(jobs) == 1 else "offers"
    return Message(
        title=f"Digest — {len(jobs)} {noun}",
        body="\n".join(lines),
        priority=3,
        tags=("clipboard",),
    )


def format_source_alert(company: str, error: str) -> Message:
    return Message(
        title=f"Source broken: {company}",
        body=f"Failing for 3 days. Last error: {error[:300]}",
        priority=2,
        tags=("warning",),
    )


def format_llm_alert() -> Message:
    return Message(
        title="LLM scoring unavailable",
        body="claude -p has been failing for a day; offers are waiting to be scored.",
        priority=2,
        tags=("warning",),
    )
