import json
from datetime import UTC, datetime

import pytest

from intern_radar.dashboard.app import Request
from intern_radar.dashboard.routes import Context, autofill_token, build_app
from intern_radar.form_answers import (
    FormAnswerer,
    FormField,
    is_personal,
    parse_fields,
    validate,
)
from intern_radar.store import Store
from tests.factories import make_assessment, make_job
from tests.test_kit import PROFILE

NOW = datetime(2026, 10, 2, 9, tzinfo=UTC)
FIELDS = [
    FormField(0, "Language Skill(s) (Check all that apply)", "checkbox",
              ("English (ENG)", "French (FRA)", "Spanish (SPA)", "German (DEU)")),
    FormField(1, "Expected graduation year", "select", ("Select...", "2027", "2028")),
    FormField(2, "Start date month", "combobox"),
    FormField(3, "Why Palantir?", "textarea"),
    FormField(4, "Gender", "select", ("Male", "Female", "Decline")),
    FormField(5, "I consent to the AI notetaker", "radio", ("Yes, I consent", "No")),
]  # fmt: skip


class Backend:
    def __init__(self, answers):
        self.answers, self.prompts = answers, []

    def complete(self, prompt, schema):
        self.prompts.append(prompt)
        return {"answers": self.answers}


@pytest.mark.parametrize(
    "label, personal",
    [("Language Skill(s)", False), ("What is your age?", True), ("Gender", True),
     ("I consent to the processing", True), ("Are you a veteran?", True),
     ("Long-term goals", False), ("Certifications held", False),
     ("Please certify the information is true", True), ("Race / ethnicity", True),
     ("Trace your path", False)],
)  # fmt: skip
def test_personal_questions(label, personal):
    assert is_personal(FormField(0, label, "text")) is personal


def test_validate_keeps_known_options_only():
    answers = validate(
        FIELDS,
        [
            {"id": 0, "values": ["english (eng)", "French (FRA)", "Klingon"]},
            {"id": 1, "value": "2028"},
            {"id": 2, "value": "September"},
            {"id": 3, "value": "Because of the mission.", "review": True},
            {"id": 4, "value": "Male"},  # personal: dropped
            {"id": 5, "value": "Yes, I consent"},  # consent: dropped
            {"id": 9, "value": "x"},  # unknown field
            {"id": 1, "value": "2031"},  # not an option: dropped (first kept)
        ],
    )
    assert answers == {
        0: {"values": ["English (ENG)", "French (FRA)"], "review": False},
        1: {"value": "2028", "review": False},
        2: {"value": "September", "review": False},
        3: {"value": "Because of the mission.", "review": True},
    }


def test_parse_fields_drops_malformed_entries():
    fields = parse_fields(
        [
            {"id": 0, "kind": "select", "label": "Year", "options": ["2027", " "]},
            {"id": "x", "kind": "text"},
            {"id": 1, "kind": "slider"},
            "junk",
        ]
    )
    assert fields == [FormField(0, "Year", "select", ("2027",), False)]
    assert parse_fields(None) == []


def test_answerer_sends_facts_and_never_asks_personal_questions():
    backend = Backend([{"id": 1, "value": "2028"}])
    kit = {
        "offer": {"company": "Palantir", "title": "FDSE Intern", "location": "London"},
        "fields": {"education_end_year": 2028, "internship_start_month": 3},
        "answers": [{"question": "Will you require visa sponsorship?", "answer": "No."},
                    {"question": "Full name", "answer": "Alex"}],
    }  # fmt: skip
    result = FormAnswerer(backend).answer(kit, "Profile text", FIELDS)
    assert result == {1: {"value": "2028", "review": False}}
    prompt = backend.prompts[0]
    assert "Will you require visa sponsorship?: No." in prompt
    assert "Full name: Alex" not in prompt  # only fixed visa/dates answers
    listed = json.loads(prompt.split("Fields:\n", 1)[1])
    assert [f["id"] for f in listed] == [0, 1, 2, 3]  # gender and consent withheld
    assert FormAnswerer(backend).answer(kit, "", [FIELDS[4]]) == {}


def make_app(tmp_path, backend):
    db = str(tmp_path / "f.db")
    store = Store(db)
    store.add(make_job(id="lever:p:1", company="Palantir"), "pending", NOW)
    store.save_assessment("lever:p:1", make_assessment(), 8.0)
    ref = store.job_ref("lever:p:1")
    token = autofill_token(store)
    store.close()
    form_backend = (lambda store: backend) if backend else None
    ctx = Context(db, clock=lambda: NOW, profile=PROFILE, form_backend=form_backend)
    return build_app(ctx), ref, token, db


def post(app, path, payload, token=None, origin=None):
    headers = {"host": "100.1.2.3:8787"}
    if token is not None:
        headers["x-radar-token"] = token
    if origin:
        headers["origin"] = origin
    return app.handle(
        Request("POST", path, {}, {}, headers, json.dumps(payload).encode())
    )


def test_fill_endpoint_requires_the_token(tmp_path):
    backend = Backend([{"id": 0, "value": "2028"}])
    app, ref, token, db = make_app(tmp_path, backend)
    fields = [{"id": 0, "kind": "select", "label": "Year", "options": ["2027", "2028"]}]
    response = post(app, f"/api/kit/{ref}/fill", {"fields": fields}, token)
    assert response.status == 200
    assert json.loads(response.body) == {
        "answers": [{"id": 0, "value": "2028", "review": False}]
    }
    assert post(app, f"/api/kit/{ref}/fill", {"fields": fields}, "wrong").status == 403
    assert post(app, f"/api/kit/{ref}/fill", {"fields": fields}).status == 403
    assert post(app, "/api/kit/999/fill", {"fields": fields}, token).status == 404
    bad = Request(
        "POST", f"/api/kit/{ref}/fill", {}, {}, {"x-radar-token": token}, b"{"
    )
    assert app.handle(bad).status == 400
    store = Store(db)
    assert autofill_token(store) == token  # stable once created
    store.close()


def test_fill_endpoint_without_backend_and_other_posts_keep_origin_check(tmp_path):
    app, ref, token, _ = make_app(tmp_path, None)
    assert post(app, f"/api/kit/{ref}/fill", {"fields": []}, token).status == 503
    # Other POST routes still require the page's own origin.
    headers = {"host": "h", "origin": "http://evil"}
    status = Request(
        "POST", f"/offers/{ref}/status", {}, {"status": "applied"}, headers
    )
    foreign = app.handle(status)
    assert foreign.status == 403


def test_userscript_carries_the_token(tmp_path):
    app, _, token, _ = make_app(tmp_path, None)
    script = app.handle(Request("GET", "/radar.user.js", {}, {}, {"host": "h:1"})).body
    assert f'const TOKEN = "{token}";'.encode() in script
