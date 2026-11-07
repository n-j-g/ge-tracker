#!/usr/bin/env python3
"""OSRS GE production profit calculator (MVP).

Prices every recipe in recipes.toml against live Grand Exchange prices from the
OSRS Wiki real-time prices API and reports profit per action and gp/xp.

Standard library only. Runs on Python 3.9+ (a TOML reader is bundled in vendor/ for pre-3.11).
"""
from __future__ import annotations

import argparse
import os
import json
import math
import sys
import time
import urllib.request
from dataclasses import dataclass, replace
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # older Pythons (e.g. macOS's built-in 3.9): bundled copy
    sys.path.insert(0, str(Path(__file__).with_name("vendor")))
    import tomli as tomllib

API_BASE = "https://prices.runescape.wiki/api/v1/osrs"
# The Wiki asks for a descriptive User-Agent with a way to contact you. The hosted
# version sets GE_PROFIT_USER_AGENT to include the GitHub repository's address.
USER_AGENT = os.environ.get("GE_PROFIT_USER_AGENT",
                            "osrs-ge-profit/0.1 (personal GE profit calculator)")

GE_TAX_RATE = 0.02
GE_TAX_CAP = 5_000_000
COINS = "coins"

DEFAULT_MIN_VOLUME = 100
DEFAULT_MARKET_SHARE = 0.10   # share of an item's trading volume you can realistically take
LIMIT_WINDOW_HOURS = 4        # GE buy limits reset every 4 hours
SOURCE_HOURS = {"1h": 1.0, "5m": 5 / 60}  # window the volumes in each source cover

DEFAULT_RECIPES = Path(__file__).with_name("recipes.toml")


# --------------------------------------------------------------------------- model

@dataclass(frozen=True)
class Recipe:
    name: str
    skill: str          # "Smithing", or "Smithing + Magic" when XP goes to several skills
    xp: float           # total XP per action across all skills
    inputs: dict[str, float]
    outputs: dict[str, float]
    ticks: float | None = None      # game ticks per action, where the Wiki gives it
    members: bool | None = None
    facility: str | None = None
    tools: tuple[str, ...] = ()     # tools needed (each takes an inventory slot)
    source: str = "manual"          # "manual" (recipes.toml) or "wiki"
    actions_per_hour: float | None = None  # hand-set rate; overrides the speed model
    coins_per_hour: float | None = None    # time-based fee (e.g. Blast Furnace coffer)

    def signature(self) -> tuple:
        """Identifies the same transformation regardless of naming or XP."""
        return (tuple(sorted((k.lower(), v) for k, v in self.inputs.items())),
                tuple(sorted((k.lower(), v) for k, v in self.outputs.items())))


@dataclass(frozen=True)
class Price:
    high: float | None  # instant-buy price: latest trade, or average over the window
    low: float | None   # instant-sell price: latest trade, or average over the window
    high_volume: int | None = None  # trades at the high side in the window (averages only)
    low_volume: int | None = None   # trades at the low side in the window (averages only)


