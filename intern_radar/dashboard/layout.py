"""Shared page shell: mobile-first CSS, white theme with a blue brand header,
top navigation on desktop and a bottom bar on phones."""

import html
import re
import zlib

from intern_radar.dashboard import pwa
from intern_radar.dashboard.icons import icon

e = html.escape

# Leading emoji and symbols of a label ("✍️ Lettre" -> "Lettre"): buttons are
# plain text; Telegram keeps the emoji versions of the same labels.
_LEADING_SYMBOLS = re.compile(r"^[^\w«(]+")


def plain(label: str) -> str:
    return _LEADING_SYMBOLS.sub("", label)


ICON_EXTERNAL = icon("external", 16)
THUMB_UP = icon("thumb", 16)
THUMB_DOWN = icon("thumb", 16, "flip")

# Company monogram colours: soft tint, readable ink (WCAG AA on the tint).
_MONO = (
    ("#e8effa", "#1d4a8f"),
    ("#e9f4ef", "#1f6b46"),
    ("#fbefe6", "#9a4313"),
    ("#f1ecf9", "#5b3a9b"),
    ("#e7f3f6", "#17606f"),
    ("#fbecef", "#9b2c48"),
    ("#f4f1e6", "#6b5a14"),
    ("#eceff3", "#3d4a5c"),
)


def monogram(name: str, size: str = "") -> str:
    """Initials of a company in a tinted square, colour stable per name."""
    words = [w for w in re.split(r"[\s\-&.]+", name) if w[:1].isalnum()]
    initials = "".join(w[0] for w in words[:2]).upper() or "?"
    bg, ink = _MONO[zlib.crc32(name.lower().encode()) % len(_MONO)]
    css = f"mono {size}".strip()
    return (
        f'<span class="{css}" style="background:{bg};color:{ink}" '
        f'aria-hidden="true">{e(initials)}</span>'
    )


NAV = (
    ("offers", "/offers", "Offres", "briefcase"),
    ("applications", "/applications", "Candidatures", "list"),
    ("insights", "/insights", "Compétences", "compass"),
    ("stats", "/stats", "Stats", "chart"),
    ("more", "/more", "Plus", "more"),
)

