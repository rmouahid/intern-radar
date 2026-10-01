"""Statistics page sections: server-rendered HTML with inline SVG charts."""

import html
from datetime import datetime

from intern_radar.dashboard.queries import (
    STEP_LABELS,
    ApplicationRow,
    Kpis,
    RunSummary,
    SourceRow,
    UsageRow,
    Week,
)
from intern_radar.dashboard.runner import RunStatus
from intern_radar.tracking import STATUS_TEXT

e = html.escape


def _tile(value: str, label: str) -> str:
    return f'<div class="tile"><b>{e(value)}</b><span>{e(label)}</span></div>'


def _kpis(k: Kpis) -> str:
    tiles = [
        (f"{k.seen}", f"offres vues (+{k.seen_week} en 7 j)"),
        (f"{k.scored}", "notées par le LLM"),
        (f"{k.immediate}", "notifications immédiates"),
        (f"{k.digested}", "offres en récap"),
        (f"{k.applied}", "candidatures"),
        (f"{k.interviews}", "entretiens"),
        (f"{k.offers}", "offres reçues"),
        (f"${k.llm_cost_week:.2f}", "LLM sur 7 j (équiv. API)"),
    ]
    return (
        '<div class="tiles">'
        + "".join(_tile(v, label) for v, label in tiles)
        + "</div>"
    )


def _funnel(weeks: list[Week]) -> str:
    stages = ("seen", "passed", "scored", "surfaced", "applied", "interviews")
    labels = ("Vues", "Pré-filtre OK", "Notées", "Envoyées", "Postulées", "Entretiens")
    totals = [sum(getattr(w, s) for w in weeks) for s in stages]
    top = max(totals[0], 1)
    bars = []
    for i, (label, total) in enumerate(zip(labels, totals, strict=True)):
        width = 560 * total / top
        y = 8 + i * 26
        bars.append(
            f'<text x="0" y="{y + 13}">{e(label)}</text>'
            f'<rect x="110" y="{y}" width="{width:.1f}" height="18" rx="3"'
            f' fill="var(--accent)"/>'
            f'<text x="{116 + width:.1f}" y="{y + 13}">{total}</text>'
        )
    chart = (
        f'<svg viewBox="0 0 740 {16 + 26 * len(stages)}" width="100%"'
        f' role="img" aria-label="Entonnoir">{"".join(bars)}</svg>'
    )
    head = "".join(f'<th class="n">{e(label)}</th>' for label in labels)
    rows = "".join(
        f"<tr><td>{w.start:%d/%m}</td>"
        + "".join(f'<td class="n">{getattr(w, s)}</td>' for s in stages)
        + "</tr>"
        for w in weeks
    )
    return (
        "<section><h2>Entonnoir (8 dernières semaines)</h2>"
        + chart
        + f"<table><tr><th>Semaine du</th>{head}</tr>{rows}</table></section>"
    )


def _histogram(bins: list[tuple[float, int]], digest: float, immediate: float) -> str:
    top = max((count for _, count in bins), default=0) or 1
    width, height, base = 700, 170, 150
    step = width / len(bins)
    bars = []
    for i, (start, count) in enumerate(bins):
        h = (base - 10) * count / top
        colour = "var(--accent)" if start >= digest else "var(--accent2)"
        bars.append(
            f'<rect x="{i * step + 1:.1f}" y="{base - h:.1f}" width="{step - 2:.1f}"'
            f' height="{h:.1f}" fill="{colour}"><title>{start:.1f}–{start + 0.5:.1f}'
            f" : {count}</title></rect>"
        )
    for value, label in ((digest, "récap"), (immediate, "immédiat")):
        x = width * value / 10
        bars.append(
            f'<line x1="{x:.1f}" x2="{x:.1f}" y1="0" y2="{base}" stroke="var(--warn)"'
            f' stroke-dasharray="4 3"/><text x="{x + 4:.1f}" y="12">{label}'
            f" {value:g}</text>"
        )
    ticks = "".join(
        f'<text x="{width * n / 10:.1f}" y="{base + 14}">{n}</text>' for n in range(11)
    )
    return (
        "<section><h2>Répartition des scores</h2>"
        f'<svg viewBox="0 0 {width + 20} {height}" width="100%" role="img"'
        f' aria-label="Histogramme des scores">{"".join(bars)}{ticks}</svg></section>'
    )


