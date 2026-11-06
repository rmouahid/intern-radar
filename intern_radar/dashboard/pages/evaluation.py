"""Hand labels for the triage evaluation (`intern-radar eval`), one offer at a time."""

from intern_radar.dashboard.layout import e
from intern_radar.evaluation import EvalOffer

DESCRIPTION_PREVIEW = 1500


def label_body(offers: list[EvalOffer], index: int | None) -> str:
    """The offer to label at `index`, or the summary when none is left."""
    done = sum(1 for o in offers if o.label is not None)
    wanted = sum(1 for o in offers if o.label)
    progress = (
        f"<p class='muted'>{done} / {len(offers)} étiquetées · {wanted} que tu"
        " voudrais voir</p>"
    )
    if index is None:
        return (
            f"<h1>Évaluation du tri</h1>{progress}<section>Tout est étiqueté. "
            "Lance <code>intern-radar eval run --prompt v1</code> puis "
            "<code>--prompt v2</code>, et <code>intern-radar eval report</code>."
            "</section>"
        )
    offer = offers[index]
    description = offer.description[:DESCRIPTION_PREVIEW]
    more = "…" if len(offer.description) > DESCRIPTION_PREVIEW else ""
    buttons = "".join(
        f'<button name="label" value="{value}" class="{css}">{e(text)}</button>'
        for value, text, css in (
            ("yes", "Je voudrais la voir", ""),
            ("no", "Pas pour moi", "ghost"),
            ("skip", "Je ne sais pas", "ghost"),
        )
    )
    return (
        f"<h1>Évaluation du tri</h1>{progress}"
        f'<section class="card"><div class="muted">{e(offer.company)} · '
        f"{e(offer.location or 'lieu non indiqué')} · {e(offer.posted_at or '')}</div>"
        f'<div class="title">{e(offer.title)}</div>'
        f'<a href="{e(offer.url)}" target="_blank" rel="noopener">Voir l\'offre</a>'
        "<details><summary>Description</summary>"
        f'<p style="white-space:pre-wrap">{e(description)}{more}</p>'
        "</details></section>"
        "<p class='muted'>Sans regarder le score : est-ce une offre que tu "
        "voudrais qu'intern-radar te montre ?</p>"
        f'<form method="post" action="/eval/{index}" class="actions">{buttons}</form>'
    )


def next_unlabelled(offers: list[EvalOffer], skipped: set[int]) -> int | None:
    """The first offer without a label, after the ones skipped this session."""
    for index, offer in enumerate(offers):
        if offer.label is None and index not in skipped:
            return index
    return None
