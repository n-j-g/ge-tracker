"""Margin study: how processing margins behave over time.

For each margin chain:
  level       median margin (gp/action and % of input cost), by year
  profitable  share of hours profitable when trading instantly; typical length
              of profitable and unprofitable spells
  stability   Augmented Dickey-Fuller test on the daily margin (% of input cost):
              does it keep returning to a level, or wander?
  half-life   gaps from the trailing 30-day norm: hours until the typical gap
              has halved (from the decay of its autocorrelation)
  events      when the margin enters its top 10% versus the past 30 days,
              how much of the excess is left 1h..7d later (no look-ahead)
  tax         change in margin around the 1% (2021) and 2% (2025) tax changes
  pass-through how much of an input-cost change shows up in the output price,
              and how fast (distributed-lag regression on hourly changes)
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller

from research.chains import CHAINS
from research.history import ROOT, TAX_SCHEDULE, chain_values, load, tax_rate

OUT = ROOT / "data" / "history" / "results"
NORM_WINDOW = "30D"
EVENT_HORIZONS = [1, 3, 6, 12, 24, 48, 72, 168]


def trailing_norm(s: pd.Series) -> pd.Series:
    """Median of the previous 30 days (shifted so it uses only past hours)."""
    return s.rolling(NORM_WINDOW, min_periods=24 * 7).median().shift(1)


def trailing_quantile(s: pd.Series, q: float) -> pd.Series:
    return s.rolling(NORM_WINDOW, min_periods=24 * 7).quantile(q).shift(1)


def spells(flag: pd.Series) -> dict:
    """Lengths (hours) of consecutive runs where flag is True and where it's False."""
    f = flag.dropna().astype(bool)
    if f.empty:
        return {}
    run_id = (f != f.shift()).cumsum()
    runs = f.groupby(run_id).agg(["first", "size"])
    out = {}
    for val, key in [(True, "profitable"), (False, "unprofitable")]:
        lens = runs.loc[runs["first"] == val, "size"]
        out[key] = {"count": int(len(lens)), "median_h": float(lens.median()) if len(lens) else None,
                    "p90_h": float(lens.quantile(0.9)) if len(lens) else None,
                    "longest_h": int(lens.max()) if len(lens) else None}
    return out


def half_life_from_events(ev: dict) -> float | None:
    """First horizon (hours, interpolated) at which half of an unusually wide
    margin's excess is gone. None if it hasn't halved within a week."""
    pts = [(0, 1.0)] + [(h, ev.get(f"left_after_{h}h")) for h in EVENT_HORIZONS]
    pts = [(h, v) for h, v in pts if v is not None]
    for (h0, v0), (h1, v1) in zip(pts, pts[1:]):
        if v1 <= 0.5 < v0:
            return float(h0 + (v0 - 0.5) / (v0 - v1) * (h1 - h0))
    return None


def hour_of_day_profile(m: pd.Series) -> dict:
    """Average gap from the trailing norm by UTC hour of day, as a share of the
    typical margin size: does the margin have a daily rhythm?"""
    dev = m - trailing_norm(m)
    prof = dev.groupby(dev.index.hour).mean()
    scale = m.abs().median()
    return {"by_utc_hour_gp": {int(h): float(v) for h, v in prof.items()},
            "swing_gp": float(prof.max() - prof.min()), "swing_share_of_margin": float((prof.max() - prof.min()) / scale),
            "best_utc_hour": int(prof.idxmax()), "worst_utc_hour": int(prof.idxmin())}


EVENT_HORIZONS = [1, 2, 3, 6, 9, 12, 18, 24, 36, 48, 72, 96, 120, 168]


def event_decay(m: pd.Series, top: bool = True) -> dict:
    """Average share of the excess left h hours after the margin enters its
    trailing-30-day top (or bottom) decile, starting a new episode."""
    norm = trailing_norm(m)
    thr = trailing_quantile(m, 0.9 if top else 0.1)
    inside = (m > thr) if top else (m < thr)
    # episode start: inside now, not inside at any point in the previous 6 hours
    recent = inside.shift(1).rolling(6, min_periods=1).max().fillna(0).astype(bool)
    starts = inside & ~recent & norm.notna()
    dev = m - norm
    idx = np.flatnonzero(starts.values)
    d0 = dev.values[idx]
    res = {"episodes": int(len(idx)), "initial_gap_gp": float(np.nanmean(d0)) if len(idx) else None}
    for h in EVENT_HORIZONS:
        j = idx + h
        ok = j < len(dev)
        # gap later, measured against the SAME norm as at the start (did the margin come back?)
        later = m.values[j[ok]] - norm.values[idx[ok]]
        res[f"left_after_{h}h"] = float(np.nanmean(later) / np.nanmean(d0[ok])) if ok.any() else None
    return res


def adf(daily: pd.Series) -> dict:
    x = daily.dropna()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        stat, p, *_ = adfuller(x.values, autolag="AIC")
    return {"adf_stat": float(stat), "p_value": float(p), "returns_to_level": bool(p < 0.05)}


