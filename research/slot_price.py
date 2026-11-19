"""Shadow price of an inventory slot, from food prices.

Model: a player values an HP at c gold and an inventory slot at lam gold. A food
that heals h and costs p really costs (p + lam) / h per HP. Where players choose
freely among foods, effective costs are equalised, so across foods

    p = c * h - lam

A cross-section regression of price on heal gives c (slope) and the slot value
lam (minus the intercept). lam / c is the slot in HP: unit-free, so it doesn't
move with the general price level. Fitted on plain single-bite members' food
(no combo eating or overheal); special foods are compared with the fitted line.

Input: data/history/food_daily.csv.gz (date, item, price, volume), made on the
machine with the full history from data/history/daily.sqlite (see daily_extract.py).

    python3 -m research.slot_price
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
IN = ROOT / "data" / "history" / "food_daily.csv.gz"
OUT = ROOT / "data" / "history" / "results"

HEAL = {  # HP healed per inventory slot (OSRS Wiki)
    "Trout": 7, "Salmon": 9, "Tuna": 10, "Lobster": 12, "Bass": 13, "Swordfish": 14,
    "Monkfish": 16, "Cooked karambwan": 18, "Shark": 20, "Sea turtle": 21,
    "Manta ray": 22, "Dark crab": 22, "Tuna potato": 22, "Anglerfish": 22, "Pineapple pizza": 22,
}
MEMBERS_PLAIN = ["Monkfish", "Shark", "Sea turtle", "Manta ray", "Dark crab", "Tuna potato"]
F2P = ["Tuna", "Lobster", "Swordfish"]


def fit(prices: pd.Series, items: list[str]) -> tuple[float, float, float]:
    """Least squares p = c*h - lam. Returns (c, lam, R^2)."""
    h = np.array([HEAL[i] for i in items], float)
    p = prices[items].to_numpy(float)
    a = np.c_[h, -np.ones_like(h)]
    (c, lam), *_ = np.linalg.lstsq(a, p, rcond=None)
    pred = a @ [c, lam]
    r2 = 1 - ((p - pred) ** 2).sum() / ((p - p.mean()) ** 2).sum()
    return float(c), float(lam), float(r2)


def monthly_prices(d: pd.DataFrame) -> pd.DataFrame:
    g = d.assign(gp=d.price * d.volume, mo=d.date.dt.to_period("M")).groupby(["mo", "item"])[["gp", "volume"]].sum()
    return (g.gp / g.volume).unstack()


def run(path: Path = IN) -> pd.DataFrame:
    d = pd.read_csv(path, parse_dates=["date"])
    rows = []
    for mo, px in monthly_prices(d).iterrows():
        if px[MEMBERS_PLAIN].notna().all():
            c, lam, r2 = fit(px, MEMBERS_PLAIN)
            rows.append({"month": str(mo), "c": round(c, 1), "lam": round(lam), "slot_hp": round(lam / c, 2),
                         "r2": round(r2, 3)})
    ts = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    ts.to_csv(OUT / "slot_monthly.csv", index=False)
    return ts


if __name__ == "__main__":
    print(run().to_string(index=False))
