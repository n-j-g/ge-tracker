"""Tests for the live paper-trading watcher (no network)."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from live import watch
from live.watch import Book, Engine, flagged_sides

ITEM = 99999          # not in the seed list
T0 = 1_800_000_000


def bucket(price, vol, side="low"):
    d = {"avgHighPrice": None, "highPriceVolume": 0, "avgLowPrice": None, "lowPriceVolume": 0}
    if side == "low":
        d.update(avgLowPrice=price, lowPriceVolume=vol)
    else:
        d.update(avgHighPrice=price, highPriceVolume=vol)
    return {str(ITEM): d}


class TestFlag(unittest.TestCase):
    def test_rules(self):
        self.assertEqual(flagged_sides(None, 0, 200_000, 5, 100), [("low", 200_000, 5)])
        self.assertEqual(flagged_sides(None, 0, 40_000, 5, 100), [])        # under 50k
        self.assertEqual(flagged_sides(None, 0, 60_000, 5, 5_000), [])      # under 20x typical
        self.assertEqual(flagged_sides(None, 0, 200_000, 0, 100), [])       # no volume
        self.assertEqual(flagged_sides(None, 0, 200_000, 5, None), [])      # no typical price

    def test_tax(self):
        self.assertEqual(watch.ge_tax(100_000), 2_000)
        self.assertEqual(watch.ge_tax(49), 0)
        self.assertEqual(watch.ge_tax(10**9), 5_000_000)


class TestNewestBook(unittest.TestCase):
    def ep(self, item, i, start=T0, price=100_000, units=1000):
        return dict(id=i, item=item, start=start, units=units, gold=price * units)

    def test_arm_delay_fill_and_stock(self):
        b = Book("n", "newest")
        b.on_transfer(self.ep(1, 1), T0, {})
        t = b.traps[1]
        self.assertEqual((t.ask, t.stock, t.active_from), (50_000, 2000, T0 + watch.ARM_DELAY))
        self.assertIsNone(b.check(1, T0 + 300, 100_000, 10, 1))             # not up yet
        f = b.check(1, T0 + 3600, 100_000, 1500, 1)
        self.assertEqual((f["qty"], f["same_episode"]), (1500, True))
        self.assertEqual(f["net"], 1500 * (50_000 - 1_000))
        self.assertIsNone(b.check(1, T0 + 3600, 40_000, 10, 1))              # below our ask
        self.assertEqual(b.check(1, T0 + 7200, 100_000, 1500, 2)["qty"], 500)  # rest of stock
        self.assertIsNone(b.check(1, T0 + 7300, 100_000, 10, 2))             # sold out

    def test_eviction_and_expiry(self):
        b = Book("n", "newest")
        for i in range(10):
            b.on_transfer(self.ep(i, i), T0 + i, {})
        self.assertEqual(sorted(b.traps), list(range(2, 10)))
        b.expire(T0 + 8 * watch.DAY)
        self.assertEqual(b.traps, {})

    def test_counts_transfers_on_trapped_items(self):
        b = Book("n", "newest")
        b.on_transfer(self.ep(1, 1), T0, {})
        b.on_transfer(self.ep(1, 2, start=T0 + watch.DAY), T0 + watch.DAY, {})
        self.assertEqual((b.seen, b.on_trap), (2, 1))

    def test_state_round_trip(self):
        b = Book("n", "newest")
        b.on_transfer(self.ep(1, 1), T0, {})
        b.check(1, T0 + 3600, 100_000, 5, 1)
        c = Book.from_dict(json.loads(json.dumps(b.to_dict())))
        self.assertEqual(c.traps, b.traps)
        self.assertEqual(c.fills, b.fills)


class TestScoreBook(unittest.TestCase):
    def test_ranks_recent_transfers_first(self):
        now = T0
        h = {i: [dict(ts=now - i * watch.DAY, price=100_000, units=100, gold=1e7)] for i in range(1, 20)}
        h[50] = []
        b = Book("s", "score")
        b.rerank(now, h)
        self.assertEqual(sorted(b.traps), list(range(1, 9)))
        h[30] = [dict(ts=now, price=100_000, units=100, gold=1e7)]
        b.on_transfer(dict(id=7, item=30, start=now, units=100, gold=1e7), now, h)
        self.assertIn(30, b.traps)
        self.assertNotIn(8, b.traps)
        self.assertEqual(b.traps[30].trigger, 7)


class TestEngine(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.eng = Engine(self.dir)
        self.eng.typical[ITEM] = 100.0
        self.eng.names[ITEM] = "Test potion(1)"

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_detect_arm_and_fill(self):
        e = self.eng
        e.ingest_5m(T0, bucket(200_000, 20), T0 + 300)                       # 4m excess: not yet
        self.assertIsNone(e.open[ITEM]["confirmed_at"])
        e.ingest_5m(T0 + 300, bucket(200_000, 60), T0 + 600)                 # 16m: confirmed
        self.assertEqual(e.open[ITEM]["confirmed_at"], T0 + 600)
        newest = e.books[0]
        self.assertEqual(newest.traps[ITEM].ask, 100_000)
        self.assertEqual(newest.traps[ITEM].stock, 160)
        fills = e.ingest_5m(T0 + 3600, bucket(150_000, 50, "high"), T0 + 3900)   # same session, later
        self.assertEqual([(f["book"], f["qty"], f["same_episode"]) for f in fills if f["book"] == "newest"],
                         [("newest", 50, True)])
        fills = e.ingest_5m(T0 + 20 * 3600, bucket(300_000, 500), T0 + 20 * 3600 + 300)  # a new episode
        f = [f for f in fills if f["book"] == "newest"][0]
        self.assertEqual((f["qty"], f["same_episode"]), (110, False))
        self.assertEqual(e.db.execute("SELECT COUNT(*) FROM episodes WHERE confirmed_at IS NOT NULL").fetchone()[0], 2)

    def test_ignores_normal_prices(self):
        self.assertEqual(self.eng.ingest_5m(T0, bucket(150, 5000), T0 + 300), [])
        self.assertNotIn(ITEM, self.eng.open)

    def test_latest_prints_and_trades(self):
        e = self.eng
        e.watched.add(ITEM)
        e.ingest_latest({str(ITEM): {"high": 120, "highTime": T0, "low": 250_000, "lowTime": T0 + 5}}, T0 + 60)
        e.ingest_latest({str(ITEM): {"high": 120, "highTime": T0, "low": 250_000, "lowTime": T0 + 5}}, T0 + 120)
        self.assertEqual(e.db.execute("SELECT COUNT(*) FROM trades").fetchone()[0], 2)
        self.assertEqual(e.db.execute("SELECT side, price FROM prints WHERE source='latest'").fetchall(), [("low", 250_000)])

    def test_typical_from_hours(self):
        e = self.eng
        for i in range(10):
            e.ingest_hour(T0 + i * 3600, {"5": {"avgHighPrice": 110, "avgLowPrice": 90 if i else 9_000_000}})
        e.recompute_typical()
        self.assertEqual(e.typical[5], 100)

    def test_hourly_history_scan(self):
        e = self.eng
        e.scan_hour_for_history(T0, {str(ITEM): {"avgLowPrice": 200_000, "lowPriceVolume": 100}})
        e.scan_hour_for_history(T0 + 3600, {str(ITEM): {"avgLowPrice": 200_000, "lowPriceVolume": 100}})
        self.assertEqual(len(e.history[ITEM]), 1)

    def test_save_load_and_export(self):
        e = self.eng
        e.last_1h = T0
        e.ingest_5m(T0, bucket(200_000, 100), T0 + 300)
        e.save()
        f = Engine(self.dir)
        self.assertEqual(f.books[0].traps, e.books[0].traps)
        self.assertIn(ITEM, f.open)
        out = self.dir / "publish"
        f.export(out, T0 + 600)
        s = json.loads((out / "status.json").read_text())
        self.assertEqual(s["transfers_total"], 1)
        self.assertEqual(s["transfers"][0]["name"], "Test potion(1)")
        self.assertEqual({p.name for p in out.iterdir()}, {"status.json", "transfers.csv", "fills.csv", "prints.csv"})


class TestPage(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "needs Node.js to syntax-check the page script")
    def test_page_script_parses(self):
        html = (Path(__file__).resolve().parent.parent / "paper" / "index.html").read_text()
        script = html.split("<script>")[1].split("</script>")[0]
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(script)
        r = subprocess.run(["node", "--check", f.name], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