def tax_effect(chain, p, values_mid: pd.DataFrame, window_days: int = 60) -> list[dict]:
    """Margin before vs after each tax change. 'Gross' = before tax; if processors
    pass the tax on, the gross margin widens by about the tax amount."""
    out = []
    rate = tax_rate(values_mid.index)
    mid = p["mid"]
    for start, r in TAX_SCHEDULE:
        before = slice(start - pd.Timedelta(days=window_days), start - pd.Timedelta(hours=1))
        after = slice(start + pd.Timedelta(days=7), start + pd.Timedelta(days=7 + window_days))
        gross = sum(q * mid[i] for i, q in chain.outputs.items()) - values_mid.cost if chain.outputs else None
        if gross is None:
            continue
        tax_now = (values_mid.revenue - sum(q * mid[i] for i, q in chain.outputs.items())).abs()
        out.append({
            "date": str(start.date()), "rate_after": r,
            "net_before": float(values_mid.margin[before].median()), "net_after": float(values_mid.margin[after].median()),
            "gross_before": float(gross[before].median()), "gross_after": float(gross[after].median()),
            "tax_per_action_after": float(tax_now[after].median()),
            "tax_per_action_before": float(tax_now[before].median()),
        })
    return out


def pass_through(chain, p, lags: int = 3) -> dict:
    """Which side moves first, using daily prices (hourly averages are too noisy).

    Granger tests: do past input-cost moves help predict output-price moves
    (and the reverse), beyond the series' own past? Plus how much the follower
    catches up: cumulative response over 0..7 days to a 1% move in the leader,
    and the long-run co-movement of 30-day changes.
    """
    from statsmodels.tsa.stattools import grangercausalitytests
    mid = p["mid"]
    if not chain.outputs:
        return {}
    cost = (sum(q * mid[i] for i, q in chain.inputs.items()) + chain.fee).resample("D").median()
    value = sum(q * mid[i] for i, q in chain.outputs.items()).resample("D").median()
    d = pd.DataFrame({"x": np.log(cost).diff(), "y": np.log(value).diff()}).dropna()
    lo, hi = d.quantile(0.01), d.quantile(0.99)
    d = d.clip(lo, hi, axis=1)  # tame data glitches
    res = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for name, cause, effect in [("input_leads_output", "x", "y"), ("output_leads_input", "y", "x")]:
            g = grangercausalitytests(d[[effect, cause]].values, maxlag=lags)
            p_val = min(g[k][0]["ssr_ftest"][1] for k in g)
            X = pd.concat({k: d[cause].shift(k) for k in range(8)}, axis=1)
            dd = pd.concat([d[effect].rename("e"), X], axis=1).dropna()
            beta, *_ = np.linalg.lstsq(np.c_[np.ones(len(dd)), dd.drop(columns="e").values], dd["e"].values,
                                       rcond=None)
            cum = np.cumsum(beta[1:])
            res[name] = {"granger_p": float(p_val), "cum_0d": float(cum[0]), "cum_1d": float(cum[1]),
                         "cum_3d": float(cum[3]), "cum_7d": float(cum[7])}
    m30 = pd.DataFrame({"x": np.log(cost).resample("30D").mean().diff(),
                        "y": np.log(value).resample("30D").mean().diff()}).dropna()
    slope = float(np.polyfit(m30.x, m30.y, 1)[0]) if len(m30) > 5 else None
    res["monthly"] = {"corr": float(m30.x.corr(m30.y)), "slope_output_on_input": slope, "n_months": int(len(m30))}
    return res


def run() -> dict:
    p = load()
    OUT.mkdir(parents=True, exist_ok=True)
    results, daily = {}, {}
    for c in [c for c in CHAINS if c.margin]:
        mid = chain_values(c, p, "mid")
        ex = chain_values(c, p, "executable")
        m = mid.margin
        d = mid.margin_pct.resample("D").mean()
        daily[c.name] = d
        by_year = mid.margin.groupby(mid.index.year).median().round(0)
        r = {
            "skill": c.skill,
            "median_margin_gp": float(m.median()),
            "median_margin_pct": float(mid.margin_pct.median()),
            "p10_p90_gp": [float(m.quantile(0.1)), float(m.quantile(0.9))],
            "median_by_year": {int(k): float(v) for k, v in by_year.items()},
            # NaN-aware: hours with a missing price are neither profitable nor not
            "share_hours_profitable": float((ex.margin.dropna() > 0).mean()),
            "spells": spells((ex.margin > 0).where(ex.margin.notna())),
            "stability": adf(d),
            "wide_events": (wide := event_decay(m, top=True)),
            "narrow_events": (narrow := event_decay(m, top=False)),
            "half_life_wide_h": half_life_from_events(wide),
            "half_life_narrow_h": half_life_from_events(narrow),
            "daily_rhythm": hour_of_day_profile(m),
            "net_margin_2024_vs_2026": [float(m["2024"].median()), float(m["2026"].median())],
            "margin_pct_2024_vs_2026": [float(mid.margin_pct["2024"].median()), float(mid.margin_pct["2026"].median())],
            "tax": tax_effect(c, p, mid),
            "pass_through": pass_through(c, p),
            "last_7d_margin_gp": float(m[m.index > m.index[-1] - pd.Timedelta(days=7)].median()),
        }
        results[c.name] = r
        hl = r["half_life_wide_h"]
        print(f"{c.name:32} half-life wide={'>168' if hl is None else f'{hl:.0f}'}h  adf p={r['stability']['p_value']:.3f}  "
              f"prof={r['share_hours_profitable']:.3f}  rhythm={r['daily_rhythm']['swing_share_of_margin']:.2f}")
    (OUT / "margin_study.json").write_text(json.dumps(results, indent=1))
    pd.DataFrame(daily).to_csv(OUT / "margin_daily_pct.csv")
    return results


if __name__ == "__main__":
    run()
