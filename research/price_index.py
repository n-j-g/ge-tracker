"""OSRS price index: what a fixed basket of everyday goods costs over time.

Reads data/history/daily_prices.csv.gz (made by daily_extract.py) and writes
data/history/results/price_index/.

Prices: an item's price for a day or month is gold spent on it / items traded
(the average transaction price, both sides of the market).

Three ways to build the index, which should roughly agree:

  fixed basket (Laspeyres)  the headline. Buy the base year's average daily
      shopping (items in base-year quantities) at each later day's prices.
      100 = the base year (the first 12 months of data). Easy to read ("the same
      shopping costs X% more"), but it ignores players switching to cheaper goods.
  chained (Törnqvist)  month to month, each item's price change counts by its
      share of gold spent in the trailing 12 months (average of the two months'
      shares), linked together. Weights follow what players actually buy now.
  equal weights (Jevons)  geometric mean of price changes, every item counting
      the same: a check that the headline isn't driven by one or two goods.

Also: the index per category; each item's change against the index; the price
of an Old School bond (gold per bond, i.e. gold against real money); and a broad
index of the most-traded items of any kind (gear included), chained.

    python3 -m research.price_index [--file data/history/daily_prices.csv.gz]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from research.basket import basket_items

ROOT = Path(__file__).resolve().parent.parent
IN = ROOT / "data" / "history" / "daily_prices.csv.gz"
OUT = ROOT / "data" / "history" / "results" / "price_index"
BASE_DAYS = 365
MIN_COVERAGE = 0.9     # an item needs a price on 90% of days, in the base year and overall
FILL_DAYS = 7          # gaps up to a week take the last known price
BOND = "Old school bond"
BROAD_MIN_DAILY_GP = 50_000_000  # broad index: items with at least this much gold traded a day (median)


def load(path: Path = IN) -> dict[str, pd.DataFrame]:
    df = pd.read_csv(path, parse_dates=["date"])
    df["gp"] = df.price * df.volume
    gp = df.pivot_table(index="date", columns="item", values="gp", aggfunc="sum")
    vol = df.pivot_table(index="date", columns="item", values="volume", aggfunc="sum")
    days = pd.date_range(gp.index.min(), gp.index.max(), freq="D")
    gp, vol = gp.reindex(days), vol.reindex(days)
    price = (gp / vol).ffill(limit=FILL_DAYS)
    return {"price": price, "gp": gp, "vol": vol}


def monthly(d: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    gp = d["gp"].resample("MS").sum(min_count=1)
    vol = d["vol"].resample("MS").sum(min_count=1)
    return {"price": gp / vol, "gp": gp, "vol": vol}


def covered(price: pd.DataFrame, base: slice) -> list[str]:
    ok_base = price.loc[base].notna().mean() >= MIN_COVERAGE
    ok_all = price.notna().mean() >= MIN_COVERAGE
    return sorted(price.columns[ok_base & ok_all])


def base_weights(d: dict[str, pd.DataFrame], items: list[str], base: slice) -> pd.DataFrame:
    """Base price p0 (average traded price), base quantity q0 (items per day), value share."""
    gp, vol = d["gp"].loc[base, items], d["vol"].loc[base, items]
    p0 = gp.sum() / vol.sum()
    q0 = vol.fillna(0).mean()
    share = p0 * q0 / (p0 * q0).sum()
    return pd.DataFrame({"p0": p0, "q0": q0, "share": share})


def laspeyres(price: pd.DataFrame, w: pd.DataFrame) -> pd.Series:
    """100 * cost of the base basket at today's prices / its cost at base prices.
    A missing price (after gap filling) counts as unchanged since the base."""
    rel = (price[w.index] / w.p0).fillna(1.0)
    return 100 * rel.mul(w.share).sum(axis=1)


def jevons(price: pd.DataFrame, w: pd.DataFrame) -> pd.Series:
    logrel = np.log(price[w.index] / w.p0)
    return 100 * np.exp(logrel.mean(axis=1))


def tornqvist_chain(m: dict[str, pd.DataFrame], items: list[str]) -> pd.Series:
    """Monthly chained Törnqvist; shares are trailing-12-month shares of gold spent."""
    p, gp = m["price"][items], m["gp"][items].fillna(0)
    share = gp.rolling(12, min_periods=1).sum()
    share = share.div(share.sum(axis=1), axis=0)
    dlog = np.log(p).diff()
    out = [0.0]
    for t in range(1, len(p)):
        ok = dlog.iloc[t].notna()
        s = (share.iloc[t - 1][ok] + share.iloc[t][ok]) / 2
        out.append(float((s / s.sum() * dlog.iloc[t][ok]).sum()) if s.sum() > 0 else 0.0)
    return pd.Series(100 * np.exp(np.cumsum(out)), index=p.index)


def rebase(s: pd.Series, base: slice) -> pd.Series:
    return 100 * s / s.loc[base].mean()


def yoy(s: pd.Series) -> pd.Series:
    """Year-over-year change of a monthly series."""
    return s / s.shift(12) - 1


def run(path: Path = IN, out: Path = OUT) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    d = load(path)
    m = monthly(d)
    start = d["price"].index.min()
    base = slice(start, start + pd.Timedelta(days=BASE_DAYS - 1))
    mbase = slice(start.to_period("M").to_timestamp(), (start + pd.Timedelta(days=BASE_DAYS - 1)).to_period("M")
                  .to_timestamp())
    cats = basket_items()
    lower = {c.lower(): c for c in d["price"].columns}
    present = [lower[n.lower()] for n in cats if n.lower() in lower]
    cat_of = {lower[n.lower()]: c for n, c in cats.items() if n.lower() in lower}
    items = covered(d["price"][present], base)
    dropped = sorted(set(present) - set(items))
    w = base_weights(d, items, base)
    w["category"] = [cat_of[i] for i in w.index]

    daily = pd.DataFrame({"fixed_basket": laspeyres(d["price"], w), "equal_weights": jevons(d["price"], w)})

    mon = pd.DataFrame({
        "fixed_basket": laspeyres(m["price"], w),
        "chained": rebase(tornqvist_chain(m, items), mbase),
        "equal_weights": jevons(m["price"], w),
    })
    for cat in w.category.unique():
        wc = w[w.category == cat].copy()
        wc["share"] = wc.share / wc.share.sum()
        mon[f"cat:{cat}"] = laspeyres(m["price"], wc)
    # broad index: every heavily traded item, gear included (chained, so new items can join)
    med_gp = d["gp"].median()
    broad = sorted(med_gp[med_gp >= BROAD_MIN_DAILY_GP].index.difference([BOND]))
    if broad:
        mon["broad_all_items"] = rebase(tornqvist_chain(m, broad), mbase)
    bond = lower.get(BOND.lower())
    if bond:
        mon["bond_price"] = m["price"][bond]
        mon["bond_index"] = rebase(m["price"][bond], mbase)
    mon["gold_buying_power"] = 100 * 100 / mon.fixed_basket   # what 100 gp of base-year gold buys now
    mon["inflation_yoy"] = yoy(mon.fixed_basket)
    mon["inflation_yoy_chained"] = yoy(mon.chained)

    # each item: change since the base year, against the basket
    recent = slice(d["price"].index.max() - pd.Timedelta(days=29), None)
    p_now = d["gp"].loc[recent, items].sum() / d["vol"].loc[recent, items].sum()
    idx_now = daily.fixed_basket.loc[recent].mean() / 100
    item_tab = w.assign(p_now=p_now, change=p_now / w.p0 - 1)
    item_tab["vs_basket"] = (p_now / w.p0) / idx_now - 1
    item_tab = item_tab.sort_values("change", ascending=False)

    daily.round(3).to_csv(out / "index_daily.csv", index_label="date")
    mon.round(4).to_csv(out / "index_monthly.csv", index_label="month")
    item_tab.round(4).to_csv(out / "items.csv", index_label="item")

    # years from the middle of the base year to the middle of the last 30 days
    years = ((d["price"].index.max() - pd.Timedelta(days=15)) - (start + pd.Timedelta(days=BASE_DAYS / 2))).days / 365.25
    level = mon.fixed_basket.dropna().iloc[-1]
    summary = {
        "data_from": str(start.date()), "data_to": str(d["price"].index.max().date()),
        "base_period": f"{base.start.date()} to {base.stop.date()}",
        "items": len(items), "dropped_for_gaps": dropped,
        "missing_from_data": sorted(set(cats) - {n for n in cats if n.lower() in lower}),
        "latest_month": str(mon.index[-1].date()),
        "fixed_basket_now": round(float(level), 1),
        "chained_now": round(float(mon.chained.iloc[-1]), 1),
        "equal_weights_now": round(float(mon.equal_weights.iloc[-1]), 1),
        "average_yearly_inflation": round(float((daily.fixed_basket.loc[recent].mean() / 100) ** (1 / years) - 1), 4),
        "inflation_last_12_months": round(float(mon.inflation_yoy.iloc[-1]), 4)
        if pd.notna(mon.inflation_yoy.iloc[-1]) else None,
        "broad_items": len(broad),
        "top_weights": w.share.sort_values(ascending=False).head(10).round(4).to_dict(),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", type=Path, default=IN)
    args = ap.parse_args(argv)
    print(json.dumps(run(args.file), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
