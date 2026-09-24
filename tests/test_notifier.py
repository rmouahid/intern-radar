import json

import httpx
import pytest

from intern_radar.models import ScoredJob
from intern_radar.notifier import (
    Action,
    ConsoleNotifier,
    Message,
    NotifyError,
    NtfyNotifier,
    format_digest,
    format_immediate,
    format_llm_alert,
    format_source_alert,
)
from tests.factories import make_assessment, make_job, mock_client


def scored(job_id="j1", score=9.7, **job_overrides):
    return ScoredJob(make_job(id=job_id, **job_overrides), make_assessment(), score)


def test_format_immediate_uses_the_card_layout():
    message = format_immediate(
        scored(company="Google DeepMind", tier="S", title="Research Engineer Intern")
    )
    assert message.title == "Google DeepMind · niveau S"
    assert message.body == (
        "Research Engineer Intern\n"
        "━━━━━━━━━━━━━━━━\n"
        "📍  London, UK\n"
        "⭐  9.7 / 10\n"
        "📅  Dates compatibles\n"
        "🛂  UK: GAE scheme via a sponsor\n"
        "━━━━━━━━━━━━━━━━\n"
        "Applied ML on LLM agents."
    )
    assert message.priority == 4
    assert message.tags == ("fire",)
    assert message.click == "https://example.com/jobs/1"
    assert message.actions == (Action("Voir l'offre", "https://example.com/jobs/1"),)


def test_format_immediate_without_location():
    message = format_immediate(scored(location=""))
    assert "📍  Lieu non précisé" in message.body


def test_format_digest_lists_offers():
    offer = scored(
        "a", 7.1, company="Databricks", title="ML Intern", location="Amsterdam"
    )
    message = format_digest([offer])
    assert message.title == "Récap du soir — 1 offre"
    assert message.body == "• [A] Databricks — ML Intern · Amsterdam · 7.1"
    assert message.priority == 3


def test_digest_is_truncated_after_20_lines():
    jobs = [
        scored(f"j{i}", 6.0, title="Machine Learning Intern " * 3) for i in range(45)
    ]
    message = format_digest(jobs)
    lines = message.body.split("\n")
    assert message.title == "Récap du soir — 45 offres"
    assert len(lines) == 21
    assert lines[-1] == "… et 25 autres (intern-radar list)"
    assert len(message.body.encode()) < 4096


def test_alert_messages():
    assert format_source_alert("Acme", "HTTP 500").title == "Source en panne : Acme"
    assert "HTTP 500" in format_source_alert("Acme", "HTTP 500").body
    assert format_llm_alert().priority == 2


def test_ntfy_notifier_posts_json_to_the_server_root():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "x"})

    client = mock_client({"POST https://ntfy.sh/": handler})
    message = Message(
        "T",
        "B",
        4,
        ("fire",),
        "https://u",
        (
            Action("Voir l'offre", "https://u"),
            Action("Lettre", "https://ntfy.sh/req", method="POST", body="job-1"),
        ),
    )
    NtfyNotifier("https://ntfy.sh/", "topic-1", client).send(message)
    assert seen["body"] == {
        "topic": "topic-1",
        "title": "T",
        "message": "B",
        "priority": 4,
        "tags": ["fire"],
        "click": "https://u",
        "actions": [
            {"action": "view", "label": "Voir l'offre", "url": "https://u"},
            {
                "action": "http",
                "label": "Lettre",
                "url": "https://ntfy.sh/req",
                "method": "POST",
                "body": "job-1",
            },
        ],
    }


def test_format_immediate_adds_the_letter_button():
    message = format_immediate(scored(), "https://ntfy.sh/req")
    assert message.actions[1] == Action(
        "✍️ Lettre de motivation", "https://ntfy.sh/req", method="POST", body="j1"
    )


def test_ntfy_notifier_raises_on_http_error():
    client = mock_client({"POST https://ntfy.sh/": 429})
    with pytest.raises(NotifyError):
        NtfyNotifier("https://ntfy.sh", "t", client).send(Message("T", "B"))


def test_console_notifier_writes_the_message():
    lines = []
    ConsoleNotifier(write=lines.append).send(Message("T", "B", 4))
    assert lines == ["[priority 4] T\nB\n"]
