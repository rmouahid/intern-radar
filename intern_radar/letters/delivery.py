"""Deliver a letter PDF through an ntfy attachment and Gmail."""

import smtplib
from collections.abc import Callable
from email.message import EmailMessage

import httpx

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


class DeliveryError(Exception):
    """A letter could not be delivered."""


class NtfyAttachmentSender:
    def __init__(self, server: str, topic: str, client: httpx.Client) -> None:
        self._url = f"{server.rstrip('/')}/{topic}"
        self._client = client

    def send(self, pdf: bytes, filename: str, title: str, message: str) -> None:
        # Metadata goes in the query string: HTTP headers cannot carry UTF-8.
        params = {
            "filename": filename,
            "title": title,
            "message": message,
            "tags": "memo",
        }
        try:
            response = self._client.put(self._url, content=pdf, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise DeliveryError(f"ntfy: {type(exc).__name__}") from exc


class GmailSender:
    def __init__(
        self,
        address: str,
        app_password: str,
        smtp_factory: Callable[..., smtplib.SMTP_SSL] = smtplib.SMTP_SSL,
    ) -> None:
        self._address = address
        self._password = app_password
        self._smtp_factory = smtp_factory

    def send(self, subject: str, body: str, pdf: bytes, filename: str) -> None:
        message = EmailMessage()
        message["From"] = self._address
        message["To"] = self._address
        message["Subject"] = subject
        message.set_content(body)
        message.add_attachment(
            pdf, maintype="application", subtype="pdf", filename=filename
        )
        try:
            with self._smtp_factory(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
                smtp.login(self._address, self._password)
                smtp.send_message(message)
        except (smtplib.SMTPException, OSError) as exc:
            raise DeliveryError(f"e-mail: {type(exc).__name__}") from exc
