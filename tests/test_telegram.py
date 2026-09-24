import json

import httpx
import pytest

from intern_radar.telegram import Button, TelegramClient, TelegramError
from tests.factories import mock_client

TOKEN = "123:SECRET"
API = f"https://api.telegram.org/bot{TOKEN}"


def ok(result=True):
    return httpx.Response(200, json={"ok": True, "result": result})


def recorder(seen, response=None):
    def handler(request):
        seen.append(request)
        return response or ok()

    return handler


def test_send_message_posts_html_with_buttons():
    seen = []
    client = mock_client({f"POST {API}/sendMessage": recorder(seen)})
    TelegramClient(client, TOKEN, 42).send_message(
        "<b>Hi</b>",
        ((Button("Voir", url="https://x"), Button("Lettre", callback="L:7")),),
        silent=True,
    )
    assert json.loads(seen[0].content) == {
        "chat_id": 42,
        "text": "<b>Hi</b>",
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
        "disable_notification": True,
        "reply_markup": {
            "inline_keyboard": [
                [
                    {"text": "Voir", "url": "https://x"},
                    {"text": "Lettre", "callback_data": "L:7"},
                ]
            ]
        },
    }


def test_send_document_uploads_the_pdf_with_a_caption():
    seen = []
    client = mock_client({f"POST {API}/sendDocument": recorder(seen)})
    TelegramClient(client, TOKEN, 42).send_document(b"%PDF", "a.pdf", "<b>c</b>")
    body = seen[0].content
    assert b'name="chat_id"' in body and b"42" in body
    assert b'filename="a.pdf"' in body and b"%PDF" in body
    assert b'name="parse_mode"' in body and b"HTML" in body


def test_get_updates_long_polls_callbacks_after_the_offset():
    seen = []
    updates = [{"update_id": 5, "callback_query": {"id": "c"}}]
    client = mock_client({f"POST {API}/getUpdates": recorder(seen, ok(updates))})
    assert TelegramClient(client, TOKEN, 42).get_updates(5) == updates
    assert json.loads(seen[0].content) == {
        "timeout": 50,
        "allowed_updates": ["callback_query"],
        "offset": 5,
    }


def test_rate_limit_is_retried_once():
    answers = iter(
        [
            httpx.Response(429, json={"ok": False, "parameters": {"retry_after": 3}}),
            ok(),
        ]
    )
    sleeps = []
    client = mock_client({f"POST {API}/answerCallbackQuery": lambda r: next(answers)})
    TelegramClient(client, TOKEN, 42, sleep=sleeps.append).answer_callback("c", "⏳")
    assert sleeps == [3.0]


def test_errors_never_contain_the_token():
    client = mock_client(
        {
            f"POST {API}/sendMessage": lambda r: httpx.Response(
                400, json={"ok": False, "description": "Bad Request: can't parse"}
            )
        }
    )
    with pytest.raises(TelegramError) as info:
        TelegramClient(client, TOKEN, 42).send_message("<b")
    assert str(info.value) == "sendMessage: HTTP 400 Bad Request: can't parse"
    assert info.value.__cause__ is None and info.value.__context__ is None
    assert "SECRET" not in str(info.value)


def test_network_errors_hide_the_request_url():
    def fail(request):
        raise httpx.ConnectError("boom", request=request)

    client = mock_client({f"POST {API}/sendMessage": fail})
    with pytest.raises(TelegramError) as info:
        TelegramClient(client, TOKEN, 42).send_message("x")
    assert str(info.value) == "sendMessage: ConnectError"
    assert info.value.__cause__ is None and info.value.__suppress_context__