def _sources(rows: list[SourceRow]) -> str:
    body = "".join(
        f"<tr><td>{e(r.company)}</td><td>{e(r.source)}</td><td>{e(r.tier)}</td>"
        f'<td class="n">{r.offers}</td><td>{e(r.last_seen)}</td>'
        + (
            f'<td class="warn">en échec depuis {e((r.failing_since or "")[:10])}'
            f" · {e((r.last_error or '')[:80])}</td>"
            if r.failing_since
            else '<td class="ok">OK</td>'
        )
        + "</tr>"
        for r in rows
    )
    return (
        "<section><h2>Sources</h2><table><tr><th>Entreprise</th><th>Source</th>"
        '<th>Niveau</th><th class="n">Offres</th><th>Dernière nouvelle offre</th>'
        f"<th>État</th></tr>{body}</table></section>"
    )


def _applications(rows: list[ApplicationRow]) -> str:
    if not rows:
        body = '<tr><td colspan="4" class="muted">Aucune candidature suivie.</td></tr>'
    else:
        body = "".join(
            f'<tr><td><a href="{e(r.url)}">{e(r.company)} — {e(r.title[:70])}</a></td>'
            f"<td>{e(STATUS_TEXT.get(r.status, r.status))}</td>"
            f"<td>{e(r.applied or '—')}</td><td>{e(r.updated)}</td></tr>"
            for r in rows
        )
    return (
        "<section><h2>Candidatures</h2><table><tr><th>Offre</th><th>Statut</th>"
        f"<th>Postulé le</th><th>Mise à jour</th></tr>{body}</table></section>"
    )


def _usage(rows: list[UsageRow]) -> str:
    total = sum(r.cost for r in rows)
    body = (
        "".join(
            f"<tr><td>{e(r.day)}</td><td>{e(r.purpose)}</td>"
            f'<td class="n">{r.calls}</td><td class="n">{r.tokens_in:,}</td>'
            f'<td class="n">{r.tokens_out:,}</td><td class="n">${r.cost:.3f}</td></tr>'
            for r in rows
        )
        or '<tr><td colspan="6" class="muted">Aucun appel enregistré.</td></tr>'
    )
    return (
        f"<section><h2>Usage LLM (14 jours, ${total:.2f} équiv. API)</h2>"
        "<table><tr><th>Jour</th><th>Usage</th><th class='n'>Appels</th>"
        "<th class='n'>Tokens entrée</th><th class='n'>Tokens sortie</th>"
        f"<th class='n'>Coût</th></tr>{body}</table></section>"
    )


def _run(run: RunStatus) -> str:
    if run.running:
        state = f"⏳ Run en cours depuis {e(run.started or '…')}"
    elif run.finished:
        outcome = "✅ réussi" if run.result == "success" else f"❌ {e(run.result)}"
        state = f"Dernier run {outcome}, terminé le {e(run.finished)}"
    else:
        state = "Aucun run enregistré"
    summary = f'<div class="muted">{e(run.summary)}</div>' if run.summary else ""
    disabled = " disabled" if run.running else ""
    return (
        '<section class="run"><div><h2>Pipeline</h2>'
        f"<div>{state}</div>{summary}</div>"
        '<form method="post" action="/run">'
        f"<button{disabled}>Lancer un run</button></form></section>"
    )


def _minutes(seconds: float) -> str:
    return (
        f"{int(seconds // 60)} min {int(seconds % 60):02d}"
        if seconds >= 60
        else (f"{seconds:.0f} s")
    )


