import smtplib

import pytest

from intern_radar.letters.delivery import (
    DeliveryError,
    GmailSender,
)


class FakeSMTP:
    instances: list["FakeSMTP"] = []

    def __init__(self, host, port, timeout):
        self.address = (host, port)
        self.sent = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        if password == "bad":
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")
        self.credentials = (user, password)

    def send_message(self, message):
        self.sent.append(message)


def test_gmail_sender_attaches_the_pdf():
    FakeSMTP.instances.clear()
    GmailSender("me@gmail.com", "app-pass", FakeSMTP).send(
        "Lettre — Acme", "Corps", b"%PDF", "letter.pdf"
    )
    smtp = FakeSMTP.instances[0]
    assert smtp.address == ("smtp.gmail.com", 465)
    assert smtp.credentials == ("me@gmail.com", "app-pass")
    message = smtp.sent[0]
    assert (message["From"], message["To"]) == ("me@gmail.com", "me@gmail.com")
    assert message["Subject"] == "Lettre — Acme"
    [attachment] = list(message.iter_attachments())
    assert attachment.get_filename() == "letter.pdf"
    assert attachment.get_content() == b"%PDF"


def test_gmail_failure_raises_delivery_error():
    with pytest.raises(DeliveryError, match="e-mail"):
        GmailSender("me@gmail.com", "bad", FakeSMTP).send("s", "b", b"x", "f.pdf")
