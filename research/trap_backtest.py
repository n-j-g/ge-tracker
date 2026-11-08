#!/usr/bin/env python3
"""Backtest resting 'trap' sell offers against suspected gold transfers
(data/history/results/transfer_episodes.csv, from transfer_episodes.py).

Each month: pick the SLOTS items with the most transfer episodes in the previous LOOKBACK
days (no look-ahead), hold STOCK_MULT x their median past episode size, and list them at
ASK_FRAC x their median past transfer price. During the month, an episode on a trapped
item at an average price >= our ask is assumed to fill our offer first (GE price
priority), up to our stock. Very optimistic on mechanics; a ceiling, not a forecast.
"""
from __future__ import annotations
import csv, statistics, collections, datetime as dt, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
E = list(csv.DictReader((ROOT / "data/history/results/transfer_episodes.csv").open()))
for e in E:
    e["t"] = dt.datetime.strptime(e["start_utc"], "%Y-%m-%d %H:%M")
    e["units"] = int(e["units"]); e["price"] = float(e["avg_price"]); e["gold"] = float(e["gold"])

def run(slots=8, lookback=365, ask_frac=0.5, stock_mult=2.0, first_only=False, start=dt.datetime(2022, 3, 1)):
    month, end = start, max(e["t"] for e in E)
    rows, caught_items = [], set()
    while month < end:
        nxt = (month.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
        past = [e for e in E if month - dt.timedelta(days=lookback) <= e["t"] < month]
        by = collections.defaultdict(list)
        for e in past: by[e["name"]].append(e)
        picks = sorted(by, key=lambda n: (-len(by[n]), n))[:slots]
        traps = {n: (ask_frac * statistics.median(x["price"] for x in by[n]),
                     stock_mult * statistics.median(x["units"] for x in by[n])) for n in picks}
        now = [e for e in E if month <= e["t"] < nxt]
        gold = hits = 0
        for e in now:
            if e["name"] in traps and e["price"] >= traps[e["name"]][0]:
                if first_only and e["name"] in caught_items: continue
                ask, stock = traps[e["name"]]
                gold += ask * min(e["units"], stock); hits += 1; caught_items.add(e["name"])
        rows.append((month.strftime("%Y-%m"), len(now), sum(e["name"] in traps for e in now), hits, gold,
                     sum(e["gold"] for e in now)))
        month = nxt
    return rows

def summary(rows, label):
    g = [r[4] for r in rows]; months = len(rows)
    print(f"{label:42} months={months} eps_on_traps={sum(r[2] for r in rows)/sum(r[1] for r in rows):5.1%} "
          f"hits={sum(r[3] for r in rows):4} months_with_hit={sum(r[3]>0 for r in rows)/months:5.1%} "
          f"median/month={statistics.median(g)/1e6:7.1f}m mean/month={statistics.mean(g)/1e6:7.1f}m "
          f"share_of_transfer_gold={sum(g)/sum(r[5] for r in rows):5.1%}")

if __name__ == "__main__":
    for kw in [dict(), dict(ask_frac=0.25), dict(ask_frac=0.75), dict(slots=3), dict(lookback=90),
               dict(stock_mult=1.0), dict(first_only=True), dict(start=dt.datetime(2025, 1, 1))]:
        summary(run(**kw), ",".join(f"{k}={v if not isinstance(v, dt.datetime) else v.date()}" for k, v in kw.items()) or "default (8 slots, 365d, 50%, 2x)")
    print()
    for r in run(start=dt.datetime(2025, 11, 1)):
        print(f"  {r[0]} episodes={r[1]:3} on_traps={r[2]:2} hits={r[3]:2} caught={r[4]/1e6:7.1f}m")
