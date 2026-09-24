from datetime import UTC, datetime

from intern_radar.letters.inbox import (
    LAST_UPDATE_KEY,
    LetterRequests,
    TelegramUpdates,
    run_listener,
)
from intern_radar.store import Store
from intern_radar.telegram import TelegramError
from tests.factories import make_job

NOW = datetime(2026, 9, 24, tzinfo=UTC)
CHAT = 42


class FakeTelegram:
    def __init__(self, batches=()):
        self.batches = list(batches)
        self.offsets = []
        self.answers = []

    def get_updates(self, offset, timeout=50):
        self.offsets.append(offset)
        batch = self.batches.pop(0)
        if isinstance(batch, Exception):
            raise batch
        return batch

    def answer_callback(self, callback_id, text):
        self.answers.append((callback_id, text))


class FakeService:
    def __init__(self):
        self.handled = []

    def handle(self, job_id):
        self.handled.append(job_id)


def callback(data, chat=CHAT, sender=CHAT, cid="c1"):
    return {
        "id": cid,
        "data": data,
        "from": {"id": sender},
        "message": {"chat": {"id": chat}},
    }


def setup():
    store = Store(":memory:")
    store.add(make_job(id="job-1"), "pending", NOW)
    telegram, service = FakeTelegram(), FakeService()
    return store, telegram, service, LetterRequests(telegram, store, service, CHAT)


def test_tap_answers_then_writes_the_letter():
    store, telegram, service, requests = setup()
    requests(callback(f"L:{store.job_ref('job-1')}"))
    assert telegram.answers == [("c1", "⏳ Lettre en préparation…")]
    assert service.handled == ["job-1"]


def test_callbacks_from_other_chats_are_ignored():
    store, telegram, service, requests = setup()
    ref = store.job_ref("job-1")
    requests(callback(f"L:{ref}", chat=7, sender=7))
    requests(callback(f"L:{ref}", chat=CHAT, sender=7))
    assert telegram.answers == [] and service.handled == []


def test_unknown_or_malformed_refs_are_answered_without_a_letter():
    _, telegram, service, requests = setup()
    requests(callback("L:999", cid="a"))
    requests(callback("X:1", cid="b"))
    assert telegram.answers == [("a", "Offre introuvable"), ("b", "Action inconnue")]
    assert service.handled == []


def test_updates_resume_after_the_last_id():
    telegram = FakeTelegram([[{"update_id": 8, "callback_query": {"id": "x"}}]])
    assert list(TelegramUpdates(telegram).callbacks(7)) == [(8, {"id": "x"})]
    assert telegram.offsets == [8]


def test_listener_survives_errors_and_resumes():
    store = Store(":memory:")
    telegram = FakeTelegram(
        [
            [
                {"update_id": 1, "callback_query": {"id": "boom"}},
                {"update_id": 2, "callback_query": {"id": "ok"}},
            ],
            TelegramError("getUpdates: ReadTimeout"),
            [{"update_id": 3}],
        ]
    )
    handled, sleeps = [], []

    def on_callback(cb):
        if cb["id"] == "boom":
            raise RuntimeError("bad")
        handled.append(cb["id"])

    rounds = iter([True, True, True, False])
    run_listener(
        TelegramUpdates(telegram),
        on_callback,
        store,
        sleep=sleeps.append,
        keep_going=lambda: next(rounds),
    )
    assert handled == ["ok"]
    assert telegram.offsets == [None, 3, 3]
    assert store.get_meta(LAST_UPDATE_KEY) == "3"
    assert sleeps == [5]