@dataclass(frozen=True)
class Result:
    recipe: Recipe
    cost: float      # gp spent on inputs per action
    revenue: float   # gp received for outputs per action, after GE tax
    # How many actions one 4-hour GE buy-limit window supports: min over tradable
    # inputs of (buy limit / qty used per action). None if any input's limit is unknown.
    actions_per_limit: float | None = None
    # Hourly trade volume (both sides) of the least-traded item in the recipe.
    # Low values mean the price is unreliable or the item is hard to buy/sell.
    # None when the price source has no volumes (e.g. --source latest).
    min_volume: int | None = None
    # Actions the market could support in one 4-hour window if you took ALL of the
    # trading volume of each item: min over items of (4h volume / qty per action).
    volume_actions: float | None = None

    def capped_actions(self, share: float) -> float | None:
        """Actions per 4-hour window: the buy limits, further capped at `share`
        (e.g. 0.1 = 10%) of the market's trading volume."""
        caps = [c for c in (self.actions_per_limit,
                            None if self.volume_actions is None else self.volume_actions * share)
                if c is not None]
        return min(caps) if caps else None

    # Estimated production speed, in actions per hour (None if unknown).
    speed: float | None = None

    def hour_plan(self, share: float) -> tuple[float, str] | None:
        """Feasible actions in the next hour and which constraint binds:
        'speed' (how fast you can do it), 'limit' (one full buy limit, which can be
        bought up front) or 'volume' (your share of one hour of trading)."""
        if self.speed is None:
            return None
        caps = [(self.speed, "speed")]
        if self.actions_per_limit is not None:
            caps.append((self.actions_per_limit, "limit"))
        if self.volume_actions is not None:
            caps.append((self.volume_actions * share / LIMIT_WINDOW_HOURS, "volume"))
        return min(caps)

    def gp_per_hour(self, share: float = None) -> float | None:
        plan = self.hour_plan(DEFAULT_MARKET_SHARE if share is None else share)
        return None if plan is None else self.profit * plan[0]

    def xp_per_hour(self, share: float = None) -> float | None:
        plan = self.hour_plan(DEFAULT_MARKET_SHARE if share is None else share)
        return None if plan is None else self.recipe.xp * plan[0]

    def gp_per_window(self, share: float) -> float | None:
        actions = self.capped_actions(share)
        return None if actions is None else self.profit * actions

    @property
    def profit(self) -> float:
        return self.revenue - self.cost

    @property
    def gp_per_xp(self) -> float | None:
        return self.profit / self.recipe.xp if self.recipe.xp > 0 else None

    @property
    def gp_per_limit(self) -> float | None:
        """Profit per 4-hour window, limited by buy limits and DEFAULT_MARKET_SHARE of volume."""
        return self.gp_per_window(DEFAULT_MARKET_SHARE)


class PricingError(Exception):
    pass


# --------------------------------------------------------------------------- data

def load_recipes(path: Path) -> list[Recipe]:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    recipes = []
    for r in data.get("recipe", []):
        recipes.append(Recipe(
            name=r["name"],
            skill=r["skill"],
            xp=float(r["xp"]),
            inputs={k: float(v) for k, v in r["inputs"].items()},
            outputs={k: float(v) for k, v in r["outputs"].items()},
            actions_per_hour=float(r["actions_per_hour"]) if "actions_per_hour" in r else None,
        ))
    return recipes


def load_speed_overrides(path: Path) -> dict[str, float]:
    """[actions_per_hour] table in recipes.toml: recipe name -> actions/hour (lowercased)."""
    with open(path, "rb") as f:
        table = tomllib.load(f).get("actions_per_hour", {})
    return {k.lower(): float(v) for k, v in table.items()}


def load_normal_training(path: Path) -> dict[str, str]:
    """[normal_training] table in recipes.toml: skill -> recipe name."""
    with open(path, "rb") as f:
        return dict(tomllib.load(f).get("normal_training", {}))


def reference_rates(results: list[Result], normal: dict[str, str]) -> dict[str, dict]:
    """Skill -> {"method", "xp_per_hour"}: the XP/hr of the normal training method,
    at full production speed (market limits don't apply to how fast you train)."""
    by_name: dict[str, Result] = {}
    for r in results:
        if r.speed is not None:
            best = by_name.get(r.recipe.name.lower())
            if best is None or r.recipe.xp * r.speed > best.recipe.xp * best.speed:
                by_name[r.recipe.name.lower()] = r
    refs = {}
    for skill, method in normal.items():
        r = by_name.get(method.lower())
        if r is not None and r.recipe.xp > 0:
            refs[skill] = {"method": r.recipe.name, "xp_per_hour": r.recipe.xp * r.speed}
        else:
            print(f"note: normal training method for {skill} ('{method}') wasn't found "
                  "or has no speed estimate", file=sys.stderr)
    return refs


def reference_for(recipe: Recipe, refs: dict[str, dict]) -> float | None:
    """Normal-training XP/hr for the recipe's (first) skill, if one is set."""
    ref = refs.get(recipe.skill.split("+")[0].strip())
    return None if ref is None else ref["xp_per_hour"]


def xp_pace(result: Result, refs: dict[str, dict], share: float = None) -> float | None:
    """XP you can actually get this hour (same limits as gp/hr), as a fraction of
    an hour of your normal training method for the skill."""
    ref = reference_for(result.recipe, refs)
    xp = result.xp_per_hour(share)
    if ref is None or xp is None or result.recipe.xp <= 0:
        return None
    return xp / ref


