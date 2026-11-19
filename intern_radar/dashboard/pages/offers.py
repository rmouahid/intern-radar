"""Offers list: filters in the query string, one card per posting group."""

from datetime import date
from urllib.parse import urlencode

from intern_radar.dashboard.icons import icon
from intern_radar.dashboard.layout import THUMB_DOWN, THUMB_UP, e, monogram
from intern_radar.dashboard.queries import (
    PER_PAGE,
    REGIONS,
    OfferFilters,
    OfferRow,
)
from intern_radar.notifier import WORK_AUTHORISATION_LABELS
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
    ("60", "60 derniers jours"),
    ("30", "30 derniers jours"),
    ("14", "14 derniers jours"),
    ("7", "7 derniers jours"),
    ("0", "Toutes dates"),
)
SORT_LABELS = (
    ("", "Score"),
    ("chance", "% de chance"),
    ("posted", "Publication récente"),
    ("seen", "Ajout récent"),
    ("company", "Entreprise"),
)
MIN_SCORES = ("0", "4", "5", "5.5", "6", "6.5", "7", "7.5", "8", "9")
DEFAULTS = OfferFilters()
# Score levels of the badge; same cut-offs as the default notification
# thresholds (digest 5.5, immediate 7.5).
HIGH, MEDIUM = 7.5, 5.5


def _select(name: str, options, current: str, title: str = "", submit=True) -> str:
    items = "".join(
        f'<option value="{e(value)}"{" selected" if value == current else ""}>'
        f"{e(label)}</option>"
        for value, label in options
    )
    attrs = f' title="{e(title)}" aria-label="{e(title)}"' if title else ""
    change = ' onchange="this.form.submit()"' if submit else ""
    return f'<select name="{name}"{attrs}{change}>{items}</select>'


def _pill(name: str, options, current: str, default: str, title: str) -> str:
    on = " on" if current != default else ""
    return f'<span class="pill{on}">{_select(name, options, current, title)}</span>'


def filters_form(f: OfferFilters, total: int | None = None) -> str:
    """Hero search (keywords and region) and the filter pills below it."""
    regions = (("", "Toutes régions"), *REGIONS)
    current_min = f"{f.min_score:g}"
    scores = tuple((v, f"Score ≥ {v}") for v in MIN_SCORES)
    if current_min not in MIN_SCORES:
        scores = ((current_min, f"Score ≥ {current_min}"), *scores)
    count = (
        f"<p>{total} offre{'s' if total != 1 else ''} de stage triée"
        f"{'s' if total != 1 else ''} pour ton profil, une carte par poste.</p>"
        if total is not None
        else "<p>Les stages repérés sur les pages carrières, triés pour ton profil.</p>"
    )
    return (
        '<form method="get" action="/offers">'
        '<div class="hero"><div class="hero-inner">'
        f"<h1>Trouve ton stage</h1>{count}"
        '<div class="searchbar" role="search">'
        f'<label class="field">{icon("search", 20)}'
        f'<input type="search" name="q" value="{e(f.q)}" '
        'placeholder="Poste, entreprise, mot-clé" aria-label="Recherche"></label>'
        f'<label class="field where">{icon("pin", 20)}'
        + _select("region", regions, f.region, "Région", submit=False)
        + "</label>"
        '<button type="submit">Rechercher</button></div></div></div>'
        '<div class="filterbar">'
        f'<span class="lbl">{icon("sliders", 16)}Filtres</span>'
        + _pill("min", scores, current_min, f"{DEFAULTS.min_score:g}", "Score minimum")
        + _pill("tier", TIERS, f.tier, "", "Niveau d'entreprise")
        + _pill("visa", VISAS, f.visa, "", "Visa")
        + _pill("status", STATUSES, f.status, "", "Suivi")
        + _pill("days", DAYS, str(f.days), str(DEFAULTS.days), "Publication")
        + f'<input type="hidden" name="sort" value="{e(f.sort)}">'
        + "</div></form>"
    )


