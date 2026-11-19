"""Offer detail: everything known about one posting, on one page."""

from dataclasses import dataclass
from urllib.parse import quote

from intern_radar.chance import Chance
from intern_radar.config import VisaPenalties, Weights
from intern_radar.conventions import convention_for
from intern_radar.dashboard.icons import icon
from intern_radar.dashboard.layout import ICON_EXTERNAL, e, monogram
from intern_radar.dashboard.pages.offers import score_badge, tier_badge
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
    kit: str = ""  # application kit, rendered by the route


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
    current = {
        1: "Tu trouves cette offre pertinente",
        -1: "Cette offre n'est pas pour toi",
    }

    def choice(value: str, label: str, checked: bool) -> str:
        mark = " checked" if checked else ""
        return (
            f'<label style="display:inline-flex;align-items:center;margin-right:18px;'
            'font-weight:600">'
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
        + choice("up", "Pertinente", vote == 1)
        + choice("down", "Pas pour moi", vote == -1)
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
        f"Voir l'offre {ICON_EXTERNAL}</a>"
        if job.url.startswith(("https://", "http://"))
        else ""
    )
    company = f'<a href="/companies/{quote(job.company, safe="")}">{e(job.company)}</a>'
    header = (
        '<p class="muted back"><a href="/offers">← Offres</a></p>'
        '<div class="dhead"><div class="dh">'
        f'{monogram(job.company, "lg")}<div class="dh-main">'
        f'<div class="company">{company} {tier_badge(job.tier)}</div>'
        f"<h1>{e(job.title)}</h1>"
        f'<div class="loc">{icon("pin", 15)}{e(job.location or "Lieu non précisé")}'
        "</div></div>"
        f"{score_badge(lead.score or 0, 'xl')}</div>"
        f'<div class="dh-actions">{link}{actions}</div></div>'
    )
    facts = [
        ("calendar", "Dates", DATES_LABELS.get(a.dates_fit, a.dates_fit)),
        (
            "passport",
            "Visa",
            f"{WORK_AUTHORISATION_LABELS[a.work_authorisation]} · {a.visa_note}",
        ),
        ("cap", "Éligibilité", ELIGIBILITY_TEXT.get(a.eligibility, a.eligibility)),
        ("pin", "Lieu", job.location or "Lieu non précisé"),
    ]
    if job.posted_at:
        facts.append(("clock", "Publication", f"Publiée le {job.posted_at[:10]}"))
    facts.append(("globe", "Source", job.source))
    summary = (
        f'<p class="lead">{e(a.summary)}</p><dl class="facts">'
        + "".join(
            f'<div class="fact">{icon(glyph, 20)}<div><dt>{e(name)}</dt>'
            f"<dd>{e(text)}</dd></div></div>"
            for glyph, name, text in facts
        )
        + "</dl>"
    )
    rows = score_rows(lead, weights, visa)
    top = max((abs(points) for _, _, points in rows), default=1) or 1
    bars = "".join(
        f'<div class="bar-row"><span class="name">{e(name)}</span>'
        f'<div class="bar-track"><div class="bar-fill{" neg" if points < 0 else ""}"'
        f' style="width:{abs(points) / top * 100:.0f}%"></div></div>'
        f'<span class="pts">{points:+.1f}</span>'
        f'<span class="detail">{e(detail)}</span></div>'
        for name, detail, points in rows
    )
    breakdown = (
        f'<div class="bars">{bars}</div>'
        f'<div class="bar-total"><span>Score final</span>'
        f"<span>{lead.score or 0:.1f} / 10</span></div>"
        "<p class='muted' style='margin-top:8px'>Score plancher à 0, arrondi au "
        "dixième.</p>"
    )
    parts = [
        header,
        _section("Résumé", summary),
        view.kit,
        _section("Score", breakdown),
    ]
    if view.chance is not None:
        reasons = "".join(
            f'<div class="{"pos" if positive else "neg"}">'
            f"{icon('check' if positive else 'spark', 16)}<span>{e(text)}</span></div>"
            for positive, text in view.chance.reasons
        )
        parts.append(
            _section(
                "Chance d'entretien",
                f'<div style="display:flex;align-items:baseline;gap:8px">'
                f'<b style="font-size:28px;letter-spacing:-.02em">'
                f"{view.chance.percent} %</b>"
                '<span class="muted">estimation</span></div>'
                f'<div class="meter"><span style="width:{view.chance.percent}%">'
                f'</span></div><div class="reasons">{reasons}</div>',
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
            f'<a class="button ghost" href="/files/letter/{view.ref}" target="_blank">'
            "Lettre (PDF)</a>"
            f'<a class="button ghost" href="/offers/{view.ref}/letter/edit">'
            "Modifier la lettre</a>"
        )
    if view.has_resume:
        documents.append(
            f'<a class="button ghost" href="/files/cv/{view.ref}" target="_blank">'
            "CV (PDF)</a>"
            f'<a class="button ghost" href="/offers/{view.ref}/cv/edit">'
            "Modifier le CV</a>"
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
            "<section><details><summary><h2 style='margin:0'>Description de "
            "l'offre</h2></summary>"
            '<p style="white-space:pre-wrap;margin-top:12px;color:var(--muted);'
            f'font-size:14px">{e(job.description[:20000])}</p>'
            "</details></section>"
        )
    return "".join(parts)