def _runs(summary: RunSummary) -> str:
    if not summary.runs:
        return (
            "<section><h2>Runs</h2><p class='muted'>Aucun run enregistré pour "
            "l'instant.</p></section>"
        )
    timeline = list(reversed(summary.runs))  # oldest first
    top = max(r.duration for r in timeline) or 1
    width = 14
    bars = "".join(
        f'<rect x="{i * width + 1}" y="{80 - round(70 * r.duration / top)}" '
        f'width="{width - 3}" height="{max(2, round(70 * r.duration / top))}" rx="2" '
        f'fill="var(--{"warn" if r.crash or r.errors else "accent"})">'
        f"<title>{e(r.started_at[:16].replace('T', ' '))} · "
        f"{_minutes(r.duration)}"
        + (f" · {len(r.errors)} erreur(s)" if r.errors else "")
        + (" · plantage" if r.crash else "")
        + "</title></rect>"
        for i, r in enumerate(timeline)
    )
    chart = (
        f'<svg viewBox="0 0 {width * len(timeline)} 84" width="100%" height="110" '
        f'role="img">{bars}</svg>'
    )
    steps = " · ".join(
        f"{STEP_LABELS.get(step, step)} {_minutes(seconds)}"
        for step, seconds in summary.steps
    )
    failing = "".join(
        f"<tr><td>{e(source)}</td><td class='n'>{count}</td>"
        f"<td>{e(message[:90])}</td></tr>"
        for source, count, message in summary.failing[:8]
    )
    latest = "".join(
        f"<tr><td>{e(r.started_at[5:16].replace('T', ' '))}</td>"
        f"<td class='n'>{_minutes(r.duration)}</td>"
        f"<td class='n'>{r.counters.get('new', 0)}</td>"
        f"<td class='n'>{r.counters.get('scored', 0)}</td>"
        f"<td class='n'>{r.counters.get('notified', 0)}</td>"
        + (
            f"<td class='warn'>{e(r.crash[:60])}</td>"
            if r.crash
            else f"<td class='{'warn' if r.errors else 'ok'}'>"
            f"{len(r.errors)} erreur(s)</td>"
        )
        + "</tr>"
        for r in summary.runs[:10]
    )
    return (
        "<section><h2>Runs</h2>"
        f"<p class='muted'>{len(summary.runs)} derniers runs · durée médiane "
        f"{_minutes(summary.median or 0)} · en orange : erreurs ou plantage</p>"
        f"{chart}<p><b>Étapes (moyenne)</b> : {e(steps) or '—'}</p>"
        + (
            "<h2>Sources en échec</h2><table><tr><th>Source</th><th class='n'>Runs"
            f"</th><th>Dernière erreur</th></tr>{failing}</table>"
            if failing
            else "<p class='ok'>Aucune source en échec sur ces runs.</p>"
        )
        + "<h2 style='margin-top:12px'>Derniers runs</h2><table><tr><th>Début (UTC)"
        "</th><th class='n'>Durée</th><th class='n'>Nouv.</th><th class='n'>Notées"
        "</th><th class='n'>Notif.</th><th>État</th></tr>"
        f"{latest}</table></section>"
    )


def stats_body(
    now: datetime,
    kpis: Kpis,
    weeks: list[Week],
    histogram: list[tuple[float, int]],
    thresholds: tuple[float, float],
    sources: list[SourceRow],
    applications: list[ApplicationRow],
    usage: list[UsageRow],
    run: RunStatus | None = None,
    runs: RunSummary | None = None,
) -> str:
    digest, immediate = thresholds
    return (
        "<h1>Statistiques</h1>"
        f'<p class="muted">Mis à jour le {now:%d/%m/%Y à %H:%M} UTC</p>'
        + (_run(run) if run else "")
        + _kpis(kpis)
        + _funnel(weeks)
        + _histogram(histogram, digest, immediate)
        + _applications(applications)
        + _sources(sources)
        + (_runs(runs) if runs is not None else "")
        + _usage(usage)
    )
