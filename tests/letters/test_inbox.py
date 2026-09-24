import httpx

from intern_radar.letters.inbox import (
    LAST_ID_KEY,
    RequestStream,
    parse_line,
    run_listener,
)
from intern_radar.store import Store
from tests.factories import mock_client


def test_parse_line_keeps_only_messages():
    line = '{"id":"a1","event":"message","message":" job-1 "}'
    assert parse_line(line) == ("a1", "job-1")
    assert parse_line('{"id":"k","event":"keepalive"}') is None
    assert parse_line("not json") is None
    assert parse_line("") is None


def test_request_stream_reads_lines_since_the_last_id():
    seen = {}

    def handler(request):
        seen["since"] = request.url.params["since"]
        return httpx.Response(
            200,
            content=(
                b'{"id":"o","event":"open"}\n'
                b'{"id":"m1","event":"message","message":"job-1"}\n'
            ),
        )

    client = mock_client({"GET https://ntfy.sh/req/json": handler})
    stream = RequestStream(client, "https://ntfy.sh", "req")
    assert list(stream.messages("m0")) == [("m1", "job-1")]
    assert seen["since"] == "m0"
    list(stream.messages(None))
    assert seen["since"] == "12h"


class FlakyStream:
    def __init__(self):
        self.calls = []

    def messages(self, since):
        self.calls.append(since)
        if len(self.calls) == 1:
            yield ("m1", "boom")
            yield ("m2", "job-2")
            raise httpx.ReadTimeout("dropped")
        yield ("m3", "job-3")


def test_listener_survives_errors_and_resumes():
    store = Store(":memory:")
    handled, sleeps = [], []

    def handle(body):
        if body == "boom":
            raise RuntimeError("bad request")
        handled.append(body)

    stream = FlakyStream()
    rounds = iter([True, True, False])
    run_listener(
        stream, handle, store, sleep=sleeps.append, keep_going=lambda: next(rounds)
    )
    assert handled == ["job-2", "job-3"]
    assert stream.calls == [None, "m2"]
    assert store.get_meta(LAST_ID_KEY) == "m3"
    assert sleeps[0] == 5
