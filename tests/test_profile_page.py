import json
from datetime import UTC, datetime

from intern_radar.candidate import parse_candidate, regenerate, save_candidate
from intern_radar.dashboard.app import Request
from intern_radar.dashboard.routes import Context, build_app
from intern_radar.dashboard.worker import Services, Worker
from intern_radar.scorer import LLMError
from intern_radar.store import Store
from tests.test_candidate import DOSSIER, FakeBackend, profile_dict

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
HEADERS = {"host": "radar", "origin": "http://radar"}


def config(tmp_path, with_candidate=True):
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "career.md").write_text(DOSSIER, encoding="utf-8")
    if with_candidate:
        save_candidate(parse_candidate(profile_dict()), config_dir / "candidate.json")
    return config_dir


def site(tmp_path, backend=None, with_candidate=True):
    db = str(tmp_path / "p.db")
    Store(db).close()
    worker = Worker(lambda: Services(letter=lambda j: None, promote=bool))
    ctx = Context(
        db, clock=lambda: NOW, config_dir=config(tmp_path, with_candidate),
        worker=worker, profile_backend=(lambda: backend) if backend else None,
    )  # fmt: skip
    return build_app(ctx), ctx, worker


def post(app, path, **form):
    return app.handle(Request("POST", path, {}, form, HEADERS))


def test_regenerate_saves_a_backup_and_reports_changes(tmp_path):
    config_dir = config(tmp_path)
    answer = profile_dict(summary="New summary.")
    answer["skills"] = [*answer["skills"], {"name": "Rust", "category": "Languages"}]
    result = regenerate(FakeBackend(answer), config_dir)
    assert result.saved and "+ skill Rust" in result.changes
    assert (config_dir / "candidate.json.bak").exists()
    saved = json.loads((config_dir / "candidate.json").read_text())
    assert saved["summary"] == "New summary."
    first = regenerate(FakeBackend(profile_dict()), config(tmp_path / "b", False))
    assert first.changes is None


def test_profile_page_shows_candidate_and_career(tmp_path):
    app, _, _ = site(tmp_path)
    body = app.handle(Request("GET", "/profile", {})).body.decode()
    assert "Engineering student building RAG systems." in body
    assert "career.md" in body and "<textarea" in body
    assert "Jamais régénéré" in body and "Régénération indisponible" in body


def test_career_edit_keeps_a_backup(tmp_path):
    app, ctx, _ = site(tmp_path)
    response = post(app, "/profile/career", career="# Career\r\nNew line\r\n")
    assert response.headers == (("Location", "/profile?done=career_saved"),)
    assert (ctx.config_dir / "career.md").read_text() == "# Career\nNew line\n"
    assert (ctx.config_dir / "career.md.bak").read_text() == DOSSIER
    empty = post(app, "/profile/career", career="   ")
    assert empty.headers == (("Location", "/profile?done=career_invalid"),)
    assert (
        app.handle(Request("POST", "/profile/career", {}, {"career": "x"})).status
        == 403
    )


def test_regeneration_runs_in_the_background_and_is_reported(tmp_path):
    answer = profile_dict()
    answer["skills"] = [*answer["skills"], {"name": "Rust", "category": "Languages"}]
    app, _, worker = site(tmp_path, FakeBackend(answer))
    response = post(app, "/profile/regenerate")
    assert response.headers == (("Location", "/profile?done=queued"),)
    worker.wait()
    body = app.handle(Request("GET", "/profile", {})).body.decode()
    assert "+ skill Rust" in body and "🔄 Régénérer le profil" in body


def test_failed_regeneration_is_reported(tmp_path):
    class Failing:
        def complete(self, prompt, schema):
            raise LLMError("timeout")

    app, ctx, worker = site(tmp_path, Failing())
    post(app, "/profile/regenerate")
    worker.wait()
    assert worker.call_state("profile").error == "timeout"
    body = app.handle(Request("GET", "/profile", {})).body.decode()
    assert "échec · timeout" in body
    assert not (ctx.config_dir / "candidate.json.bak").exists()
