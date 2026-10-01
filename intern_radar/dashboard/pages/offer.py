"""Offer detail: everything known about one posting, on one page."""

from dataclasses import dataclass
from urllib.parse import quote

from intern_radar.chance import Chance
from intern_radar.config import VisaPenalties, Weights
from intern_radar.conventions import convention_for
from intern_radar.dashboard.layout import e
from intern_radar.models import ScoredJob
from intern_radar.notifier import (
    DATES_LABELS,
    WORK_AUTHORISATION_LABELS,
    tier_label,
)
from intern_radar.ranking import DATES_POINTS, LOCAL_STUDENTS_PENALTY, TIER_POINTS
from intern_radar.tracking import STATUS_TEXT

ELIGIBILITY_TEXT = {
    "ok": "Éligible",
    "local_students_only": "Réservé aux étudiants locaux",
    "phd_only": "Doctorants uniquement",
    "undergrad_only": "Licence uniquement",
}


@dataclass(frozen=True)
class OfferView:
    ref: int
    group: list[ScoredJob]  # the offer first, then its copies elsewhere
    chance: Chance | None
    application: str | None
    history: list[tuple[str, str]]
    has_letter: bool
    has_resume: bool
    sibling_refs: tuple[int, ...] = ()  # refs of group[1:]
    feedback: tuple[int, str] | None = None  # vote and reason
    details_form: str = ""  # CRM fields form, rendered by the route


def score_rows(
    scored: ScoredJob, weights: Weights, visa: VisaPenalties
) -> list[tuple[str, str, float]]:
    """How the final score is made: (factor, detail, points)."""
    a, tier = scored.assessment, scored.job.tier
    rows = [
        (
            "Entreprise",
            f"{tier_label(tier)} : {TIER_POINTS[tier]}/10 × {weights.tier:g}",
            weights.tier * TIER_POINTS[tier],
        ),
        (
            "Pertinence IA",
            f"{a.ai_relevance}/10 × {weights.relevance:g}",
            weights.relevance * a.ai_relevance,
        ),
    ]
    if a.dates_fit in DATES_POINTS:
        rows.append(
            (
                "Dates",
                f"{DATES_LABELS[a.dates_fit]} : "
                f"{DATES_POINTS[a.dates_fit]}/10 × {weights.dates:g}",
                weights.dates * DATES_POINTS[a.dates_fit],
            )
        )
    if a.eligibility == "local_students_only":
        rows.append(("Éligibilité", "Étudiants locaux", -LOCAL_STUDENTS_PENALTY))
    penalty = getattr(visa, a.work_authorisation, 0)
    if penalty:
        label = WORK_AUTHORISATION_LABELS[a.work_authorisation]
        rows.append(("Visa", label, -penalty))
    return rows


def feedback_form(view: OfferView) -> str:
    vote, reason = view.feedback or (0, "")
    current = {1: "👍 Tu aimes cette offre", -1: "👎 Tu n'aimes pas cette offre"}

    def choice(value: str, label: str, checked: bool) -> str:
        mark = " checked" if checked else ""
        return (
            f'<label style="display:inline-block;margin-right:14px">'
            f'<input type="radio" name="vote" value="{value}"{mark} '
            f'style="width:auto"> {label}</label>'
        )

    clear = (
        f'<form class="inline" method="post" action="/offers/{view.ref}/feedback">'
        '<input type="hidden" name="vote" value="clear">'
        '<button class="ghost">Retirer mon avis</button></form>'
        if view.feedback
        else ""
    )
    return (
        f"<p><b>{e(current.get(vote, 'Pas encore d’avis'))}</b></p>"
        f'<form method="post" action="/offers/{view.ref}/feedback">'
        + choice("up", "👍 J'aime", vote == 1)
        + choice("down", "👎 Pas pour moi", vote == -1)
        + '<textarea name="reason" maxlength="300" '
        'style="min-height:60px;margin-top:8px" '
        f'placeholder="Pourquoi ? (facultatif, aide la notation)">{e(reason)}'
        "</textarea>"
        f'<div class="actions"><button>Enregistrer</button></div></form>{clear}'
        '<p class="muted">Tes derniers avis sont résumés dans le prompt de notation '
        "et ajustent la pertinence des offres similaires.</p>"
    )


def _section(title: str, body: str) -> str:
    return f"<section><h2>{e(title)}</h2>{body}</section>"