def load_hourly_fees(path: Path) -> dict[str, float]:
    """[coins_per_hour] table in recipes.toml: recipe name -> coins per hour (lowercased)."""
    with open(path, "rb") as f:
        table = tomllib.load(f).get("coins_per_hour", {})
    return {k.lower(): float(v) for k, v in table.items()}


def apply_speed_overrides(recipes: list[Recipe], overrides: dict[str, float],
                          fees: dict[str, float] | None = None) -> list[Recipe]:
    fees = fees or {}
    out = []
    for r in recipes:
        key = r.name.lower()
        if key in overrides:
            r = replace(r, actions_per_hour=overrides[key])
        if key in fees:
            r = replace(r, coins_per_hour=fees[key])
        out.append(r)
    return out


def load_excludes(path: Path) -> set[str]:
    """Output item names listed under exclude_outputs in recipes.toml (lowercased)."""
    with open(path, "rb") as f:
        return {n.lower() for n in tomllib.load(f).get("exclude_outputs", [])}


def apply_excludes(recipes: list[Recipe], excludes: set[str]) -> list[Recipe]:
    return [r for r in recipes if not any(o.lower() in excludes for o in r.outputs)]


def merge_recipes(manual: list[Recipe], wiki: list[Recipe]) -> list[Recipe]:
    """Manual recipes win over Wiki recipes with the same inputs and outputs,
    so recipes.toml can correct or extend the Wiki data."""
    wiki_by_sig: dict[tuple, Recipe] = {}
    for r in wiki:
        wiki_by_sig.setdefault(r.signature(), r)
    merged, seen = [], set()
    for r in manual:
        w = wiki_by_sig.get(r.signature())
        if w is not None and r.ticks is None:
            # Keep the hand-written numbers, but borrow what the Wiki knows about speed.
            r = replace(r, ticks=w.ticks, tools=w.tools, facility=w.facility, members=w.members)
        merged.append(r)
        seen.add(r.signature())
    for r in wiki:
        if r.signature() not in seen:
            seen.add(r.signature())
            merged.append(r)
    return merged


# --------------------------------------------------------------------------- speed

TICK_SECONDS = 0.6
INVENTORY_SLOTS = 28
DEFAULT_BANK_TICKS = 10  # time per bank trip (withdraw + deposit), in game ticks

# Recipes whose Wiki "ticks" don't describe a repeatable rate: runecrafting is
# dominated by travel to the altar. These get no gp/hr unless set by hand.
SPEED_UNMODELLED_SKILLS = {"runecraft"}
# Facilities you have to travel to (altars, Wilderness obelisks): same problem.
SPEED_UNMODELLED_FACILITIES = ("altar", "obelisk")
# Known-bad Wiki timings: some cooking recipes list 1 tick, but cooking on a
# range or fire takes 4 ticks per item (ignoring tick-manipulation tricks).
COOKING_MIN_TICKS = 4

_STACKABLE_WORDS = ("rune", "coins", "feather", "arrow", "bolt", "dart", "javelin", "nails",
                    "cannonball", "seed", "thread", "chinchompa", "tokkul", "shard", "tips",
                    "headless", "throwing knife", "ammo")
_STACKABLE_EXACT = {"bronze knife", "iron knife", "steel knife", "black knife", "mithril knife",
                    "adamant knife", "rune knife", "dragon knife", "wool"}


def is_stackable(item: str) -> bool:
    """Best guess from the name; the Wiki has no stackable flag. Errs toward
    'not stackable', which makes trips shorter and speed estimates lower."""
    n = item.lower()
    if n in _STACKABLE_EXACT:
        return True
    if n in ("rune essence", "pure essence") or n.endswith(" essence"):
        return False
    return any(w in n for w in _STACKABLE_WORDS) and "bar" not in n.split()


