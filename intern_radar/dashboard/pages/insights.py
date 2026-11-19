"""Skills gap: what relevant offers ask for that the profile does not show."""

from intern_radar.dashboard.layout import e
from intern_radar.dashboard.queries import TREND_WEEKS, SkillDemand

RELEVANCE_CHOICES = (6, 7, 8, 9)


def _spark(trend: tuple[int, ...]) -> str:
    """Offers per week as tiny bars (oldest first)."""
    top = max(trend) or 1
    bars = "".join(
        f'<rect x="{i * 9}" y="{20 - round(18 * n / top)}" width="7" '
        f'height="{max(1, round(18 * n / top))}" rx="1" fill="var(--accent)"/>'
        for i, n in enumerate(trend)
    )
    title = " · ".join(str(n) for n in trend)
    return (
        f'<svg width="{9 * TREND_WEEKS}" height="20" role="img">'
        f"<title>Par semaine : {e(title)}</title>{bars}</svg>"
    )


def _row(skill: SkillDemand) -> str:
    examples = " · ".join(
        f'<a href="/offers/{ref}">{e(company)}</a>'
        for ref, company, _ in skill.examples
    )
    width = round(100 * skill.share)
    return (
        '<div class="skill"><div class="skill-name">'
        f"<b>{e(skill.name)}</b>"
        f'<span class="muted">{e(skill.category)} · ex. {examples}</span></div>'
        f'<div class="bar-track"><div class="bar-fill" style="width:{width}%">'
        f'</div></div><span class="pts">{skill.share:.0%}</span>'
        f'<span class="spark">{_spark(skill.trend)}</span></div>'
    )


def insights_body(
    skills: list[SkillDemand], offers: int, min_relevance: int, source: str
) -> str:
    choices = "".join(
        f'<a class="seg{" on" if n == min_relevance else ""}" '
        f'href="/insights?relevance={n}">≥ {n}</a>'
        for n in RELEVANCE_CHOICES
    )
    head = (
        '<div class="pagehead"><div><h1>Compétences</h1>'
        f'<p class="muted">{offers} poste(s) pertinent(s) sur 90 jours · '
        f"profil lu depuis {e(source)} · aucun appel LLM</p></div>"
        f'<div class="segs" title="Pertinence minimum">'
        f'<span class="muted">Pertinence</span>{choices}</div></div>'
    )
    if not skills:
        return head + '<section class="muted">Pas encore assez d\'offres.</section>'
    missing = [s for s in skills if not s.covered][:15]
    covered = [s for s in skills if s.covered][:12]
    have = "".join(
        f'<span class="chip ok">{e(s.name)} · {s.share:.0%}</span>' for s in covered
    )
    return (
        head + "<section><h2>À développer</h2>"
        "<p class='muted'>Demandées par les offres, absentes du profil "
        f"(tendance sur {TREND_WEEKS} semaines à droite).</p>"
        + (
            f'<div class="skills">{"".join(_row(s) for s in missing)}</div>'
            or "<p class='muted'>Rien !</p>"
        )
        + f"</section><section><h2>Déjà dans ton profil</h2>{have}</section>"
    )
