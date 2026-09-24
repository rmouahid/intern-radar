"""Letter requests: button taps received by long polling Telegram."""

import logging
import time
from collections.abc import Callable, Iterator
from typing import Any

from intern_radar.store import Store
from intern_radar.telegram import TelegramError

log = logging.getLogger(__name__)

LAST_UPDATE_KEY = "last_update_id"
FIRST_DELAY = 5
MAX_DELAY = 300


class TelegramUpdates:
    def __init__(self, telegram: Any) -> None:
        self._telegram = telegram

    def callbacks(self, after: int | None) -> Iterator[tuple[int, dict | None]]:
        offset = after + 1 if after is not None else None
        for update in self._telegram.get_updates(offset):
            yield update["update_id"], update.get("callback_query")


class LetterRequests:
    """Turns a button tap from the candidate's chat into a letter."""

    def __init__(self, telegram: Any, store: Store, service: Any, chat_id: int) -> None:
        self._telegram = telegram
        self._store = store
        self._service = service
        self._chat_id = chat_id

    def __call__(self, callback: dict) -> None:
        chat = ((callback.get("message") or {}).get("chat") or {}).get("id")
        sender = (callback.get("from") or {}).get("id")
        if chat != self._chat_id or sender != self._chat_id:
            log.warning("ignored a button tap from another chat")
            return
        data = str(callback.get("data") or "")
        if not (data.startswith("L:") and data[2:].isdigit()):
            self._answer(callback, "Action inconnue")
            return
        job = self._store.job_by_ref(int(data[2:]))
        if job is None:
            self._answer(callback, "Offre introuvable")
            return
        self._answer(callback, "⏳ Lettre en préparation…")
        self._service.handle(job.id)

    def _answer(self, callback: dict, text: str) -> None:
        try:
            self._telegram.answer_callback(str(callback.get("id")), text)
        except TelegramError as exc:
            log.warning("could not answer a button tap: %s", exc)


def run_listener(
    updates: TelegramUpdates,
    on_callback: Callable[[dict], object],
    store: Store,
    sleep: Callable[[float], None] = time.sleep,
    keep_going: Callable[[], bool] = lambda: True,
) -> None:
    delay = FIRST_DELAY
    while keep_going():
        last = store.get_meta(LAST_UPDATE_KEY)
        try:
            for update_id, callback in updates.callbacks(int(last) if last else None):
                if callback:
                    try:
                        on_callback(callback)
                    except Exception:  # one bad tap must not stop the listener
                        log.exception("button tap %s failed", update_id)
                store.set_meta(LAST_UPDATE_KEY, str(update_id))
            delay = FIRST_DELAY  # any successful poll, even an empty one
        except TelegramError as exc:
            log.warning("Telegram polling failed (%s), retrying in %s s", exc, delay)
            sleep(delay)
            delay = min(delay * 2, MAX_DELAY)