def speed(recipe: Recipe, bank_ticks: float = DEFAULT_BANK_TICKS) -> float | None:
    """Estimated actions per hour, including one bank trip per inventory.
    None when there's no usable timing data."""
    if recipe.actions_per_hour is not None:
        return recipe.actions_per_hour
    skills = {s.strip().lower() for s in recipe.skill.split("+")}
    facility = (recipe.facility or "").lower()
    if (skills & SPEED_UNMODELLED_SKILLS or not recipe.ticks or recipe.ticks <= 0
            or any(f in facility for f in SPEED_UNMODELLED_FACILITIES)):
        return None
    ticks = recipe.ticks
    if "cooking" in skills and ("range" in facility or "fire" in facility):
        ticks = max(ticks, COOKING_MIN_TICKS)
    slots = sum(q for item, q in recipe.inputs.items()
                if item.lower() != COINS and not is_stackable(item))
    if slots <= 0:  # everything stacks: no banking needed
        return 3600 / (ticks * TICK_SECONDS)
    per_trip = math.floor((INVENTORY_SLOTS - len(recipe.tools)) / slots)
    if per_trip < 1:
        return None
    trip_ticks = per_trip * ticks + bank_ticks
    return per_trip * 3600 / (trip_ticks * TICK_SECONDS)


def _get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def parse_mapping(raw: list[dict]) -> dict[str, int]:
    """Item name (lowercased) -> item id, from the /mapping endpoint."""
    return {item["name"].lower(): int(item["id"]) for item in raw}


def parse_limits(raw: list[dict]) -> dict[int, int]:
    """Item id -> GE buy limit per 4 hours, from the /mapping endpoint (where known)."""
    return {int(item["id"]): int(item["limit"]) for item in raw if item.get("limit")}


SOURCES = ("1h", "5m", "latest")
DEFAULT_SOURCE = "1h"


def parse_latest(raw: dict) -> dict[int, Price]:
    """Item id -> Price, from the /latest endpoint (single most recent trades)."""
    return {int(k): Price(v.get("high"), v.get("low")) for k, v in raw["data"].items()}


def parse_average(raw: dict) -> dict[int, Price]:
    """Item id -> Price, from the /1h or /5m endpoint (volume-weighted averages).
    A side is null when nothing traded on that side during the window."""
    return {int(k): Price(v.get("avgHighPrice"), v.get("avgLowPrice"),
                          v.get("highPriceVolume"), v.get("lowPriceVolume"))
            for k, v in raw["data"].items()}


def fill_missing(primary: dict[int, Price], fallback: dict[int, Price]) -> dict[int, Price]:
    """Use primary prices (e.g. 1-hour averages), filling any side that had no trades
    from fallback (e.g. latest trades). Volumes stay those of the primary source."""
    merged = {}
    for item_id in primary.keys() | fallback.keys():
        p, f = primary.get(item_id), fallback.get(item_id)
        if p is None:
            merged[item_id] = Price(f.high, f.low, 0, 0)
        elif f is None:
            merged[item_id] = p
        else:
            merged[item_id] = Price(p.high if p.high is not None else f.high,
                                    p.low if p.low is not None else f.low,
                                    p.high_volume, p.low_volume)
    return merged


def parse_prices(raw: dict) -> dict[int, Price]:
    """Parse either price format, detected from its fields (used for saved files)."""
    sample = next(iter(raw["data"].values()), {})
    return parse_average(raw) if "avgHighPrice" in sample else parse_latest(raw)


def fetch_mapping_raw() -> list[dict]:
    return _get_json(f"{API_BASE}/mapping")


def fetch_mapping() -> dict[str, int]:
    return parse_mapping(fetch_mapping_raw())


def fetch_prices(source: str = DEFAULT_SOURCE) -> dict[int, Price]:
    if source not in SOURCES:
        raise ValueError(f"unknown price source '{source}'")
    return parse_prices(fetch_prices_raw(source))


def fetch_prices_raw(source: str = DEFAULT_SOURCE) -> dict:
    if source not in SOURCES:
        raise ValueError(f"unknown price source '{source}'")
    return _get_json(f"{API_BASE}/{source}")


LAST_FETCH_DIR = Path(__file__).with_name("data")


def save_last_fetch(name: str, raw) -> None:
    """Keep a copy of the most recent API data so results can be re-run offline."""
    LAST_FETCH_DIR.mkdir(exist_ok=True)
    (LAST_FETCH_DIR / name).write_text(json.dumps(raw), encoding="utf-8")


# --------------------------------------------------------------------------- pricing