def offer_body(
    view: OfferView, weights: Weights, visa: VisaPenalties, actions: str = ""
) -> str:
    lead = view.group[0]
    job, a = lead.job, lead.assessment
    convention = convention_for(job.location)
    link = (
        f'<a class="button" href="{e(job.url)}" target="_blank" rel="noopener">'
        "🔗 Voir l'offre</a>"
        if job.url.startswith(("https://", "http://"))
        else ""
    )
    header = (
        f'<p class="muted"><a href="/offers">← Offres</a></p>'
        f'<div class="top" style="display:flex;justify-content:space-between;gap:8px">'
        f'<div><div class="muted"><a href="/companies/{quote(job.company, safe="")}">'
        f"{e(job.company)}</a> · {e(tier_label(job.tier))}</div>"
        f"<h1>{e(job.title)}</h1></div>"
        f'<div class="score" style="font-size:26px">{lead.score or 0:.1f}</div></div>'
        f'<div class="actions">{link}</div>{actions}'
    )
    facts = [
        ("📍", job.location or "Lieu non précisé"),
        ("📅", DATES_LABELS.get(a.dates_fit, a.dates_fit)),
        ("🛂", f"{WORK_AUTHORISATION_LABELS[a.work_authorisation]} · {a.visa_note}"),
        ("🎓", ELIGIBILITY_TEXT.get(a.eligibility, a.eligibility)),
    ]
    if job.posted_at:
        facts.append(("🗓️", f"Publiée le {job.posted_at[:10]}"))
    facts.append(("🔎", f"Source : {job.source}"))
    summary = f"<p><i>{e(a.summary)}</i></p>" + "".join(
        f"<div>{icon} {e(text)}</div>" for icon, text in facts
    )
    rows = score_rows(lead, weights, visa)
    table = "".join(
        f"<tr><td>{e(name)}</td><td>{e(detail)}</td>"
        f"<td class='n'>{points:+.1f}</td></tr>"
        for name, detail, points in rows
    )
    breakdown = (
        f'<table class="breakdown">{table}<tr><th>Score</th><th></th>'
        f"<th class='n'>{lead.score or 0:.1f}</th></tr></table>"
        "<p class='muted'>Score plancher à 0, arrondi au dixième.</p>"
    )
    parts = [header, _section("Résumé", summary), _section("Score", breakdown)]
    if view.chance is not None:
        reasons = "".join(
            f"<div>{'✅' if positive else '⚠️'} {e(text)}</div>"
            for positive, text in view.chance.reasons
        )
        parts.append(
            _section(
                "Chance d'entretien",
                f'<p class="score" style="font-size:22px">{view.chance.percent} %</p>'
                f"{reasons}",
            )
        )
    if len(view.group) > 1:
        places = "".join(
            f'<li><a href="/offers/{ref}">{e(s.job.location or "?")}</a></li>'
            for ref, s in zip(view.sibling_refs, view.group[1:], strict=False)
        )
        parts.append(_section("Autres lieux", f"<ul>{places}</ul>"))
    convention_text = (
        f"<div>Région : {e(convention.region)}</div>"
        f"<div>Format {e(convention.paper)}, CV de {convention.cv_pages} page(s) "
        f"maximum, lettre de {convention.letter_words[0]} à "
        f"{convention.letter_words[1]} mots</div>"
        f'<div class="muted">{e(convention.spelling)}</div>'
    )
    parts.append(_section("Conventions du pays", convention_text))
    parts.append(_section("Ton avis", feedback_form(view)))
    status = STATUS_TEXT.get(view.application or "", "Aucun suivi")
    history = "".join(
        f"<li>{e(at[:16].replace('T', ' '))} · {e(STATUS_TEXT.get(s, s))}</li>"
        for s, at in view.history
    )
    parts.append(
        _section(
            "Candidature",
            f"<p><b>{e(status)}</b></p>"
            + (f"<ul>{history}</ul>" if history else "")
            + view.details_form,
        )
    )
    documents = []
    if view.has_letter:
        documents.append(
            f'<a class="button ghost" href="/files/letter/{view.ref}">'
            "✍️ Lettre (PDF)</a>"
            f'<a class="button ghost" href="/offers/{view.ref}/letter/edit">'
            "✏️ Modifier la lettre</a>"
        )
    if view.has_resume:
        documents.append(
            f'<a class="button ghost" href="/files/cv/{view.ref}">📄 CV (PDF)</a>'
            f'<a class="button ghost" href="/offers/{view.ref}/cv/edit">'
            "✏️ Modifier le CV</a>"
        )
    parts.append(
        _section(
            "Documents",
            f'<div class="actions">{"".join(documents)}</div>'
            if documents
            else '<p class="muted">Aucune lettre ni CV générés pour cette offre.</p>',
        )
    )
    if job.description:
        parts.append(
            "<section><details><summary><b>Description de l'offre</b></summary>"
            f'<p style="white-space:pre-wrap">{e(job.description[:20000])}</p>'
            "</details></section>"
        )
    return "".join(parts)
