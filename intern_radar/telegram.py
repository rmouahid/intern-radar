"""Minimal Telegram Bot API client.

The token is part of every URL, so it must never reach exception messages
or logs: errors carry the method name and the HTTP status only.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

API = "https://api.telegram.org/bot{token}/{method}"
DOCUMENT_TIMEOUT = 60.0


class TelegramError(Exception):
    """A Bot API call failed; `status` is the HTTP status when there was one."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Button:
    label: str
    url: str | None = None
    callback: str | None = None


def _keyboard(rows: tuple[tuple[Button, ...], ...]) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": b.label, "url": b.url}
                if b.url is not None
                else {"text": b.label, "callback_data": b.callback}
                for b in row
            ]
            for row in rows
        ]
    }


class TelegramClient:
    def __init__(
        self,
        client: httpx.Client,
        token: str,
        chat_id: int,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client
        self._token = token
        self.chat_id = chat_id
        self._sleep = sleep

    def send_message(
        self,
        html: str,
        buttons: tuple[tuple[Button, ...], ...] = (),
        silent: bool = False,
    ) -> None:
        body: dict[str, Any] = {
            "chat_id": self.chat_id,
            "text": html,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
            "disable_notification": silent,
        }
        if buttons:
            body["reply_markup"] = _keyboard(buttons)
        self._call("sendMessage", json=body)

    def send_document(
        self, content: bytes, filename: str, caption: str, html: bool = True
    ) -> None:
        data = {"chat_id": str(self.chat_id), "caption": caption}
        if html:
            data["parse_mode"] = "HTML"
        self._call(
            "sendDocument",
            data=data,
            files={"document": (filename, content, "application/pdf")},
            timeout=DOCUMENT_TIMEOUT,
        )

    def answer_callback(self, callback_id: str, text: str) -> None:
        self._call(
            "answerCallbackQuery",
            json={"callback_query_id": callback_id, "text": text},
        )

    def get_updates(self, offset: int | None, timeout: int = 50) -> list[dict]:
        body: dict[str, Any] = {
            "timeout": timeout,
            "allowed_updates": ["callback_query"],
        }
        if offset is not None:
            body["offset"] = offset
        result = self._call(
            "getUpdates", json=body, timeout=httpx.Timeout(20.0, read=timeout + 10)
        )
        return result if isinstance(result, list) else []

    def _call(self, method: str, **kwargs: Any) -> Any:
        url = API.format(token=self._token, method=method)
        for attempt in range(2):
            try:
                response = self._client.post(url, **kwargs)
            except httpx.HTTPError as exc:
                raise TelegramError(f"{method}: {type(exc).__name__}") from None
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            if response.status_code == 429 and attempt == 0:
                retry = (payload.get("parameters") or {}).get("retry_after", 1)
                self._sleep(float(retry))
                continue
            if response.status_code >= 400 or not payload.get("ok"):
                detail = payload.get("description", "")
                raise TelegramError(
                    f"{method}: HTTP {response.status_code} {detail}".strip(),
                    status=response.status_code,
                )
            return payload.get("result")
        raise TelegramError(f"{method}: HTTP 429", status=429)