MODES = ("conservative", "mid", "optimistic")


def ge_tax(unit_sell_price: float) -> int:
    """GE tax on one item sold: 2%, rounded down, capped at 5m.
    Rounding down means items selling under 50 gp pay nothing."""
    return min(math.floor(unit_sell_price * GE_TAX_RATE), GE_TAX_CAP)


def _pick(p: Price, side: str, mode: str) -> float | None:
    """side is 'buy' or 'sell'.
    conservative: buy at instant-buy (high), sell at instant-sell (low)
    optimistic:   buy at low, sell at high (you wait for offers to fill)
    mid:          average of high and low
    """
    if mode == "mid":
        vals = [v for v in (p.high, p.low) if v is not None]
        return sum(vals) / len(vals) if vals else None
    vals = [v for v in (p.high, p.low) if v is not None]
    if len(vals) < 2:
        # Only one side has traded recently; refuse rather than guess.
        return None
    # high/low are the latest instant-buy/instant-sell trades and can cross
    # (low > high), so take the larger/smaller value rather than trusting the label.
    pessimistic_side = (side == "buy") == (mode == "conservative")
    return max(vals) if pessimistic_side else min(vals)


def unit_price(item: str, side: str, mode: str,
               ids: dict[str, int], prices: dict[int, Price]) -> float:
    if item.lower() == COINS:
        return 1.0
    item_id = ids.get(item.lower())
    if item_id is None:
        raise PricingError(f"unknown item name '{item}'")
    p = prices.get(item_id)
    value = _pick(p, side, mode) if p else None
    if value is None:
        raise PricingError(f"no {side} price for '{item}'")
    return value


def actions_per_limit(recipe: Recipe, ids: dict[str, int],
                      limits: dict[int, int]) -> float | None:
    caps = []
    for item, qty in recipe.inputs.items():
        if item.lower() == COINS:
            continue
        limit = limits.get(ids.get(item.lower(), -1))
        if limit is None:
            return None
        caps.append(limit / qty)
    return min(caps) if caps else None


def evaluate(recipe: Recipe, ids: dict[str, int], prices: dict[int, Price],
             mode: str = "conservative", tax: bool = True,
             limits: dict[int, int] | None = None, volume_hours: float = 1.0) -> Result:
    cost = sum(qty * unit_price(item, "buy", mode, ids, prices)
               for item, qty in recipe.inputs.items())
    revenue = 0.0
    for item, qty in recipe.outputs.items():
        unit = unit_price(item, "sell", mode, ids, prices)
        if tax and item.lower() != COINS:
            unit -= ge_tax(unit)
        revenue += qty * unit
    spd = speed(recipe)
    if recipe.coins_per_hour and spd:
        cost += recipe.coins_per_hour / spd  # spread a per-hour fee over each action
    apl = actions_per_limit(recipe, ids, limits) if limits is not None else None
    return Result(recipe, cost, revenue, apl, min_volume(recipe, ids, prices),
                  volume_actions(recipe, ids, prices, volume_hours), spd)


def volume_actions(recipe: Recipe, ids: dict[str, int], prices: dict[int, Price],
                   volume_hours: float) -> float | None:
    """Actions per 4-hour window if you took every trade of each item.
    volume_hours is the length of the window the volumes were measured over."""
    caps = []
    for item, qty in [*recipe.inputs.items(), *recipe.outputs.items()]:
        if item.lower() == COINS:
            continue
        p = prices.get(ids.get(item.lower(), -1))
        if p is None or (p.high_volume is None and p.low_volume is None):
            return None
        per_window = ((p.high_volume or 0) + (p.low_volume or 0)) * LIMIT_WINDOW_HOURS / volume_hours
        caps.append(per_window / qty)
    return min(caps) if caps else None


def min_volume(recipe: Recipe, ids: dict[str, int], prices: dict[int, Price]) -> int | None:
    vols = []
    for item in [*recipe.inputs, *recipe.outputs]:
        if item.lower() == COINS:
            continue
        p = prices.get(ids.get(item.lower(), -1))
        if p is None or (p.high_volume is None and p.low_volume is None):
            return None
        vols.append((p.high_volume or 0) + (p.low_volume or 0))
    return min(vols) if vols else None


