from datetime import UTC, date, datetime

import pytest

from intern_radar.answers import defaults, merged, offer_answers
from intern_radar.candidate import parse_candidate
from intern_radar.config import Contact
from intern_radar.dashboard.app import Request
from intern_radar.dashboard.routes import Context, build_app
from intern_radar.store import Store
from tests.factories import make_profile
from tests.test_candidate import profile_dict

NOW = datetime(2026, 10, 2, 9, tzinfo=UTC)
HEADERS = {"host": "radar", "origin": "http://radar"}
CONTACT = Contact("Alex Martin", "Paris", "+33 1", "a@x.io", "li/alex", "gh/alex")
PROFILE = make_profile(
    contact=CONTACT,
    window_start=date(2027, 3, 8),
    window_end=date(2027, 8, 31),
    min_months=4,
)
CANDIDATE = parse_candidate(profile_dict())


def test_defaults_come_from_the_profiles():
    values = defaults(PROFILE, CANDIDATE)
    assert values["full_name"] == "Alex Martin" and values["github"] == "gh/alex"
    assert values["school"] == CANDIDATE.education[0].school
    assert values["availability"].startswith(
        "Available for a 6-month internship from 8 March 2027 to 31 August 2027"
    )
    assert defaults(make_profile(), None)["full_name"] == ""


def test_saved_answers_override_defaults_and_custom_ones_follow():
    saved = {
        "salary": ("Salary expectations", "1 500 € per month"),
        "custom:1": ("Why AI?", "Because."),
    }
    answers = merged(saved, PROFILE, CANDIDATE)
    by_key = {a.key: a for a in answers}
    assert by_key["salary"].value == "1 500 € per month" and by_key["salary"].validated
    assert not by_key["email"].validated and by_key["email"].value == "a@x.io"
    assert answers[-1].question == "Why AI?"


@pytest.mark.parametrize(
    "authorisation, authorised, sponsorship",
    [
        ("free", "Yes. I am a French (EU) citizen", "No."),
        ("self_arranged", "Yes, with a Working Holiday visa", "No, I do not need"),
        (
            "programme",
            "Not yet: I would need the standard intern visa",
            "Yes: an intern",
        ),
        ("uncertain", "Not yet: I would need a work visa", "Yes, I would need visa"),
        ("unlikely", "Not yet: I would need a work visa", "Yes, I would need visa"),
    ],
)
def test_offer_answers_follow_the_work_authorisation(
    authorisation, authorised, sponsorship
):
    answers = dict(offer_answers(authorisation, "Berlin, Germany; Munich", PROFILE))
    assert answers["Are you legally authorised to work in this country?"].startswith(
        authorised
    )
    assert answers[
        "Will you now or in the future require visa sponsorship?"
    ].startswith(sponsorship)
    assert answers["Are you willing to relocate?"].endswith("to Berlin, Germany.")
    assert answers["Earliest start date"] == "8 March 2027"


def test_offer_answers_in_french():
    answers = dict(offer_answers("free", "Genève", PROFILE, "fr"))
    assert answers["Date de début au plus tôt"] == "8 mars 2027"
    assert answers["Aurez-vous besoin d'un parrainage de visa ?"] == "Non."
    assert offer_answers("free", "", PROFILE, "de")[0][0].startswith("Are you")


def test_answers_routes(tmp_path):
    path = str(tmp_path / "a.db")
    Store(path).close()
    app = build_app(Context(path, clock=lambda: NOW, profile=PROFILE))
    page = app.handle(Request("GET", "/answers", {})).body.decode()
    assert "proposée" in page and "Alex Martin" in page and "8 March 2027" in page

    def post(path, **form):
        return app.handle(Request("POST", path, {}, form, HEADERS))

    assert post("/answers", salary="1 500 €", email="me@x.io").status == 303
    store = Store(path)
    assert store.answers()["salary"] == ("Salary expectations", "1 500 €")
    store.close()
    page = app.handle(Request("GET", "/answers", {})).body.decode()
    assert "me@x.io" in page and "validée" in page
    post("/answers/custom", question="Why us?", answer="Mission.")
    assert "Why us?" in app.handle(Request("GET", "/answers", {})).body.decode()
    missing = post("/answers/custom", question="x", answer=" ")
    assert missing.headers == (("Location", "/answers?done=answers_missing"),)
    store = Store(path)
    key = next(k for k in store.answers() if k.startswith("custom:"))
    store.close()
    post("/answers/delete", key="salary")  # standard answers are not deletable
    post("/answers/delete", key=key)
    store = Store(path)
    assert set(store.answers()) == {"salary", "email"}
    store.close()
    assert app.handle(Request("POST", "/answers", {}, {"salary": "x"})).status == 403
    no_profile = build_app(Context(path))
    assert no_profile.handle(Request("GET", "/answers", {})).status == 404
