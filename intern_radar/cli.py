"""Command-line entry point."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import typer

from intern_radar import ranking
from intern_radar.candidate import (
    CandidateError,
    candidate_text,
    load_candidate,
    regenerate,
    select_items,
)
from intern_radar.chance import CachedChance, ChanceEstimator
from intern_radar.config import (
    ConfigError,
    Profile,
    load_companies,
    load_profile,
)
from intern_radar.conventions import convention_for, visa_fact
from intern_radar.dashboard.routes import Context
from intern_radar.dashboard.runner import run_status, start_run
from intern_radar.dashboard.server import make_server, tailscale_ip
from intern_radar.dashboard.worker import Services, Worker
from intern_radar.description import clean_description
from intern_radar.feedback import feedback_summary
from intern_radar.http import make_client
from intern_radar.letters.cv import CvSource
from intern_radar.letters.delivery import GmailSender
from intern_radar.letters.inbox import ButtonRequests, TelegramUpdates, run_listener
from intern_radar.letters.service import LetterService
from intern_radar.letters.writer import LetterWriter
from intern_radar.models import Company, Job
from intern_radar.notifier import ConsoleNotifier, NotifyError, TelegramNotifier
from intern_radar.pipeline import Pipeline, utcnow
from intern_radar.promotion import Promoter
from intern_radar.resume.service import ResumeService
from intern_radar.scorer import ClaudeCliBackend, LLMError, Scorer
from intern_radar.searches import SearchAlerts
from intern_radar.sources import SOURCE_NAMES, build_sources
from intern_radar.store import Store
from intern_radar.telegram import TelegramClient
from intern_radar.tracking import STATUS_TEXT, Tracker

app = typer.Typer(
    help="Watch top AI/tech companies for internship offers.",
    no_args_is_help=True,
)

LOG_PATH = Path("logs/intern-radar.log")
CV_CACHE = Path("data/cv-cache.json")
LETTERS_DIR = Path("data/letters")
RESUMES_DIR = Path("data/cvs")
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
    # httpx logs every request URL at INFO, including API keys in query strings.
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _load(config_dir: Path) -> tuple[Profile, list[Company]]:
    try:
        profile = load_profile(config_dir / "profile.yaml")
        companies = load_companies(config_dir / "companies.yaml", SOURCE_NAMES)
    except ConfigError as exc:
        typer.echo(f"Configuration error: {exc}", err=True)
        raise typer.Exit(2) from exc
    return profile, companies


def _telegram(profile: Profile, client: httpx.Client) -> TelegramClient:
    return TelegramClient(client, profile.telegram_token, profile.telegram_chat_id)


def _open_store(db: Path, dry_run: bool) -> Store:
    if dry_run:
        return Store(":memory:")
    db.parent.mkdir(parents=True, exist_ok=True)
    return Store(str(db))


def _recorder(store: Store, purpose: str) -> Callable[[dict[str, Any]], None]:
    """Stores the tokens and cost of each LLM call (shown by the dashboard)."""

    def record(usage: dict[str, Any]) -> None:
        store.record_llm_usage(purpose, usage, datetime.now(UTC))

    return record


def _chance(config_dir: Path, profile: Profile, store: Store) -> CachedChance | None:
    """Interview-chance estimates, available once a candidate profile exists."""
    path = config_dir / "candidate.json"
    if not path.exists():
        return None
    try:
        candidate = load_candidate(path)
    except CandidateError as exc:
        logging.getLogger(__name__).warning("no interview chance: %s", exc)
        return None
    window = (
        f"{profile.min_months}+ months between {profile.window_start:%B %Y}"
        f" and {profile.window_end:%B %Y}"
    )
    backend = ClaudeCliBackend(
        model=profile.chance_model,
        effort=profile.chance_effort,
        on_usage=_recorder(store, "chance"),
    )
    estimator = ChanceEstimator(
        backend,
        candidate,
        window,
        self_sponsored=profile.self_sponsored_countries,
    )
    return CachedChance(store, estimator)


def _pipeline(
    config_dir: Path, db: Path, dry_run: bool
) -> tuple[Pipeline, Store, httpx.Client]:
    profile, companies = _load(config_dir)
    client = make_client()
    store = _open_store(db, dry_run)
    scorer = Scorer(
        ClaudeCliBackend(
            model=profile.llm_model,
            effort=profile.llm_effort,
            on_usage=_recorder(store, "scoring"),
        ),
        profile.candidate_summary,
        profile.window_start,
        profile.window_end,
        profile.min_months,
        preferences=feedback_summary(store.feedback_entries()),
    )
    notifier = (
        ConsoleNotifier() if dry_run else TelegramNotifier(_telegram(profile, client))
    )
    sources = build_sources(client, companies, profile)
    pipeline = Pipeline(
        companies,
        sources,
        store,
        scorer,
        notifier,
        profile,
        chance=_chance(config_dir, profile, store),
        resumes=bool(profile.contact and (config_dir / "candidate.json").exists()),
        tracking=bool(profile.cv_url and profile.contact),  # the listener runs
        searches=SearchAlerts(
            store, notifier, utcnow, profile.max_offer_age_days
        ).check,
    )
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
        f" errors={len(report.errors)} grouped={report.grouped}"
        f" out_of_scope={report.out_of_scope} stale={report.stale}"
        f" discovery={report.discovery} search_alerts={report.search_alerts}"
    )


@app.command()
def digest(
    dry_run: bool = DRY_RUN, config_dir: Path = CONFIG_DIR, db: Path = DB_PATH
) -> None:
    """Send the evening digest of mid-score offers."""
    _setup_logging()
    profile, _ = _load(config_dir)
    pipeline, store, client = _pipeline(config_dir, db, dry_run)
    try:
        count = pipeline.digest()
        reminders = pipeline.remind(profile.reminder_days)
    except NotifyError as exc:
        typer.echo(f"Digest not sent: {exc}", err=True)
        raise typer.Exit(1) from exc
    finally:
        store.close()
        client.close()
    typer.echo(f"digest: {count} offer(s), {reminders} reminder(s)")


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


@app.command()
def rescore(config_dir: Path = CONFIG_DIR, db: Path = DB_PATH) -> None:
    """Recompute stored scores with the current weights (no LLM call)."""
    profile, _ = _load(config_dir)
    store = Store(str(db))
    try:
        changed = store.rescore(
            lambda job, assessment: ranking.final_score(
                job.tier,
                assessment,
                profile.weights,
                profile.thresholds.min_relevance,
                profile.visa_penalties,
            ),
            adjust=lambda job, assessment: ranking.with_rule_based_visa(
                assessment, job.location, profile.self_sponsored_countries
            ),
        )
        # Estimates depend on the profile and the method: recompute on demand.
        cleared = store.clear_chances()
        due = len(store.due_immediate(profile.thresholds.immediate))
    finally:
        store.close()
    typer.echo(f"rescored={changed} due_immediate={due} chances_cleared={cleared}")


@app.command("generate-profile")
def generate_profile(
    config_dir: Path = CONFIG_DIR,
    dry_run: bool = typer.Option(False, "--dry-run", help="Print, do not save."),
) -> None:
    """Build config/candidate.json from config/career.md (one LLM call)."""
    profile, _ = _load(config_dir)
    backend = ClaudeCliBackend(model=profile.profile_model, timeout=900)
    try:
        result = regenerate(backend, config_dir, save=not dry_run)
    except CandidateError as exc:
        typer.echo(f"Configuration error: {exc}", err=True)
        raise typer.Exit(2) from exc
    except LLMError as exc:
        typer.echo(f"Profile not generated: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(result.summary)
    for warning in result.warnings:
        typer.echo(f"warning: {warning}")
    if result.changes is not None:
        for line in result.changes or ("no change",):
            typer.echo(line)
    if result.saved:
        typer.echo(f"saved {config_dir / 'candidate.json'}")


@app.command()
def dashboard(
    config_dir: Path = CONFIG_DIR,
    db: Path = DB_PATH,
    host: str | None = typer.Option(None, "--host", help="Default: Tailscale IP."),
    port: int | None = typer.Option(None, "--port"),
) -> None:
    """Serve the read-only statistics page on the Tailscale address."""
    _setup_logging()
    profile, watched = _load(config_dir)
    address = host or profile.dashboard_host or tailscale_ip()
    if not address:
        typer.echo(
            "No Tailscale address found: set dashboard_host or pass --host",
            err=True,
        )
        raise typer.Exit(2)
    Store(str(db)).close()  # creates or migrates the schema once
    thresholds = (profile.thresholds.digest, profile.thresholds.immediate)
    context = Context(
        str(db),
        thresholds,
        max_offer_age_days=profile.max_offer_age_days,
        status=run_status,
        trigger=start_run,
        config_dir=config_dir,
        data_dir=db.parent,
        profile=profile,
        worker=Worker(lambda: _web_services(config_dir, db)),
        companies=tuple((c.name, c.tier, c.source) for c in watched),
        profile_backend=lambda: ClaudeCliBackend(
            model=profile.profile_model, timeout=900
        ),
    )
    server = make_server(
        str(db), address, port or profile.dashboard_port, thresholds, context=context
    )
    typer.echo(f"dashboard on http://{address}:{server.server_address[1]}/")
    try:
        server.serve_forever()
    finally:
        server.server_close()


@app.command()
def applications(db: Path = DB_PATH) -> None:
    """Print tracked applications, most recent update first."""
    store = Store(str(db))
    try:
        for job, status, updated, applied in store.applications():
            since = f" · postulé le {applied[:10]}" if applied else ""
            typer.echo(
                f"{STATUS_TEXT.get(status, status):<20} {job.company} — {job.title}"
                f" · maj {updated[:10]}{since}\n      {job.url}"
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


def _letter_service(config_dir: Path, db: Path):
    profile, _ = _load(config_dir)
    missing = [key for key in ("cv_url", "contact") if getattr(profile, key) is None]
    if missing:
        typer.echo(
            f"Configuration error: set {', '.join(missing)} in profile.yaml",
            err=True,
        )
        raise typer.Exit(2)
    client = make_client()
    store = _open_store(db, dry_run=False)
    cv = CvSource(client, profile.cv_url, CV_CACHE)
    backend = ClaudeCliBackend(
        model=profile.letter_model,
        effort=profile.letter_effort,
        on_usage=_recorder(store, "letter"),
    )

    candidate_path = config_dir / "candidate.json"

    def make_writer(job: Job) -> LetterWriter:
        """Letters use the structured profile when it exists, else the CV;
        they follow the conventions of the offer's country."""
        window = (profile.window_start, profile.window_end, profile.min_months)
        scored = store.scored_job(job.id)
        local = {
            "convention": convention_for(job.location),
            "visa": visa_fact(scored.assessment.work_authorisation) if scored else "",
        }
        if not candidate_path.exists():
            return LetterWriter(backend, cv.text(), *window, **local)
        candidate = load_candidate(candidate_path)
        offer = f"{job.title}\n{clean_description(job.description)}"
        selected = select_items(candidate, offer)
        return LetterWriter(
            backend,
            candidate_text(candidate, selected),
            *window,
            reference_text=candidate_text(candidate),
            **local,
        )

    mail = (
        GmailSender(profile.letters_email, profile.smtp_app_password)
        if profile.letters_email and profile.smtp_app_password
        else None
    )
    telegram = _telegram(profile, client)
    service = LetterService(
        store,
        make_writer,
        profile.contact,
        LETTERS_DIR,
        telegram,
        mail,
        TelegramNotifier(telegram),
        profile.max_letters_per_day,
    )
    return service, store, client, profile, telegram


