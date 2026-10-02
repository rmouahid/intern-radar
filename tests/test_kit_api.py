import json
from datetime import UTC, datetime

import pytest

from intern_radar.dashboard.app import Request
from intern_radar.dashboard.kit_api import month_year, posting_key
from intern_radar.dashboard.routes import Context, build_app
from intern_radar.store import Store
from tests.factories import make_assessment, make_job
from tests.test_kit import CANDIDATE, PROFILE

NOW = datetime(2026, 10, 2, 9, tzinfo=UTC)
HEADERS = {"host": "100.1.2.3:8787"}
LEVER = "4d29249a-d7e8-4c39-880d-3b35d7b2f6f6"


@pytest.mark.parametrize(
    "url, key",
    [
        ("https://job-boards.greenhouse.io/drweng/jobs/7991171", "7991171"),
        ("https://job-boards.greenhouse.io/drweng/jobs/7991171#radar=4", "7991171"),
        ("https://www.jumptrading.com/hr/job?gh_jid=8027938", "8027938"),
        ("https://job-boards.greenhouse.io/embed/job_app?for=jump&token=8027938",
         "8027938"),
        (f"https://jobs.lever.co/palantir/{LEVER}/apply", LEVER),
        (f"https://jobs.ashbyhq.com/perplexity/{LEVER}/application", LEVER),
        ("https://www.amazon.jobs/en/jobs/123", None),
    ],
)  # fmt: skip
def test_posting_key(url, key):
    assert posting_key(url) == key


@pytest.mark.parametrize(
    "text, expected",
    [("Sept. 2028", (9, 2028)), ("March 2027", (3, 2027)), ("août 2026", (8, 2026)),
     ("2028", (None, 2028)), ("", (None, None))],
)  # fmt: skip
def test_month_year(text, expected):
    assert month_year(text) == expected


def make_app(tmp_path):
    db = str(tmp_path / "api.db")
    store = Store(db)
    store.add(
        make_job(id="greenhouse:drweng:7991171", company="DRW", source="greenhouse",
                 location="Montreal, Canada",
                 url="https://job-boards.greenhouse.io/drweng/jobs/7991171"),
        "pending", NOW,
    )  # fmt: skip
    store.save_assessment(
        "greenhouse:drweng:7991171",
        make_assessment(work_authorisation="self_arranged"), 8.0,
    )  # fmt: skip
    store.add(
        make_job(id=f"lever:palantir:{LEVER}", company="Palantir", source="lever"),
        "pending", NOW,
    )  # fmt: skip
    store.save_assessment(f"lever:palantir:{LEVER}", make_assessment(), 7.0)
    store.save_why("greenhouse:drweng:7991171", "Because markets.", [], NOW)
    store.save_resume("greenhouse:drweng:7991171", str(tmp_path / "cv.pdf"), {}, NOW)
    refs = (
        store.job_ref("greenhouse:drweng:7991171"),
        store.job_ref(f"lever:palantir:{LEVER}"),
    )
    store.close()
    config = tmp_path / "config"
    config.mkdir()
    from intern_radar.candidate import save_candidate

    save_candidate(CANDIDATE, config / "candidate.json")
    app = build_app(Context(db, clock=lambda: NOW, profile=PROFILE, config_dir=config))
    return app, refs


def get_json(app, path, **query):
    response = app.handle(Request("GET", path, query, {}, HEADERS))
    return response.status, response.content_type, json.loads(response.body)


def test_lookup_finds_the_offer_from_the_form_url(tmp_path):
    app, (drw, palantir) = make_app(tmp_path)
    status, kind, data = get_json(
        app, "/api/kit/lookup",
        url="https://www.drw.com/careers?gh_jid=7991171",
    )  # fmt: skip
    assert (status, data) == (200, {"ref": drw}) and kind.startswith("application/json")
    lever = f"https://jobs.lever.co/palantir/{LEVER}/apply"
    _, _, data = get_json(app, "/api/kit/lookup", url=lever)
    assert data == {"ref": palantir}
    status, _, data = get_json(app, "/api/kit/lookup", url="https://example.com/x")
    assert status == 404


def test_kit_json(tmp_path):
    app, (drw, _) = make_app(tmp_path)
    status, _, data = get_json(app, f"/api/kit/{drw}.json")
    assert status == 200
    fields = data["fields"]
    assert fields["first_name"] == "Alex" and fields["last_name"] == "Martin"
    assert fields["city"] == "Paris" and fields["linkedin"] == "https://li/alex"
    assert (fields["start_month"], fields["start_year"]) == (3, 2027)
    assert data["offer"]["ats"] == "greenhouse" and data["why"] == "Because markets."
    assert data["documents"] == {"cv": f"http://100.1.2.3:8787/files/cv/{drw}"}
    assert data["offer"]["page"] == f"http://100.1.2.3:8787/offers/{drw}#kit"
    questions = {a["question"]: a["answer"] for a in data["answers"]}
    assert questions["Will you now or in the future require visa sponsorship?"] == (
        "No, I do not need employer sponsorship."
    )
    _, _, french = get_json(app, f"/api/kit/{drw}.json", lang="fr")
    assert any(a["question"] == "Nom complet" for a in french["answers"])
    assert get_json(app, "/api/kit/999.json")[0] == 404


def test_form_link_carries_the_offer_ref(tmp_path):
    app, (drw, _) = make_app(tmp_path)
    page = app.handle(Request("GET", f"/offers/{drw}", {})).body.decode()
    assert f'jobs/7991171#radar={drw}"' in page
