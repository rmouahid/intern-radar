import smtplib

import httpx
import pytest

from intern_radar.letters.delivery import (
    DeliveryError,
    GmailSender,
    NtfyAttachmentSender,
)
from tests.factories import mock_client


def test_ntfy_attachment_is_put_with_query_metadata():
    seen = {}

    def handler(request: httpx.Request):
        seen["method"] = request.method
        seen["params"] = dict(request.url.params)
        seen["body"] = request.content
        return httpx.Response(200, json={})

    client = mock_client({"PUT https://ntfy.sh/topic-1": handler})
    NtfyAttachmentSender("https://ntfy.sh/", "topic-1", client).send(
        b"%PDF-1.4", "letter.pdf", "✍️ Lettre prête · Acme", "ATS : 3/4"
    )
    assert seen == {
        "method": "PUT",
        "params": {
            "filename": "letter.pdf",
            "title": "✍️ Lettre prête · Acme",
            "message": "ATS : 3/4",
            "tags": "memo",
        },
        "body": b"%PDF-1.4",
    }


def test_ntfy_attachment_failure_raises():
    client = mock_client({"PUT https://ntfy.sh/t": 500})
    with pytest.raises(DeliveryError):
        NtfyAttachmentSender("https://ntfy.sh", "t", client).send(b"x", "a", "b", "c")


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
