"""Applications board: one column per stage, and the upcoming calendar."""

from intern_radar.dashboard.icons import icon
from intern_radar.dashboard.layout import e
from intern_radar.dashboard.pages.offers import score_badge
from intern_radar.dashboard.queries import COLUMNS, BoardCard, Event
from intern_radar.store import ApplicationDetails
from intern_radar.tracking import STATUS_TEXT

EVENT_TEXT = {
    "interview": ("Entretien", "calendar"),
    "deadline": ("Date limite", "clock"),
    "action": ("À faire", "chevron"),
    "reminder": ("Relance", "bell"),
}
# Board order: the pipeline from left to right.
LANES = ("to_apply", "applied", "interview", "offer", "closed")


def _card(card: BoardCard) -> str:
    chips = []
    if card.reminder_due:
        chips.append(f'<span class="tag warn">{icon("bell", 14)}Relance due</span>')
    if card.liked:
        chips.append(f'<span class="tag blue">{icon("thumb", 14)}Pertinente</span>')
    if card.status in ("rejected", "no_answer"):
        chips.append(f'<span class="tag">{e(STATUS_TEXT[card.status])}</span>')
    if card.submitted_at:
        chips.append(
            f'<span class="tag ok">{icon("check", 14)}'
            f"envoyée le {e(card.submitted_at[:10])}</span>"
        )
    if card.deadline:
        chips.append(f'<span class="tag">{icon("clock", 14)}{e(card.deadline)}</span>')
    if card.interviews:
        chips.append(
            f'<span class="tag blue">{icon("calendar", 14)}'
            f"{e(card.interviews[-1].replace('T', ' '))}</span>"
        )
    action = ""
    if card.next_action:
        when = f" · {card.next_action_date}" if card.next_action_date else ""
        action = (
            f'<div class="loc">{icon("chevron", 14)}{e(card.next_action)}{e(when)}'
            "</div>"
        )
    score = score_badge(card.score) if card.score is not None else ""
    tags = f'<div class="tags">{"".join(chips)}</div>' if chips else ""
    return (
        f'<a class="card bcard" href="/offers/{card.ref}'
        f'{"#kit" if card.submitted_at else ""}"><div class="job">'
        '<div class="job-main">'
        f'<div class="title">{e(card.title)}</div>'
        f'<div class="company">{e(card.company)}</div>'
        f'<div class="age">depuis le {e(card.since)}</div>{action}</div>'
        f"{score}</div>{tags}</a>"
    )


def _event(ev: Event) -> str:
    when = ev.when.replace("T", " à ")
    detail = f" · {e(ev.detail)}" if ev.detail else ""
    label, glyph = EVENT_TEXT[ev.kind]
    return (
        f'<tr><td><b>{e(when)}</b></td><td><span class="tag">{icon(glyph, 14)}'
        f"{label}</span>{detail}</td>"
        f'<td><a href="/offers/{ev.ref}">{e(ev.company)}</a></td></tr>'
    )


def applications_body(columns: dict[str, list[BoardCard]], events: list[Event]) -> str:
    due = sum(card.reminder_due for cards in columns.values() for card in cards)
    labels = dict(COLUMNS)
    calendar = (
        f"<table>{''.join(_event(ev) for ev in events)}</table>"
        if events
        else '<p class="muted">Rien de prévu : ajoute des dates depuis la page '
        "d'une offre (section Suivi).</p>"
    )
    lanes = "".join(
        f'<div class="lane"><div class="lane-head"><span>{e(labels[key])}</span>'
        f'<span class="count">{len(columns[key])}</span></div>'
        + (
            "".join(_card(c) for c in columns[key][:60])
            or '<p class="empty">Aucune candidature</p>'
        )
        + "</div>"
        for key in LANES
    )
    alert = f'<div class="notice">{due} relance(s) à faire.</div>' if due else ""
    return (
        '<div class="pagehead"><div><h1>Candidatures</h1>'
        '<p class="muted">À postuler : offres jugées pertinentes ou notifiées depuis '
        "30 jours, sans suivi.</p></div>"
        f'<a class="button ghost" href="/applications.csv">{icon("download", 16)}'
        f"Exporter (CSV)</a></div>{alert}"
        f'<div class="board">{lanes}</div>'
        f"<section><h2>Agenda</h2>{calendar}</section>"
    )


def details_form(ref: int, d: ApplicationDetails) -> str:
    def field(name: str, label: str, value: str | None, kind: str = "text") -> str:
        return (
            f'<div><label for="{name}">{e(label)}</label>'
            f'<input id="{name}" type="{kind}" name="{name}" '
            f'value="{e(value or "")}"></div>'
        )

    interviews = list(d.interviews) + [""]
    slots = "".join(
        field(f"interview{i}", f"Entretien {i + 1}", when, "datetime-local")
        for i, when in enumerate(interviews[:4])
    )
    return (
        f'<form method="post" action="/offers/{ref}/details">'
        '<div class="filters" style="margin-bottom:8px">'
        + field("contact_name", "Contact", d.contact_name)
        + field("contact_email", "E-mail du contact", d.contact_email, "email")
        + field("deadline", "Date limite", d.deadline, "date")
        + "</div>"
        + '<div class="filters">'
        + slots
        + "</div>"
        + '<div class="filters">'
        + field("next_action", "Prochaine action", d.next_action)
        + field("next_action_date", "Pour le", d.next_action_date, "date")
        + "</div>"
        + '<label for="notes" style="margin-top:8px">Notes</label>'
        f'<textarea id="notes" name="notes" rows="4">{e(d.notes)}</textarea>'
        '<div class="actions"><button>Enregistrer le suivi</button></div></form>'
    )
