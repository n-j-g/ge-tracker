#!/usr/bin/env python3
"""Build the data for the supply-chain map: every Wiki recipe (tradeable or not)
plus current GE prices, as one compact JSON file the page loads.

    python3 chain/build_graph.py                       # live prices -> chain/graph.json
    python3 chain/build_graph.py --offline --out x.json # use data/last_*.json instead

Items are listed once and referred to by position; recipes carry profit, GP/hr
and XP/hr from the same model as the main page (conservative pricing, GE tax,
speed/buy-limit/volume limits), where every item has a price.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ge_profit as g  # noqa: E402
from wiki_recipes import convert, load_cache  # noqa: E402

DATA = ROOT / "data"


def load_market(offline: bool):
    if offline:
        mapping = json.loads((DATA / "last_mapping.json").read_text())
        prices = g.fill_missing(g.parse_prices(json.loads((DATA / "last_1h.json").read_text())),
                                g.parse_prices(json.loads((DATA / "last_latest.json").read_text())))
        stamp = int((DATA / "last_1h.json").stat().st_mtime)
    else:
        mapping = g.fetch_mapping_raw()
        prices = g.fill_missing(g.fetch_prices("1h"), g.fetch_prices("latest"))
        stamp = int(time.time())
    return mapping, prices, stamp


def build(offline: bool = False) -> dict:
    rows = load_cache()
    if rows is None:
        raise SystemExit("No Wiki recipe cache: run python3 wiki_recipes.py first")
    recipes = g.merge_recipes(g.load_recipes(g.DEFAULT_RECIPES), convert(rows, lenient=True))
    recipes = g.apply_excludes(recipes, g.load_excludes(g.DEFAULT_RECIPES))
    recipes = g.apply_speed_overrides(recipes, g.load_speed_overrides(g.DEFAULT_RECIPES),
                                      g.load_hourly_fees(g.DEFAULT_RECIPES))
    mapping, prices, stamp = load_market(offline)
    ids, limits = g.parse_mapping(mapping), g.parse_limits(mapping)
    by_name = {m["name"].lower(): m for m in mapping}

    # one entry per distinct recipe (the Wiki repeats some rows)
    seen, unique = set(), []
    for r in recipes:
        key = (r.name.lower(), r.signature(), r.skill)
        if key not in seen:
            seen.add(key)
            unique.append(r)

    index: dict[str, int] = {}
    items: list[dict] = []

    def item(name: str) -> int:
        key = name.lower()
        if key in index:
            return index[key]
        m = by_name.get(key)
        entry = {"n": m["name"] if m else name, "ic": (m.get("icon") if m else None) or f"{name}.png"}
        if m:
            p = prices.get(m["id"])
            entry.update({"id": m["id"], "l": m.get("limit"), "m": bool(m.get("members"))})
            if p is not None:
                entry.update({"b": p.high, "s": p.low,
                              "v": (p.high_volume or 0) + (p.low_volume or 0) if p.high_volume is not None else None})
        index[key] = len(items)
        items.append(entry)
        return index[key]

    out_recipes = []
    for r in unique:
        rec = {"n": r.name, "k": r.skill, "x": r.xp,
               "i": [[item(n), q] for n, q in r.inputs.items() if n.lower() != g.COINS],
               "o": [[item(n), q] for n, q in r.outputs.items() if n.lower() != g.COINS]}
        coins = sum(q for n, q in r.inputs.items() if n.lower() == g.COINS)
        if coins:
            rec["c"] = coins
        if r.xp_varies:
            rec["xv"] = 1
        if r.levels:
            rec["lv"] = [list(l) for l in r.levels]
        if r.facility:
            rec["f"] = r.facility
        if r.tools:
            rec["t"] = list(r.tools)
        if r.members is not None:
            rec["m"] = bool(r.members)
        try:
            res = g.evaluate(r, ids, prices, "conservative", True, limits)
        except g.PricingError:
            res = None
        if res is not None:
            rec["p"] = round(res.profit, 1)
            plan = res.hour_plan(g.DEFAULT_MARKET_SHARE)
            if plan is not None:
                rec["g"] = round(res.profit * plan[0])
                rec["xh"] = round(r.xp * plan[0])
                rec["bd"] = plan[1]
            if res.min_volume is not None:
                rec["mv"] = res.min_volume
        out_recipes.append(rec)
    return {"generated": int(time.time()), "prices_at": stamp, "market_share": g.DEFAULT_MARKET_SHARE,
            "items": items, "recipes": out_recipes}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=Path(__file__).with_name("graph.json"))
    ap.add_argument("--offline", action="store_true", help="use data/last_*.json instead of the API")
    args = ap.parse_args(argv)
    graph = build(args.offline)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(graph, separators=(",", ":")), encoding="utf-8")
    priced = sum("p" in r for r in graph["recipes"])
    print(f"{len(graph['items']):,} items, {len(graph['recipes']):,} recipes ({priced:,} priced) "
          f"-> {args.out} ({args.out.stat().st_size / 1e6:.1f} MB)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
