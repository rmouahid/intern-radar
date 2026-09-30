from datetime import UTC, datetime

from intern_radar.promotion import Promoter
from intern_radar.store import Store
from tests.factories import make_assessment, make_job

NOW = datetime(2026, 9, 30, 19, tzinfo=UTC)


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def send(self, message):
        self.sent.append(message)


def setup(letters=True):
    store = Store(":memory:")
    for job_id, title, location in (
        ("de", "SDE Intern - Germany", "Berlin"),
        ("uk", "SDE Intern - UK", "London"),
        ("other", "Data Intern", "Madrid"),
    ):
        store.add(make_job(id=job_id, title=title, location=location), "pending", NOW)
        store.save_assessment(job_id, make_assessment(), 6.5)
    store.mark_digested(["de", "uk", "other"], NOW)
    notifier = FakeNotifier()
    return store, notifier, Promoter(store, notifier, letters, clock=lambda: NOW)


def test_promotion_sends_the_full_notification_for_the_whole_group():
    store, notifier, promoter = setup()
    assert promoter.promote(store.job_ref("de")) is True
    [message] = notifier.sent
    assert message.html.startswith("🔥 <b>Acme · niveau A</b>")
    assert "Berlin" in message.html and "London" in message.html
    labels = [button.label for row in message.buttons for button in row]
    assert labels == ["🔗 Voir l'offre", "✍️ Lettre de motivation"]
    assert message.buttons[0][1].callback == f"L:{store.job_ref('de')}"
    notified = {s.job.id for s in store.scored(0) if s.job.id in ("de", "uk")}
    assert notified == {"de", "uk"}
    assert store.due_immediate(0) == []


def test_repeated_promotion_sends_again_without_duplicating_state():
    store, notifier, promoter = setup()
    ref = store.job_ref("de")
    promoter.promote(ref)
    promoter.promote(ref)
    assert len(notifier.sent) == 2
    assert len(store.scored(0)) == 3


def test_unknown_or_unscored_refs_are_refused():
    store, notifier, promoter = setup()
    store.add(make_job(id="p", title="Pending Intern"), "pending", NOW)
    assert promoter.promote(999) is False
    assert promoter.promote(store.job_ref("p")) is False
    assert notifier.sent == []


def test_no_letter_button_when_letters_are_disabled():
    store, notifier, promoter = setup(letters=False)
    promoter.promote(store.job_ref("other"))
    labels = [button.label for row in notifier.sent[0].buttons for button in row]
    assert labels == ["🔗 Voir l'offre"]


def test_promotion_includes_the_interview_chance():
    from intern_radar.chance import Chance

    store, notifier, _ = setup()
    promoter = Promoter(
        store,
        notifier,
        True,
        clock=lambda: NOW,
        chance=lambda s: Chance(30, ((True, "x"),)),
    )
    promoter.promote(store.job_ref("other"))
    assert "Chance d'entretien : 30 %" in notifier.sent[0].html
