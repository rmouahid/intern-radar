"""The feedback given on offers, latest first."""

from intern_radar.dashboard.layout import e
from intern_radar.feedback import feedback_summary
from intern_radar.models import Job


def feedback_body(entries: list[tuple[Job, int, str, str]], refs: list[int]) -> str:
    if not entries:
        return (
            "<h1>Mes avis</h1><section class='muted'>Aucun avis pour l'instant : "
            "utilise 👍/👎 sur les offres.</section>"
        )
    liked = sum(1 for _, vote, _, _ in entries if vote > 0)
    cards = "".join(
        f'<a class="card" href="/offers/{ref}"><div class="top"><div>'
        f'<div class="muted">{e(job.company)} · {e(at[:10])}</div>'
        f'<div class="title">{e(job.title)}</div>'
        + (f'<div class="muted">« {e(reason)} »</div>' if reason else "")
        + f'</div><div class="score">{"👍" if vote > 0 else "👎"}</div></div></a>'
        for (job, vote, reason, at), ref in zip(entries, refs, strict=True)
    )
    summary = feedback_summary(entries)
    return (
        f"<h1>Mes avis</h1><p class='muted'>{liked} 👍 · "
        f"{len(entries) - liked} 👎</p>"
        "<section><details><summary><b>Ce que voit la notation</b></summary>"
        f'<pre style="white-space:pre-wrap;font-size:12px">{e(summary)}</pre>'
        f"</details></section>{cards}"
    )
