"""Load the study subset and compute hourly margins and XP prices for each chain.

Prices are the API's hourly averages. Per item and hour:
  high = average instant-buy price, low = average instant-sell price
  (a side with no trades is missing; gaps of up to 3 hours are filled forward).
Two pricing conventions:
  mid        both sides at the average of high and low (smoothest; for dynamics)
  executable buy inputs at the higher side, sell outputs at the lower side
             (what you get trading instantly; for "is it profitable")
GE tax uses the rate in force at the time: none before 9 Dec 2021, 1% until
29 May 2025, 2% after; per item, rounded down, capped at 5m.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from research.chains import CHAINS, Chain

ROOT = Path(__file__).resolve().parent.parent
SUBSET = ROOT / "data" / "history" / "study_subset.sqlite"

TAX_SCHEDULE = [  # (start, rate)
    (pd.Timestamp("2021-12-09 12:00", tz="UTC"), 0.01),
    (pd.Timestamp("2025-05-29 12:00", tz="UTC"), 0.02),
]
TAX_CAP = 5_000_000
FFILL_HOURS = 3


def load(path: Path = SUBSET) -> dict[str, pd.DataFrame]:
    """{'high','low','mid','vol'}: hourly DataFrames, columns = item names (as in chains.py)."""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    items = dict(con.execute("SELECT item_id, name FROM items"))
    df = pd.read_sql("SELECT * FROM prices", con)
    lo, hi = con.execute("SELECT MIN(ts), MAX(ts) FROM fetched WHERE n_items > 0").fetchone()
    index = pd.date_range(pd.Timestamp(lo, unit="s", tz="UTC"), pd.Timestamp(hi, unit="s", tz="UTC"), freq="h")
    df["time"] = pd.to_datetime(df.ts, unit="s", utc=True)
    df["item"] = df.item_id.map(items)
    canon = {n.lower(): n for c in CHAINS for n in [*c.inputs, *c.outputs]}
    df["item"] = df.item.str.lower().map(canon)

    def panel(col):
        return (df.pivot(index="time", columns="item", values=col).reindex(index)
                .astype(float).ffill(limit=FFILL_HOURS))
    high, low = panel("avg_high"), panel("avg_low")
    vol = (df.assign(v=df.high_vol + df.low_vol).pivot(index="time", columns="item", values="v")
           .reindex(index).astype(float))
    mid = pd.concat([high, low]).groupby(level=0).mean()  # mean of available sides
    return {"high": high, "low": low, "mid": mid.reindex(index), "vol": vol}


def tax_rate(index: pd.DatetimeIndex) -> pd.Series:
    rate = pd.Series(0.0, index=index)
    for start, r in TAX_SCHEDULE:
        rate[index >= start] = r
    return rate


def net_of_tax(price: pd.Series, rate: pd.Series) -> pd.Series:
    tax = np.minimum(np.floor(price * rate), TAX_CAP)
    return price - tax


def chain_values(chain: Chain, p: dict[str, pd.DataFrame], how: str = "mid") -> pd.DataFrame:
    """Hourly cost, revenue and margin per action for a chain."""
    index = p["mid"].index
    if how == "mid":
        buy = sell = p["mid"]
    elif how == "executable":
        both = {"high": p["high"], "low": p["low"]}
        buy = np.fmax(both["high"], both["low"])   # fmax ignores a missing side
        sell = np.fmin(both["high"], both["low"])
    else:
        raise ValueError(how)
    rate = tax_rate(index)
    cost = pd.Series(chain.fee, index=index)
    for item, q in chain.inputs.items():
        cost = cost + q * buy[item]
    revenue = pd.Series(0.0, index=index)
    for item, q in chain.outputs.items():
        revenue = revenue + q * net_of_tax(sell[item], rate)
    out = pd.DataFrame({"cost": cost, "revenue": revenue})
    out["margin"] = out.revenue - out.cost
    out["margin_pct"] = out.margin / out.cost
    if chain.xp:
        out["gp_per_xp"] = -out.margin / chain.xp   # positive = XP costs gold
    return out


def min_volume(chain: Chain, p: dict[str, pd.DataFrame]) -> pd.Series:
    return p["vol"][[*chain.inputs, *chain.outputs]].min(axis=1)
