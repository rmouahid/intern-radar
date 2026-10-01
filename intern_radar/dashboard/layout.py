"""Shared page shell: mobile-first CSS, light/dark themes, bottom navigation."""

import html

e = html.escape

NAV = (
    ("offers", "/offers", "Offres", "🔎"),
    ("applications", "/applications", "Candidatures", "📋"),
    ("insights", "/insights", "Compétences", "🧭"),
    ("stats", "/stats", "Stats", "📊"),
    ("more", "/more", "Plus", "⋯"),
)

CSS = """
:root { --bg:#f6f6f4; --card:#fff; --text:#1d1d1f; --muted:#6b6b70;
  --line:#e3e3e0; --accent:#2f6fde; --accent2:#9bb8ef; --warn:#c2410c;
  --ok:#15803d; --chip:#eef2fb; }
@media (prefers-color-scheme: dark) { :root { --bg:#141416; --card:#1e1e21;
  --text:#ececec; --muted:#9a9aa0; --line:#2e2e33; --accent:#6c9bf0;
  --accent2:#34507f; --warn:#fb923c; --ok:#4ade80; --chip:#262a33; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text);
  font:15px/1.45 -apple-system, "Segoe UI", Roboto, sans-serif;
  padding-bottom:76px; }
main { max-width:960px; margin:0 auto; padding:14px; }
h1 { font-size:21px; margin:6px 0 4px; } h2 { font-size:16px; margin:0 0 10px; }
.muted { color:var(--muted); font-size:13px; }
section, .card { background:var(--card); border:1px solid var(--line);
  border-radius:14px; padding:14px; margin:12px 0; overflow-x:auto; }
.card { display:block; color:inherit; }
.cardlink { display:block; color:inherit; }
.votes { display:flex; gap:6px; justify-content:flex-end; margin-top:6px; }
button.vote { background:var(--chip); color:var(--text); padding:4px 12px;
  font-size:16px; opacity:.55; }
button.vote.on { opacity:1; outline:2px solid var(--accent); }
.card .top { display:flex; justify-content:space-between; gap:8px; }
.card .title { font-weight:600; margin:2px 0; }
.score { font-weight:700; font-size:17px; white-space:nowrap; }
.chip { display:inline-block; background:var(--chip); border-radius:999px;
  padding:2px 9px; margin:4px 4px 0 0; font-size:12px; color:var(--text); }
.chip.warn { color:var(--warn); } .chip.ok { color:var(--ok); }
.tiles { display:grid; grid-template-columns:repeat(auto-fit, minmax(140px, 1fr));
  gap:10px; }
.tile { background:var(--card); border:1px solid var(--line); border-radius:12px;
  padding:12px; }
.tile b { display:block; font-size:24px; } .tile span { color:var(--muted);
  font-size:13px; }
table { border-collapse:collapse; width:100%; font-size:14px; }
th, td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--line);
  white-space:nowrap; }
th { color:var(--muted); font-weight:600; } td.n, th.n { text-align:right; }
.warn { color:var(--warn); font-weight:600; } .ok { color:var(--ok); }
a { color:var(--accent); text-decoration:none; }
.run { display:flex; flex-wrap:wrap; gap:12px; align-items:center;
  justify-content:space-between; }
button, .button { background:var(--accent); color:#fff; border:0;
  border-radius:10px; padding:9px 16px; font-size:15px; font-weight:600;
  cursor:pointer; display:inline-block; }
button.ghost, .button.ghost { background:var(--chip); color:var(--text); }
button:disabled { opacity:.5; cursor:default; }
form.inline { display:inline; }
.actions { display:flex; flex-wrap:wrap; gap:8px; margin-top:10px; }
.filters { display:grid; grid-template-columns:repeat(auto-fit, minmax(140px, 1fr));
  gap:8px; }
input, select, textarea { width:100%; padding:8px 10px; border-radius:10px;
  border:1px solid var(--line); background:var(--card); color:var(--text);
  font:inherit; }
textarea { min-height:90px; }
label { font-size:13px; color:var(--muted); display:block; }
.notice { background:var(--card); border:1px solid var(--accent);
  border-radius:12px; padding:10px 14px; margin:12px 0; }
.pager { display:flex; justify-content:space-between; margin:12px 0; }
.columns { display:grid; grid-template-columns:repeat(auto-fit, minmax(230px, 1fr));
  gap:10px; }
nav.bottom { position:fixed; left:0; right:0; bottom:0; background:var(--card);
  border-top:1px solid var(--line); display:flex; justify-content:space-around;
  padding:6px 0 calc(6px + env(safe-area-inset-bottom)); z-index:10; }
nav.bottom a { color:var(--muted); font-size:11px; text-align:center;
  flex:1; }
nav.bottom a span { display:block; font-size:19px; }
nav.bottom a.active { color:var(--accent); font-weight:600; }
table.breakdown td:nth-child(2) { white-space:normal; color:var(--muted); }
svg text { fill:var(--muted); font-size:11px; }
"""


def page(
    title: str,
    body: str,
    active: str = "",
    notice: str | None = None,
    refresh: int | None = None,
) -> str:
    """A complete HTML page with the shared CSS and the bottom navigation."""
    meta = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    links = "".join(
        f'<a href="{href}" class="{"active" if key == active else ""}">'
        f"<span>{icon}</span>{e(label)}</a>"
        for key, href, label, icon in NAV
    )
    banner = f'<div class="notice">{e(notice)}</div>' if notice else ""
    return (
        '<!doctype html><html lang="fr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1, '
        'viewport-fit=cover">'
        f"{meta}{HEAD_EXTRA}<title>{e(title)} · intern-radar</title>"
        f"<style>{CSS}</style></head><body><main>{banner}{body}</main>"
        f'<nav class="bottom">{links}</nav></body></html>'
    )


# Filled by the installable-app issue (manifest, icons); empty until then.
HEAD_EXTRA = ""
