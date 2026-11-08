"""Render results as a simple, self-contained, sortable web page.

Kept separate from the calculation code so a future server can call
render_html(results, meta) and return the same page.
"""
from __future__ import annotations

import html
import json

PAGE_SIZE = 20


def _qty(q: float) -> str:
    return f"{q:g}"


def _io(r) -> str:
    ins = " + ".join(f"{_qty(q)} {n}" for n, q in r.inputs.items())
    outs = " + ".join(f"{_qty(q)} {n}" for n, q in r.outputs.items())
    return f"{ins} → {outs}"


def _rows(results, refs=None) -> list[dict]:
    from ge_profit import reference_for
    return [{
        "recipe": r.recipe.name,
        "io": _io(r.recipe),
        "inputs": [[q, n] for n, q in r.recipe.inputs.items()],
        "outputs": [[q, n] for n, q in r.recipe.outputs.items()],
        "skill": r.recipe.skill,
        "cost": r.cost,
        "revenue": r.revenue,
        "profit": r.profit,
        "xp": r.recipe.xp,
        "gp_per_xp": r.gp_per_xp,
        "actions_per_limit": r.actions_per_limit,
        "min_volume": r.min_volume,
        "volume_actions": r.volume_actions,
        "speed": r.speed,
        "ref_xp": reference_for(r.recipe, refs or {}),
    } for r in results]


