"""Can a main act on an unusually wide margin in time to profit from it?

Simulates: hour t's average shows the margin entering its top 10% vs the past
30 days (detectable only once hour t ends). The player buys inputs instantly
during hour t+1, processes for d hours, and sells outputs instantly at hour
t+1+d. Compares the realised margin with the normal margin (trailing 30-day
median), and splits the extra into the input side (inputs cheaper than usual,
locked in when you buy) and the output side (outputs dearer than usual, which
must last until you sell).
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from research.chains import CHAINS
from research.history import chain_values, load, net_of_tax, tax_rate
from research.margin_study import OUT, trailing_norm, trailing_quantile

SELL_DELAYS = [0, 1, 3, 6, 24]


def sides(chain, p):
    """Hourly instant-buy input cost and instant-sell output value (after tax)."""
    buy = np.fmax(p["high"], p["low"]); sell = np.fmin(p["high"], p["low"])
    rate = tax_rate(p["mid"].index)
    cost = sum(q * buy[i] for i, q in chain.inputs.items()) + chain.fee
    value = sum(q * net_of_tax(sell[i], rate) for i, q in chain.outputs.items())
    return cost, value


def run():
    p = load()
    res = {}
    for c in [c for c in CHAINS if c.margin]:
        cost, value = sides(c, p)
        m = value - cost
        norm, thr = trailing_norm(m), trailing_quantile(m, 0.9)
        norm_cost, norm_value = trailing_norm(cost), trailing_norm(value)
        inside = m > thr
        recent = inside.shift(1).rolling(6, min_periods=1).max().fillna(0).astype(bool)
        starts = np.flatnonzero((inside & ~recent & norm.notna()).values)
        n = len(m)
        starts = starts[starts + 1 + max(SELL_DELAYS) < n]
        months = (m.index[-1] - m.index[0]).days / 30.4
        gap0 = (m.values[starts] - norm.values[starts])
        r = {"skill": c.skill, "episodes_per_month": len(starts) / months,
             "normal_margin": float(np.nanmedian(norm.values[starts])),
             "gap_seen": float(np.nanmean(gap0))}
        t1 = starts + 1
        in_gain = norm_cost.values[starts] - cost.values[t1]          # inputs cheaper than usual, locked at purchase
        r["input_side_seen"] = float(np.nanmean(norm_cost.values[starts] - cost.values[starts]))
        r["input_side_locked"] = float(np.nanmean(in_gain))
        for d in SELL_DELAYS:
            out_gain = value.values[t1 + d] - norm_value.values[starts]
            extra = (value.values[t1 + d] - cost.values[t1]) - norm.values[starts]
            r[f"extra_sell_{d}h"] = float(np.nanmean(extra))
            r[f"hit_rate_{d}h"] = float(np.nanmean(extra > 0))
            r[f"output_side_{d}h"] = float(np.nanmean(out_gain))
        r["output_side_seen"] = float(np.nanmean(value.values[starts] - norm_value.values[starts]))
        res[c.name] = r
    (OUT / "early_detection.json").write_text(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    res = run()
    print(f"{'chain':30} {'ep/mo':>5} {'normal':>7} {'gap seen':>8} | {'extra if sell at +1h / +4h / +25h':>32} | {'hit +4h':>7} | {'input locked':>12} {'output@+4h':>10}")
    for k, r in res.items():
        print(f"{k[:30]:30} {r['episodes_per_month']:5.1f} {r['normal_margin']:7.0f} {r['gap_seen']:8.0f} | "
              f"{r['extra_sell_0h']:9.0f} {r['extra_sell_3h']:9.0f} {r['extra_sell_24h']:9.0f}      | {100*r['hit_rate_3h']:6.0f}% | "
              f"{r['input_side_locked']:12.0f} {r['output_side_3h']:10.0f}")
