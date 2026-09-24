"""HTTP client shared by the source plugins."""

import time
from collections.abc import Callable

import httpx

USER_AGENT = "intern-radar/0.1 (+https://github.com/rmouahid/intern-radar)"
TIMEOUT_SECONDS = 20.0


class Throttle:
    """Request hook keeping `interval` seconds between requests to one host."""

    def __init__(
        self,
        interval: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._interval = interval
        self._clock = clock
        self._sleep = sleep
        self._last: dict[str, float] = {}

    def __call__(self, request: httpx.Request) -> None:
        host = request.url.host
        last = self._last.get(host)
        if last is not None:
            wait = self._interval - (self._clock() - last)
            if wait > 0:
                self._sleep(wait)
        self._last[host] = self._clock()


def make_client(
    throttle: Throttle | None = None,
    transport: httpx.BaseTransport | None = None,
) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=TIMEOUT_SECONDS,
        follow_redirects=True,
        event_hooks={"request": [throttle or Throttle()]},
        transport=transport,
    )
