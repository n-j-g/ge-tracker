"""XP-price study: what the market charges for XP, per skill, since 2021.

For each training method: gold lost per XP when buying inputs and selling
outputs instantly (after the tax in force), hour by hour. A skill's price of
XP on a day is its cheapest listed method that day (methods differ in speed;
see chains.py).

Outputs (data/history/results/):
  xp_price.json        summary per method and per skill
  xp_price_daily.csv   daily median gp/XP per method and per skill (cheapest method)
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from research.chains import CHAINS
from research.history import chain_values, load
from research.margin_study import OUT

BIG_GOAL_XP = 10_000_000          # "what would 10M XP cost" comparisons


def rhythm(series: pd.Series) -> dict:
    """Hour-of-day and day-of-week pattern of a price, as % deviation from its
    centred 24-hour (resp. 7-day) average, so trends don't leak in."""
    s = series.dropna()
    hourly = (s / s.rolling(24, center=True, min_periods=18).mean() - 1).dropna()
    by_hour = hourly.groupby(hourly.index.hour).mean()
    daily = s.resample("D").mean()
    dly = (daily / daily.rolling(7, center=True, min_periods=6).mean() - 1).dropna()
    by_dow = dly.groupby(dly.index.dayofweek).mean()
    return {"by_utc_hour_pct": {int(h): float(v) for h, v in by_hour.items()},
            "cheapest_utc_hour": int(by_hour.idxmin()), "dearest_utc_hour": int(by_hour.idxmax()),
            "hour_swing_pct": float(by_hour.max() - by_hour.min()),
            "by_weekday_pct": {int(d): float(v) for d, v in by_dow.items()},  # 0 = Monday
            "cheapest_weekday": int(by_dow.idxmin()), "dearest_weekday": int(by_dow.idxmax()),
            "weekday_swing_pct": float(by_dow.max() - by_dow.min())}


def summarise(daily: pd.Series) -> dict:
    d = daily.dropna()
    last7 = float(d.iloc[-7:].median())
    monthly = d.resample("MS").mean().dropna()
    # changes in gp/XP (not %, since some skills' XP price is close to zero)
    roll14 = d.rolling(14).mean()
    rise = (roll14 - roll14.shift(14)).dropna()
    return {
        "median": float(d.median()), "p10": float(d.quantile(0.1)), "p90": float(d.quantile(0.9)),
        "min": float(d.min()), "min_date": str(d.idxmin().date()),
        "max": float(d.max()), "max_date": str(d.idxmax().date()),
        "last_7d": last7, "last_7d_percentile": float((d < last7).mean()),
        "by_year": {int(k): float(v) for k, v in d.groupby(d.index.year).median().items()},
        "cheapest_month": [str(monthly.idxmin().date())[:7], float(monthly.min())],
        "dearest_month": [str(monthly.idxmax().date())[:7], float(monthly.max())],
        "median_month": float(monthly.median()),
        "biggest_14d_rise": [str(rise.idxmax().date()), float(rise.max())],
        "biggest_14d_fall": [str(rise.idxmin().date()), float(rise.min())],
    }


def run() -> dict:
    p = load()
    methods = [c for c in CHAINS if c.xp_method]
    daily, out = {}, {"methods": {}, "skills": {}}
    for c in methods:
        ex = chain_values(c, p, "executable")
        mid = chain_values(c, p, "mid")
        d = ex.gp_per_xp.resample("D").median()
        daily[c.name] = d
        cost = sum(q * p["mid"][i] for i, q in c.inputs.items())
        # trading at the mid price instead of instantly: gp/XP saved, and as a share of input spend
        saved = (ex.gp_per_xp - mid.gp_per_xp)
        out["methods"][c.name] = {"skill": c.skill, **summarise(d), "input_rhythm": rhythm(cost),
                                  "patient_saving_gp_per_xp": float(saved.median()),
                                  "patient_saving_share_of_spend": float((saved * c.xp / ex.cost).median())}
        s = out["methods"][c.name]
        print(f"{c.name:38} median {s['median']:7.1f} gp/xp  now {s['last_7d']:7.1f} "
              f"(pct {100*s['last_7d_percentile']:3.0f})  hour swing {100*s['input_rhythm']['hour_swing_pct']:.1f}%")
    df = pd.DataFrame(daily)
    for skill in sorted({c.skill for c in methods}):
        cols = [c.name for c in methods if c.skill == skill]
        cheapest = df[cols].min(axis=1)
        which = df[cols].idxmin(axis=1)
        s = summarise(cheapest)
        monthly = cheapest.resample("MS").mean().dropna()
        s["goal_cost_10M"] = {"cheapest_month": float(monthly.min() * BIG_GOAL_XP),
                              "median_month": float(monthly.median() * BIG_GOAL_XP),
                              "dearest_month": float(monthly.max() * BIG_GOAL_XP)}
        s["methods"] = cols
        s["cheapest_method_share"] = {k: float(v) for k, v in which.value_counts(normalize=True).items()}
        out["skills"][skill] = s
        df[f"[{skill}]"] = cheapest
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "xp_price.json").write_text(json.dumps(out, indent=1))
    df.to_csv(OUT / "xp_price_daily.csv")
    return out


if __name__ == "__main__":
    run()