@app.command()
def letter(job_id: str, config_dir: Path = CONFIG_DIR, db: Path = DB_PATH) -> None:
    """Write, render and deliver the cover letter for one stored offer."""
    _setup_logging()
    service, store, client, _, _ = _letter_service(config_dir, db)
    try:
        path = service.handle(job_id)
    finally:
        store.close()
        client.close()
    if path is None:
        typer.echo("No letter produced (see logs).", err=True)
        raise typer.Exit(1)
    typer.echo(str(path))


def _resume_service(
    config_dir: Path, profile: Profile, store: Store, telegram: TelegramClient
) -> ResumeService | None:
    """Tailored CVs, available once a candidate profile and a contact exist."""
    path = config_dir / "candidate.json"
    if profile.contact is None or not path.exists():
        return None
    return ResumeService(
        store,
        lambda: load_candidate(path),
        ClaudeCliBackend(
            model=profile.resume_model,
            effort=profile.resume_effort,
            on_usage=_recorder(store, "cv"),
        ),
        profile.contact,
        RESUMES_DIR,
        telegram,
        TelegramNotifier(telegram),
        profile.max_resumes_per_day,
    )


def _web_services(config_dir: Path, db: Path) -> Services:
    """The listener's services, for the web actions (built in their thread)."""
    service, store, _, profile, telegram = _letter_service(config_dir, db)
    resumes = _resume_service(config_dir, profile, store, telegram)
    promoter = Promoter(
        store,
        TelegramNotifier(telegram),
        letters=True,
        chance=_chance(config_dir, profile, store),
        resumes=resumes is not None,
        tracking=True,
    )
    return Services(
        letter=service.handle,
        promote=promoter.promote,
        resume=resumes.handle if resumes else None,
    )


@app.command()
def listen(config_dir: Path = CONFIG_DIR, db: Path = DB_PATH) -> None:
    """Wait for letter button taps on Telegram (runs forever)."""
    _setup_logging()
    service, store, client, profile, telegram = _letter_service(config_dir, db)
    try:
        resumes = _resume_service(config_dir, profile, store, telegram)
        promoter = Promoter(
            store,
            TelegramNotifier(telegram),
            letters=True,
            chance=_chance(config_dir, profile, store),
            resumes=resumes is not None,
            tracking=True,
        )
        requests = ButtonRequests(
            telegram,
            store,
            service,
            profile.telegram_chat_id,
            promoter,
            resumes,
            Tracker(store, telegram),
        )
        run_listener(TelegramUpdates(telegram), requests, store)
    finally:
        store.close()
        client.close()
