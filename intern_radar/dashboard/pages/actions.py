"""Action buttons of an offer page: tracking, documents, Telegram."""

from intern_radar.dashboard.layout import e
from intern_radar.dashboard.worker import FAILED, PENDING, RUNNING, Worker
from intern_radar.tracking import LABELS, TRANSITIONS

TASK_LABELS = {
    "letter": ("✍️ Générer la lettre", "✍️ Lettre"),
    "cv": ("📄 Générer le CV", "📄 CV"),
    "telegram": ("📲 Envoyer sur Telegram", "📲 Telegram"),
}
STATE_TEXT = {
    PENDING: "en attente",
    RUNNING: "en cours…",
    "done": "terminé",
    FAILED: "échec",
}
NOTICES = {
    "status": "Statut mis à jour.",
    "refused": "Ce changement de statut n'est pas possible depuis le statut actuel.",
    "queued": "C'est parti : la page se met à jour toute seule.",
    "already": "Cette action est déjà en cours.",
    "unavailable": "Actions indisponibles : le service n'est pas configuré.",
}


def _post(action: str, label: str, name: str = "", value: str = "", ghost=False):
    field = f'<input type="hidden" name="{name}" value="{e(value)}">' if name else ""
    css = ' class="ghost"' if ghost else ""
    return (
        f'<form class="inline" method="post" action="{e(action)}">{field}'
        f"<button{css}>{e(label)}</button></form>"
    )


def actions_html(
    ref: int,
    status: str | None,
    has_letter: bool,
    has_resume: bool,
    worker: Worker | None,
) -> str:
    moves = "".join(
        _post(f"/offers/{ref}/status", LABELS[new], "status", new, ghost=True)
        for new in TRANSITIONS.get(status, ())
    )
    tasks = []
    lines = []
    if worker is not None:
        done = {"letter": has_letter, "cv": has_resume, "telegram": False}
        for kind, (label, short) in TASK_LABELS.items():
            state = worker.state(kind, ref)
            busy = state is not None and state.state in (PENDING, RUNNING)
            if busy:
                tasks.append(f"<button disabled>{e(short)} · en cours…</button>")
            else:
                text = label
                if done[kind]:
                    text = f"{short} · renvoyer"
                tasks.append(_post(f"/offers/{ref}/{kind}", text))
            if state is not None:
                detail = f" : {state.error}" if state.error else ""
                lines.append(f"{short} {STATE_TEXT[state.state]}{detail}")
    status_html = "".join(f'<div class="muted">{e(line)}</div>' for line in lines)
    return (
        (f'<div class="actions">{moves}</div>' if moves else "")
        + (f'<div class="actions">{"".join(tasks)}</div>' if tasks else "")
        + status_html
    )
