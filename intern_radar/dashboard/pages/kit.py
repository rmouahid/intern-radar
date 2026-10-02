"""Application kit: everything needed to fill the offer's form."""

from intern_radar.dashboard.layout import e
from intern_radar.dashboard.worker import PENDING, RUNNING, TaskState
from intern_radar.store import WhyText


def _copy_row(index: int, question: str, value: str) -> str:
    return (
        '<div style="border-bottom:1px solid var(--line);padding:6px 0">'
        f'<div class="muted">{e(question)}</div>'
        '<div style="display:flex;gap:8px;align-items:flex-start;'
        'justify-content:space-between">'
        f'<span id="kit-{index}" style="white-space:pre-wrap">{e(value)}</span>'
        f'<button class="ghost" data-copy="kit-{index}" '
        'style="padding:4px 10px;font-size:13px;flex:none">Copier</button>'
        "</div></div>"
    )


def _document(label: str, ready: bool, stale: bool, href: str, edit: str) -> str:
    if not ready:
        return (
            f"<li>{e(label)} : pas encore généré (bouton « Générer » en haut de "
            "la page)</li>"
        )
    warning = (
        ' <span class="chip warn">généré avant la dernière mise à jour du profil</span>'
        if stale
        else ' <span class="chip ok">prêt</span>'
    )
    return (
        f'<li>{e(label)}{warning} · <a href="{href}">PDF</a> · '
        f'<a href="{edit}">modifier</a></li>'
    )


def _why(ref: int, why: WhyText | None, state: TaskState | None) -> str:
    running = state is not None and state.state in (PENDING, RUNNING)
    if running:
        return "<p class='muted'>Rédaction en cours… (la page se met à jour)</p>"
    failed = (
        f"<p class='warn'>Échec : {e(state.error)}</p>"
        if state is not None and state.error
        else ""
    )
    generate = (
        f'<form class="inline" method="post" action="/offers/{ref}/why">'
        f'<button class="ghost">{"Régénérer" if why else "✨ Rédiger un brouillon"}'
        "</button></form>"
    )
    if why is None:
        return (
            failed
            + "<p class='muted'>Réponse à « Pourquoi cette entreprise / ce poste ? », "
            "80 à 120 mots, rédigée à partir de l'offre et de ton profil.</p>"
            + generate
        )
    warnings = (
        ""
        if why.edited or not why.warnings
        else "<ul>"
        + "".join(f"<li class='warn'>{e(w)}</li>" for w in why.warnings)
        + "</ul>"
    )
    return (
        failed + warnings + f'<form method="post" action="/offers/{ref}/why/edit">'
        f'<textarea id="kit-why" name="text" rows="7">{e(why.text)}</textarea>'
        '<div class="actions"><button>Enregistrer</button>'
        '<button class="ghost" data-copy="kit-why">Copier</button></div></form>'
        + generate
        + (" <span class='muted'>(modifié à la main)</span>" if why.edited else "")
    )


def kit_html(
    ref: int,
    url: str,
    answers: list[tuple[str, str]],
    language: str,
    documents: dict[str, tuple[bool, bool]],
    why: WhyText | None,
    why_state: TaskState | None,
) -> str:
    """`documents` maps "letter"/"cv" to (ready, stale)."""
    open_form = (
        f'<a class="button" href="{e(url)}" target="_blank" rel="noopener">'
        "📝 Ouvrir le formulaire</a>"
        if url.startswith(("https://", "http://"))
        else ""
    )
    other = "fr" if language == "en" else "en"
    switch = (
        f'<a class="chip" href="/offers/{ref}?lang={other}#kit">'
        f"{'Réponses en français' if other == 'fr' else 'Answers in English'}</a>"
    )
    rows = "".join(_copy_row(i, q, v) for i, (q, v) in enumerate(answers) if v)
    letter_ready, letter_stale = documents.get("letter", (False, False))
    cv_ready, cv_stale = documents.get("cv", (False, False))
    docs = (
        "<ul>"
        + _document("CV adapté", cv_ready, cv_stale, f"/files/cv/{ref}",
                    f"/offers/{ref}/cv/edit")
        + _document("Lettre de motivation", letter_ready, letter_stale,
                    f"/files/letter/{ref}", f"/offers/{ref}/letter/edit")
        + "</ul>"
    )  # fmt: skip
    checklist = "".join(
        f'<label style="display:block;color:var(--text)"><input type="checkbox" '
        f'style="width:auto"> {e(item)}</label>'
        for item in (
            "CV adapté relu",
            "Lettre relue (si demandée)",
            "Réponses vérifiées",
            "« Pourquoi nous » relu",
        )
    )
    return (
        '<section id="kit"><h2>Postuler</h2>'
        f'<div class="actions">{open_form}</div>'
        "<p class='muted'>Tu remplis et envoies toi-même le formulaire ; tout est "
        "prêt à copier ci-dessous.</p>"
        f"<h2 style='margin-top:12px'>Documents</h2>{docs}"
        f"<h2>Réponses</h2><div>{switch} "
        '<a class="chip" href="/answers">Modifier mes réponses types</a></div>'
        f"{rows}"
        f"<h2 style='margin-top:12px'>Pourquoi cette entreprise</h2>"
        f"{_why(ref, why, why_state)}"
        f"<h2 style='margin-top:12px'>Avant d'envoyer</h2>{checklist}"
        "</section>"
    )