CSS = """
:root { color-scheme:light;
  --bg:#fff; --card:#fff; --surface:#f7f6f5; --text:#2d2d2d; --muted:#595959;
  --subtle:#767676; --line:#e4e2e0; --line-strong:#d4d2d0; --field:#949494;
  --brand:#2557a7; --brand-dark:#164081; --brand-ink:#0d2d5e;
  --accent:#2557a7; --accent-hover:#164081; --accent2:#a9c1e8;
  --accent-soft:#eef3fb; --select:#f5f8fd; --on-accent:#fff;
  --warn:#a33f13; --warn-bg:#fdf0ea; --ok:#1f6b46; --ok-bg:#e9f4ef;
  --chip:#f3f2f1; --chip-text:#424242; --row:#faf9f8;
  --focus:rgba(37,87,167,.28);
  --shadow-1:0 1px 2px rgba(0,0,0,.06);
  --shadow-2:0 2px 8px rgba(0,0,0,.08), 0 1px 2px rgba(0,0,0,.04);
  --shadow-3:0 8px 28px rgba(13,45,94,.16);
  --radius:12px; --radius-sm:8px; }
* { box-sizing:border-box; }
html { background:var(--bg); -webkit-text-size-adjust:100%; }
body { margin:0; background:var(--bg); color:var(--text); overflow-x:clip;
  font:15px/1.5 "Noto Sans", -apple-system, BlinkMacSystemFont, "Segoe UI",
  Roboto, Helvetica, Arial, sans-serif; padding-bottom:72px;
  -webkit-font-smoothing:antialiased; text-rendering:optimizeLegibility; }
main { max-width:1040px; margin:0 auto; padding:24px 16px 48px; }
.ico { display:inline-block; vertical-align:-3px; flex:none; }
.ico.flip { transform:rotate(180deg); }

/* ---- Header ---- */
header.brand { background:var(--brand); color:#fff; position:sticky; top:0;
  z-index:30; box-shadow:0 1px 0 rgba(0,0,0,.08); }
.brand .bar { max-width:1040px; margin:0 auto; padding:0 16px; height:60px;
  display:flex; align-items:center; justify-content:space-between; gap:24px; }
.brand .logo { display:inline-flex; align-items:center; gap:10px; color:#fff;
  font-weight:600; font-size:17px; letter-spacing:-0.01em; }
.brand .logo:hover { color:#fff; }
.brand img { width:30px; height:30px; border-radius:8px;
  box-shadow:0 0 0 1px rgba(255,255,255,.25); }
.brand b { font-weight:800; }
nav.top { display:none; height:100%; gap:2px; }
nav.top a { position:relative; display:flex; align-items:center; gap:8px;
  height:100%; padding:0 14px; color:rgba(255,255,255,.78); font-size:14px;
  font-weight:600; }
nav.top a .ico { opacity:.85; }
nav.top a:hover { color:#fff; background:rgba(255,255,255,.06); }
nav.top a.active { color:#fff; }
nav.top a.active::after { content:""; position:absolute; left:14px; right:14px;
  bottom:0; height:3px; border-radius:3px 3px 0 0; background:#fff; }

/* ---- Type ---- */
h1 { font-size:26px; line-height:1.25; font-weight:700; margin:0 0 6px;
  letter-spacing:-0.02em; }
h2 { font-size:17px; line-height:1.35; font-weight:700; margin:0 0 12px;
  letter-spacing:-0.01em; }
h3 { font-size:15px; font-weight:700; margin:16px 0 8px; }
p { margin:0 0 10px; }
.muted { color:var(--muted); font-size:13px; }
a { color:var(--accent); text-decoration:none; }
a:hover { color:var(--accent-hover); text-decoration:underline;
  text-underline-offset:2px; }
.eyebrow { font-size:12px; font-weight:700; letter-spacing:.06em;
  text-transform:uppercase; color:var(--subtle); }
code { font:13px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace;
  background:var(--chip); padding:1px 5px; border-radius:4px; }

/* ---- Surfaces ---- */
section, .card { background:var(--card); border:1px solid var(--line);
  border-radius:var(--radius); padding:20px; margin:16px 0; overflow-x:auto; }
section > h2:first-child { margin-top:0; }
details > summary { cursor:pointer; list-style:none; display:flex;
  align-items:center; gap:8px; }
details > summary::-webkit-details-marker { display:none; }
details > summary::before { content:""; width:7px; height:7px; flex:none;
  border:solid var(--muted); border-width:0 2px 2px 0; transform:rotate(-45deg);
  transition:transform .15s; margin-right:4px; }
details[open] > summary::before { transform:rotate(45deg); }
ul { padding-left:20px; margin:6px 0; } li { margin:3px 0; }
hr { border:0; border-top:1px solid var(--line); margin:16px 0; }

/* ---- Page head ---- */
.pagehead { display:flex; flex-wrap:wrap; align-items:flex-end;
  justify-content:space-between; gap:12px; margin:4px 0 8px; }
.pagehead p { margin:0; }

/* ---- Hero search (offers) ---- */
.hero { background:var(--brand); color:#fff;
  margin:-24px calc(50% - 50vw) 0; padding:28px calc(50vw - 50%) 34px;
  background-image:radial-gradient(1200px 300px at 85% -40%,
    rgba(255,255,255,.12), transparent 60%); }
.hero-inner { margin:0 auto; }
.hero h1 { color:#fff; font-size:28px; margin-bottom:4px; }
.hero p { color:rgba(255,255,255,.82); font-size:14px; margin:0 0 18px; }
.searchbar { display:flex; align-items:stretch; background:#fff;
  border-radius:var(--radius); box-shadow:var(--shadow-3); padding:6px;
  gap:0; max-width:880px; }
.searchbar .field { display:flex; align-items:center; gap:10px; flex:1;
  padding:0 14px; min-width:0; color:var(--subtle); }
.searchbar .field + .field { border-left:1px solid var(--line); }
.searchbar .field.where { flex:0 0 240px; }
.searchbar input, .searchbar select { border:0; padding:12px 0; font-size:15px;
  background:transparent; box-shadow:none; color:var(--text); }
.searchbar input:focus, .searchbar select:focus { box-shadow:none; }
.searchbar button { padding:0 26px; font-size:15px; border-radius:var(--radius-sm); }
.filterbar { display:flex; flex-wrap:wrap; align-items:center; gap:8px;
  padding:14px 0; border-bottom:1px solid var(--line); }
.filterbar .lbl { display:inline-flex; align-items:center; gap:6px;
  color:var(--muted); font-size:13px; font-weight:600; margin-right:4px; }
.pill { position:relative; display:inline-flex; align-items:center; }
.pill select, .pill input { width:auto; appearance:none; -webkit-appearance:none;
  border:1px solid var(--line-strong); border-radius:999px; background:var(--card);
  padding:6px 32px 6px 14px; font-size:13px; font-weight:600; color:var(--text);
  cursor:pointer; }
.pill input { width:118px; padding-right:12px; cursor:text; }
.pill::after { content:""; position:absolute; right:14px; top:50%; width:6px;
  height:6px; margin-top:-5px; border:solid var(--muted); border-width:0 1.5px 1.5px 0;
  transform:rotate(45deg); pointer-events:none; }
.pill.num::after { display:none; }
.pill select:hover, .pill input:hover { border-color:var(--text); }
.pill.on select, .pill.on input { border-color:var(--brand); color:var(--brand);
  background:var(--accent-soft); }
.resultsbar { display:flex; flex-wrap:wrap; align-items:center;
  justify-content:space-between; gap:10px; margin:18px 0 6px; }
.resultsbar .count { font-size:14px; color:var(--muted); }
.resultsbar .count b { color:var(--text); }
.resultsbar .sort { display:flex; align-items:center; gap:8px; font-size:13px;
  color:var(--muted); }
.resultsbar .sort select { width:auto; border:0; padding:4px 2px; font-weight:700;
  font-size:14px; color:var(--text); background:transparent; cursor:pointer;
  field-sizing:content; }
.resultsbar .sort select:focus { box-shadow:none; text-decoration:underline; }
.alert-pop { position:relative; }
.alert-pop > summary { list-style:none; }
.alert-pop > summary::before { display:none; }
.alert-pop[open] > summary { background:var(--chip); }
.alert-pop .pop { position:absolute; right:0; top:calc(100% + 8px); z-index:15;
  width:320px; background:var(--card); border:1px solid var(--line);
  border-radius:var(--radius); box-shadow:var(--shadow-3); padding:16px; }
.alert-pop .pop p { font-size:13px; color:var(--muted); }

/* ---- Job cards ---- */
.card { display:block; color:inherit; position:relative; }
.list .card, .joblist .card { padding:18px 18px 12px; margin:12px 0;
  transition:box-shadow .15s, border-color .15s; }
.list .card:hover, .joblist .card:hover { box-shadow:var(--shadow-2);
  border-color:var(--line-strong); }
.card.sel { border-color:var(--brand); box-shadow:0 0 0 1px var(--brand),
  var(--shadow-2); }
.card.sel::before { content:""; position:absolute; left:-1px; top:14px; bottom:14px;
  width:4px; border-radius:0 4px 4px 0; background:var(--brand); }
.cardlink { display:block; color:inherit; }
.cardlink:hover { color:inherit; text-decoration:none; }
.job { display:flex; gap:14px; align-items:flex-start; }
.job-main { flex:1; min-width:0; }
.card .title { font-weight:700; font-size:16px; line-height:1.35; margin:0 0 2px;
  color:var(--text); }
.cardlink:hover .title { text-decoration:underline; text-underline-offset:2px; }
.company { font-size:14px; color:var(--text); display:flex; align-items:center;
  gap:6px; flex-wrap:wrap; }
.loc { font-size:14px; color:var(--muted); display:flex; align-items:center;
  gap:6px; margin-top:2px; }
.loc .ico { color:var(--subtle); }
.tags { display:flex; flex-wrap:wrap; gap:6px; margin-top:12px; }
.tag { display:inline-flex; align-items:center; gap:5px; background:var(--chip);
  color:var(--chip-text); border-radius:6px; padding:3px 9px; font-size:12.5px;
  font-weight:600; line-height:1.5; }
.tag .ico { width:14px; height:14px; color:var(--subtle); }
.tag.blue { background:var(--accent-soft); color:var(--brand-dark); }
.tag.blue .ico { color:var(--brand); }
.tag.ok { background:var(--ok-bg); color:var(--ok); }
.tag.warn { background:var(--warn-bg); color:var(--warn); }
.tier { display:inline-flex; align-items:center; justify-content:center;
  height:20px; min-width:20px; padding:0 6px; border-radius:5px; font-size:11px;
  font-weight:800; letter-spacing:.02em; border:1px solid var(--line-strong);
  color:var(--muted); background:var(--card); }
.tier.t-S { border-color:var(--brand); color:var(--brand); }
.new { display:inline-flex; font-size:11.5px; font-weight:700; color:var(--ok);
  background:var(--ok-bg); padding:1px 7px; border-radius:5px; }
.foot { display:flex; align-items:center; justify-content:space-between;
  gap:10px; margin-top:12px; padding-top:10px; border-top:1px solid var(--line); }
.age { display:inline-flex; align-items:center; gap:6px; font-size:12.5px;
  color:var(--subtle); }
.age .ico { width:14px; height:14px; }

/* Monogram */
.mono { display:inline-flex; align-items:center; justify-content:center; flex:none;
  width:44px; height:44px; border-radius:10px; font-weight:800; font-size:15px;
  letter-spacing:.02em; }
.mono.lg { width:56px; height:56px; border-radius:12px; font-size:19px; }

/* Score badge */
.score { display:inline-flex; flex-direction:column; align-items:center;
  justify-content:center; flex:none; min-width:52px; padding:5px 8px;
  border-radius:10px; background:var(--chip); color:var(--text); font-weight:800;
  font-size:17px; line-height:1.1; white-space:nowrap; height:fit-content; }
.score small { font-size:10px; font-weight:700; color:var(--subtle);
  letter-spacing:.04em; text-transform:uppercase; margin-top:2px; }
.score.hi { background:var(--accent-soft); color:var(--brand-dark);
  box-shadow:inset 0 0 0 1px var(--accent2); }
.score.hi small { color:var(--brand); }
.score.xl { min-width:72px; font-size:26px; padding:8px 12px; border-radius:12px; }

/* Votes */
.votes { display:flex; gap:4px; }
button.vote { background:transparent; color:var(--subtle); padding:6px;
  border:1px solid transparent; border-radius:8px; }
button.vote:hover { background:var(--chip); color:var(--text);
  border-color:transparent; }
button.vote.on { color:var(--brand); background:var(--accent-soft); }
button.vote svg { width:17px; height:17px; }

/* ---- Buttons ---- */
button, .button { display:inline-flex; align-items:center; justify-content:center;
  gap:8px; background:var(--accent); color:var(--on-accent);
  border:1px solid var(--accent); border-radius:var(--radius-sm); padding:9px 18px;
  font:inherit; font-size:14px; font-weight:700; line-height:1.3; cursor:pointer;
  white-space:nowrap; text-decoration:none; transition:background .12s,
  border-color .12s, color .12s; }
button:hover, .button:hover { background:var(--accent-hover);
  border-color:var(--accent-hover); color:var(--on-accent); text-decoration:none; }
button:active, .button:active { transform:translateY(1px); }
button.ghost, .button.ghost { background:var(--card); color:var(--text);
  border-color:var(--line-strong); }
button.ghost:hover, .button.ghost:hover { background:var(--surface);
  border-color:var(--field); color:var(--text); }
button.sm, .button.sm { padding:6px 12px; font-size:13px; }
button:disabled, button:disabled:hover { background:var(--chip);
  border-color:var(--line); color:var(--subtle); cursor:default; transform:none; }
button:focus-visible, .button:focus-visible, a:focus-visible, summary:focus-visible {
  outline:none; box-shadow:0 0 0 3px var(--focus); }
form.inline { display:inline; }
.actions { display:flex; flex-wrap:wrap; gap:8px; margin-top:12px; }

/* ---- Forms ---- */
.filters { display:grid; grid-template-columns:repeat(auto-fit, minmax(160px, 1fr));
  gap:12px; }
input, select, textarea { width:100%; padding:10px 12px;
  border-radius:var(--radius-sm); border:1px solid var(--field);
  background:var(--card); color:var(--text); font:inherit; font-size:15px; }
input:hover, select:hover, textarea:hover { border-color:var(--text); }
input:focus, select:focus, textarea:focus { outline:none;
  border-color:var(--accent); box-shadow:0 0 0 3px var(--focus); }
input[type=checkbox], input[type=radio] { width:auto; accent-color:var(--accent);
  margin-right:6px; }
textarea { min-height:96px; resize:vertical; line-height:1.5; }
label { font-size:13px; font-weight:700; color:var(--text); display:block;
  margin-bottom:4px; }

/* ---- Data ---- */
.tiles { display:grid; grid-template-columns:repeat(auto-fit, minmax(170px, 1fr));
  gap:12px; margin:16px 0; }
.tile { background:var(--card); border:1px solid var(--line);
  border-radius:var(--radius); padding:16px 18px; display:flex;
  flex-direction:column-reverse; gap:4px; }
.tile b { display:block; font-size:28px; line-height:1.1; font-weight:800;
  letter-spacing:-0.02em; color:var(--text); }
.tile span { color:var(--muted); font-size:13px; font-weight:600; }
.tile:first-child { background:var(--brand); border-color:var(--brand); }
.tile:first-child b { color:#fff; }
.tile:first-child span { color:rgba(255,255,255,.82); }
table { border-collapse:separate; border-spacing:0; width:100%; font-size:14px; }
th, td { text-align:left; padding:11px 12px; border-bottom:1px solid var(--line);
  white-space:nowrap; vertical-align:middle; }
th { color:var(--subtle); font-weight:700; font-size:11.5px; text-transform:uppercase;
  letter-spacing:.06em; background:var(--surface); border-bottom-color:var(--line); }
th:first-child { border-top-left-radius:8px; }
th:last-child { border-top-right-radius:8px; }
tbody tr:hover td, tr:hover > td { background:var(--row); }
tr:last-child > td { border-bottom:0; }
td.n, th.n { text-align:right; font-variant-numeric:tabular-nums; }
.warn { color:var(--warn); font-weight:600; } .ok { color:var(--ok); }
.chip { display:inline-flex; align-items:center; gap:5px; background:var(--chip);
  border-radius:6px; padding:3px 9px; margin:4px 6px 0 0; font-size:12.5px;
  font-weight:600; color:var(--chip-text); }
.chip.warn { color:var(--warn); background:var(--warn-bg); }
.chip.ok { color:var(--ok); background:var(--ok-bg); }
.run { display:flex; flex-wrap:wrap; gap:12px; align-items:center;
  justify-content:space-between; }
.notice { display:flex; gap:10px; align-items:center; background:var(--accent-soft);
  border:1px solid var(--accent2); border-radius:var(--radius-sm);
  padding:12px 16px; margin:0 0 16px; font-size:14px; color:var(--brand-ink); }
.notice::before { content:""; width:8px; height:8px; border-radius:50%; flex:none;
  background:var(--brand); }
.pager { display:flex; justify-content:space-between; align-items:center;
  margin:20px 0; }
.pager a { font-weight:700; }
.columns { display:grid; grid-template-columns:repeat(auto-fit, minmax(240px, 1fr));
  gap:12px; }
.columns > * { margin:0; }
svg text { fill:var(--subtle); font-size:11px; }

/* ---- Skills ---- */
.skills { display:grid; gap:4px; margin-top:8px; }
.skill { display:grid; grid-template-columns:minmax(180px, 2fr) 3fr 48px 60px;
  gap:16px; align-items:center; padding:12px 0; border-bottom:1px solid var(--line); }
.skill:last-child { border-bottom:0; }
.skill-name { display:flex; flex-direction:column; min-width:0; }
.skill .pts { text-align:right; font-weight:800; font-variant-numeric:tabular-nums; }
.skill .spark { display:flex; justify-content:flex-end; }
.segs { display:inline-flex; align-items:center; gap:4px; }
.segs .muted { margin-right:6px; font-weight:600; }
.seg { padding:5px 12px; border-radius:99px; border:1px solid var(--line-strong);
  font-size:13px; font-weight:700; color:var(--text); }
.seg:hover { border-color:var(--text); text-decoration:none; color:var(--text); }
.seg.on { background:var(--brand); border-color:var(--brand); color:#fff; }
@media (max-width:640px) {
  .skill { grid-template-columns:1fr 44px; }
  .skill .bar-track { grid-column:1 / -1; grid-row:2; }
  .skill .spark { display:none; }
}

/* ---- Tile links (Plus) ---- */
.tilegrid { display:grid; grid-template-columns:repeat(auto-fill, minmax(300px, 1fr));
  gap:12px; margin-top:16px; }
.card.tilelink { display:flex; align-items:center; gap:14px; margin:0;
  padding:18px; transition:box-shadow .15s, border-color .15s; }
.card.tilelink:hover { text-decoration:none; box-shadow:var(--shadow-2);
  border-color:var(--line-strong); }
.card.tilelink > span:nth-child(2) { flex:1; min-width:0; }
.card.tilelink .title { display:block; font-size:15px; }
.card.tilelink .muted { display:block; }
.tl-ico { display:inline-flex; align-items:center; justify-content:center;
  width:44px; height:44px; border-radius:10px; flex:none;
  background:var(--accent-soft); color:var(--brand); }
.tl-go { color:var(--subtle); }
.card.tilelink:hover .tl-go { color:var(--brand); }

/* ---- Applications board ---- */
body:has(.board) main, body:has(.board) .brand .bar { max-width:1320px; }
.board { display:grid; grid-auto-flow:column; grid-auto-columns:minmax(230px, 1fr);
  gap:12px; overflow-x:auto; padding-bottom:6px; margin:16px 0; }
.lane { background:var(--surface); border-radius:var(--radius); padding:12px;
  min-height:140px; }
.lane-head { display:flex; align-items:center; justify-content:space-between;
  font-size:13px; font-weight:800; text-transform:uppercase; letter-spacing:.05em;
  color:var(--muted); padding:2px 4px 10px; }
.lane-head .count { background:var(--card); border:1px solid var(--line);
  border-radius:99px; padding:0 9px; font-size:12px; color:var(--text); }
.lane .empty { font-size:13px; color:var(--subtle); text-align:center;
  padding:18px 0; margin:0; }
.card.bcard { padding:14px; margin:0 0 10px; box-shadow:var(--shadow-1); }
.card.bcard:hover { box-shadow:var(--shadow-2); text-decoration:none; }
.card.bcard .age { margin-top:4px; white-space:nowrap; }
.card.bcard .title { font-size:14.5px; }
.card.bcard .score { min-width:44px; font-size:15px; padding:4px 6px; }
.card.bcard .tags { margin-top:10px; }
.card.bcard:hover .title { text-decoration:underline; }

/* ---- Offer detail ---- */
.dh { display:flex; gap:16px; align-items:flex-start; }
.dh-main { flex:1; min-width:0; }
.dh h1 { font-size:24px; margin:2px 0 6px; }
.dh .company a { color:var(--text); font-weight:600; }
.dh .company a:hover { color:var(--accent); }
.dh-actions { display:flex; flex-wrap:wrap; align-items:center; gap:8px;
  margin-top:16px; }
.dh-actions .actions { margin:0; }
.track { display:flex; flex-wrap:wrap; align-items:center; gap:6px; margin-top:12px;
  font-size:13px; color:var(--muted); }
.track .actions { margin:0; gap:6px; }
.track button { padding:5px 11px; font-size:13px; font-weight:600; }
.lead { font-size:15px; color:var(--text); background:var(--surface);
  border-left:3px solid var(--brand); padding:12px 16px; border-radius:0 8px 8px 0;
  margin:0 0 16px; }
.facts { display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr));
  gap:14px 24px; margin:0; }
.fact { display:flex; gap:12px; align-items:flex-start; }
.fact .ico { color:var(--brand); margin-top:2px; }
.fact dt { font-size:12px; font-weight:700; color:var(--subtle);
  text-transform:uppercase; letter-spacing:.05em; }
.fact dd { margin:1px 0 0; font-size:14px; }
.bars { display:grid; gap:12px; }
.bar-row { display:grid; grid-template-columns:130px 1fr 52px; gap:12px;
  align-items:center; font-size:14px; }
.bar-row .name { font-weight:600; }
.bar-row .detail { grid-column:2; font-size:12.5px; color:var(--muted);
  margin-top:-8px; }
.bar-track { height:8px; border-radius:99px; background:var(--chip); overflow:hidden; }
.bar-fill { height:100%; border-radius:99px; background:var(--brand); }
.bar-fill.neg { background:var(--warn); }
.bar-row .pts { text-align:right; font-weight:700; font-variant-numeric:tabular-nums; }
.bar-total { display:flex; justify-content:space-between; align-items:center;
  border-top:1px solid var(--line); padding-top:12px; margin-top:4px;
  font-weight:800; }
.meter { height:10px; border-radius:99px; background:var(--chip); overflow:hidden;
  margin:8px 0 12px; }
.meter > span { display:block; height:100%; background:var(--brand);
  border-radius:99px; }
.reasons { display:grid; gap:6px; font-size:14px; }
.reasons div { display:flex; gap:8px; align-items:flex-start; }
.reasons .ico { margin-top:2px; }
.reasons .pos .ico { color:var(--ok); } .reasons .neg .ico { color:var(--warn); }
table.breakdown td:nth-child(2) { white-space:normal; color:var(--muted); }

/* ---- Split view (offers) ---- */
.split { display:block; }
.pane { display:none; }

/* ---- Bottom nav (phones) ---- */
nav.bottom { position:fixed; left:0; right:0; bottom:0; background:var(--card);
  border-top:1px solid var(--line); display:flex; justify-content:space-around;
  padding:6px 0 calc(6px + env(safe-area-inset-bottom)); z-index:30;
  box-shadow:0 -2px 10px rgba(0,0,0,.04); }
nav.bottom a { color:var(--subtle); font-size:11px; font-weight:600;
  text-align:center; flex:1; display:flex; flex-direction:column;
  align-items:center; gap:2px; padding:2px 0; }
nav.bottom a:hover { text-decoration:none; }
nav.bottom a.active { color:var(--brand); }

@media (max-width:640px) {
  h1 { font-size:22px; }
  .hero { padding-top:20px; padding-bottom:22px; }
  .hero h1 { font-size:22px; }
  .searchbar { flex-direction:column; padding:4px; }
  .searchbar .field + .field { border-left:0; border-top:1px solid var(--line); }
  .searchbar .field.where { flex:1; }
  .searchbar button { padding:12px; margin:4px; }
  .filterbar { flex-wrap:nowrap; overflow-x:auto; margin:0 -16px; padding:12px 16px;
    scrollbar-width:none; }
  .filterbar .lbl { display:none; }
  section, .card { padding:16px; }
  .alert-pop .pop { width:min(320px, calc(100vw - 32px)); }
  .bar-row { grid-template-columns:96px 1fr 44px; }
  .dh .mono.lg { display:none; }
  .dh h1 { font-size:21px; }
  .score.xl { min-width:60px; font-size:21px; }
  .dh-actions > .button:first-child { flex:1 1 100%; padding:12px; }
}
@media (min-width:760px) {
  body { padding-bottom:0; }
  nav.top { display:flex; }
  nav.bottom { display:none; }
}
@media (min-width:900px) {
  body:has(.split) main, body:has(.split) .brand .bar { max-width:1240px; }
  .split { display:grid; grid-template-columns:minmax(360px, 5fr) 7fr; gap:24px;
    align-items:start; }
  .pane { display:block; position:sticky; top:76px; margin:12px 0;
    max-height:calc(100vh - 92px); overflow-y:auto; background:var(--card);
    border:1px solid var(--line); border-radius:var(--radius);
    box-shadow:var(--shadow-1); padding:0; scrollbar-width:thin; }
  .pane.loading { opacity:.55; transition:opacity .1s; }
  .pane .back { display:none; }
  .pane .dhead { padding:24px 24px 20px; border-bottom:1px solid var(--line); }
  .pane section { border:0; border-radius:0; padding:22px 24px; margin:0;
    box-shadow:none; }
  .pane section + section { border-top:1px solid var(--line); }
}
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
        f"{icon(glyph, 22)}{e(label)}</a>"
        for key, href, label, glyph in NAV
    )
    top = "".join(
        f'<a href="{href}" class="{"active" if key == active else ""}">'
        f"{icon(glyph, 18)}{e(label)}</a>"
        for key, href, label, glyph in NAV
    )
    banner = f'<div class="notice">{e(notice)}</div>' if notice else ""
    return (
        '<!doctype html><html lang="fr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1, '
        'viewport-fit=cover">'
        f"{meta}{HEAD_EXTRA}<title>{e(title)} · intern-radar</title>"
        f"<style>{CSS}</style></head><body>{_brand(top)}<main>{banner}{body}</main>"
        f'<nav class="bottom">{links}</nav></body></html>'
    )


# The logo mark and the word mark, white on the brand blue (bold "radar").
# Desktop gets the navigation in the header; phones keep the bottom bar.
def _brand(links: str) -> str:
    return (
        '<header class="brand"><div class="bar"><a class="logo" href="/offers">'
        '<img src="/icon-192.png" alt="" width="30" height="30">'
        "<span>intern-<b>radar</b></span></a>"
        f'<nav class="top">{links}</nav></div></header>'
    )


# Manifest, icons and service worker registration (installable app).
HEAD_EXTRA = pwa.HEAD
