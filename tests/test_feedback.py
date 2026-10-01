from datetime import UTC, datetime, timedelta

import pytest

from intern_radar.dashboard.app import Request
from intern_radar.dashboard.routes import Context, build_app
from intern_radar.feedback import feedback_summary
from intern_radar.scorer import Scorer
from intern_radar.store import Store
from tests.factories import make_assessment, make_job

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
HEADERS = {"host": "radar", "origin": "http://radar"}


def test_store_keeps_one_vote_per_offer_latest_first():
    store = Store(":memory:")
    for i in range(3):
        store.add(make_job(id=f"j{i}", title=f"Intern {i}"), "pending", NOW)
    store.set_feedback("j0", 1, "  RAG  ", NOW)
    store.set_feedback("j1", -1, "", NOW + timedelta(minutes=1))
    store.set_feedback("j0", -1, "finance", NOW + timedelta(minutes=2))
    assert store.feedback("j0") == (-1, "finance")
    assert [(j.id, v) for j, v, _, _ in store.feedback_entries()] == [
        ("j0", -1),
        ("j1", -1),
    ]
    store.clear_feedback("j0")
    assert store.feedback("j0") is None
    with pytest.raises(ValueError):
        store.set_feedback("j2", 0, "", NOW)


def test_summary_is_bounded_and_split_by_side():
    entries = [
        (
            make_job(company=f"Co{i}", title="ML Intern"),
            1 if i % 2 else -1,
            "x" * 200,
            "",
        )
        for i in range(40)
    ]
    text = feedback_summary(entries)
    assert text.startswith("Offers the candidate liked:")
    assert "Offers the candidate disliked:\n- Co" in text
    assert len(text) <= 1200
    assert text.count("- Co") <= 16
    assert feedback_summary([]) == ""
    short = feedback_summary(
        [(make_job(company="Acme", title="ML Engineer Intern"), -1, "", "")]
    )
    assert short == "Offers the candidate disliked:\n- Acme — ML Engineer Intern"


def test_scoring_prompt_includes_the_feedback_only_when_given():
    args = (object(), "Candidate X", NOW.date(), NOW.date(), 6)
    plain = Scorer(*args).build_prompt([make_job()])
    assert "own feedback" not in plain
    tuned = Scorer(*args, preferences="Offers the candidate liked:\n- A — B")
    prompt = tuned.build_prompt([make_job()])
    assert "own feedback" in prompt and "- A — B" in prompt
    assert "only to calibrate\nai_relevance" in prompt


def make_app(tmp_path):
    path = str(tmp_path / "f.db")
    store = Store(path)
    store.add(make_job(id="j1", company="Acme", title="ML Intern"), "pending", NOW)
    store.save_assessment("j1", make_assessment(), 8.0)
    ref = store.job_ref("j1")
    store.close()
    return path, ref, build_app(Context(path, clock=lambda: NOW))


def post(app, path, **form):
    return app.handle(Request("POST", path, {}, form, HEADERS))


def test_votes_from_the_list_and_the_detail_page(tmp_path):
    path, ref, app = make_app(tmp_path)
    listing = app.handle(Request("GET", "/offers", {})).body.decode()
    assert f'action="/offers/{ref}/feedback"' in listing
    response = post(app, f"/offers/{ref}/feedback", vote="up", next="/offers?tier=S")
    assert response.headers == (("Location", "/offers?tier=S"),)
    listing = app.handle(Request("GET", "/offers", {})).body.decode()
    assert 'class="vote on" title="👍"' in listing
    response = post(app, f"/offers/{ref}/feedback", vote="down", reason="Trop infra")
    assert response.headers == (("Location", f"/offers/{ref}?done=feedback"),)
    detail = app.handle(Request("GET", f"/offers/{ref}", {})).body.decode()
    assert "Tu n&#x27;aimes pas cette offre" in detail and "Trop infra" in detail
    page = app.handle(Request("GET", "/feedback", {})).body.decode()
    assert "Acme" in page and "« Trop infra »" in page and "0 👍 · 1 👎" in page
    post(app, f"/offers/{ref}/feedback", vote="clear")
    store = Store(path)
    assert store.feedback("j1") is None
    store.close()


def test_feedback_redirects_stay_on_the_site(tmp_path):
    _, ref, app = make_app(tmp_path)
    for target in ("https://evil.example/", "//evil.example/offers", "/stats"):
        response = post(app, f"/offers/{ref}/feedback", vote="up", next=target)
        assert response.headers == (("Location", f"/offers/{ref}?done=feedback"),)
    assert post(app, "/offers/999/feedback", vote="up").status == 404
    no_origin = Request("POST", f"/offers/{ref}/feedback", {}, {"vote": "up"})
    assert app.handle(no_origin).status == 403