def passes_volume(result: Result, threshold: int) -> bool:
    """Unknown volume passes, so sources without volume data aren't emptied."""
    return result.min_volume is None or result.min_volume >= threshold


def evaluate_all(recipes, ids, prices, mode="conservative", tax=True, limits=None,
                 volume_hours=1.0):
    results, errors = [], []
    for r in recipes:
        try:
            results.append(evaluate(r, ids, prices, mode, tax, limits, volume_hours))
        except PricingError as e:
            errors.append((r.name, str(e)))
    results.sort(key=_sort_key, reverse=True)
    return results, errors


def _sort_key(res: Result) -> float:
    # Best gp/xp first. Zero-xp steps sort to the top if they make money, bottom if not.
    if res.gp_per_xp is not None:
        return res.gp_per_xp
    return math.inf if res.profit > 0 else -math.inf


# --------------------------------------------------------------------------- output

def _gp(x: float) -> str:
    return f"{x:,.0f}"


def render_table(results: list[Result]) -> str:
    headers = ["Recipe", "Skill", "Cost", "Revenue", "Profit", "XP", "GP/XP"]
    rows = []
    for r in results:
        gpxp = r.gp_per_xp
        rows.append([
            r.recipe.name,
            r.recipe.skill,
            _gp(r.cost),
            _gp(r.revenue),
            f"{r.profit:+,.0f}",
            f"{r.recipe.xp:g}",
            f"{gpxp:+,.2f}" if gpxp is not None else "n/a (0 xp)",
        ])
    widths = [max(len(str(c)) for c in col) for col in zip(headers, *rows)]
    left = {0, 1}  # text columns left-aligned, numbers right-aligned

    def fmt(row):
        return "  ".join(c.ljust(w) if i in left else c.rjust(w)
                         for i, (c, w) in enumerate(zip(row, widths)))

    lines = [fmt(headers), "  ".join("-" * w for w in widths)]
    lines += [fmt(r) for r in rows]
    return "\n".join(lines)


def to_json(results: list[Result], refs: dict[str, dict] | None = None) -> str:
    return json.dumps([{
        "recipe": r.recipe.name,
        "skill": r.recipe.skill,
        "xp": r.recipe.xp,
        "cost": r.cost,
        "revenue": r.revenue,
        "profit": r.profit,
        "gp_per_xp": r.gp_per_xp,
        "actions_per_limit": r.actions_per_limit,
        "gp_per_limit": r.gp_per_limit,
        "min_volume": r.min_volume,
        "volume_actions": r.volume_actions,
        "capped_actions": r.capped_actions(DEFAULT_MARKET_SHARE),
        "speed": r.speed,
        "gp_per_hour": r.gp_per_hour(),
        "xp_per_hour": r.xp_per_hour(),
        "hour_bound": (r.hour_plan(DEFAULT_MARKET_SHARE) or (None, None))[1],
        "xp_pace": xp_pace(r, refs or {}),
    } for r in results], indent=2)


