import re

import pytest

from intern_radar.models import ScoredJob
from intern_radar.notifier import (
    ConsoleNotifier,
    Message,
    NotifyError,
    TelegramNotifier,
    format_cap_notice,
    format_digest,
    format_immediate,
    format_letter_failure,
    format_llm_alert,
    format_source_alert,
)
from intern_radar.telegram import Button, TelegramError
from tests.factories import make_assessment, make_job

SEP = "━" * 16


def scored(job_id="j1", score=9.7, **job_overrides):
    return ScoredJob(make_job(id=job_id, **job_overrides), make_assessment(), score)


def visible(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html)


def test_format_immediate_matches_the_approved_layout():
    message = format_immediate(
        scored(company="Google DeepMind", tier="S", title="Research Engineer Intern"),
        "L:7",
    )
    assert message.html == (
        "🔥 <b>Google DeepMind · niveau S</b>\n"
        "<b>Research Engineer Intern</b>\n"
        f"{SEP}\n"
        "📍  London, UK\n"
        "⭐  9.7 / 10\n"
        "📅  Dates compatibles\n"
        "🛂  UK: GAE scheme via a sponsor\n"
        f"{SEP}\n"
        "<i>Applied ML on LLM agents.</i>"
    )
    assert message.buttons == (
        (
            Button("🔗 Voir l'offre", url="https://example.com/jobs/1"),
            Button("✍️ Lettre de motivation", callback="L:7"),
        ),
    )
    assert message.silent is False


def test_letter_button_only_when_letters_are_enabled():
    assert len(format_immediate(scored()).buttons[0]) == 1


def test_dynamic_values_are_escaped():
    message = format_immediate(scored(company="R&D <Labs>", title="C++ <Intern>"))
    assert "R&amp;D &lt;Labs&gt;" in message.html
    assert "C++ &lt;Intern&gt;" in message.html


def test_format_digest_matches_the_approved_layout():
    offer = scored(
        "a", 7.1, company="Databricks", title="ML Intern", location="Amsterdam"
    )
    message = format_digest([offer])
    assert message.html == (
        "📋 <b>Récap du soir — 1 offre</b>\n"
        f"{SEP}\n\n"
        "<b>Databricks</b> · niveau A\n"
        '<a href="https://example.com/jobs/1">ML Intern</a>\n'
        "📍 Amsterdam   ⭐ 7.1 / 10\n\n"
        f"{SEP}"
    )
    assert message.silent is True


def test_digest_stays_under_the_telegram_limit():
    jobs = [
        scored(f"j{i}", 6.0, title="Machine Learning Intern " * 10, location="X" * 90)
        for i in range(45)
    ]
    message = format_digest(jobs)
    assert "… et 30 autres (intern-radar list)" in message.html
    assert len(visible(message.html)) < 4096


def test_alerts_and_failures():
    assert format_source_alert("Acme", "HTTP 500").html.startswith(
        "⚠️ <b>Source en panne : Acme</b>\n"
    )
    assert format_llm_alert().silent is True
    failure = format_letter_failure("Acme", "ML Intern", "CV unavailable")
    assert failure.html == (
        "❌ <b>Lettre non générée · Acme</b>\nML Intern\nCV unavailable"
    )
    assert failure.silent is False
    assert "10 lettres" in format_cap_notice(10).html


class FakeTelegram:
    def __init__(self, error=None):
        self.sent = []
        self.error = error

    def send_message(self, html, buttons=(), silent=False):
        if self.error:
            raise self.error
        self.sent.append((html, buttons, silent))


def test_telegram_notifier_sends_and_wraps_errors():
    telegram = FakeTelegram()
    TelegramNotifier(telegram).send(Message("<b>x</b>", (), True))
    assert telegram.sent == [("<b>x</b>", (), True)]
    failing = TelegramNotifier(FakeTelegram(TelegramError("sendMessage: HTTP 500")))
    with pytest.raises(NotifyError, match="telegram: sendMessage: HTTP 500"):
        failing.send(Message("x"))


def test_console_notifier_prints_html_and_buttons():
    lines = []
    ConsoleNotifier(write=lines.append).send(
        Message("<b>T</b>", ((Button("Voir", url="u"),),))
    )
    assert lines == ["<b>T</b>\n[Voir]\n"]


def test_long_llm_fields_are_capped_and_bad_urls_dropped():
    job = scored(title="T" * 900, location="L" * 900, url="javascript:alert(1)")
    message = format_immediate(job)
    assert len(visible(message.html)) < 2000
    assert message.buttons == ()


def test_permanent_telegram_errors_are_flagged():
    rejected = TelegramError("sendMessage: HTTP 400 bad", status=400)
    notifier = TelegramNotifier(FakeTelegram(rejected))
    with pytest.raises(NotifyError) as info:
        notifier.send(Message("x"))
    assert info.value.permanent is True
