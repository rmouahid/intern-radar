from datetime import UTC, datetime, timedelta

import pytest

from intern_radar.store import Store
from intern_radar.telegram import TelegramError
from intern_radar.tracking import (
    Tracker,
    can_move,
    format_reminder,
    tracking_row,
    updated_keyboard,
)
from tests.factories import make_job

NOW = datetime(2026, 10, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    "current, new, allowed",
    [
        (None, "applied", True),
        (None, "dismissed", True),
        (None, "interview", False),
        ("applied", "interview", True),
        ("applied", "no_answer", True),
        ("interview", "offer", True),
        ("dismissed", "applied", True),
        ("rejected", "applied", False),
        ("offer", "rejected", False),
    ],
)
def test_state_machine(current, new, allowed):
    assert can_move(current, new) is allowed


def test_tracking_rows_follow_the_state():
    assert [b.label for b in tracking_row(None, 7)] == [
        "✅ Postulé",
        "🙈 Pas intéressé",
    ]
    assert [b.callback for b in tracking_row("applied", 7)] == ["I:7", "R:7", "N:7"]
    assert tracking_row("offer", 7) == ()


def test_updated_keyboard_keeps_other_buttons():
    keyboard = [
        [{"text": "🔗", "url": "https://x"}, {"text": "✍️", "callback_data": "L:7"}],
        [
            {"text": "✅", "callback_data": "A:7"},
            {"text": "🙈", "callback_data": "D:7"},
        ],
    ]
    rows = updated_keyboard(keyboard, "applied", 7)
    assert rows[0] == keyboard[0]
    assert [b["callback_data"] for b in rows[1]] == ["I:7", "R:7", "N:7"]
    assert updated_keyboard(keyboard, "offer", 7) == [keyboard[0]]


class FakeTelegram:
    def __init__(self, fail=False):
        self.edits, self.fail = [], fail

    def edit_reply_markup(self, message_id, keyboard):
        if self.fail:
            raise TelegramError("old message")
        self.edits.append((message_id, keyboard))


def setup(fail=False):
    store = Store(":memory:")
    store.add(make_job(id="j"), "pending", NOW)
    telegram = FakeTelegram(fail)
    return store, telegram, Tracker(store, telegram, clock=lambda: NOW)


def tap(ref, keyboard=()):
    return {
        "message": {
            "message_id": 5,
            "reply_markup": {"inline_keyboard": list(keyboard)},
        }
    }


def test_tracker_records_steps_and_updates_the_keyboard():
    store, telegram, tracker = setup()
    ref = store.job_ref("j")
    assert tracker.handle("A", ref, tap(ref)) == "Candidature envoyée"
    assert store.application_status("j") == "applied"
    assert telegram.edits[0][0] == 5
    assert tracker.handle("O", ref, tap(ref)) == "Déjà : Candidature envoyée"
    assert tracker.handle("I", ref, tap(ref)) == "Entretien obtenu"
    [(job, status, _, applied)] = store.applications()
    assert (job.id, status, applied) == ("j", "interview", NOW.isoformat())
    assert tracker.handle("A", 999, tap(999)) == "Offre introuvable"


def test_keyboard_failure_does_not_lose_the_status():
    store, _, tracker = setup(fail=True)
    ref = store.job_ref("j")
    assert tracker.handle("D", ref, tap(ref)) == "Offre écartée"
    assert store.application_status("j") == "dismissed"


def test_due_reminders_once_after_the_delay():
    store, _, tracker = setup()
    tracker.handle("A", store.job_ref("j"), tap(1))
    assert store.due_reminders(NOW - timedelta(days=14)) == []
    [(job, applied)] = store.due_reminders(NOW + timedelta(days=1))
    assert job.id == "j" and applied == NOW.isoformat()
    store.mark_reminded("j", NOW)
    assert store.due_reminders(NOW + timedelta(days=30)) == []


def test_reminder_text():
    assert format_reminder("A&B", "ML <Intern>", 14) == (
        "⏰ <b>Relance · A&amp;B</b>\nML &lt;Intern&gt;\n"
        "Candidature envoyée il y a 14 jours, sans nouvelles. Du nouveau ?"
    )
