#!/usr/bin/env python3
"""Do suspected gold transfers cluster? (input: data/history/results/transfer_episodes.csv)
1. After a transfer on an item, how likely is another on the same item / a sibling (same
   item at another dose or poison level) / anything soon, vs chance?
2. Backtest a *reactive* trap: after each transfer, list that item (and siblings) for D days
   at ASK_FRAC of the price just seen, using at most SLOTS offers (newest triggers win)."""
from __future__ import annotations
import csv, re, collections, statistics, datetime as dt, math
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
E = list(csv.DictReader((ROOT / "data/history/results/transfer_episodes.csv").open()))
for e in E:
    e["t"] = dt.datetime.strptime(e["start_utc"], "%Y-%m-%d %H:%M"); e["units"] = int(e["units"])
    e["price"] = float(e["avg_price"]); e["gold"] = float(e["gold"])
E.sort(key=lambda e: e["t"])
def family(n):
    return re.sub(r"\s*\((\d|p\+*|m)\)", "", n).strip().lower()
for e in E: e["fam"] = family(e["name"])
T0, T1 = E[0]["t"], E[-1]["t"]; span = (T1 - T0).days

def repeat_stats(key, days):
    by = collections.defaultdict(list)
    for e in E: by[e[key]].append(e["t"])
    hit = exp = n = 0
    for k, ts in by.items():
        rate = len(ts) / span                     # episodes per day for this item/family
        for i, t in enumerate(ts):
            if t + dt.timedelta(days=days) > T1: continue
            n += 1
            hit += any(dt.timedelta(hours=12) <= u - t <= dt.timedelta(days=days) for u in ts[i + 1:])
            exp += 1 - math.exp(-rate * days)
    return hit / n, exp / n

if __name__ == "__main__":
    print("chance of another transfer soon after one (observed vs if spread evenly over 5.6 years):")
    for key, label in (("name", "same item"), ("fam", "same family")):
        for d in (1, 3, 7, 30):
            o, x = repeat_stats(key, d); print(f"  {label:12} within {d:2}d: {o:5.1%} vs {x:5.1%} ({o/x:4.1f}x)")
    # same-day multi-item sessions
    days = collections.defaultdict(set)
    for e in E: days[e["t"].date()].add(e["name"])
    print(f"days with any transfer: {len(days)} of {span}; items per active day: median {statistics.median(len(v) for v in days.values())}, "
          f"share of transfers on days with 3+ items: {sum(len(days[e['t'].date()])>=3 for e in E)/len(E):.0%}")
    # price memory: does a repeat on the same item reuse the same price?
    by = collections.defaultdict(list)
    for e in E: by[e["name"]].append(e)
    ratios = [b["price"] / a["price"] for v in by.values() for a, b in zip(v, v[1:]) if (b["t"] - a["t"]).days <= 30]
    print(f"repeat on same item within 30d: next price / last price median {statistics.median(ratios):.2f}, "
          f"within ±20%: {sum(0.8<=r<=1.25 for r in ratios)/len(ratios):.0%}, at or above 50% of last: {sum(r>=0.5 for r in ratios)/len(ratios):.0%}")

def reactive(days=7, slots=8, ask_frac=0.5, siblings=True, start=dt.datetime(2022, 1, 1), end=None):
    end = end or T1
    traps = collections.OrderedDict()            # key -> (expires, ask, stock)
    gold = hits = considered = 0; per_month = collections.Counter(); caught_gold = 0
    for e in E:
        if e["t"] < start - dt.timedelta(days=days) or e["t"] > end: continue
        for k in list(traps):
            if traps[k][0] < e["t"]: del traps[k]
        if e["t"] >= start:
            considered += 1
            for k in ((e["name"], e["fam"]) if siblings else (e["name"],)):
                if k in traps and e["price"] >= traps[k][1]:
                    g = traps[k][1] * min(e["units"], traps[k][2]); gold += g; hits += 1
                    per_month[e["t"].strftime("%Y-%m")] += g; break
        for k in ((e["name"], e["fam"]) if siblings else (e["name"],)):
            traps.pop(k, None); traps[k] = (e["t"] + dt.timedelta(days=days), ask_frac * e["price"], 2 * e["units"])
        while len(traps) > slots: traps.popitem(last=False)
    months = max(1, round((end - start).days / 30.4))
    vals = [per_month.get(m, 0) for m in sorted({(start + dt.timedelta(days=30.4 * i)).strftime("%Y-%m") for i in range(months)})]
    return dict(hits=hits, of=considered, gold=gold, mean_month=gold / months, median_month=statistics.median(vals), months_with_hit=sum(v > 0 for v in vals) / len(vals))

if __name__ == "__main__":
    print("\nreactive trap (list the item just used, and its family, at half the price seen):")
    for kw in (dict(), dict(days=3), dict(days=30), dict(siblings=False), dict(slots=3), dict(ask_frac=0.25),
               dict(start=dt.datetime(2025, 1, 1)), dict(start=dt.datetime(2026, 1, 1))):
        r = reactive(**kw)
        print(f"  {str({k:(v.date() if isinstance(v, dt.datetime) else v) for k,v in kw.items()}) or 'default':34} hits {r['hits']:4}/{r['of']:5} "
              f"({r['hits']/r['of']:4.1%})  mean {r['mean_month']/1e6:6.0f}m/mo  median {r['median_month']/1e6:6.0f}m/mo  months with a catch {r['months_with_hit']:.0%}")
