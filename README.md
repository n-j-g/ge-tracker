# ge-tracker

bankstand profitably

**Live page (updated hourly): https://n-j-g.github.io/ge-tracker/**

Finds the OSRS skilling/production methods you can do by buying inputs and
selling outputs on the Grand Exchange, and ranks them by feasible gp/hr, XP/hr,
gp/xp and how they compare with your normal way of training each skill.

Prices come from the OSRS Wiki real-time price API; recipes come from the
Wiki's structured recipe data plus `recipes.toml`.

Python 3.9+, no installs needed (a small TOML reader is bundled in `vendor/`
for Pythons older than 3.11).

## Running it

```
python3 wiki_recipes.py                    # download recipes from the Wiki (occasionally)
python3 ge_profit.py --html results.html   # live prices -> sortable web page
python3 ge_profit.py                       # same, as a text table
python3 ge_profit.py --profitable          # only money-makers
python3 ge_profit.py --skill Fletching     # filter by skill (repeatable)
python3 ge_profit.py --mode mid            # conservative | mid | optimistic
python3 ge_profit.py --source latest       # 1h (default) | 5m | latest
python3 ge_profit.py --json                # machine-readable output
python3 -m unittest                        # run tests
```

Each live run saves the price data it fetched in `data/` (`last_mapping.json`,
`last_1h.json`, `last_latest.json`), so a run can be repeated offline:

```
python3 ge_profit.py --mapping-file data/last_mapping.json \
  --prices-file data/last_1h.json --fallback-file data/last_latest.json --html results.html
```

## Hosted version

`.github/workflows/update.yml` runs every hour on GitHub Actions: it runs the
tests, downloads Wiki recipes (at most once a day), fetches prices, builds the
page and publishes it with GitHub Pages. It also runs on every push to `main`
and on demand from the Actions tab. Pages must be enabled once under
Settings → Pages → Source: GitHub Actions (free for public repositories).

## Supply-chain map

`chain/index.html` shows any item in the middle, the recipes that make it on one
side and the recipes that use it on the other; click a branch to move along the
chain. It reads `graph.json`, built by `chain/build_graph.py` from every Wiki recipe
plus current prices (same profit model as the main page). The hourly job publishes
it at `/chain/`. To try it locally:

```
python3 chain/build_graph.py --offline        # after a normal run has saved data/last_*.json
cd chain && python3 -m http.server             # then open http://localhost:8000
```

## Transfer-trap paper trading

`live/watch.py` runs around the clock on a small server, watching for suspected gold
transfers and paper-trading resting sell offers against them. Results:
https://n-j-g.github.io/ge-tracker/paper/. Setup steps: [live/README.md](live/README.md).

## Research: price history

`research/backfill_history.py` downloads the API's full hourly history (every
item, from early 2021) into `data/history/prices_1h.sqlite` (~4 GB): one
request per hour of history, at most one per second, newest first, resumable.

```
caffeinate -i python3 research/backfill_history.py   # run/resume (keeps a Mac awake)
python3 research/backfill_history.py --status        # what's stored so far
```

## Model

A recipe is `n_1·item_1 + … + n_k·item_k → m_1·out_1 + … + m_j·out_j`, plus XP.

- **cost** = Σ input qty × buy price (+ any per-hour fee spread over the actions)
- **revenue** = Σ output qty × (sell price − GE tax)
- **profit** (GP/action) = revenue − cost, **gp/xp** = profit / xp
- **actions/hr (speed)** = Wiki ticks per action plus one 10-tick bank trip per
  inventory (28 slots minus tools, divided by non-stackable inputs per action).
  Runecrafting and anything at an altar or obelisk get no estimate (travel-bound);
  cooking on a range/fire is at least 4 ticks. Set any rate by hand in the
  `[actions_per_hour]` table in `recipes.toml` (Blast Furnace rates are set
  there from the Wiki money making guides).
- **GP/hr, XP/hr** = for the next hour, actions = the smallest of speed, one full
  buy limit (it can all be bought up front) and your market share (default 10%)
  of an hour's trading volume. The page marks which one binds: S, L or V.
- **XP pace** = this hour's XP as a % of an hour of your normal training method
  for the skill, set under `[normal_training]` in `recipes.toml`. 100% means
  you train as fast as usual and the gp is a bonus.
- **actions/4h, GP/4h** = the same idea over a 4-hour buy-limit window: the
  inputs' buy limits, capped by your market share of 4 hours of volume.
- **min vol/hr** = hourly trades of the recipe's least-traded item; the page
  hides recipes under 100 by default because their prices are unreliable.

Prices default to the API's 1-hour averages (`--source 1h`); a side with no
trades in that hour is filled from the latest trade. Price modes:

| mode | buy inputs at | sell outputs at |
|---|---|---|
| conservative (default) | the higher of high/low | the lower of high/low |
| mid | avg | avg |
| optimistic | the lower | the higher |

high/low are last trades or averages and can cross, which is why the modes use max/min.

GE tax: 2% per item sold, rounded down (so items under 50 gp are untaxed), capped at 5m.

## Recipes

Most recipes come from the OSRS Wiki
([Bucket:Recipe](https://oldschool.runescape.wiki/w/Bucket:Recipe)), cached in
`data/wiki_recipes.json` by `python3 wiki_recipes.py`. Recipes whose XP depends
on the player (e.g. "1× Construction level") are skipped, recipes giving XP in
several skills use the total, burnt-food "recipes" are dropped, and anything
with an item that isn't on the GE is left out.

`recipes.toml` adds to and corrects the Wiki data:

- `exclude_outputs`: rare/chance by-products the Wiki lists as recipes (e.g. squid beak)
- `[actions_per_hour]`: hand-set production speeds by recipe name
- `[coins_per_hour]`: time-based fees by recipe name (e.g. the Blast Furnace coffer)
- `[normal_training]`: your normal training method per skill, for XP pace
- `[[recipe]]` blocks: extra recipes. One with the same inputs and outputs as a
  Wiki recipe replaces it (keeping the Wiki's timing data). Item names must
  match the Wiki's GE names (case-insensitive); fractional quantities are fine
  and `Coins` covers flat gp fees.

## Not modelled yet

Gathering skills, burn/fail rates, available cash, chance-based secondary
outputs (e.g. Amulet of chemistry), level requirements, and prices moving
when you buy or sell in bulk.