def _sort_form(f: OfferFilters) -> str:
    """The sort menu, keeping every other filter."""
    hidden = "".join(
        f'<input type="hidden" name="{k}" value="{e(v)}">'
        for k, v in (
            ("q", f.q),
            ("min", f"{f.min_score:g}"),
            ("tier", f.tier),
            ("region", f.region),
            ("visa", f.visa),
            ("status", f.status),
            ("days", str(f.days)),
        )
        if v
    )
    return (
        '<form class="sort" method="get" action="/offers">'
        f"{hidden}<span>Trier par</span>"
        + _select("sort", SORT_LABELS, f.sort, "Trier par")
        + "</form>"
    )


def _age(posted_at: str | None, today: date) -> tuple[str, bool]:
    """'Publiée il y a 3 jours' and whether the posting is new (≤ 3 days)."""
    if not posted_at:
        return "Date de publication inconnue", False
    try:
        days = (today - date.fromisoformat(posted_at[:10])).days
    except ValueError:
        return f"Publiée le {posted_at[:10]}", False
    if days <= 0:
        text = "Publiée aujourd'hui"
    elif days == 1:
        text = "Publiée hier"
    elif days < 31:
        text = f"Publiée il y a {days} jours"
    else:
        text = f"Publiée le {posted_at[:10]}"
    return text, 0 <= days <= 3


def score_badge(score: float, size: str = "") -> str:
    level = "hi" if score >= HIGH else "mid" if score >= MEDIUM else ""
    css = " ".join(c for c in ("score", level, size) if c)
    return (
        f'<div class="{css}" title="Score sur 10">{score:.1f}<small>/10</small></div>'
    )


def tier_badge(tier: str) -> str:
    if tier == "unlisted":
        return '<span class="tier" title="Hors liste suivie">Découverte</span>'
    return f'<span class="tier t-{e(tier)}" title="Niveau {e(tier)}">{e(tier)}</span>'


def offer_card(
    row: OfferRow,
    back: str = "/offers",
    selected: bool = False,
    today: date | None = None,
) -> str:
    tags = [
        (
            "passport",
            WORK_AUTHORISATION_LABELS.get(row.work_authorisation, "Visa ?"),
            "",
        )
    ]
    if row.chance is not None:
        tags.append(("target", f"{row.chance} % de chance", "blue"))
    if row.application:
        tags.append(("check", STATUS_TEXT.get(row.application, row.application), "ok"))
    if row.notified:
        tags.append(("bell", "Notifiée", ""))
    elif row.digested:
        tags.append(("bell", "Récap", ""))
    tag_html = "".join(
        f'<span class="tag {css}">{icon(glyph, 14)}{e(text)}</span>'
        for glyph, text, css in tags
    )
    places = f" · +{row.other_places} lieu(x)" if row.other_places else ""
    age, new = _age(row.posted_at, today or date.today())
    fresh = '<span class="new">Nouveau</span>' if new else ""
    return (
        f'<div class="card{" sel" if selected else ""}" data-ref="{row.ref}">'
        f'<a class="cardlink" href="/offers/{row.ref}">'
        f'<div class="job">{monogram(row.company)}<div class="job-main">'
        f'<div class="title">{e(row.title)}</div>'
        f'<div class="company">{e(row.company)} {tier_badge(row.tier)}</div>'
        f'<div class="loc">{icon("pin", 15)}'
        f"{e(row.location[:80] or 'Lieu non précisé')}{places}</div>"
        f"</div>{score_badge(row.score)}</div>"
        f'<div class="tags">{tag_html}</div></a>'
        f'<div class="foot"><span class="age">{icon("clock", 14)}{e(age)} {fresh}'
        f"</span>{vote_buttons(row.ref, row.vote, back)}</div></div>"
    )


