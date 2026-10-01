"""Saved searches: list, open, pause or delete."""

from intern_radar.dashboard.layout import e
from intern_radar.store import SavedSearch


def _post(action: str, label: str, ghost: bool = True) -> str:
    css = ' class="ghost"' if ghost else ""
    return (
        f'<form class="inline" method="post" action="{action}">'
        f"<button{css}>{e(label)}</button></form>"
    )


def searches_body(searches: list[SavedSearch]) -> str:
    if not searches:
        cards = (
            '<section class="muted">Aucune recherche : règle les filtres de la page '
            "Offres puis « 🔔 Alerte Telegram ».</section>"
        )
    else:
        cards = "".join(
            '<div class="card"><div class="top"><div>'
            f'<div class="title">{e(s.name)}</div>'
            f'<div class="muted">{e(s.query or "filtres par défaut")}</div>'
            f'<div class="muted">Créée le {e(s.created_at[:10])} · '
            f"{s.hits} alerte(s) envoyée(s)</div></div>"
            f'<div class="score">{"🔔" if s.active else "🔕"}</div></div>'
            '<div class="actions">'
            f'<a class="button ghost" href="/offers?{e(s.query)}">Voir les offres</a>'
            + _post(
                f"/searches/{s.id}/toggle",
                "Mettre en pause" if s.active else "Réactiver",
            )
            + _post(f"/searches/{s.id}/delete", "Supprimer")
            + "</div></div>"
            for s in searches
        )
    return (
        "<h1>Recherches</h1><p class='muted'>Après chaque run, les nouvelles offres "
        "correspondantes sont envoyées sur Telegram (une fois par offre, 5 au plus "
        "par recherche et par run).</p>" + cards
    )
