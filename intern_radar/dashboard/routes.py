"""The web app's pages and actions."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from intern_radar.dashboard import queries
from intern_radar.dashboard.app import App, Request, html_response, redirect
from intern_radar.dashboard.layout import e, page
from intern_radar.dashboard.pages.offers import offers_body
from intern_radar.dashboard.render import stats_body
from intern_radar.dashboard.runner import RunStatus

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
    services: dict[str, Any] = field(default_factory=dict)


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
        from intern_radar.dashboard.app import text_response

        return text_response("ok")

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
