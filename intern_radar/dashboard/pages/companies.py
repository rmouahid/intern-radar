"""Companies: what each one publishes and where applications stand."""

from urllib.parse import quote

from intern_radar.dashboard.layout import e
from intern_radar.dashboard.pages.offers import offer_card
from intern_radar.dashboard.queries import CompanyDetail, CompanyRow
from intern_radar.notifier import tier_label
from intern_radar.tracking import STATUS_TEXT


def company_url(name: str) -> str:
    return "/companies/" + quote(name, safe="")


def _health(c: CompanyRow) -> str:
    if c.error:
        since = (c.failing_since or "")[:10]
        return f'<span class="chip warn">⚠️ en échec depuis le {e(since)}</span>'
    if not c.watched:
        return '<span class="chip">Découverte</span>'
    return '<span class="chip ok">Source OK</span>'


def companies_body(rows: list[CompanyRow], q: str) -> str:
    query = q.lower()
    shown = [c for c in rows if query in c.name.lower()] if query else rows
    cards = "".join(
        f'<a class="card" href="{company_url(c.name)}"><div class="top"><div>'
        f'<div class="title">{e(c.name)}</div>'
        f'<div class="muted">{e(tier_label(c.tier))} · {e(c.source)} · '
        f"{c.seen} offre(s) vue(s)"
        + (f" · dernière le {e(c.last_new)}" if c.last_new else "")
        + "</div></div>"
        f'<div class="score">{c.open}</div></div>{_health(c)}'
        + (f'<span class="chip">📋 {c.applications}</span>' if c.applications else "")
        + "</a>"
        for c in shown
    )
    failing = sum(1 for c in rows if c.error)
    return (
        "<h1>Entreprises</h1>"
        f"<p class='muted'>{len(rows)} entreprise(s) · {failing} source(s) en échec · "
        "le chiffre à droite compte les offres ouvertes</p>"
        '<form method="get" action="/companies"><input type="search" name="q" '
        f'value="{e(q)}" placeholder="Rechercher une entreprise…"></form>'
        + (cards or '<section class="muted">Aucune entreprise.</section>')
    )


def _weekly(weekly: list[tuple[str, int]]) -> str:
    top = max((n for _, n in weekly), default=0) or 1
    width = 24
    bars = "".join(
        f'<rect x="{i * width + 2}" y="{70 - round(60 * n / top)}" '
        f'width="{width - 4}" height="{max(1, round(60 * n / top))}" rx="2" '
        f'fill="var(--accent)"><title>{e(week)} : {n}</title></rect>'
        for i, (week, n) in enumerate(weekly)
    )
    first, last = weekly[0][0], weekly[-1][0]
    return (
        f'<svg viewBox="0 0 {width * len(weekly)} 86" width="100%" height="110">'
        f'{bars}<text x="0" y="84">{e(first[5:])}</text>'
        f'<text x="{width * len(weekly)}" y="84" text-anchor="end">{e(last[5:])}'
        "</text></svg>"
    )


def company_body(detail: CompanyDetail) -> str:
    c = detail.company
    since = (c.failing_since or "")[:10]
    error = (
        f'<p class="warn">Source en échec depuis le {e(since)} : '
        f"{e((c.error or '')[:300])}</p>"
        if c.error
        else ""
    )
    applications = "".join(
        f'<tr><td><a href="/offers/{ref}">{e(title[:70])}</a></td>'
        f"<td>{e(STATUS_TEXT.get(status, status))}</td><td>{e(updated)}</td></tr>"
        for ref, title, status, updated in detail.applications
    )
    offers = "".join(offer_card(o) for o in detail.offers) or (
        '<p class="muted">Aucune offre ouverte.</p>'
    )
    return (
        '<p class="muted"><a href="/companies">← Entreprises</a></p>'
        f"<h1>{e(c.name)}</h1>"
        f'<p class="muted">{e(tier_label(c.tier))} · source {e(c.source)}'
        + ("" if c.watched else " · trouvée par la découverte")
        + f" · {c.seen} offre(s) vue(s)"
        + (f" · dernière nouvelle le {e(c.last_new)}" if c.last_new else "")
        + f"</p>{_health(c)}{error}"
        f"<section><h2>Offres vues par semaine</h2>{_weekly(detail.weekly)}</section>"
        + (
            f"<section><h2>Candidatures</h2><table>{applications}</table></section>"
            if applications
            else ""
        )
        + f"<h2 style='margin-top:16px'>Offres ouvertes ({len(detail.offers)})</h2>"
        + offers
    )
