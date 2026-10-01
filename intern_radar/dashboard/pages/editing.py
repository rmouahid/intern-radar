"""Forms to edit a generated letter or CV."""

from intern_radar.dashboard.layout import e
from intern_radar.letters.writer import Letter
from intern_radar.resume.writer import Resume


def _area(name: str, label: str, value: str, rows: int = 4) -> str:
    return (
        f'<label for="{name}">{e(label)}</label>'
        f'<textarea id="{name}" name="{name}" rows="{rows}">{e(value)}</textarea>'
    )


def _footer(back: str) -> str:
    return (
        '<label style="margin-top:10px"><input type="checkbox" name="resend" '
        'value="1" style="width:auto" checked> Renvoyer le PDF sur Telegram</label>'
        '<div class="actions"><button>Enregistrer et régénérer le PDF</button>'
        f'<a class="button ghost" href="{e(back)}">Annuler</a></div>'
    )


def letter_form(ref: int, company: str, title: str, letter: Letter) -> str:
    paragraphs = list(letter.paragraphs) + [""]  # one empty slot to add a paragraph
    fields = "".join(
        _area(f"p{i}", f"Paragraphe {i + 1}", text, 7)
        for i, text in enumerate(paragraphs)
    )
    return (
        f'<p class="muted"><a href="/offers/{ref}">← {e(company)}</a></p>'
        f"<h1>Modifier la lettre</h1><p class='muted'>{e(title)}</p>"
        f'<section><form method="post" action="/offers/{ref}/letter/edit">'
        + _area("greeting", "Formule d'appel", letter.greeting, 1)
        + fields
        + _area("closing", "Formule finale", letter.closing, 2)
        + '<p class="muted">Un paragraphe vidé est supprimé. Le PDF garde la '
        "convention du pays de l'offre.</p>"
        + _footer(f"/offers/{ref}")
        + "</form></section>"
    )


def resume_form(ref: int, company: str, title: str, resume: Resume) -> str:
    items = "".join(
        _area(
            f"b_{item.id}",
            f"{item.title} · {item.organisation}",
            "\n".join(bullets),
            max(3, len(bullets) + 1),
        )
        for item, bullets in resume.items
    )
    return (
        f'<p class="muted"><a href="/offers/{ref}">← {e(company)}</a></p>'
        f"<h1>Modifier le CV</h1><p class='muted'>{e(title)}</p>"
        f'<section><form method="post" action="/offers/{ref}/cv/edit">'
        f'<label for="headline">Titre</label><input id="headline" name="headline" '
        f'value="{e(resume.headline)}">'
        + _area("summary", "Résumé", resume.summary, 4)
        + "<h2 style='margin-top:14px'>Puces (une par ligne)</h2>"
        + items
        + '<p class="muted">Si le CV dépasse la limite de pages du pays, les '
        "dernières puces sont retirées au rendu.</p>"
        + _footer(f"/offers/{ref}")
        + "</form></section>"
    )