def render_html(results, meta: dict) -> str:
    refs = meta.get("references") or {}
    ref_note = ("<p class='note'>XP pace = this hour's XP (same limits as GP/hr) as a % of an hour of your "
                "normal training method: " + html.escape("; ".join(
                    f"{s} = {v['method']} ({v['xp_per_hour']:,.0f} xp/hr)" for s, v in sorted(refs.items())))
                + ". Change these under [normal_training] in recipes.toml.</p>") if refs else ""
    data = json.dumps(_rows(results, refs)).replace("</", "<\\/")
    skipped = meta.get("skipped") or 0
    skipped_note = (f"<p class='note'>{skipped:,} more recipes not shown: an item isn't on the GE "
                    "or has no recent price.</p>" if skipped else "")
    info = (f"Prices: {html.escape(meta.get('source', ''))} · mode: {html.escape(meta.get('mode', ''))}"
            f" · GE tax {'on' if meta.get('tax', True) else 'off'} · updated <time id='gen' datetime='{html.escape(meta.get('generated', ''))}'>{html.escape(meta.get('generated', ''))}</time>")
    return TEMPLATE.replace("__DATA__", data).replace("__INFO__", info) \
                   .replace("__SKIPPED__", skipped_note + ref_note).replace("__PAGE_SIZE__", str(PAGE_SIZE)) \
                   .replace("__MIN_VOL__", str(int(meta.get("min_volume", 100)))) \
                   .replace("__SHARE__", f"{100 * meta.get('market_share', 0.1):g}")


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GE Production Profits</title>
<style>
  /* Light: OSRS Wiki parchment. Dark: in-game interface (brown stone, orange text). */
  :root { color-scheme: light dark;
          --bg: #d8ccb4; --panel: #e2dbc8; --fg: #3a2f1e; --muted: #6e5f47;
          --line: #b8a888; --frame: #94866d; --head: #c0a886; --head-fg: #3a2f1e;
          --zebra: #ebe4d3; --title: #6b3f1c; --accent: #936039;
          --pos: #1d6b16; --neg: #a8221a; --input: #f3eee2; }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) { color-scheme: dark;
            --bg: #2b241b; --panel: #3e3529; --fg: #e6d6b0; --muted: #a8977a;
            --line: #2b241b; --frame: #1e1912; --head: #2b241b; --head-fg: #ff981f;
            --zebra: #463c2f; --title: #ff981f; --accent: #ffff00;
            --pos: #30d030; --neg: #ff4a3d; --input: #2b241b; }
  }
  :root[data-theme="dark"] { color-scheme: dark;
            --bg: #2b241b; --panel: #3e3529; --fg: #e6d6b0; --muted: #a8977a;
            --line: #2b241b; --frame: #1e1912; --head: #2b241b; --head-fg: #ff981f;
            --zebra: #463c2f; --title: #ff981f; --accent: #ffff00;
            --pos: #30d030; --neg: #ff4a3d; --input: #2b241b; }
  :root[data-theme="light"] { color-scheme: light; }
  /* Text font (switchable); numbers always use the monospace font so digits align. */
  :root { --num-font: ui-monospace, Menlo, Consolas, monospace;
          --text-font: "Segoe UI", system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif; }
  :root[data-font="mono"] { --text-font: var(--num-font); }
  body { font: 14px/1.45 var(--text-font); color: var(--fg);
         background: var(--bg); margin: 0; padding: 24px 16px; }
  h1 { font: 700 22px/1.2 Georgia, "Times New Roman", serif; color: var(--title); margin: 0 0 6px;
       letter-spacing: 0.02em; }
  .note { color: var(--muted); margin: 0 0 12px; }
  .wrap { overflow-x: auto; border: 2px solid var(--frame); border-radius: 3px;
          box-shadow: inset 0 0 0 1px var(--line); }
  /* Fixed layout: column widths never depend on what's on the current page. */
  table { font-family: var(--num-font); border-collapse: collapse; table-layout: fixed;
          width: calc(144ch + 13 * 16px);
          min-width: 100%; background: var(--panel); }
  td { overflow: hidden; text-overflow: ellipsis; }
  tbody tr:nth-child(even) { background: var(--zebra); }
  th, td { padding: 5px 8px; border-bottom: 1px solid var(--line); white-space: nowrap; }
  th { white-space: normal; vertical-align: bottom; }
  td.l { white-space: normal; overflow-wrap: anywhere; }
  /* Collapsed: every cell on one line, so all rows are the same height. */
  table.collapsed td, table.collapsed td.l { white-space: nowrap; overflow-wrap: normal; }
  table.collapsed tbody tr { height: 34px; }
  .ing { display: grid; grid-template-columns: auto 1fr; gap: 1px 8px; margin-top: 3px;
         font-size: 12px; color: var(--muted); }
  .ing .k { font-weight: 700; color: var(--fg); opacity: 0.7; }
  .ing .q { text-align: right; padding-right: 4px; }
  .ing ul { list-style: none; margin: 0; padding: 0; }
  .ing li { display: grid; grid-template-columns: 6ch 1fr; }
  th { background: var(--head); color: var(--head-fg); text-align: right; font-weight: 700;
       border-bottom: 2px solid var(--frame); }
  td { text-align: right; font-variant-numeric: tabular-nums; }
  th.l, td.l { text-align: left; }
  th.sort { cursor: pointer; text-decoration: underline dotted; }
  th.active { text-decoration: underline; color: var(--accent); }
  .pos { color: var(--pos); } .neg { color: var(--neg); } .na { color: var(--muted); }
  .io { color: var(--muted); font-size: 12px; }
  .acct { display: flex; justify-content: space-between; gap: 0.6em; }

  select, input { font: inherit; color: var(--fg); background: var(--input);
                  border: 1px solid var(--frame); border-radius: 2px; padding: 1px 4px; }
  .top { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
  th, td.l { font-family: var(--text-font); }
  input[type="number"] { font-family: var(--num-font); }
  .pager { margin: 12px 0; display: flex; gap: 12px; align-items: center; }
  button { font: inherit; padding: 3px 12px; color: var(--head-fg); background: var(--head);
           border: 2px solid var(--frame); border-radius: 3px; cursor: pointer; }
  button:disabled { opacity: 0.45; cursor: default; }
  .navbtn { display: inline-block; padding: 3px 12px; color: var(--head-fg); background: var(--head);
            border: 2px solid var(--frame); border-radius: 3px; text-decoration: none; }
</style>
</head>
<body>
<div class="top"><h1>GE production profits</h1>
<span><a class="navbtn" href="chain/">Supply chains</a>
<button id="font" type="button" title="Switch text font">Aa Mono</button>
<button id="theme" type="button" title="Switch light/dark">☾ Dark</button></span></div>
<p class="note">__INFO__</p>
<p class="note">Click GP/hr, XP/hr, GP/action, GP/XP or GP/4h to sort. GP/hr = profit over the next hour: actions are limited by production speed (Wiki ticks + a bank trip per inventory; S), one full buy limit (L) or your market share of an hour's volume (V). Recipes without usable timing data (e.g. runecrafting) show — unless a speed is set in recipes.toml. GP/4h = GP/action × actions per 4-hour buy-limit window, where actions are capped by the inputs' buy limits and by your market share of each item's trading volume (* = volume is the tighter cap). Min vol/hr = trades in the last hour of the recipe's least-traded item; thinly traded items have unreliable prices.</p>
__SKIPPED__
<p><label>Skill: <select id="skill"><option value="">All</option></select></label>
&nbsp;&nbsp;<label><input type="checkbox" id="zeroxp"> Include 0-XP recipes</label>
&nbsp;&nbsp;<label><input type="checkbox" id="showing"> Show ingredients</label>
&nbsp;&nbsp;<label>Min volume/hr: <input type="number" id="minvol" min="0" step="10" value="__MIN_VOL__" style="width:7em"></label>
&nbsp;&nbsp;<label>Market share %: <input type="number" id="share" min="1" max="100" step="5" value="__SHARE__" style="width:5em"></label>
&nbsp;&nbsp;<label>Min XP pace %: <input type="number" id="minpace" min="0" step="10" value="0" style="width:5em"></label></p>
<div class="pager"><button id="prev">← Prev</button><span id="pageinfo"></span><button id="next">Next →</button></div>
<div class="wrap"><table id="tbl" class="collapsed">
<colgroup>
  <col style="width:5ch"><col style="width:28ch"><col style="width:13ch">
  <col style="width:12ch"><col style="width:10ch"><col style="width:6ch"><col style="width:9ch">
  <col style="width:10ch"><col style="width:8ch"><col style="width:11ch"><col style="width:10ch">
  <col style="width:8ch"><col style="width:14ch">
</colgroup>
<thead><tr>
  <th>#</th><th class="l">Recipe</th><th class="l">Skill</th>
  <th class="sort" data-key="gp_per_hour" title="Profit you can make in the next hour">GP/hr</th>
  <th class="sort" data-key="xp_per_hour">XP/hr</th>
  <th class="sort" data-key="xp_pace" title="This hour's XP as a % of an hour of your normal training method for the skill">XP pace</th>
  <th title="Feasible actions in the next hour. Bound by: S = production speed, L = one full buy limit, V = your market share of an hour's volume">Actions/hr</th>
  <th class="sort" data-key="profit" title="Hover a value for cost and revenue">GP/action</th><th>XP</th>
  <th class="sort" data-key="gp_per_xp">GP/XP</th>
  <th title="Hourly trades of the least-traded item in the recipe">Min vol/hr</th><th title="Actions per 4-hour window: the lower of the buy limits and your market share of trading volume (* = volume is the limit)">Actions/4h</th><th class="sort" data-key="gp_per_limit">GP/4h</th>
</tr></thead>
<tbody id="rows"></tbody>
</table></div>
<script>
// Theme: start from the saved choice, else the OS setting; the button flips it.
const root = document.documentElement, themeBtn = document.getElementById("theme");
const osDark = () => window.matchMedia("(prefers-color-scheme: dark)").matches;
let theme = null;
try { theme = localStorage.getItem("ge-theme"); } catch (e) {}
function applyTheme() {
  const t = theme || (osDark() ? "dark" : "light");
  root.dataset.theme = t;
  themeBtn.textContent = t === "dark" ? "☀ Light" : "☾ Dark";
}
// Font: sans-serif text by default; the button switches to all-monospace (remembered).
const fontBtn = document.getElementById("font");
let font = "sans";
try { font = localStorage.getItem("ge-font") || "sans"; } catch (e) {}
function applyFont() {
  root.dataset.font = font;
  fontBtn.textContent = font === "mono" ? "Aa Sans" : "Aa Mono";
}
fontBtn.onclick = () => {
  font = font === "mono" ? "sans" : "mono";
  try { localStorage.setItem("ge-font", font); } catch (e) {}
  applyFont();
};
applyFont();
// Show when prices were fetched in the viewer's own time zone, and how long ago.
const gen = document.getElementById("gen");
if (gen && !isNaN(Date.parse(gen.dateTime))) {
  const d = new Date(gen.dateTime), mins = Math.round((Date.now() - d) / 60000);
  const ago = mins < 1 ? "just now" : mins < 60 ? `${mins} min ago` : mins < 1440 ? `${Math.round(mins / 60)} h ago` : `${Math.round(mins / 1440)} days ago`;
  gen.textContent = `${d.toLocaleString(undefined, {dateStyle: "medium", timeStyle: "short"})} (${ago})`;
}
themeBtn.onclick = () => {
  theme = root.dataset.theme === "dark" ? "light" : "dark";
  try { localStorage.setItem("ge-theme", theme); } catch (e) {}
  applyTheme();
};
applyTheme();
const DATA = __DATA__;
const PAGE = __PAGE_SIZE__;
let minPace = 0;
// Ingredients toggle (remembered): collapsed rows are one line; expanded lists in/out.
let showIng = false;
try { showIng = localStorage.getItem("ge-ingredients") === "1"; } catch (e) {}
const ingBox = document.getElementById("showing"), tbl = document.getElementById("tbl");
ingBox.checked = showIng;
ingBox.onchange = () => {
  showIng = ingBox.checked;
  try { localStorage.setItem("ge-ingredients", showIng ? "1" : "0"); } catch (e) {}
  render();
};
const qty = q => fmt(q, q % 1 ? 2 : 0);
const items = list => "<ul>" + list.map(([q, n]) =>
  `<li><span class="q">${qty(q)} ×</span><span>${esc(n)}</span></li>`).join("") + "</ul>";
const recipeCell = r => showIng
  ? `${esc(r.recipe)}<div class="ing"><span class="k">In</span>${items(r.inputs)}<span class="k">Out</span>${items(r.outputs)}</div>`
  : `<span title="${esc(r.recipe + "\\n" + r.io)}">${esc(r.recipe)}</span>`;
let key = "gp_per_hour", desc = true, page = 0, skill = "", zeroXp = false, minVol = __MIN_VOL__, share = __SHARE__ / 100;
function applyShare() {
  // Actions per 4-hour window: buy limits, capped at `share` of the market's volume.
  for (const r of DATA) {
    const caps = [r.actions_per_limit, r.volume_actions === null ? null : r.volume_actions * share]
      .filter(c => c !== null);
    r.capped = caps.length ? Math.min(...caps) : null;
    r.volume_bound = r.volume_actions !== null &&
      (r.actions_per_limit === null || r.volume_actions * share < r.actions_per_limit);
    r.gp_per_limit = r.capped === null ? null : r.profit * r.capped;
    // Next hour: production speed vs one full buy limit vs share of an hour's volume.
    if (r.speed === null) { r.hour = null; r.bound = ""; }
    else {
      const hcaps = [[r.speed, "S"]];
      if (r.actions_per_limit !== null) hcaps.push([r.actions_per_limit, "L"]);
      if (r.volume_actions !== null) hcaps.push([r.volume_actions * share / 4, "V"]);
      [r.hour, r.bound] = hcaps.reduce((a, b) => b[0] < a[0] ? b : a);
    }
    r.gp_per_hour = r.hour === null ? null : r.profit * r.hour;
    r.xp_per_hour = r.hour === null ? null : r.xp * r.hour;
    r.xp_pace = (r.xp_per_hour === null || !r.ref_xp || r.xp <= 0) ? null : r.xp_per_hour / r.ref_xp;
  }
}
applyShare();
const skillsOf = r => r.skill.split(" + ");
const sel = document.getElementById("skill");
[...new Set(DATA.flatMap(skillsOf))].sort().forEach(s => sel.add(new Option(s, s)));
sel.onchange = () => { skill = sel.value; page = 0; render(); };
document.getElementById("share").oninput = e => { share = Math.max(0, Number(e.target.value) || 0) / 100; applyShare(); render(); };
document.getElementById("minpace").oninput = e => { minPace = (Number(e.target.value) || 0) / 100; page = 0; render(); };
document.getElementById("minvol").oninput = e => { minVol = Number(e.target.value) || 0; page = 0; render(); };
document.getElementById("zeroxp").onchange = e => { zeroXp = e.target.checked; page = 0; render(); };
const fmt = (x, d = 0) => x.toLocaleString(undefined, {minimumFractionDigits: d, maximumFractionDigits: d});
const signed = (x, d = 0) => (x > 0 ? "+" : "") + fmt(x, d);
// Accounting style: sign pinned to the left of the cell, digits right-aligned.
// Accounting cells shorten to "1.6m" / "2.2b" only when the full number wouldn't
// fit its column (maxLen characters); hover shows the full number.
const acct = (x, d = 0, maxLen = 9) => {
  const a = Math.abs(x);
  let txt = fmt(a, d);
  if (txt.length > maxLen) txt = a >= 1e9 ? fmt(a / 1e9, 1) + "b" : a >= 1e6 ? fmt(a / 1e6, 1) + "m" : fmt(a / 1e3, 1) + "k";
  const short = txt !== fmt(a, d);
  return `<span class="acct"${short ? ` title="${fmt(x, d)}"` : ""}><span>${x > 0 ? "+" : x < 0 ? "−" : ""}</span><span>${txt}</span></span>`;
};
const cls = x => x > 0 ? "pos" : x < 0 ? "neg" : "";
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function sorted() {
  return DATA.filter(r => (!skill || skillsOf(r).includes(skill)) && (zeroXp || r.xp > 0)
    && (r.min_volume === null || r.min_volume >= minVol)
    && (minPace === 0 || (r.xp_pace !== null && r.xp_pace >= minPace))).sort((a, b) => {
    const x = a[key], y = b[key];
    if (x === null && y === null) return 0;
    if (x === null) return 1;            // missing values always last
    if (y === null) return -1;
    return desc ? y - x : x - y;
  });
}
function render() {
  tbl.classList.toggle("collapsed", !showIng);
  const rows = sorted(), pages = Math.max(1, Math.ceil(rows.length / PAGE));
  page = Math.min(page, pages - 1);
  document.getElementById("rows").innerHTML = rows.slice(page * PAGE, page * PAGE + PAGE).map((r, i) => `
    <tr><td class="na">${page * PAGE + i + 1}</td><td class="l recipe">${recipeCell(r)}</td><td class="l" title="${esc(r.skill)}">${esc(r.skill)}</td>
    <td class="${r.gp_per_hour === null ? "na" : cls(r.gp_per_hour)}">${r.gp_per_hour === null ? "—" : acct(r.gp_per_hour, 0, 9)}</td>
    <td>${r.xp_per_hour === null ? "<span class=na>—</span>" : fmt(r.xp_per_hour)}</td>
    <td>${r.xp_pace === null ? "<span class=na>—</span>" : fmt(100 * r.xp_pace) + "%"}</td>
    <td>${r.hour === null ? "<span class=na>—</span>" : fmt(r.hour) + " <span class=na>" + r.bound + "</span>"}</td>
    <td class="${cls(r.profit)}" title="cost ${fmt(r.cost)} → revenue ${fmt(r.revenue)}">${acct(r.profit, 0, 7)}</td><td>${fmt(r.xp, r.xp % 1 ? 1 : 0)}</td>
    <td class="${r.gp_per_xp === null ? "na" : cls(r.gp_per_xp)}">${r.gp_per_xp === null ? "—" : acct(r.gp_per_xp, 2, 8)}</td>
    <td>${r.min_volume === null ? "<span class=na>—</span>" : fmt(r.min_volume)}</td>
    <td>${r.capped === null ? "<span class=na>—</span>" : fmt(r.capped) + (r.volume_bound ? "*" : "")}</td>
    <td class="${r.gp_per_limit === null ? "na" : cls(r.gp_per_limit)}">${r.gp_per_limit === null ? "—" : acct(r.gp_per_limit, 0, 11)}</td></tr>`).join("");
  document.getElementById("pageinfo").textContent = `Page ${page + 1} of ${pages} · ${rows.length} recipes`;
  document.getElementById("prev").disabled = page === 0;
  document.getElementById("next").disabled = page >= pages - 1;
  document.querySelectorAll("th.sort").forEach(th => {
    const on = th.dataset.key === key;
    th.classList.toggle("active", on);
    th.textContent = th.textContent.replace(/ [▲▼]$/, "") + (on ? (desc ? " ▼" : " ▲") : "");
  });
}
document.querySelectorAll("th.sort").forEach(th => th.addEventListener("click", () => {
  if (th.dataset.key === key) desc = !desc; else { key = th.dataset.key; desc = true; }
  page = 0; render();
}));
document.getElementById("prev").onclick = () => { page--; render(); };
document.getElementById("next").onclick = () => { page++; render(); };
render();
</script>
</body>
</html>
"""
