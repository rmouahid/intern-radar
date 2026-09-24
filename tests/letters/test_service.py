from datetime import UTC, datetime

from intern_radar.config import Contact
from intern_radar.letters.cv import CvError
from intern_radar.letters.delivery import DeliveryError
from intern_radar.letters.service import LetterService, format_letter_caption
from intern_radar.letters.writer import Letter, LetterReport
from intern_radar.store import Store
from tests.factories import make_job

NOW = datetime(2026, 9, 24, 12, tzinfo=UTC)
CONTACT = Contact("Rayân Mouahid", "Paris", "+33", "me@example.com", "li", "gh")
LETTER = Letter("en", "Dear Hiring Team,", ("One.", "Two.", "Three."), "Sincerely,")
REPORT = LetterReport(("Python",), ("PyTorch",), ("Kubernetes",), 4, (), ("40%",))
SEP = "━" * 16


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
    """Records documents, notifications (one argument) and mails (keywords)."""

    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    def send(self, *args, **kwargs):
        if self.fail:
            raise DeliveryError("e-mail: SMTPAuthenticationError")
        self.sent.append(args[0] if len(args) == 1 else args or kwargs)

    def send_document(self, *args):
        self.sent.append(args)


def build(tmp_path, writer=None, mail=None, max_per_day=10, jobs=None):
    store = Store(":memory:")
    for job in jobs or [make_job(id="j1", company="Acme", title="ML Intern")]:
        store.add(job, "pending", NOW)
    FakeWriter.calls = 0
    documents, notifier = Recorder(), Recorder()
    service = LetterService(
        store,
        lambda: writer or FakeWriter(),
        CONTACT,
        tmp_path / "letters",
        documents,
        mail,
        notifier,
        max_per_day,
        clock=lambda: NOW,
    )
    return service, store, documents, notifier


def test_generates_stores_and_delivers(tmp_path):
    mail = Recorder()
    service, store, documents, notifier = build(tmp_path, mail=mail)
    path = service.handle("j1\n")
    assert path.name == "Mouahid_CoverLetter_Acme_ML-Intern.pdf"
    assert path.read_bytes().startswith(b"%PDF")
    stored_path, report = store.letter("j1")
    assert stored_path == str(path) and report["ai_changes"] == 4
    pdf, filename, caption = documents.sent[0]
    assert filename == path.name and pdf.startswith(b"%PDF")
    assert caption.startswith("✍️ <b>Lettre prête · Acme</b>\n<b>ML Intern</b>")
    assert "🎯  <b>ATS</b> : 1/2 mots-clés" in caption
    assert "📧  Envoyée par e-mail" in caption
    assert mail.sent[0]["subject"] == "Lettre — Acme · ML Intern"
    assert "<b>" not in mail.sent[0]["body"] and "One." in mail.sent[0]["body"]
    assert notifier.sent == []


def test_second_request_redelivers_without_llm(tmp_path):
    service, _, documents, _ = build(tmp_path)
    first = service.handle("j1")
    second = service.handle("j1")
    assert first == second and FakeWriter.calls == 1
    assert len(documents.sent) == 2


def test_unknown_job_is_ignored(tmp_path):
    service, _, documents, notifier = build(tmp_path)
    assert service.handle("nope") is None
    assert documents.sent == [] and notifier.sent == []


def test_daily_cap_sends_one_notice(tmp_path):
    jobs = [make_job(id=f"j{i}") for i in range(3)]
    service, _, _, notifier = build(tmp_path, max_per_day=1, jobs=jobs)
    service.handle("j0")
    assert service.handle("j1") is None
    assert service.handle("j2") is None
    assert [m.html.split("\n")[0] for m in notifier.sent] == [
        "⚠️ <b>Limite de lettres atteinte</b>"
    ]


def test_writer_failure_sends_a_failure_notification(tmp_path):
    service, store, _, notifier = build(
        tmp_path, writer=FakeWriter(CvError("CV unavailable: ConnectError"))
    )
    assert service.handle("j1") is None
    [message] = notifier.sent
    assert message.html.startswith("❌ <b>Lettre non générée · Acme</b>")
    assert "CV unavailable" in message.html
    assert store.letter("j1") is None


def test_unexpected_error_still_sends_a_failure_notification(tmp_path):
    service, _, _, notifier = build(
        tmp_path, writer=FakeWriter(RuntimeError("fpdf exploded"))
    )
    assert service.handle("j1") is None
    [message] = notifier.sent
    assert "RuntimeError" in message.html


def test_email_failure_is_reported_in_the_caption(tmp_path):
    service, _, documents, _ = build(tmp_path, mail=Recorder(fail=True))
    service.handle("j1")
    caption = documents.sent[0][2]
    assert "📧  E-mail en échec : e-mail: SMTPAuthenticationError" in caption


def test_letter_for_a_job_without_description(tmp_path):
    job = make_job(id="j1", company="Acme", title="ML Intern", description="")
    service, _, _, _ = build(tmp_path, jobs=[job])
    assert service.handle("j1") is not None


