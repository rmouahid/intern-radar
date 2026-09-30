"""Application tracking from Telegram buttons.

Each notified offer can move through a small state machine:

    (new) ──✅──► applied ──🗣──► interview ──🎉──► offer
      │             │ │               └──❌──► rejected
      │             │ └──❌──► rejected
      │             └──🔕──► no_answer ──🗣/❌──► interview / rejected
      └──🙈──► dismissed ──✅──► applied

A tap updates the store and replaces the tracking row of the tapped
message's keyboard with the next possible steps. Applications without news
after `reminder_days` get one reminder with the same buttons.
"""

import html
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from intern_radar.telegram import Button, TelegramError

log = logging.getLogger(__name__)
e = html.escape

ACTIONS = {
    "A": "applied",
    "D": "dismissed",
    "I": "interview",
    "O": "offer",
    "R": "rejected",
    "N": "no_answer",
}
CODES = {status: code for code, status in ACTIONS.items()}
TRANSITIONS: dict[str | None, tuple[str, ...]] = {
    None: ("applied", "dismissed"),
    "dismissed": ("applied",),
    "applied": ("interview", "rejected", "no_answer"),
    "no_answer": ("interview", "rejected"),
    "interview": ("offer", "rejected"),
    "offer": (),
    "rejected": (),
}
LABELS = {
    "applied": "✅ Postulé",
    "dismissed": "🙈 Pas intéressé",
    "interview": "🗣 Entretien",
    "offer": "🎉 Offre",
    "rejected": "❌ Refusé",
    "no_answer": "🔕 Pas de réponse",
}
STATUS_TEXT = {
    "applied": "Candidature envoyée",
    "dismissed": "Offre écartée",
    "interview": "Entretien obtenu",
    "offer": "Offre reçue",
    "rejected": "Candidature refusée",
    "no_answer": "Sans réponse",
}


def can_move(current: str | None, new: str) -> bool:
    return new in TRANSITIONS.get(current, ())


def tracking_row(status: str | None, ref: int) -> tuple[Button, ...]:
    """Buttons for the steps allowed after `status`."""
    return tuple(
        Button(LABELS[step], callback=f"{CODES[step]}:{ref}")
        for step in TRANSITIONS.get(status, ())
    )


def _is_tracking(button: dict[str, Any]) -> bool:
    data = str(button.get("callback_data") or "")
    return len(data) > 2 and data[0] in ACTIONS and data[1] == ":"


def updated_keyboard(
    keyboard: list[list[dict[str, Any]]], status: str, ref: int
) -> list[list[dict[str, Any]]]:
    """The message keyboard with its tracking buttons replaced for `status`."""
    rows = [[b for b in row if not _is_tracking(b)] for row in keyboard]
    rows = [row for row in rows if row]
    following = tracking_row(status, ref)
    if following:
        rows.append([{"text": b.label, "callback_data": b.callback} for b in following])
    return rows


def format_reminder(company: str, title: str, days: int) -> str:
    return (
        f"⏰ <b>Relance · {e(company[:80])}</b>\n{e(title[:200])}\n"
        f"Candidature envoyée il y a {days} jours, sans nouvelles. Du nouveau ?"
    )


class Tracker:
    def __init__(
        self,
        store: Any,
        telegram: Any,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._telegram = telegram
        self._clock = clock

    def handle(self, code: str, ref: int, callback: dict[str, Any]) -> str:
        """Apply a tracking tap; returns the text to answer the tap with."""
        job = self._store.job_by_ref(ref)
        if job is None or code not in ACTIONS:
            return "Offre introuvable"
        new = ACTIONS[code]
        current = self._store.application_status(job.id)
        if not can_move(current, new):
            return f"Déjà : {STATUS_TEXT.get(current, 'aucun suivi')}"
        self._store.set_application(job.id, new, self._clock())
        message = callback.get("message") or {}
        keyboard = (message.get("reply_markup") or {}).get("inline_keyboard") or []
        try:
            self._telegram.edit_reply_markup(
                message.get("message_id"), updated_keyboard(keyboard, new, ref)
            )
        except TelegramError as exc:  # the status is saved; the buttons are cosmetic
            log.warning("could not update the buttons: %s", exc)
        return STATUS_TEXT[new]
