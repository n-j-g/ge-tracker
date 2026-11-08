#!/usr/bin/env python3
"""Download every production recipe from the OSRS Wiki and convert it to Recipe objects.

The Wiki stores its recipe boxes as structured data in the "recipe" bucket
(https://oldschool.runescape.wiki/w/Bucket:Recipe). Run this file to refresh
the local cache:

    python3 wiki_recipes.py

which writes data/wiki_recipes.json. ge_profit.py reads that cache, so the
Wiki is only contacted when you choose to refresh.
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from ge_profit import USER_AGENT, Recipe

WIKI_API = "https://oldschool.runescape.wiki/api.php"
PAGE_SIZE = 5000  # the bucket API's maximum rows per request
CACHE = Path(__file__).with_name("data") / "wiki_recipes.json"


# --------------------------------------------------------------------------- fetch

def _query(offset: int) -> list[dict]:
    q = ("bucket('recipe').select('page_name','page_name_sub','source_template','production_json')"
         f".where('source_template','recipe').limit({PAGE_SIZE}).offset({offset}).run()")
    url = f"{WIKI_API}?action=bucket&format=json&query={urllib.parse.quote(q)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.load(resp)
    if "error" in data:
        raise RuntimeError(f"Wiki API error: {data['error']}")
    return data.get("bucket", [])


def fetch_raw() -> list[dict]:
    """All recipe rows from the Wiki, paging until a short page comes back."""
    rows, offset = [], 0
    while True:
        page = _query(offset)
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        offset += PAGE_SIZE


def refresh_cache(path: Path = CACHE) -> int:
    rows = fetch_raw()
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(rows), encoding="utf-8")
    return len(rows)


def load_cache(path: Path = CACHE) -> list[dict] | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


# --------------------------------------------------------------------------- convert

def _num(value) -> float | None:
    """Parse '1,234' / '6.2' / 5 as a number; None for 'Varies', '1-5', blanks, etc."""
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return None


# "Tools" that are spells or worn items rather than something taking an inventory slot.
_NOT_INVENTORY = ("magic imbue", "string jewellery", "necklace", "tiara")


def _tools(value) -> tuple[str, ...]:
    if not value:
        return ()
    names = [t.strip().strip("[]").split("|")[0] for t in str(value).split(",")]
    return tuple(n for n in names if n and not any(x in n.lower() for x in _NOT_INVENTORY))


def convert_row(row: dict, lenient: bool = False) -> Recipe | None:
    """One Wiki row -> Recipe, or None if it can't be expressed (non-numeric XP etc.).
    lenient=True keeps recipes whose XP depends on the player (xp=0, xp_varies=True),
    for uses like the supply-chain map where the connection matters more than the XP."""
    try:
        p = json.loads(row["production_json"])
    except (KeyError, TypeError, ValueError):
        return None
    out = p.get("output") or {}
    out_name, out_qty = out.get("name"), _num(out.get("quantity"))
    if not out_name or not out_qty:
        return None
    if out_name.lower().startswith("burnt "):
        return None  # a failure outcome of cooking, not a separate recipe

    inputs: dict[str, float] = {}
    for m in p.get("materials") or []:
        qty = _num(m.get("quantity"))
        if not m.get("name") or qty is None:
            return None
        inputs[m["name"]] = inputs.get(m["name"], 0) + qty
    if not inputs:
        return None

    xp, skills, levels, varies = 0.0, [], [], False
    for s in p.get("skills") or []:
        val = _num(s.get("experience"))
        if val is None:
            if not lenient:
                return None  # e.g. "1×Construction level": depends on the player
            varies, val = True, 0.0
        xp += val
        if s.get("name"):
            name = s["name"].strip()
            name = name[:1].upper() + name[1:]  # a few rows say "cooking"
            skills.append(name)
            lvl = _num(s.get("level"))
            if lvl is not None:
                levels.append((name, int(lvl)))

    name = out_name + (f" ({out['subtxt']})" if out.get("subtxt") else "")
    return Recipe(
        name=name,
        skill=" + ".join(skills) or "None",
        xp=xp,
        inputs=inputs,
        outputs={out_name: out_qty},
        ticks=_num(p.get("ticks")),
        members=p.get("members"),
        facility=p.get("facilities") or None,
        tools=_tools(p.get("tools")),
        source="wiki",
        levels=tuple(levels),
        xp_varies=varies,
    )


def convert(rows: list[dict], lenient: bool = False) -> list[Recipe]:
    return [r for r in (convert_row(row, lenient) for row in rows) if r is not None]


if __name__ == "__main__":
    print("Downloading recipes from the OSRS Wiki...")
    n = refresh_cache()
    print(f"Saved {n:,} recipe rows to {CACHE}. Usable recipes: {len(convert(load_cache())):,}")
