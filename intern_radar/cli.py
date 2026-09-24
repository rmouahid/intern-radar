"""Command-line entry point."""

import logging
from pathlib import Path

import httpx
import typer

from intern_radar.config import (
    ConfigError,
    Profile,
    load_companies,
    load_profile,
)
from intern_radar.http import make_client
from intern_radar.models import Company
from intern_radar.notifier import ConsoleNotifier, NotifyError, NtfyNotifier
from intern_radar.pipeline import Pipeline
from intern_radar.scorer import ClaudeCliBackend, Scorer
from intern_radar.sources import SOURCE_NAMES, build_sources
from intern_radar.store import Store

app = typer.Typer(
    help="Watch top AI/tech companies for internship offers.",
    no_args_is_help=True,
)

LOG_PATH = Path("logs/intern-radar.log")
CONFIG_DIR = typer.Option(Path("config"), "--config-dir", help="Configuration dir.")
DB_PATH = typer.Option(Path("data/intern-radar.db"), "--db", help="SQLite file.")
DRY_RUN = typer.Option(False, "--dry-run", help="Print instead of notifying.")


def _setup_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(LOG_PATH, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def _load(config_dir: Path) -> tuple[Profile, list[Company]]:
    try:
        profile = load_profile(config_dir / "profile.yaml")
        companies = load_companies(config_dir / "companies.yaml", SOURCE_NAMES)
    except ConfigError as exc:
        typer.echo(f"Configuration error: {exc}", err=True)
        raise typer.Exit(2) from exc
    return profile, companies


def _open_store(db: Path, dry_run: bool) -> Store:
    if dry_run:
        return Store(":memory:")
    db.parent.mkdir(parents=True, exist_ok=True)
    return Store(str(db))


def _pipeline(
    config_dir: Path, db: Path, dry_run: bool
) -> tuple[Pipeline, Store, httpx.Client]:
    profile, companies = _load(config_dir)
    client = make_client()
    store = _open_store(db, dry_run)
    scorer = Scorer(
        ClaudeCliBackend(model=profile.llm_model),
        profile.candidate_summary,
        profile.window_start,
        profile.window_end,
        profile.min_months,
    )
    notifier = (
        ConsoleNotifier()
        if dry_run
        else NtfyNotifier(profile.ntfy_server, profile.ntfy_topic, client)
    )
    sources = build_sources(client, companies, profile)
    pipeline = Pipeline(companies, sources, store, scorer, notifier, profile)
    return pipeline, store, client


@app.command()
def run(
    dry_run: bool = DRY_RUN, config_dir: Path = CONFIG_DIR, db: Path = DB_PATH
) -> None:
    """Fetch, filter, score and notify new internship offers."""
    _setup_logging()
    pipeline, store, client = _pipeline(config_dir, db, dry_run)
    try:
        report = pipeline.run()
    finally:
        store.close()
        client.close()
    typer.echo(
        f"fetched={report.fetched} new={report.new} candidates={report.candidates}"
        f" scored={report.scored} notified={report.notified}"
        f" errors={len(report.errors)}"
    )


@app.command()
def digest(
    dry_run: bool = DRY_RUN, config_dir: Path = CONFIG_DIR, db: Path = DB_PATH
) -> None:
    """Send the evening digest of mid-score offers."""
    _setup_logging()
    pipeline, store, client = _pipeline(config_dir, db, dry_run)
    try:
        count = pipeline.digest()
    except NotifyError as exc:
        typer.echo(f"Digest not sent: {exc}", err=True)
        raise typer.Exit(1) from exc
    finally:
        store.close()
        client.close()
    typer.echo(f"digest: {count} offer(s)")


@app.command("list")
def list_jobs(
    min_score: float = typer.Option(0.0, "--min-score"), db: Path = DB_PATH
) -> None:
    """Print stored offers, best first."""
    store = Store(str(db))
    try:
        for scored in store.scored(min_score):
            job = scored.job
            typer.echo(
                f"{scored.score:4.1f}  [{job.tier}] {job.company} — {job.title}"
                f" · {job.location}\n      {job.url}"
            )
    finally:
        store.close()


@app.command("check-sources")
def check_sources(config_dir: Path = CONFIG_DIR) -> None:
    """Fetch every company once and report which ones are covered."""
    profile, companies = _load(config_dir)
    client = make_client()
    sources = build_sources(client, companies, profile)
    failures = 0
    try:
        for company in companies:
            label = f"{company.name:<24} {company.source:<16}"
            if company.source == "none":
                typer.echo(f"NONE  {label} no feed, covered by Adzuna only")
                continue
            try:
                jobs = sources[company.source].fetch(company, set())
            except Exception as exc:  # report every failure, keep going
                failures += 1
                typer.echo(f"FAIL  {label} {exc}")
                continue
            typer.echo(f"OK    {label} {len(jobs)} internship offer(s)")
    finally:
        client.close()
    if failures:
        raise typer.Exit(1)
