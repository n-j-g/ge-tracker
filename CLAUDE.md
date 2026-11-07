# ge-tracker: notes for Claude

OSRS tool that ranks skilling/production methods (buy inputs on the GE, process,
sell outputs) by feasible gp/hr, XP/hr, gp/xp and "XP pace". See README.md for
the model and the meaning of every column.

## The person

Math/econ background, not a programmer. Explain in plain language, avoid jargon,
and keep them out of the terminal where possible. Ask before changing the model
in ways that change the numbers they see; small fixes and UI tweaks are fine.

## Layout

- `ge_profit.py`: data model, pricing, speed model, CLI. Pure calculation
  functions; network access only in `_get_json` / `fetch_*`.
- `wiki_recipes.py`: downloads and converts the Wiki recipe bucket.
- `web.py`: renders the results page (`render_html(results, meta)`): one
  self-contained HTML file; the template is a Python string, so JavaScript
  escapes need doubling (`"\\n"`, not `"\n"`).
- `recipes.toml`: user-editable data (exclusions, speed overrides, fees,
  normal training methods, manual recipes). TOML: top-level keys and tables
  must come before the `[[recipe]]` array.
- `test_ge_profit.py`: unittest suite; run `python3 -m unittest`. One test
  syntax-checks the page's JavaScript with Node (skipped if Node is missing).
- `.github/workflows/update.yml`: hourly build + GitHub Pages deploy.
- `vendor/tomli`: bundled TOML reader for Python < 3.11 (the user's Mac has 3.9).

Keep it standard-library only and Python 3.9 compatible
(`from __future__ import annotations`; no `match`, no 3.10+ only APIs).

## Data and network

- Prices: `https://prices.runescape.wiki/api/v1/osrs/` (`mapping`, `1h`, `latest`).
- Recipes: `https://oldschool.runescape.wiki/api.php?action=bucket` (see `wiki_recipes.py`).
- Both ask for a descriptive User-Agent; set via `GE_PROFIT_USER_AGENT`.
- Sandboxed environments may block these hosts. Without network, use saved
  data in `data/` (gitignored) via `--mapping-file/--prices-file/--fallback-file`.

## Lessons learned (data quality)

- Wiki recipe rows include chance outcomes (squid beak) and burnt food; handle
  with `exclude_outputs` / the burnt filter, not by trusting every row.
- Wiki `ticks` are sometimes wrong (cooking listed as 1 tick) or meaningless
  (runecrafting: travel-bound). Speed overrides go in `recipes.toml`.
- Thinly traded items give nonsense margins; the min-volume filter exists for that.
- Check results against the Wiki money making guides when something looks off.

## Before finishing a change

Run the tests, rebuild the page from saved data, and check it renders without
errors (fixed column widths, uniform row heights when ingredients are collapsed).
