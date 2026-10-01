"""The web app's pages and actions."""

import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote

from intern_radar.candidate import (
    CandidateError,
    Regeneration,
    candidate_text,
    load_candidate,
    regenerate,
)
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
from intern_radar.dashboard.pages.actions import NOTICES as ACTION_NOTICES
from intern_radar.dashboard.pages.actions import actions_html
from intern_radar.dashboard.pages.applications import (
    applications_body,
    details_form,
)
from intern_radar.dashboard.pages.companies import companies_body, company_body
from intern_radar.dashboard.pages.editing import letter_form, resume_form
from intern_radar.dashboard.pages.feedback import feedback_body
from intern_radar.dashboard.pages.insights import insights_body
from intern_radar.dashboard.pages.offer import OfferView, offer_body
from intern_radar.dashboard.pages.offers import offers_body, query_string
from intern_radar.dashboard.pages.profile import (
    LAST_KEY,
    profile_body,
    regeneration_report,
)
from intern_radar.dashboard.pages.searches import searches_body
from intern_radar.dashboard.render import stats_body
from intern_radar.dashboard.runner import RunStatus
from intern_radar.dashboard.worker import KINDS, PENDING, RUNNING, Worker
from intern_radar.editing import DocumentEditor, EditError
from intern_radar.scorer import LLMBackend
from intern_radar.store import ApplicationDetails, Store
from intern_radar.tracking import can_move

NOTICES: dict[str, str] = {
    **ACTION_NOTICES,
    "feedback": "Avis enregistré.",
    "details": "Suivi enregistré.",
    "search_saved": "Recherche enregistrée : alertes après chaque run.",
    "search_name": "Donne un nom à la recherche.",
    "career_saved": "career.md enregistré (ancienne version : career.md.bak).",
    "career_invalid": "career.md vide ou trop long : non enregistré.",
    "edited": "Document modifié : le PDF a été régénéré.",
    "edited_sent": "Document modifié : le PDF régénéré part sur Telegram.",
}
VOTES = {"up": 1, "down": -1}
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
    worker: Worker | None = None
    profile_backend: Callable[[], LLMBackend] | None = None
    companies: tuple[tuple[str, str, str], ...] = ()  # watched: name, tier, source

    def editor(self, store: Store) -> DocumentEditor | None:
        """Edits need the contact block; CV edits also the candidate profile."""
        if self.profile is None or self.profile.contact is None:
            return None
        path = self.config_dir / "candidate.json" if self.config_dir else None
        candidate = (
            (lambda: load_candidate(path))
            if path is not None and path.exists()
            else None
        )
        return DocumentEditor(store, self.profile.contact, candidate)

    def profile_text(self) -> tuple[str, str]:
        """The candidate's profile as text, and where it was read from."""
        path = self.config_dir / "candidate.json" if self.config_dir else None
        if path is not None and path.exists():
            return candidate_text(load_candidate(path)), "candidate.json"
        summary = self.profile.candidate_summary if self.profile else ""
        return summary, "profile.yaml"

    @contextmanager
    def store(self) -> Iterator[Store]:
        """A read-write store for one request (SQLite handles concurrency)."""
        store = Store(self.db_path)
        try:
            yield store
        finally:
            store.close()


def not_found(message: str) -> Response:
    body = (
        f"<h1>Introuvable</h1><p>{e(message)}</p><p><a href='/offers'>← Offres</a></p>"
    )
    return html_response(page("Introuvable", body), 404)


MAX_CAREER = 300_000  # characters
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")


