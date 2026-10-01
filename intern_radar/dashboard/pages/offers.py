"""Offers list: filters in the query string, one card per posting group."""

from urllib.parse import urlencode

from intern_radar.dashboard.layout import e
from intern_radar.dashboard.queries import (
    PER_PAGE,
    REGIONS,
    OfferFilters,
    OfferRow,
)
from intern_radar.notifier import WORK_AUTHORISATION_LABELS, tier_label
from intern_radar.tracking import STATUS_TEXT

TIERS = (
    ("", "Tous niveaux"),
    ("S", "Niveau S"),
    ("A", "Niveau A"),
    ("B", "Niveau B"),
    ("unlisted", "Découverte"),
)
VISAS = (
    ("", "Tous visas"),
    ("none", "Sans sponsoring"),
    ("sponsor", "Sponsoring requis"),
)
STATUSES = (("", "Ouvertes"), ("none", "Sans suivi"), *STATUS_TEXT.items())
DAYS = (
    ("60", "60 jours"),
    ("30", "30 jours"),
    ("14", "14 jours"),
    ("7", "7 jours"),
    ("0", "Toutes dates"),
)


def _select(name: str, options, current: str) -> str:
    items = "".join(
        f'<option value="{e(value)}"{" selected" if value == current else ""}>'
        f"{e(label)}</option>"
        for value, label in options
    )
    return f'<select name="{name}" onchange="this.form.submit()">{items}</select>'


def filters_form(f: OfferFilters) -> str:
    regions = (("", "Toutes régions"), *REGIONS)
    return (
        '<form class="filters" method="get" action="/offers">'
        f'<input type="search" name="q" value="{e(f.q)}" '
        'placeholder="Entreprise, poste…">'
        f'<input type="number" name="min" step="0.5" min="0" max="10" '
        f'value="{f.min_score:g}" title="Score minimum">'
        + _select("tier", TIERS, f.tier)
        + _select("region", regions, f.region)
        + _select("visa", VISAS, f.visa)
        + _select("status", STATUSES, f.status)
        + _select("days", DAYS, str(f.days))
        + '<button type="submit">Filtrer</button></form>'
    )


def offer_card(row: OfferRow) -> str:
    label = tier_label(row.tier)
    chips = [label[:1].upper() + label[1:]]
    chips.append(WORK_AUTHORISATION_LABELS.get(row.work_authorisation, "Visa ?"))
    if row.chance is not None:
        chips.append(f"🎯 {row.chance} %")
    if row.application:
        chips.append(STATUS_TEXT.get(row.application, row.application))
    if row.notified:
        chips.append("Notifiée")
    elif row.digested:
        chips.append("Récap")
    if row.posted_at:
        chips.append(f"Publiée le {row.posted_at[:10]}")
    places = f" · +{row.other_places} lieu(x)" if row.other_places else ""
    chip_html = "".join(f'<span class="chip">{e(c)}</span>' for c in chips)
    return (
        f'<a class="card" href="/offers/{row.ref}">'
        f'<div class="top"><div><div class="muted">{e(row.company)}</div>'
        f'<div class="title">{e(row.title)}</div>'
        f'<div class="muted">📍 {e(row.location[:80] or "Lieu non précisé")}'
        f"{places}</div>"
        f'</div><div class="score">{row.score:.1f}</div></div>{chip_html}</a>'
    )


def offers_body(rows: list[OfferRow], total: int, f: OfferFilters) -> str:
    def link(page: int) -> str:
        params = {
            "q": f.q,
            "min": f"{f.min_score:g}",
            "tier": f.tier,
            "region": f.region,
            "visa": f.visa,
            "status": f.status,
            "days": str(f.days),
            "page": str(page),
        }
        return "/offers?" + urlencode({k: v for k, v in params.items() if v})

    pages = max(1, -(-total // PER_PAGE))
    pager = '<div class="pager">'
    pager += (
        f'<a href="{link(f.page - 1)}">← Précédent</a>'
        if f.page > 1
        else "<span></span>"
    )
    pager += f'<span class="muted">Page {f.page}/{pages}</span>'
    pager += (
        f'<a href="{link(f.page + 1)}">Suivant →</a>'
        if f.page < pages
        else "<span></span>"
    )
    pager += "</div>"
    cards = "".join(offer_card(row) for row in rows) or (
        '<section class="muted">Aucune offre ne correspond à ces filtres.</section>'
    )
    return (
        f"<h1>Offres</h1><p class='muted'>{total} offre(s) · "
        f"une carte par poste (les autres villes sont regroupées)</p>"
        f"<section>{filters_form(f)}</section>{cards}"
        + (pager if total > PER_PAGE else "")
    )
