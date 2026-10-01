from datetime import UTC, datetime, timedelta

import pytest

from intern_radar.dashboard import queries
from intern_radar.dashboard.app import Request
from intern_radar.dashboard.routes import Context, build_app, parse_details
from intern_radar.store import ApplicationDetails, Store
from tests.factories import make_assessment, make_job, make_profile

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
HEADERS = {"host": "radar", "origin": "http://radar"}


def make_db(tmp_path) -> str:
    path = str(tmp_path / "apps.db")
    store = Store(path)
    for job_id in ("liked", "notified", "old", "plain", "applied", "late",
                   "interview", "offer", "rejected", "gone"):  # fmt: skip
        store.add(make_job(id=job_id, company=f"Co {job_id}"), "pending", NOW)
        store.save_assessment(job_id, make_assessment(), 7.0)
    store.set_feedback("liked", 1, "", NOW)
    store.mark_notified("notified", NOW - timedelta(days=2))
    store.mark_notified("old", NOW - timedelta(days=45))
    store.set_application("applied", "applied", NOW - timedelta(days=3))
    store.set_application("late", "applied", NOW - timedelta(days=20))
    store.set_application("interview", "applied", NOW - timedelta(days=9))
    store.set_application("interview", "interview", NOW - timedelta(days=1))
    store.set_application("offer", "offer", NOW)
    store.set_application("rejected", "rejected", NOW)
    store.set_application("gone", "dismissed", NOW)
    store.save_application_details(
        "interview",
        ApplicationDetails(
            interviews=("2026-10-03T10:00", "2026-09-20T09:00"),
            next_action="Envoyer un merci",
            next_action_date="2026-10-04",
        ),
        NOW,
    )
    store.save_application_details(
        "liked", ApplicationDetails(deadline="2026-10-10"), NOW
    )
    store.close()
    return path


def companies(cards):
    return sorted(card.company for card in cards)


def test_board_columns(tmp_path):
    db = queries.connect(make_db(tmp_path))
    columns = queries.board(db, NOW, reminder_days=14)
    assert companies(columns["to_apply"]) == ["Co liked", "Co notified"]
    assert companies(columns["applied"]) == ["Co applied", "Co late"]
    assert companies(columns["interview"]) == ["Co interview"]
    assert companies(columns["offer"]) == ["Co offer"]
    assert companies(columns["closed"]) == ["Co rejected"]
    late = next(c for c in columns["applied"] if c.company == "Co late")
    assert late.reminder_due and columns["applied"][0] is late  # due first
    liked = columns["to_apply"][0]
    assert liked.company == "Co liked" and liked.deadline == "2026-10-10"
    assert liked.liked


def test_calendar_lists_upcoming_events_soonest_first(tmp_path):
    db = queries.connect(make_db(tmp_path))
    events = queries.calendar(db, NOW, reminder_days=14)
    assert [(ev.when, ev.kind, ev.company) for ev in events] == [
        ("2026-10-01", "reminder", "Co late"),  # overdue reminders show today
        ("2026-10-03T10:00", "interview", "Co interview"),
        ("2026-10-04", "action", "Co interview"),
        ("2026-10-10", "deadline", "Co liked"),
        ("2026-10-12", "reminder", "Co applied"),
    ]


def test_details_round_trip_and_parsing():
    store = Store(":memory:")
    store.add(make_job(id="j1"), "pending", NOW)
    assert store.application_details("j1") == ApplicationDetails()
    details = parse_details(
        {
            "contact_name": " Ada ",
            "contact_email": "ada@acme.io",
            "deadline": "2026-10-20",
            "interview1": "2026-10-12T14:30",
            "interview0": "2026-10-08T09:00",
            "interview2": "",
            "next_action": "Relancer",
            "next_action_date": "",
            "notes": "Équipe RAG",
        }
    )
    assert details.interviews == ("2026-10-08T09:00", "2026-10-12T14:30")
    assert details.contact_name == "Ada" and details.next_action_date is None
    store.save_application_details("j1", details, NOW)
    assert store.application_details("j1") == details
    for bad in ({"deadline": "demain"}, {"interview0": "2026-10-08"},
                {"contact_email": "ada"}):  # fmt: skip
        with pytest.raises(ValueError):
            parse_details(bad)


def test_applications_routes(tmp_path):
    path = make_db(tmp_path)
    ctx = Context(path, clock=lambda: NOW, profile=make_profile(reminder_days=14))
    app = build_app(ctx)
    body = app.handle(Request("GET", "/applications", {})).body.decode()
    assert "Agenda" in body and "Envoyer un merci" in body
    assert "1 relance(s) à faire" in body and "Co rejected" in body
    assert "Co gone" not in body
    store = Store(path)
    ref = store.job_ref("applied")
    store.close()
    detail = app.handle(Request("GET", f"/offers/{ref}", {})).body.decode()
    assert f'action="/offers/{ref}/details"' in detail
    form = {"contact_name": "Ada", "deadline": "2026-10-20", "notes": "ok"}
    response = app.handle(Request("POST", f"/offers/{ref}/details", {}, form, HEADERS))
    assert response.headers == (("Location", f"/offers/{ref}?done=details"),)
    detail = app.handle(Request("GET", f"/offers/{ref}", {})).body.decode()
    assert 'value="Ada"' in detail and 'value="2026-10-20"' in detail
    bad = app.handle(
        Request("POST", f"/offers/{ref}/details", {}, {"deadline": "x"}, HEADERS)
    )
    assert bad.status == 400
    foreign = Request("POST", f"/offers/{ref}/details", {}, form)
    assert app.handle(foreign).status == 403


def test_board_shows_one_card_per_posting_group(tmp_path):
    store = Store(":memory:")
    for job_id, location in (("a", "Berlin"), ("b", "London"), ("c", "Paris")):
        store.add(
            make_job(id=job_id, company="Acme", title="ML Intern", location=location),
            "pending", NOW,
        )  # fmt: skip
        store.save_assessment(job_id, make_assessment(), 7.0)
        store.mark_notified(job_id, NOW)
    store.add(make_job(id="d", company="Beta", title="AI Intern"), "pending", NOW)
    store.save_assessment("d", make_assessment(), 6.0)
    store.add(
        make_job(id="e", company="Beta", title="AI Intern", location="Madrid"),
        "pending", NOW,
    )  # fmt: skip
    store.save_assessment("e", make_assessment(), 6.0)
    store.set_feedback("d", 1, "", NOW)
    store.set_application("e", "applied", NOW)
    columns = queries.board(store._db, NOW, reminder_days=14)
    assert companies(columns["to_apply"]) == ["Acme"]  # Beta is tracked via "e"
    assert companies(columns["applied"]) == ["Beta"]
