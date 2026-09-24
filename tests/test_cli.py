from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from intern_radar import cli
from intern_radar.pipeline import RunReport
from intern_radar.sources.base import SourceError
from intern_radar.store import Store
from tests.factories import make_assessment, make_job

runner = CliRunner()

PROFILE = """candidate_summary: Student.
window_start: 2027-03-08
window_end: 2027-08-31
min_months: 4
ntfy_topic: t
"""
COMPANIES = """- {name: Acme, tier: A, source: greenhouse, board: acme}
- {name: Meta, tier: S, source: none}
- {name: Broken, tier: B, source: lever, site: broken}
"""


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / "config"
    directory.mkdir()
    (directory / "profile.yaml").write_text(PROFILE)
    (directory / "companies.yaml").write_text(COMPANIES)
    return directory


class OkSource:
    def fetch(self, company, known_ids):
        return [make_job(id="x")]


class BrokenSource:
    def fetch(self, company, known_ids):
        raise SourceError("HTTP 404")


def test_check_sources_reports_each_company(config_dir, monkeypatch):
    monkeypatch.setattr(
        cli,
        "build_sources",
        lambda client, companies, profile: {
            "greenhouse": OkSource(),
            "lever": BrokenSource(),
        },
    )
    result = runner.invoke(cli.app, ["check-sources"])
    assert result.exit_code == 1
    assert "OK    Acme" in result.output
    assert "1 internship offer(s)" in result.output
    assert "NONE  Meta" in result.output
    assert "FAIL  Broken" in result.output
    assert "HTTP 404" in result.output


def test_invalid_config_exits_with_message(config_dir):
    (config_dir / "companies.yaml").write_text("- {name: X, tier: Z, source: none}")
    result = runner.invoke(cli.app, ["check-sources"])
    assert result.exit_code == 2
    assert "invalid tier" in result.output


def test_list_prints_scored_jobs(config_dir):
    db = config_dir.parent / "data" / "intern-radar.db"
    db.parent.mkdir()
    store = Store(str(db))
    now = datetime(2026, 9, 24, tzinfo=UTC)
    store.add(make_job(id="a", title="ML Intern"), "pending", now)
    store.save_assessment("a", make_assessment(), 8.4)
    store.close()
    result = runner.invoke(cli.app, ["list", "--min-score", "5"])
    assert result.exit_code == 0
    assert "8.4  [A] Acme — ML Intern · London, UK" in result.output
    assert "https://example.com/jobs/1" in result.output


def test_run_dry_run_uses_console_notifier_and_memory_db(config_dir, monkeypatch):
    built = {}

    class FakePipeline:
        def __init__(self, companies, sources, store, scorer, notifier, profile):
            built["notifier"] = type(notifier).__name__

        def run(self):
            return RunReport(fetched=3, new=2, candidates=1, scored=1, notified=1)

    monkeypatch.setattr(cli, "Pipeline", FakePipeline)
    result = runner.invoke(cli.app, ["run", "--dry-run"])
    assert result.exit_code == 0
    assert built["notifier"] == "ConsoleNotifier"
    assert "fetched=3 new=2 candidates=1 scored=1 notified=1 errors=0" in result.output
    assert not (config_dir.parent / "data" / "intern-radar.db").exists()