def test_same_company_and_title_do_not_share_a_file(tmp_path):
    jobs = [
        make_job(id="a", company="Acme", title="ML Intern", location="Paris"),
        make_job(id="b", company="Acme", title="ML Intern", location="London"),
    ]
    service, _, _, _ = build(tmp_path, jobs=jobs)
    first, second = service.handle("a"), service.handle("b")
    assert first != second
    assert first.name == second.name == "Mouahid_CoverLetter_Acme_ML-Intern.pdf"


def test_caption_matches_the_approved_layout():
    report = {
        "keywords_present": ["Python"],
        "keywords_missing": ["Go"],
        "keywords_not_in_cv": ["Rust"],
        "keywords_inferred": ["Information Retrieval"],
        "ai_changes": 2,
        "unverified": ["40%"],
        "blacklist_left": [],
        "dropped": ["🚀"],
        "pages": 2,
    }
    caption = format_letter_caption(
        make_job(company="Acme", title="ML Intern"), report, "📧  Envoyée par e-mail"
    )
    assert caption == (
        f"✍️ <b>Lettre prête · Acme</b>\n<b>ML Intern</b>\n{SEP}\n\n"
        "🎯  <b>ATS</b> : 1/2 mots-clés\n\n"
        "🚫  <b>Absents de ton CV</b> :\nRust\n\n"
        "🔎  <b>Déduits de ton CV (à vérifier)</b> :\nInformation Retrieval\n\n"
        "🧹  <b>Anti-IA</b> : 2 tournures corrigées\n\n"
        "⚠️  <b>À vérifier</b> : 40%\n"
        "⚠️  <b>Caractères retirés du PDF</b> : 🚀\n"
        "⚠️  <b>2 pages</b> : à raccourcir\n\n"
        f"📧  Envoyée par e-mail\n\n{SEP}"
    )


def test_caption_without_description_says_ats_skipped():
    caption = format_letter_caption(make_job(), {"ats_skipped": True}, "📧  x")
    assert "🎯  <b>ATS</b> : description de l'offre absente" in caption


def test_caption_stays_under_the_telegram_limit():
    words = [f"Keyword number {i} with a long name" for i in range(40)]
    report = {
        "keywords_not_in_cv": words,
        "keywords_inferred": words,
        "unverified": words,
    }
    job = make_job(company="C" * 200, title="T" * 500)
    assert len(format_letter_caption(job, report, "📧  x")) <= 1024


def _balanced(html):
    import re

    tags = re.findall(r"</?([a-z]+)[^>]*>", html)
    stack = []
    for tag, closing in zip(tags, re.findall(r"<(/?)[a-z]+", html), strict=True):
        if closing:
            if not stack or stack.pop() != tag:
                return False
        else:
            stack.append(tag)
    return not stack


def test_oversized_captions_drop_sections_and_stay_valid_html():
    import html as html_lib
    import re

    words = [f"R&D keyword <{i}> with a long name" for i in range(8)]
    report = {
        "keywords_not_in_cv": words,
        "keywords_inferred": words,
        "unverified": words,
        "dropped": ["x"],
        "pages": 2,
    }
    for repeat in range(0, 60, 3):
        for title in ("T&", "T&" * 60):
            job = make_job(company="AT&T Labs", title=title)
            status = "📧  E-mail en échec : R&D " * repeat
            caption = format_letter_caption(job, report, status)
            visible = html_lib.unescape(re.sub(r"<[^>]+>", "", caption))
            assert len(visible) <= 1024
            assert _balanced(caption), caption[-80:]
            assert not re.search(r"&(?!amp;|lt;|gt;|quot;|#x27;)", caption)
            assert caption.startswith("✍️ <b>Lettre prête · AT&amp;T Labs</b>")
            assert caption.endswith(SEP)  # sections are dropped, never cut


class RejectingDocuments:
    def __init__(self, fail_times):
        self.fail_times = fail_times
        self.calls = []

    def send_document(self, content, filename, caption, html=True):
        from intern_radar.telegram import TelegramError

        self.calls.append((caption, html))
        if len(self.calls) <= self.fail_times:
            raise TelegramError("sendDocument: HTTP 400 can't parse entities")


def test_rejected_caption_is_resent_as_plain_text(tmp_path):
    service, _, _, notifier = build(tmp_path)
    documents = RejectingDocuments(fail_times=1)
    service._documents = documents
    service.handle("j1")
    assert [html for _, html in documents.calls] == [True, False]
    assert "<b>" not in documents.calls[1][0]
    assert notifier.sent == []


def test_undeliverable_letter_sends_a_failure_notification(tmp_path):
    service, _, _, notifier = build(tmp_path)
    service._documents = RejectingDocuments(fail_times=2)
    service.handle("j1")
    [message] = notifier.sent
    assert message.html.startswith("❌ <b>Lettre non envoyée · Acme</b>")
