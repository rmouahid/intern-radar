"""Candidate profile: readable candidate.json, career.md editor, regeneration."""

import json
from datetime import datetime
from typing import Any

from intern_radar.candidate import Candidate, Regeneration
from intern_radar.dashboard.layout import e

LAST_KEY = "profile_regeneration"  # meta key of the last regeneration report


def regeneration_report(result: Regeneration | None, error: str, now: datetime) -> str:
    """The meta value describing a regeneration (JSON)."""
    data: dict[str, Any] = {"at": now.isoformat(), "error": error}
    if result is not None:
        data |= {
            "summary": result.summary,
            "warnings": list(result.warnings),
            "changes": None if result.changes is None else list(result.changes),
        }
    return json.dumps(data)


def _last(report: str | None) -> str:
    if not report:
        return '<p class="muted">Jamais régénéré depuis le web.</p>'
    data = json.loads(report)
    when = f"Le {data['at'][:16].replace('T', ' à ')} UTC"
    if data.get("error"):
        return f'<p class="warn">{e(when)} : échec · {e(data["error"])}</p>'
    warnings = "".join(f"<li>{e(w)}</li>" for w in data.get("warnings") or ())
    changes = data.get("changes")
    if changes is None:
        diff = "<p class='muted'>Premier profil : pas de comparaison.</p>"
    elif not changes:
        diff = "<p class='muted'>Aucun changement.</p>"
    else:
        diff = (
            '<pre style="white-space:pre-wrap;font-size:13px">'
            + e("\n".join(changes))
            + "</pre>"
        )
    return (
        f"<p><b>{e(when)}</b> · {e(data.get('summary', ''))}</p>"
        + (
            f'<p class="warn">Avertissements</p><ul>{warnings}</ul>'
            if warnings
            else "<p class='ok'>Aucun avertissement.</p>"
        )
        + "<p class='muted'>Changements (+ ajouté, - retiré, ~ modifié) :</p>"
        + diff
    )


def _candidate(candidate: Candidate | None, error: str) -> str:
    if candidate is None:
        return f'<p class="muted">{e(error or "candidate.json absent.")}</p>'

    def items(values) -> str:
        return "".join(
            f"<li><b>{e(i.title)}</b> · {e(i.organisation)} "
            f'<span class="muted">{e(i.dates)}</span></li>'
            for i in values
        )

    education = "".join(
        f"<li><b>{e(ed.degree)}</b> · {e(ed.school)} "
        f'<span class="muted">{e(ed.dates)}</span></li>'
        for ed in candidate.education
    )
    skills = "".join(
        f'<span class="chip" title="{e(s.category)}">{e(s.name)}</span>'
        for s in candidate.skills
    )
    languages = " · ".join(f"{x.language} ({x.level})" for x in candidate.languages)
    certifications = "".join(f"<li>{e(c)}</li>" for c in candidate.certifications)
    return (
        f"<p><i>{e(candidate.summary)}</i></p>"
        f"<h2>Formation</h2><ul>{education}</ul>"
        f"<h2>Expériences</h2><ul>{items(candidate.experiences)}</ul>"
        f"<h2>Projets</h2><ul>{items(candidate.projects)}</ul>"
        f"<h2>Compétences ({len(candidate.skills)})</h2><div>{skills}</div>"
        f"<h2 style='margin-top:12px'>Langues</h2><p>{e(languages)}</p>"
        + (
            f"<h2>Certifications</h2><ul>{certifications}</ul>"
            if certifications
            else ""
        )
    )


def profile_body(
    candidate: Candidate | None,
    candidate_error: str,
    career: str | None,
    last_report: str | None,
    running: bool,
    can_regenerate: bool,
) -> str:
    if running:
        action = "<button disabled>Régénération en cours… (quelques minutes)</button>"
    elif can_regenerate:
        action = (
            '<form method="post" action="/profile/regenerate">'
            "<button>🔄 Régénérer le profil</button></form>"
            '<p class="muted">Un appel LLM (modèle du profil) relit career.md et '
            "réécrit candidate.json ; l'ancien est gardé en candidate.json.bak.</p>"
        )
    else:
        action = '<p class="muted">Régénération indisponible ici.</p>'
    editor = (
        '<form method="post" action="/profile/career">'
        f'<textarea name="career" rows="22" style="font-family:monospace;'
        f'font-size:13px">{e(career)}</textarea>'
        '<div class="actions"><button>Enregistrer career.md</button></div>'
        '<p class="muted">L\'ancienne version est gardée en career.md.bak. '
        "Pense à régénérer le profil ensuite.</p></form>"
        if career is not None
        else '<p class="muted">config/career.md introuvable.</p>'
    )
    return (
        "<h1>Profil</h1>"
        f"<section><h2>Régénération</h2>{action}{_last(last_report)}</section>"
        f"<section><h2>candidate.json</h2>{_candidate(candidate, candidate_error)}"
        "</section>"
        f"<section><h2>career.md</h2>{editor}</section>"
    )