def vote_buttons(ref: int, vote: int | None, back: str) -> str:
    """Thumb up/down forms; tapping the current vote again removes it."""

    def button(value: int, title: str, glyph: str) -> str:
        chosen = vote == value
        action = "clear" if chosen else ("up" if value > 0 else "down")
        css = "vote on" if chosen else "vote"
        return (
            f'<form class="inline" method="post" action="/offers/{ref}/feedback">'
            f'<input type="hidden" name="vote" value="{action}">'
            f'<input type="hidden" name="next" value="{e(back)}">'
            f'<button class="{css}" title="{title}" aria-label="{title}">{glyph}'
            "</button></form>"
        )

    up = button(1, "Pertinente", THUMB_UP)
    down = button(-1, "Pas pour moi", THUMB_DOWN)
    return f'<div class="votes">{up}{down}</div>'


def query_string(f: OfferFilters, page: int | None = None) -> str:
    """The filters as a query string (without the page unless given)."""
    params = {
        "q": f.q,
        "min": f"{f.min_score:g}",
        "tier": f.tier,
        "region": f.region,
        "visa": f.visa,
        "status": f.status,
        "days": str(f.days),
        "sort": f.sort,
        "page": str(page) if page and page > 1 else "",
    }
    return urlencode({k: v for k, v in params.items() if v})


def save_search_form(f: OfferFilters) -> str:
    return (
        '<details class="alert-pop"><summary class="button ghost sm">'
        f'{icon("bell", 16)}Créer une alerte</summary><div class="pop">'
        "<p>Reçois sur Telegram les nouvelles offres qui correspondent à ces "
        "filtres.</p>"
        '<form method="post" action="/searches" class="actions">'
        f'<input type="hidden" name="query" value="{e(query_string(f))}">'
        '<input name="name" required maxlength="80" '
        'placeholder="Nom de l\'alerte" aria-label="Nom de l\'alerte">'
        '<button class="ghost">Créer une alerte</button></form></div></details>'
    )


# Desktop split view: a click on a card loads its detail into the right pane
# (fragment from /offers/<ref>?pane=1) instead of leaving the list. Phones and
# no-JS browsers follow the link to the full offer page.
SPLIT_JS = """<script>(function(){
var pane=document.getElementById('pane');if(!pane)return;
var wide=window.matchMedia('(min-width:900px)');
document.addEventListener('click',function(ev){
var a=ev.target.closest('a.cardlink');
if(!a||!wide.matches||ev.metaKey||ev.ctrlKey)return;
ev.preventDefault();var card=a.closest('.card');
document.querySelectorAll('.card.sel').forEach(function(c){c.classList.remove('sel')});
card.classList.add('sel');pane.classList.add('loading');
fetch(a.getAttribute('href')+'?pane=1').then(function(r){return r.text()})
.then(function(h){pane.innerHTML=h;pane.scrollTop=0;pane.classList.remove('loading');
var u=new URL(location.href);u.searchParams.set('sel',card.dataset.ref);
history.replaceState(null,'',u)})
.catch(function(){location.href=a.href})});})();</script>"""


def offers_body(
    rows: list[OfferRow],
    total: int,
    f: OfferFilters,
    selected: int | None = None,
    pane: str | None = None,
    today: date | None = None,
) -> str:
    def link(page: int) -> str:
        return "/offers?" + query_string(f, page)

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
    here = link(f.page)
    cards = "".join(
        offer_card(row, here, row.ref == selected, today) for row in rows
    ) or (
        '<section class="muted">Aucune offre ne correspond à ces filtres. '
        "Baisse le score minimum ou élargis la période.</section>"
    )
    results = (
        f'<div class="resultsbar"><div class="count"><b>{total}</b> '
        f"résultat{'s' if total != 1 else ''}</div>"
        f'<div style="display:flex;gap:12px;align-items:center">{_sort_form(f)}'
        f"{save_search_form(f)}</div></div>"
    )
    listing = cards + (pager if total > PER_PAGE else "")
    head = filters_form(f, total) + results
    if pane is None:
        return head + f'<div class="joblist">{listing}</div>'
    return (
        f'{head}<div class="split"><div class="list">{listing}</div>'
        f'<aside class="pane" id="pane">{pane}</aside></div>{SPLIT_JS}'
    )
