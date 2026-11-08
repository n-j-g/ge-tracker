#!/usr/bin/env python3
"""What happens on a transfer item in the hours before a suspected transfer?
Needs transfer_items_extract.py output. Compares the 48h before each episode (since Feb 2024)
with the same item's normal activity in days 30..3 before."""
from __future__ import annotations
import csv, sqlite3, statistics, collections, datetime as dt
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
db = sqlite3.connect(str(Path.home() / "scratch" / "transfer_items.sqlite"))
E = [e for e in csv.DictReader((ROOT / "data/history/results/transfer_episodes.csv").open()) if e["start_utc"] >= "2024-02-01"]
H = 3600
res = []
for e in E:
    item = int(e["item_id"]); t = int(dt.datetime.strptime(e["start_utc"], "%Y-%m-%d %H:%M").replace(tzinfo=dt.timezone.utc).timestamp())
    typ = float(e["typical"]); units = int(e["units"])
    rows = db.execute("SELECT ts, avg_high, high_vol, avg_low, low_vol FROM prices WHERE item_id=? AND ts>=? AND ts<=?", (item, t - 30 * 24 * H, t)).fetchall()
    def stats(a, b):
        hrs = trade_hrs = spike_hrs = 0; normal_vol = 0
        for ts, h, hv, l, lv in rows:
            if a <= ts < b:
                trade_hrs += 1
                spike = any(p and v and p >= 20 * typ for p, v in ((h, hv), (l, lv)))
                spike_hrs += spike
                normal_vol += sum(v for p, v in ((h, hv), (l, lv)) if p and v and p < 5 * typ)
        return trade_hrs, spike_hrs, normal_vol
    base = stats(t - 30 * 24 * H, t - 3 * 24 * H); n_base = 27 * 24
    pre = stats(t - 48 * H, t); pre6 = stats(t - 6 * H, t)
    same = [r for r in rows if r[0] == t][0]
    same_normal = sum(v for p, v in ((same[1], same[2]), (same[3], same[4])) if p and v and p < 5 * typ)
    res.append(dict(name=e["name"], units=units, p_trade=base[0] / n_base, p_spike=base[1] / n_base, base_normal_per_hr=base[2] / n_base,
                    pre_trade=pre[0], pre_spike=pre[1], pre_normal=pre[2], pre6_trade=pre6[0], pre6_normal=pre6[2], same_normal=same_normal))
n = len(res); med = statistics.median
print(f"{n} episodes since Feb 2024")
print(f"typical item: trades in {med(r['p_trade'] for r in res):.1%} of normal hours; small spike prints in {med(r['p_spike'] for r in res):.2%}")
exp48 = [1 - (1 - r['p_trade']) ** 48 for r in res]
print(f"any trade in the 48h before: {sum(r['pre_trade']>0 for r in res)/n:.0%} (expected from normal activity {statistics.mean(exp48):.0%})")
exp6 = [1 - (1 - r['p_trade']) ** 6 for r in res]
print(f"any trade in the 6h before:  {sum(r['pre6_trade']>0 for r in res)/n:.0%} (expected {statistics.mean(exp6):.0%})")
expsp = [1 - (1 - r['p_spike']) ** 48 for r in res]
print(f"a small high-price 'test' print in the 48h before: {sum(r['pre_spike']>0 for r in res)/n:.0%} (expected {statistics.mean(expsp):.0%})")
print(f"normal-price volume in 48h before, as share of transfer size: median {med(r['pre_normal']/r['units'] for r in res):.0%}; "
      f"same hour: median {med(r['same_normal']/r['units'] for r in res):.0%}, >=50% in {sum(r['same_normal']>=0.5*r['units'] for r in res)/n:.0%} of episodes")
print(f"normal-price volume in 48h before vs normal 48h: median ratio {med((r['pre_normal']+1)/(48*r['base_normal_per_hr']+1) for r in res):.1f}x")
# precision: of all small test prints on these items, how many are followed by an episode within 48h?
eps_by_item = collections.defaultdict(list)
for e in csv.DictReader((ROOT / "data/history/results/transfer_episodes.csv").open()):
    eps_by_item[int(e["item_id"])].append((int(dt.datetime.strptime(e["start_utc"], "%Y-%m-%d %H:%M").replace(tzinfo=dt.timezone.utc).timestamp()), float(e["typical"])))
lo = int(dt.datetime(2024, 2, 1, tzinfo=dt.timezone.utc).timestamp())
tests = followed = 0
for item, eps in eps_by_item.items():
    typ = med(x[1] for x in eps); starts = sorted(x[0] for x in eps)
    for ts, h, hv, l, lv in db.execute("SELECT ts, avg_high, high_vol, avg_low, low_vol FROM prices WHERE item_id=? AND ts>=?", (item, lo)):
        if ts in starts: continue
        if any(p and v and p >= 20 * typ and p * v < 10e6 for p, v in ((h, hv), (l, lv))):
            tests += 1; followed += any(0 < s - ts <= 48 * H for s in starts)
print(f"small test prints on transfer items since Feb 2024: {tests}; followed by a transfer within 48h: {followed/tests:.0%}")
