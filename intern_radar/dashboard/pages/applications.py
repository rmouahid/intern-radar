"""Applications board: one column per stage, and the upcoming calendar."""

from intern_radar.dashboard.layout import e
from intern_radar.dashboard.queries import COLUMNS, BoardCard, Event
from intern_radar.store import ApplicationDetails
from intern_radar.tracking import STATUS_TEXT

EVENT_TEXT = {
    "interview": "🗣 Entretien",
    "deadline": "⏳ Date limite",
    "action": "➡️ À faire",
    "reminder": "🔔 Relance",
}


def _card(card: BoardCard) -> str:
    chips = []
    if card.reminder_due:
        chips.append('<span class="chip warn">🔔 Relance due</span>')
    if card.liked:
        chips.append('<span class="chip">👍</span>')
    if card.status in ("rejected", "no_answer"):
        chips.append(f'<span class="chip">{e(STATUS_TEXT[card.status])}</span>')
    if card.deadline:
        chips.append(f'<span class="chip">⏳ {e(card.deadline)}</span>')
    if card.interviews:
        chips.append(
            f'<span class="chip">🗣 {e(card.interviews[-1].replace("T", " "))}</span>'
        )
    action = ""
    if card.next_action:
        when = f" · {card.next_action_date}" if card.next_action_date else ""
        action = f'<div class="muted">➡️ {e(card.next_action)}{e(when)}</div>'
    score = f"{card.score:.1f}" if card.score is not None else ""
    return (
        f'<a class="card" href="/offers/{card.ref}"><div class="top"><div>'
        f'<div class="muted">{e(card.company)} · depuis le {e(card.since)}</div>'
        f'<div class="title">{e(card.title)}</div>{action}</div>'
        f'<div class="score">{score}</div></div>{"".join(chips)}</a>'
    )


def _event(ev: Event) -> str:
    when = ev.when.replace("T", " à ")
    detail = f" · {e(ev.detail)}" if ev.detail else ""
    return (
        f"<tr><td>{e(when)}</td><td>{EVENT_TEXT[ev.kind]}{detail}</td>"
        f'<td><a href="/offers/{ev.ref}">{e(ev.company)}</a></td></tr>'
    )


def applications_body(columns: dict[str, list[BoardCard]], events: list[Event]) -> str:
    due = sum(card.reminder_due for cards in columns.values() for card in cards)
    counts = " · ".join(f"{label} {len(columns[key])}" for key, label in COLUMNS)
    calendar = (
        f"<table>{''.join(_event(ev) for ev in events)}</table>"
        if events
        else '<p class="muted">Rien de prévu : ajoute des dates depuis la page '
        "d'une offre (section Suivi).</p>"
    )
    sections = "".join(
        f"<div><h2>{e(label)} ({len(columns[key])})</h2>"
        + ("".join(_card(c) for c in columns[key][:60]) or '<p class="muted">—</p>')
        + "</div>"
        for key, label in COLUMNS
    )
    alert = f'<div class="notice">🔔 {due} relance(s) à faire.</div>' if due else ""
    return (
        f"<h1>Candidatures</h1><p class='muted'>{e(counts)}</p>{alert}"
        '<p><a class="button ghost" href="/applications.csv">⬇️ Exporter (CSV)</a></p>'
        f"<section><h2>Agenda</h2>{calendar}</section>"
        '<p class="muted">À postuler : offres 👍 ou notifiées depuis 30 jours, '
        "sans suivi.</p>"
        f'<div class="columns">{sections}</div>'
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
