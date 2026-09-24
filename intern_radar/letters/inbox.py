"""Letter requests: the ntfy topic stream and the listener loop."""

import json
import logging
import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx

from intern_radar.store import Store

log = logging.getLogger(__name__)

LAST_ID_KEY = "last_request_id"
FIRST_DELAY = 5
MAX_DELAY = 300


def parse_line(line: str) -> tuple[str, str] | None:
    try:
        event = json.loads(line)
    except ValueError:
        return None
    if not isinstance(event, dict) or event.get("event") != "message":
        return None
    return str(event.get("id", "")), str(event.get("message", "")).strip()


class RequestStream:
    def __init__(self, client: httpx.Client, server: str, topic: str) -> None:
        self._client = client
        self._url = f"{server.rstrip('/')}/{topic}/json"

    def messages(self, since: str | None) -> Iterator[tuple[str, str]]:
        # ntfy sends a keepalive every ~45 s; 90 s without data means a
        # dead connection.
        with self._client.stream(
            "GET",
            self._url,
            params={"since": since or "12h"},
            timeout=httpx.Timeout(20.0, read=90.0),
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                parsed = parse_line(line)
                if parsed:
                    yield parsed


def run_listener(
    stream: Any,
    handle: Callable[[str], object],
    store: Store,
    sleep: Callable[[float], None] = time.sleep,
    keep_going: Callable[[], bool] = lambda: True,
) -> None:
    delay = FIRST_DELAY
    while keep_going():
        try:
            for message_id, body in stream.messages(store.get_meta(LAST_ID_KEY)):
                try:
                    handle(body)
                except Exception:  # one bad request must not stop the listener
                    log.exception("letter request %s failed", message_id)
                store.set_meta(LAST_ID_KEY, message_id)
                delay = FIRST_DELAY
        except httpx.HTTPError as exc:
            log.warning("request stream lost (%s), retrying in %s s", exc, delay)
            sleep(delay)
            delay = min(delay * 2, MAX_DELAY)