def parse_details(form: dict[str, str]) -> ApplicationDetails:
    """CRM fields from the form; empty fields clear, malformed dates refuse."""

    def date(name: str) -> str | None:
        value = form.get(name, "").strip()
        if value and not DATE_RE.match(value):
            raise ValueError(f"date invalide : {value[:20]}")
        return value or None

    interviews = []
    for key in sorted(k for k in form if k.startswith("interview")):
        value = form[key].strip()[:16]
        if value:
            if not DATETIME_RE.match(value):
                raise ValueError(f"date d'entretien invalide : {value}")
            interviews.append(value)
    email = form.get("contact_email", "").strip()[:200]
    if email and "@" not in email:
        raise ValueError("e-mail du contact invalide")
    return ApplicationDetails(
        notes=form.get("notes", "").strip()[:4000],
        contact_name=form.get("contact_name", "").strip()[:200],
        contact_email=email,
        deadline=date("deadline"),
        interviews=tuple(sorted(set(interviews))),
        next_action=form.get("next_action", "").strip()[:300],
        next_action_date=date("next_action_date"),
    )


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
        feedback=store.feedback(job_id),
        details_form=details_form(ref, store.application_details(job_id)),
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
            queries.runs(db),
            queries.calibration(db),
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
        actions = actions_html(
            ref, view.application, view.has_letter, view.has_resume, ctx.worker
        )
        body = offer_body(view, weights, visa, actions)
        notice = NOTICES.get(request.arg("done"))
        busy = ctx.worker is not None and ctx.worker.busy(ref)
        return html_response(
            page(title, body, "offers", notice, refresh=5 if busy else None)
        )

    @app.route("POST", "/offers/<int:ref>/status")
    def set_status(request: Request, ref: int):
        new = request.form.get("status", "")
        with ctx.store() as store:
            job = store.job_by_ref(ref)
            if job is None:
                return not_found("Offre introuvable.")
            if not can_move(store.application_status(job.id), new):
                return redirect(f"/offers/{ref}?done=refused")
            store.set_application(job.id, new, ctx.clock())
        return redirect(f"/offers/{ref}?done=status")

    @app.route("GET", "/offers/<int:ref>/<str:kind>/edit")
    def edit_form(request: Request, ref: int, kind: str):
        if kind not in ("letter", "cv"):
            return not_found("Document inconnu.")
        with ctx.store() as store:
            job = store.job_by_ref(ref)
            editor = ctx.editor(store)
            if job is None or editor is None:
                return not_found("Édition indisponible (profil sans contact).")
            try:
                if kind == "letter":
                    form = letter_form(
                        ref, job.company, job.title, editor.letter(job.id)
                    )
                else:
                    form = resume_form(
                        ref, job.company, job.title, editor.resume(job.id)
                    )
            except EditError as exc:
                return not_found(f"Impossible de modifier : {exc}.")
        return html_response(page("Modifier", form, "offers"))

    @app.route("POST", "/offers/<int:ref>/<str:kind>/edit")
    def save_edit(request: Request, ref: int, kind: str):
        if kind not in ("letter", "cv"):
            return not_found("Document inconnu.")
        form = request.form
        with ctx.store() as store:
            job = store.job_by_ref(ref)
            editor = ctx.editor(store)
            if job is None or editor is None:
                return not_found("Édition indisponible (profil sans contact).")
            try:
                if kind == "letter":
                    paragraphs = [
                        form[k]
                        for k in sorted(
                            (k for k in form if k[:1] == "p" and k[1:].isdigit()),
                            key=lambda k: int(k[1:]),
                        )
                    ]
                    editor.edit_letter(
                        job.id,
                        form.get("greeting", ""),
                        paragraphs,
                        form.get("closing", ""),
                        ctx.clock(),
                    )
                else:
                    bullets = {k[2:]: v for k, v in form.items() if k.startswith("b_")}
                    editor.edit_resume(
                        job.id,
                        form.get("headline", ""),
                        form.get("summary", ""),
                        bullets,
                        ctx.clock(),
                    )
            except EditError as exc:
                body = (
                    f"<h1>Non enregistré</h1><p>{e(str(exc))}</p>"
                    f'<p><a href="/offers/{ref}/{kind}/edit">'
                    "← Revenir au formulaire</a></p>"
                )
                return html_response(page("Non enregistré", body, "offers"), 400)
        if form.get("resend") and ctx.worker is not None:
            ctx.worker.submit(kind, ref, job.id)
            return redirect(f"/offers/{ref}?done=edited_sent")
        return redirect(f"/offers/{ref}?done=edited")

    @app.route("POST", "/offers/<int:ref>/details")
    def save_details(request: Request, ref: int):
        try:
            details = parse_details(request.form)
        except ValueError as exc:
            body = (
                f"<h1>Non enregistré</h1><p>{e(str(exc))}</p>"
                f'<p><a href="/offers/{ref}">← Retour</a></p>'
            )
            return html_response(page("Non enregistré", body, "offers"), 400)
        with ctx.store() as store:
            job = store.job_by_ref(ref)
            if job is None:
                return not_found("Offre introuvable.")
            store.save_application_details(job.id, details, ctx.clock())
        return redirect(f"/offers/{ref}?done=details")

    @app.route("GET", "/insights")
    def insights(request: Request):
        try:
            relevance = int(request.arg("relevance") or 7)
        except ValueError:
            relevance = 7
        relevance = min(max(relevance, 0), 10)
        text, source = ctx.profile_text()
        db = queries.connect(ctx.db_path)
        try:
            skills, offers = queries.skill_demand(db, text, ctx.clock(), relevance)
        finally:
            db.close()
        body = insights_body(skills, offers, relevance, source)
        return html_response(page("Compétences", body, "insights"))

    @app.route("GET", "/searches")
    def searches_page(request: Request):
        with ctx.store() as store:
            body = searches_body(store.searches())
        notice = NOTICES.get(request.arg("done"))
        return html_response(page("Recherches", body, "more", notice))

    @app.route("POST", "/searches")
    def save_search(request: Request):
        name = request.form.get("name", "").strip()
        query = request.form.get("query", "")
        if not name:
            return redirect("/searches?done=search_name")
        # Normalise through the filters: unknown keys and values are dropped.
        filters = queries.OfferFilters.from_query(
            {k: v[-1] for k, v in parse_qs(query).items()}, ctx.max_offer_age_days
        )
        with ctx.store() as store:
            store.add_search(name, query_string(filters), ctx.clock())
        return redirect("/searches?done=search_saved")

    @app.route("POST", "/searches/<int:search_id>/<str:action>")
    def change_search(request: Request, search_id: int, action: str):
        with ctx.store() as store:
            found = next((s for s in store.searches() if s.id == search_id), None)
            if found is None:
                return not_found("Recherche introuvable.")
            if action == "toggle":
                store.set_search_active(search_id, not found.active)
            elif action == "delete":
                store.delete_search(search_id)
            else:
                return not_found("Action inconnue.")
        return redirect("/searches")

    @app.route("GET", "/profile")
    def profile_page(request: Request):
        candidate, error, career = None, "", None
        if ctx.config_dir is not None:
            path = ctx.config_dir / "candidate.json"
            try:
                candidate = load_candidate(path) if path.exists() else None
            except CandidateError as exc:
                error = str(exc)
            career_path = ctx.config_dir / "career.md"
            if career_path.exists():
                career = career_path.read_text(encoding="utf-8")
        with ctx.store() as store:
            last = store.get_meta(LAST_KEY)
        state = ctx.worker.call_state("profile") if ctx.worker else None
        running = state is not None and state.state in (PENDING, RUNNING)
        body = profile_body(
            candidate,
            error,
            career,
            last,
            running,
            ctx.worker is not None
            and ctx.profile_backend is not None
            and ctx.config_dir is not None,
        )
        notice = NOTICES.get(request.arg("done"))
        return html_response(
            page("Profil", body, "more", notice, refresh=10 if running else None)
        )

    @app.route("POST", "/profile/career")
    def save_career(request: Request):
        if ctx.config_dir is None:
            return not_found("Dossier de configuration inconnu.")
        text = request.form.get("career", "").replace("\r\n", "\n")
        if not text.strip() or len(text) > MAX_CAREER:
            return redirect("/profile?done=career_invalid")
        path = ctx.config_dir / "career.md"
        if path.exists():
            path.replace(path.with_suffix(".md.bak"))
        path.write_text(text, encoding="utf-8")
        return redirect("/profile?done=career_saved")

    @app.route("POST", "/profile/regenerate")
    def regenerate_profile(request: Request):
        if ctx.worker is None or ctx.profile_backend is None or not ctx.config_dir:
            return redirect("/profile?done=unavailable")
        config_dir, backend, db_path, clock = (
            ctx.config_dir, ctx.profile_backend, ctx.db_path, ctx.clock,
        )  # fmt: skip

        def task() -> Regeneration:
            result, error = None, ""
            try:
                result = regenerate(backend(), config_dir)
                return result
            except Exception as exc:
                error = str(exc) or type(exc).__name__
                raise
            finally:
                store = Store(db_path)
                try:
                    store.set_meta(
                        LAST_KEY, regeneration_report(result, error, clock())
                    )
                finally:
                    store.close()

        queued = ctx.worker.submit_call("profile", task)
        return redirect(f"/profile?done={'queued' if queued else 'already'}")

    @app.route("GET", "/companies")
    def companies_page(request: Request):
        db = queries.connect(ctx.db_path)
        try:
            rows = queries.companies(
                db, ctx.companies, ctx.clock().date(), ctx.thresholds[0],
                ctx.max_offer_age_days,
            )  # fmt: skip
        finally:
            db.close()
        body = companies_body(rows, request.arg("q")[:80])
        return html_response(page("Entreprises", body, "more"))

    @app.route("GET", "/companies/<str:name>")
    def company_page(request: Request, name: str):
        name = unquote(name)
        db = queries.connect(ctx.db_path)
        try:
            detail = queries.company_detail(
                db, name, ctx.companies, ctx.clock(), ctx.thresholds[0],
                ctx.max_offer_age_days,
            )  # fmt: skip
        finally:
            db.close()
        if detail is None:
            return not_found("Entreprise inconnue.")
        return html_response(page(name, company_body(detail), "more"))

    @app.route("GET", "/applications")
    def applications_page(request: Request):
        days = ctx.profile.reminder_days if ctx.profile else 14
        now = ctx.clock()
        db = queries.connect(ctx.db_path)
        try:
            body = applications_body(
                queries.board(db, now, days), queries.calendar(db, now, days)
            )
        finally:
            db.close()
        return html_response(page("Candidatures", body, "applications"))

    @app.route("POST", "/offers/<int:ref>/feedback")
    def give_feedback(request: Request, ref: int):
        vote = request.form.get("vote", "")
        back = request.form.get("next", "")
        if not back.startswith("/offers") or "//" in back:
            back = f"/offers/{ref}?done=feedback"
        with ctx.store() as store:
            job = store.job_by_ref(ref)
            if job is None:
                return not_found("Offre introuvable.")
            if vote == "clear":
                store.clear_feedback(job.id)
            elif vote in VOTES:
                store.set_feedback(
                    job.id, VOTES[vote], request.form.get("reason", ""), ctx.clock()
                )
            else:
                return redirect(f"/offers/{ref}")
        return redirect(back)

    @app.route("GET", "/feedback")
    def feedback_page(request: Request):
        with ctx.store() as store:
            entries = store.feedback_entries()
            refs = [store.job_ref(job.id) or 0 for job, *_ in entries]
        body = feedback_body(entries, refs)
        return html_response(page("Mes avis", body, "more"))

    @app.route("POST", "/offers/<int:ref>/<str:kind>")
    def start_task(request: Request, ref: int, kind: str):
        if kind not in KINDS:
            return not_found("Action inconnue.")
        if ctx.worker is None:
            return redirect(f"/offers/{ref}?done=unavailable")
        with ctx.store() as store:
            job = store.job_by_ref(ref)
        if job is None:
            return not_found("Offre introuvable.")
        queued = ctx.worker.submit(kind, ref, job.id)
        return redirect(f"/offers/{ref}?done={'queued' if queued else 'already'}")

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
    ("/companies", "Entreprises", "Offres, candidatures et santé des sources"),
    ("/profile", "Profil", "candidate.json, career.md et régénération"),
    ("/searches", "Recherches", "Alertes Telegram sur des filtres enregistrés"),
    ("/feedback", "Mes avis", "Les offres notées 👍/👎, prises en compte au scoring"),
]
