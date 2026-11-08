#!/usr/bin/env python3
"""Group suspected gold transfers (research/transfer_scan.py output) into episodes and
backtest a resting "trap" sell offer. Standard library only.

An event = an hour where a cheap item traded at >= 20x its month's median and the gold
above normal (excess = (price - typical) x volume) was >= MIN_EXCESS.
Items' first 30 days on the GE are dropped (launch prices are not transfers).
Episodes = events on the same item less than 12 hours apart.
"""
from __future__ import annotations
import csv, json, sqlite3, statistics, collections, datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FULL = ROOT / "data" / "history" / "prices_1h.sqlite"
EVENTS = ROOT / "data" / "history" / "results" / "transfer_events.csv"
OUTDIR = ROOT / "data" / "history" / "results"
MIN_EXCESS = 10_000_000
DAY = 86400

src = sqlite3.connect(f"file:{FULL}?mode=ro", uri=True)
lo, hi = src.execute("SELECT MIN(ts), MAX(ts) FROM fetched WHERE n_items > 0").fetchone()
first_seen: dict[int, int] = {}
hours = list(range(lo, hi + 1, DAY // 4))          # four sampled hours a day
for i in range(0, len(hours), 300):
    b = hours[i:i + 300]
    for ts, item in src.execute(f"SELECT ts, item_id FROM prices WHERE ts IN ({','.join(map(str, b))})"):
        if item not in first_seen or ts < first_seen[item]:
            first_seen[item] = ts

ev = []
for r in csv.DictReader(EVENTS.open()):
    item, ts = int(r["item_id"]), int(r["ts"])
    if item not in first_seen or ts < first_seen[item] + 30 * DAY:
        continue
    r["excess"] = (int(r["price"]) - float(r["typical"])) * int(r["volume"])
    if r["excess"] >= MIN_EXCESS:
        ev.append(r)

# collapse to item-hours (both sides can be flagged in one hour)
ih = {}
for r in ev:
    k = (int(r["item_id"]), int(r["ts"]))
    if k not in ih:
        ih[k] = dict(item=k[0], ts=k[1], name=r["name"], typical=float(r["typical"]), units=0, gold=0.0, top=0, sides=set())
    ih[k]["units"] += int(r["volume"]); ih[k]["gold"] += int(r["price"]) * int(r["volume"])
    ih[k]["top"] = max(ih[k]["top"], int(r["price"])); ih[k]["sides"].add(r["side"])

episodes = []
for item in sorted({k[0] for k in ih}):
    hs = sorted((v for k, v in ih.items() if k[0] == item), key=lambda v: v["ts"])
    cur = None
    for h in hs:
        if cur and h["ts"] - cur["end"] < 12 * 3600:
            cur["end"] = h["ts"]; cur["hours"] += 1; cur["units"] += h["units"]; cur["gold"] += h["gold"]
            cur["min_price"] = min(cur["min_price"], h["gold"] / h["units"]); cur["sides"] |= h["sides"]
        else:
            cur = dict(item=item, name=h["name"], start=h["ts"], end=h["ts"], hours=1, units=h["units"],
                       gold=h["gold"], typical=h["typical"], min_price=h["gold"] / h["units"], sides=set(h["sides"]))
            episodes.append(cur)

f = lambda t: dt.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d %H:00")
with (OUTDIR / "transfer_episodes.csv").open("w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["item_id", "name", "start_utc", "hours", "units", "gold", "avg_price", "lowest_hour_avg", "typical", "sides"])
    for e in sorted(episodes, key=lambda e: e["start"]):
        w.writerow([e["item"], e["name"], f(e["start"]), e["hours"], e["units"], round(e["gold"]),
                    round(e["gold"] / e["units"]), round(e["min_price"]), round(e["typical"], 1), "/".join(sorted(e["sides"]))])
json.dump({"n_events": len(ev), "n_item_hours": len(ih), "n_episodes": len(episodes)},
          (OUTDIR / "transfer_summary.json").open("w"))
print(len(ev), "events,", len(ih), "item-hours,", len(episodes), "episodes on", len({e['item'] for e in episodes}), "items")