# --------------------------------------------------------------------------- cli

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Find profitable OSRS production activities (gp/xp).")
    ap.add_argument("--recipes", type=Path, default=DEFAULT_RECIPES, help="recipe TOML file")
    ap.add_argument("--mode", choices=MODES, default="conservative",
                    help="which GE price to use for buying/selling (default: conservative)")
    ap.add_argument("--source", choices=SOURCES, default=DEFAULT_SOURCE,
                    help="1h = hourly averages (default), 5m = 5-minute averages, "
                         "latest = single most recent trades")
    ap.add_argument("--no-tax", action="store_true", help="ignore the 2%% GE sale tax")
    ap.add_argument("--skill", action="append", help="only show this skill (repeatable)")
    ap.add_argument("--profitable", action="store_true", help="only show recipes with profit > 0")
    ap.add_argument("--json", action="store_true", help="output JSON instead of a table")
    ap.add_argument("--html", type=Path, metavar="FILE",
                    help="also write a sortable web page of the results to FILE")
    ap.add_argument("--watch", type=int, metavar="SECONDS",
                    help="re-fetch prices and reprint every N seconds")
    ap.add_argument("--no-wiki", action="store_true",
                    help="use only recipes.toml, not the downloaded Wiki recipes")
    ap.add_argument("--min-volume", type=int, default=DEFAULT_MIN_VOLUME, metavar="N",
                    help=f"hide recipes whose least-traded item had fewer than N trades in the "
                         f"price window (default {DEFAULT_MIN_VOLUME}; the web page has its own control)")
    ap.add_argument("--verbose", action="store_true", help="list every skipped recipe")
    ap.add_argument("--mapping-file", type=Path, help="use a saved /mapping JSON instead of the API")
    ap.add_argument("--fallback-file", type=Path,
                    help="saved /latest JSON used to fill gaps in --prices-file")
    ap.add_argument("--prices-file", type=Path, help="use a saved /1h, /5m or /latest JSON instead of the API")
    args = ap.parse_args(argv)

    recipes = load_recipes(args.recipes)
    if not args.no_wiki:
        from wiki_recipes import CACHE, convert, load_cache
        rows = load_cache()
        if rows is None:
            print(f"note: no Wiki recipe cache at {CACHE}; using recipes.toml only. "
                  "Run 'python3 wiki_recipes.py' to download the full list.", file=sys.stderr)
        else:
            recipes = merge_recipes(recipes, convert(rows))
    recipes = apply_excludes(recipes, load_excludes(args.recipes))
    recipes = apply_speed_overrides(recipes, load_speed_overrides(args.recipes),
                                    load_hourly_fees(args.recipes))
    if args.skill:
        wanted = {s.lower() for s in args.skill}
        recipes = [r for r in recipes
                   if wanted & {part.strip().lower() for part in r.skill.split("+")}]

    if args.mapping_file:
        mapping_raw = json.loads(args.mapping_file.read_text())
    else:
        mapping_raw = fetch_mapping_raw()
        save_last_fetch("last_mapping.json", mapping_raw)
    ids, limits = parse_mapping(mapping_raw), parse_limits(mapping_raw)

    while True:
        if args.prices_file:
            prices = parse_prices(json.loads(args.prices_file.read_text()))
            if args.fallback_file:
                prices = fill_missing(prices, parse_prices(json.loads(args.fallback_file.read_text())))
        else:
            prices_raw = fetch_prices_raw(args.source)
            save_last_fetch(f"last_{args.source}.json", prices_raw)
            prices = parse_prices(prices_raw)
            if args.source != "latest":
                # Thinly traded items often miss a side in the averaging window.
                latest_raw = fetch_prices_raw("latest")
                save_last_fetch("last_latest.json", latest_raw)
                prices = fill_missing(prices, parse_prices(latest_raw))
        volume_hours = SOURCE_HOURS.get(args.source, 1.0)
        results, errors = evaluate_all(recipes, ids, prices, args.mode, not args.no_tax, limits,
                                       volume_hours)
        if args.profitable:
            results = [r for r in results if r.profit > 0]
        if not args.html:  # the web page has its own volume control
            results = [r for r in results if passes_volume(r, args.min_volume)]

        if args.json:
            print(to_json(results, reference_rates(results, load_normal_training(args.recipes))))
        else:
            print(f"\n{time.strftime('%Y-%m-%d %H:%M:%S')}  source={args.prices_file or args.source}  mode={args.mode}  "
                  f"tax={'off' if args.no_tax else 'on'}  {len(results)} recipes")
            print(render_table(results))
        if errors:
            if args.verbose:
                for name, msg in errors:
                    print(f"skipped '{name}': {msg}", file=sys.stderr)
            else:
                print(f"{len(errors)} recipes skipped (an item isn't on the GE or has no recent "
                      "price); add --verbose to list them", file=sys.stderr)
        refs = reference_rates(results, load_normal_training(args.recipes))
        if args.html:
            from web import render_html
            meta = {"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "source": str(args.prices_file or args.source), "mode": args.mode,
                    "tax": not args.no_tax, "skipped": len(errors),
                    "min_volume": args.min_volume, "market_share": DEFAULT_MARKET_SHARE,
                    "references": refs}
            args.html.write_text(render_html(results, meta), encoding="utf-8")
            print(f"wrote {args.html}", file=sys.stderr)

        if not args.watch:
            return 0
        time.sleep(args.watch)


if __name__ == "__main__":
    sys.exit(main())
