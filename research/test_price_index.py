"""Tests for the daily extract and the price index, on made-up data with known answers.

    python3 -m unittest research.test_price_index
"""
from __future__ import annotations

import io
import math
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from research import daily_extract
from research.backfill_history import SCHEMA

START = 1_617_235_200  # 2021-04-01 00:00 UTC
DAYS = 3 * 365 + 40
# name: (start price, yearly growth, items traded per hour)
ITEMS = {
    "Shark": (900, 0.10, 400),
    "Nature rune": (200, 0.10, 3000),
    "Coal": (150, 0.10, 2000),
    "Prayer potion(4)": (8000, 0.10, 100),
    "Twisted bow": (1_000_000_000, 0.0, 1),
}


def make_db(path: Path, growth_override: dict | None = None) -> None:
    con = sqlite3.connect(str(path))
    con.executescript(SCHEMA)
    growth_override = growth_override or {}
    rows, fetched = [], []
    ids = {n: i + 1 for i, n in enumerate(ITEMS)}
    for h in range(DAYS * 24):
        ts = START + h * 3600
        years = h / (24 * 365)
        for name, (p0, g, v) in ITEMS.items():
            g = growth_override.get(name, g)
            p = p0 * (1 + g) ** years
            # buy side a bit above, sell side a bit below; one side missing now and then
            hi = round(p * 1.01) if h % 17 else None
            rows.append((ts, ids[name], hi, v if hi else 0, round(p * 0.99), v))
        fetched.append((ts, len(ITEMS), 0))
    con.executemany("INSERT INTO prices VALUES (?,?,?,?,?,?)", rows)
    con.executemany("INSERT INTO fetched VALUES (?,?,?)", fetched)
    con.executemany("INSERT INTO items VALUES (?,?,?,?,?,?,?)",
                    [(i, n, 100, 1, 1, 1, 0) for n, i in ids.items()])
    con.commit()
    con.close()


class PriceIndexTest(unittest.TestCase):
    def run_all(self, tmp: Path, **kw):
        from research import price_index
        full, daily, out = tmp / "full.sqlite", tmp / "daily.sqlite", tmp / "daily.csv.gz"
        make_db(full, **kw)
        quiet = lambda *a: None  # noqa: E731
        self.assertTrue(daily_extract.build_daily(full, daily, log=quiet))
        daily_extract.export(daily, out, top_n=10, log=quiet)
        with redirect_stdout(io.StringIO()):
            return price_index.run(out, tmp / "results"), tmp / "results"

    def test_uniform_inflation(self):
        import pandas as pd
        with tempfile.TemporaryDirectory() as t:
            s, res = self.run_all(Path(t))
            mon = pd.read_csv(res / "index_monthly.csv", index_col=0)
            # every basket good rises 10% a year, so every index rises 10% a year
            for col in ["inflation_yoy", "inflation_yoy_chained"]:
                self.assertAlmostEqual(mon[col].dropna().median(), 0.10, delta=0.003, msg=col)
            self.assertAlmostEqual(s["average_yearly_inflation"], 0.10, delta=0.01)
            self.assertEqual(s["items"], 4)  # the bow isn't in the basket
            self.assertIn("Anglerfish", s["missing_from_data"])
            items = pd.read_csv(res / "items.csv", index_col=0)
            self.assertLess(items.vs_basket.abs().max(), 0.01)

    def test_weights_by_gold_spent(self):
        import pandas as pd
        with tempfile.TemporaryDirectory() as t:
            # only prayer potions inflate (20%/yr); they're ~40% of base-year spending
            s, res = self.run_all(Path(t), growth_override={"Shark": 0, "Nature rune": 0, "Coal": 0,
                                                            "Prayer potion(4)": 0.2})
            items = pd.read_csv(res / "items.csv", index_col=0)
            spend = {n: p * v for n, (p, _, v) in ITEMS.items() if n != "Twisted bow"}
            spend["Prayer potion(4)"] *= 0.2 / math.log(1.2)  # its average price over the base year
            self.assertAlmostEqual(items.share["Prayer potion(4)"], spend["Prayer potion(4)"] / sum(spend.values()),
                                   delta=0.005)
            mon = pd.read_csv(res / "index_monthly.csv", index_col=0)
            # equal weights: 1 of 4 goods at +20%/yr  ->  (1.2)^(1/4) - 1 a year
            jev = mon.equal_weights.dropna()
            self.assertAlmostEqual(jev.iloc[-1] / jev.iloc[-13] - 1, 1.2 ** 0.25 - 1, delta=0.005)
            self.assertGreater(mon["cat:Potions"].iloc[-1], 150)
            self.assertAlmostEqual(mon["cat:Food"].iloc[-1], 100, delta=0.5)

    def test_daily_price_is_average_traded_price(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            full, daily = tmp / "full.sqlite", tmp / "daily.sqlite"
            con = sqlite3.connect(str(full))
            con.executescript(SCHEMA)
            con.executemany("INSERT INTO prices VALUES (?,?,?,?,?,?)", [
                (START, 1, 110, 10, 90, 30),          # 10 at 110, 30 at 90
                (START + 3600, 1, None, 0, 100, 20),  # no buys this hour
            ])
            con.executemany("INSERT INTO fetched VALUES (?,?,?)", [(START, 1, 0), (START + 3600, 1, 0)])
            con.execute("INSERT INTO items VALUES (1,'Shark',1,1,1,1,0)")
            con.commit()
            daily_extract.build_daily(full, daily, log=lambda *a: None)
            c = sqlite3.connect(str(daily))
            gp, vol = c.execute("SELECT gp, vol FROM daily").fetchone()
            c.close()
            self.assertEqual(vol, 60)
            self.assertTrue(math.isclose(gp / vol, (1100 + 2700 + 2000) / 60))


if __name__ == "__main__":
    unittest.main()
