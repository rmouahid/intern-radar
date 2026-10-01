"""The web app's pages and actions."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from intern_radar.config import Profile, VisaPenalties, Weights
from intern_radar.dashboard import queries
from intern_radar.dashboard.app import (
    App,
    Request,
    Response,
    file_response,
    html_response,
    redirect,
    text_response,
)
from intern_radar.dashboard.layout import e, page
from intern_radar.dashboard.pages.offer import OfferView, offer_body
from intern_radar.dashboard.pages.offers import offers_body
from intern_radar.dashboard.render import stats_body
from intern_radar.dashboard.runner import RunStatus
from intern_radar.store import Store

NOTICES: dict[str, str] = {}
RUN_NOTICES = {
    "started": "Run lancé : les résultats apparaîtront à la fin (environ une minute).",
    "busy": "Un run est déjà en cours.",
    "error": "systemd a refusé de lancer le run (voir les logs du serveur).",
}


@dataclass
class Context:
    """What the pages need; services are optional so tests can omit them."""

    db_path: str
    thresholds: tuple[float, float] = (5.5, 7.5)
    max_offer_age_days: int = 60
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    status: Callable[[], RunStatus] | None = None
    trigger: Callable[[], bool] | None = None
    config_dir: Path | None = None
    data_dir: Path | None = None  # generated PDFs are served from here only
    profile: Profile | None = None
    services: dict[str, Any] = field(default_factory=dict)

    @contextmanager
    def store(self) -> Iterator[Store]:
        """A read-write store for one request (SQLite handles concurrency)."""
        store = Store(self.db_path)
        try:
            yield store
        finally:
            store.close()

    def actions_for(self, view: OfferView) -> str:
        """Action buttons for an offer (filled by the web actions)."""
        return ""


def not_found(message: str) -> Response:
    body = (
        f"<h1>Introuvable</h1><p>{e(message)}</p><p><a href='/offers'>← Offres</a></p>"
    )
    return html_response(page("Introuvable", body), 404)


def load_offer(store: Store, ref: int) -> OfferView | None:
    group = store.group_by_ref(ref)
    if not group:
        return None
    job_id = group[0].job.id
    return OfferView(
        ref=ref,
        group=group,
        chance=store.chance(job_id),
        application=store.application_status(job_id),
        history=store.application_history(job_id),
        has_letter=store.letter(job_id) is not None,
        has_resume=store.resume(job_id) is not None,
        sibling_refs=tuple(store.job_ref(s.job.id) or 0 for s in group[1:]),
    )


def serve_document(ctx: "Context", kind: str, ref: int) -> Response:
    """A generated letter or CV, only from the data directory."""
    if kind not in ("letter", "cv") or ctx.data_dir is None:
        return not_found("Document inconnu.")
    with ctx.store() as store:
        job = store.job_by_ref(ref)
        saved = (
            (store.letter if kind == "letter" else store.resume)(job.id)
            if job
            else None
        )
    if saved is None:
        return not_found("Aucun document généré pour cette offre.")
    path = Path(saved[0]).resolve()
    if not path.is_relative_to(ctx.data_dir.resolve()) or not path.is_file():
        return not_found("Le fichier n'existe plus.")
    return file_response(path.read_bytes(), "application/pdf", path.name)


def render_stats(ctx: Context, notice: str | None = None) -> str:
    now = ctx.clock()
    db = queries.connect(ctx.db_path)
    try:
        run = ctx.status() if ctx.status else None
        body = stats_body(
            now,
            queries.kpis(db, now),
            queries.weekly_funnel(db, now),
            queries.score_histogram(db),
            ctx.thresholds,
            queries.sources(db),
            queries.applications(db),
            queries.llm_usage(db, now),
            run,
        )
    finally:
        db.close()
    refresh = 15 if run and run.running else None
    return page("Statistiques", body, "stats", notice, refresh)


def build_app(ctx: Context) -> App:
    app = App()

    @app.route("GET", "/")
    def home(request: Request):
        return redirect("/offers")

    @app.route("GET", "/healthz")
    def healthz(request: Request):
        return text_response("ok")

    @app.route("GET", "/offers/<int:ref>")
    def offer(request: Request, ref: int):
        with ctx.store() as store:
            view = load_offer(store, ref)
        if view is None:
            return not_found("Offre introuvable.")
        weights = ctx.profile.weights if ctx.profile else Weights()
        visa = ctx.profile.visa_penalties if ctx.profile else VisaPenalties()
        title = view.group[0].job.title
        body = offer_body(view, weights, visa, ctx.actions_for(view))
        return html_response(
            page(title, body, "offers", NOTICES.get(request.arg("done")))
        )

    @app.route("GET", "/files/<str:kind>/<int:ref>")
    def files(request: Request, ref: int, kind: str):
        return serve_document(ctx, kind, ref)

    @app.route("GET", "/offers")
    def offers(request: Request):
        filters = queries.OfferFilters.from_query(request.query, ctx.max_offer_age_days)
        db = queries.connect(ctx.db_path)
        try:
            rows, total = queries.offers(db, filters, ctx.clock().date())
        finally:
            db.close()
        return html_response(
            page("Offres", offers_body(rows, total, filters), "offers")
        )

    @app.route("GET", "/stats")
    def stats(request: Request):
        return html_response(render_stats(ctx, RUN_NOTICES.get(request.arg("run"))))

    @app.route("POST", "/run")
    def run(request: Request):
        if ctx.trigger is None:
            return redirect("/stats?run=error")
        if ctx.status is not None and ctx.status().running:
            return redirect("/stats?run=busy")
        return redirect(f"/stats?run={'started' if ctx.trigger() else 'error'}")

    @app.route("GET", "/more")
    def more(request: Request):
        links = "".join(
            f'<a class="card" href="{href}"><div class="title">{e(label)}</div>'
            f'<div class="muted">{e(hint)}</div></a>'
            for href, label, hint in MORE_LINKS
        )
        return html_response(page("Plus", f"<h1>Plus</h1>{links}", "more"))

    return app


# Pages reachable from the "Plus" tab (extended by later pages).
MORE_LINKS: list[tuple[str, str, str]] = [
    ("/stats", "Statistiques", "Entonnoir, scores, sources, usage LLM, runs"),
]
