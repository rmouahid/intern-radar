from datetime import UTC, datetime

from intern_radar.config import Contact
from intern_radar.letters.cv import CvError
from intern_radar.letters.delivery import DeliveryError
from intern_radar.letters.service import LetterService, format_letter_card
from intern_radar.letters.writer import Letter, LetterReport
from intern_radar.store import Store
from tests.factories import make_job

NOW = datetime(2026, 9, 24, 12, tzinfo=UTC)
CONTACT = Contact("Rayân Mouahid", "Paris", "+33", "me@example.com", "li", "gh")
LETTER = Letter("en", "Dear Hiring Team,", ("One.", "Two.", "Three."), "Sincerely,")
REPORT = LetterReport(("Python",), ("PyTorch",), ("Kubernetes",), 4, (), ("40%",))


class FakeWriter:
    calls = 0

    def __init__(self, error=None):
        self.error = error

    def write(self, job):
        FakeWriter.calls += 1
        if self.error:
            raise self.error
        return LETTER, REPORT


class Recorder:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    def send(self, *args, **kwargs):
        if self.fail:
            raise DeliveryError("e-mail: SMTPAuthenticationError")
        self.sent.append(args or kwargs)


def build(tmp_path, writer=None, mail=None, max_per_day=10, jobs=None):
    store = Store(":memory:")
    for job in jobs or [make_job(id="j1", company="Acme", title="ML Intern")]:
        store.add(job, "pending", NOW)
    FakeWriter.calls = 0
    attachments, notifier = Recorder(), Recorder()
    service = LetterService(
        store,
        lambda: writer or FakeWriter(),
        CONTACT,
        tmp_path / "letters",
        attachments,
        mail,
        notifier,
        max_per_day,
        clock=lambda: NOW,
    )
    return service, store, attachments, notifier


def test_generates_stores_and_delivers(tmp_path):
    mail = Recorder()
    service, store, attachments, notifier = build(tmp_path, mail=mail)
    path = service.handle("j1\n")
    assert path.name == "Mouahid_CoverLetter_Acme_ML-Intern.pdf"
    assert path.read_bytes().startswith(b"%PDF")
    stored_path, report = store.letter("j1")
    assert stored_path == str(path) and report["ai_changes"] == 4
    pdf, filename, title, card = attachments.sent[0]
    assert (filename, title) == (path.name, "✍️ Lettre prête · Acme")
    assert "🎯  ATS : 1/2 mots-clés" in card
    assert "📧  Envoyée par e-mail" in card
    assert mail.sent[0]["subject"] == "Lettre — Acme · ML Intern"
    assert notifier.sent == []


def test_second_request_redelivers_without_llm(tmp_path):
    service, _, attachments, _ = build(tmp_path)
    first = service.handle("j1")
    second = service.handle("j1")
    assert first == second and FakeWriter.calls == 1
    assert len(attachments.sent) == 2


def test_unknown_job_is_ignored(tmp_path):
    service, _, attachments, notifier = build(tmp_path)
    assert service.handle("nope") is None
    assert attachments.sent == [] and notifier.sent == []


def test_daily_cap_sends_one_notice(tmp_path):
    jobs = [make_job(id=f"j{i}") for i in range(3)]
    service, _, _, notifier = build(tmp_path, max_per_day=1, jobs=jobs)
    service.handle("j0")
    assert service.handle("j1") is None
    assert service.handle("j2") is None
    assert [m.title for (m,) in notifier.sent] == ["Limite de lettres atteinte"]


def test_writer_failure_sends_a_failure_notification(tmp_path):
    service, store, _, notifier = build(
        tmp_path, writer=FakeWriter(CvError("CV unavailable: ConnectError"))
    )
    assert service.handle("j1") is None
    [(message,)] = notifier.sent
    assert message.title == "❌ Lettre non générée · Acme"
    assert "CV unavailable" in message.body
    assert store.letter("j1") is None


def test_email_failure_is_reported_in_the_card(tmp_path):
    service, _, attachments, _ = build(tmp_path, mail=Recorder(fail=True))
    service.handle("j1")
    card = attachments.sent[0][3]
    assert "📧  E-mail en échec : e-mail: SMTPAuthenticationError" in card


def test_letter_for_a_job_without_description(tmp_path):
    job = make_job(id="j1", company="Acme", title="ML Intern", description="")
    service, _, _, _ = build(tmp_path, jobs=[job])
    assert service.handle("j1") is not None


def test_format_letter_card_lists_every_check():
    report = {
        "keywords_present": ["Python"],
        "keywords_missing": ["Go"],
        "keywords_not_in_cv": ["Rust"],
        "ai_changes": 2,
        "unverified": ["40%"],
        "blacklist_left": [],
        "dropped": [],
    }
    card = format_letter_card(
        make_job(title="ML Intern"), report, "f.pdf", "📧  Envoyée par e-mail"
    )
    assert card == (
        "ML Intern\n━━━━━━━━━━━━━━━━\n🎯  ATS : 1/2 mots-clés\n"
        "🚫  Absents de ton CV : Rust\n🧹  Anti-IA : 2 tournures corrigées\n"
        "⚠️  À vérifier : 40%\n📧  Envoyée par e-mail\n━━━━━━━━━━━━━━━━\n📎 f.pdf"
    )


def test_unexpected_error_still_sends_a_failure_notification(tmp_path):
    service, _, _, notifier = build(
        tmp_path, writer=FakeWriter(RuntimeError("fpdf exploded"))
    )
    assert service.handle("j1") is None
    [(message,)] = notifier.sent
    assert message.title == "❌ Lettre non générée · Acme"
    assert "RuntimeError" in message.body


def test_same_company_and_title_do_not_share_a_file(tmp_path):
    jobs = [
        make_job(id="a", company="Acme", title="ML Intern", location="Paris"),
        make_job(id="b", company="Acme", title="ML Intern", location="London"),
    ]
    service, _, _, _ = build(tmp_path, jobs=jobs)
    first, second = service.handle("a"), service.handle("b")
    assert first != second
    assert first.name == second.name == "Mouahid_CoverLetter_Acme_ML-Intern.pdf"


def test_card_reports_dropped_characters_and_inferred_keywords():
    report = {
        "keywords_present": ["Python"],
        "keywords_missing": [],
        "keywords_inferred": ["Information Retrieval"],
        "ai_changes": 0,
        "dropped": ["🚀"],
    }
    card = format_letter_card(make_job(title="T"), report, "f.pdf", "📧  x")
    assert "🔎  Déduits de ton CV (à vérifier) : Information Retrieval" in card
    assert "⚠️  Caractères retirés du PDF : 🚀" in card
    report["pages"] = 2
    card = format_letter_card(make_job(title="T"), report, "f.pdf", "📧  x")
    assert "⚠️  2 pages : à raccourcir" in card


def test_card_without_description_says_ats_skipped():
    report = {"ats_skipped": True, "ai_changes": 1}
    card = format_letter_card(make_job(title="T"), report, "f.pdf", "📧  x")
    assert "🎯  ATS : description de l'offre absente" in card
