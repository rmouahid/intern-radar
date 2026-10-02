"""The bank of standard answers to application forms."""

from intern_radar.answers import Answer
from intern_radar.dashboard.layout import e


def answers_body(answers: list[Answer], examples: list[tuple[str, str]]) -> str:
    standard = [a for a in answers if not a.key.startswith("custom:")]
    custom = [a for a in answers if a.key.startswith("custom:")]
    fields = "".join(
        f'<div style="margin-bottom:10px"><label for="{e(a.key)}">{e(a.label)} '
        f"· <i>{e(a.question)}</i> "
        + (
            '<span class="chip ok">validée</span>'
            if a.validated
            else '<span class="chip warn">proposée</span>'
        )
        + f'</label><textarea id="{e(a.key)}" name="{e(a.key)}" rows="2">'
        f"{e(a.value)}</textarea></div>"
        for a in standard
    )
    customs = "".join(
        f'<div class="card"><div class="title">{e(a.question)}</div>'
        f'<p style="white-space:pre-wrap">{e(a.value)}</p>'
        f'<form class="inline" method="post" action="/answers/delete">'
        f'<input type="hidden" name="key" value="{e(a.key)}">'
        '<button class="ghost">Supprimer</button></form></div>'
        for a in custom
    )
    computed = "".join(
        f"<tr><td>{e(q)}</td><td style='white-space:normal'>{e(v)}</td></tr>"
        for q, v in examples
    )
    return (
        "<h1>Réponses types</h1>"
        "<p class='muted'>Tes réponses aux questions habituelles des formulaires, "
        "reprises dans le kit de candidature de chaque offre. Les réponses "
        "« proposées » viennent de ton profil : relis-les puis enregistre.</p>"
        f'<section><form method="post" action="/answers">{fields}'
        '<div class="actions"><button>Enregistrer et valider</button></div>'
        "</form></section>"
        "<section><h2>Questions personnalisées</h2>"
        f"{customs or '<p class=muted>Aucune.</p>'}"
        '<form method="post" action="/answers/custom">'
        '<label for="question">Question</label>'
        '<input id="question" name="question" required maxlength="300">'
        '<label for="answer">Réponse</label>'
        '<textarea id="answer" name="answer" rows="3" required></textarea>'
        '<div class="actions"><button>Ajouter</button></div></form></section>'
        "<section><h2>Réponses calculées pour chaque offre</h2>"
        "<p class='muted'>Elles dépendent du pays de l'offre (visa, parrainage, "
        "mobilité) et de ta fenêtre de stage ; exemple pour une offre en Allemagne :"
        f"</p><table>{computed}</table></section>"
    )
