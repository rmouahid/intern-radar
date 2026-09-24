"""Deliver a letter PDF by Gmail."""

import smtplib
from collections.abc import Callable
from email.message import EmailMessage

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


class DeliveryError(Exception):
    """A letter could not be delivered."""


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
