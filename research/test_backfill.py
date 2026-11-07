import sqlite3
import tempfile
import unittest
import urllib.error
from pathlib import Path

from research import backfill_history as bf

H = bf.HOUR
START = bf.SEARCH_FROM + 60 * 24 * H        # pretend history begins 60 days in
NOW = START + 10 * H + 1234                 # "now": a bit after 10 hours of history


class FakeApi:
    """Answers /mapping and /1h?timestamp= like the real API."""

    def __init__(self, fail_times=0):
        self.calls, self.fail_times = [], fail_times

    def __call__(self, url):
        self.calls.append(url)
        if url.endswith("/mapping"):
            return [{"id": 2363, "name": "Runite bar", "limit": 10000, "members": False}]
        ts = int(url.split("timestamp=")[1])
        if self.fail_times:
            self.fail_times -= 1
            raise urllib.error.URLError("boom")
        if ts < START:
            return {"data": {}}
        return {"data": {"2363": {"avgHighPrice": 12000 + ts // H % 10, "highPriceVolume": 5,
                                  "avgLowPrice": 11990, "lowPriceVolume": 7},
                         "453": {"avgHighPrice": None, "highPriceVolume": 0,
                                 "avgLowPrice": 130, "lowPriceVolume": 3}}}


class TestBackfill(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "h.sqlite"

    def tearDown(self):
        self.tmp.cleanup()

    def run_bf(self, api, limit=None, max_failures=8):
        return bf.run(self.db, 1.0, max_failures, limit, getter=api,
                      sleep=lambda s: None, now=lambda: NOW)

    def test_full_run_newest_first_and_stored(self):
        api = FakeApi()
        self.assertEqual(self.run_bf(api), 0)
        con = sqlite3.connect(str(self.db))
        hours = [r[0] for r in con.execute("SELECT ts FROM fetched WHERE n_items > 0 ORDER BY ts")]
        last = bf.latest_complete_hour(NOW)
        self.assertEqual(hours, list(range(START, last + 1, H)))
        fetched_order = [int(u.split("=")[1]) for u in api.calls if "timestamp=" in u]
        backfill_part = [t for t in fetched_order if t >= START][-len(hours):]
        self.assertEqual(backfill_part, sorted(backfill_part, reverse=True))  # newest first
        row = con.execute("SELECT avg_high, high_vol, avg_low, low_vol FROM prices "
                          "WHERE item_id = 453 AND ts = ?", (START,)).fetchone()
        self.assertEqual(row, (None, 0, 130, 3))
        self.assertEqual(con.execute("SELECT name FROM items").fetchone()[0], "Runite bar")

    def test_resume_skips_done_hours_and_history_search(self):
        self.run_bf(FakeApi(), limit=3)
        api = FakeApi()
        self.run_bf(api)
        hours = [int(u.split("=")[1]) for u in api.calls if "timestamp=" in u]
        self.assertEqual(len(hours), len(set(hours)))  # no repeats, no binary search again
        last = bf.latest_complete_hour(NOW)
        self.assertNotIn(last, hours)  # the 3 newest were already done
        con = sqlite3.connect(str(self.db))
        self.assertEqual(con.execute("SELECT COUNT(*) FROM fetched").fetchone()[0],
                         (last - START) // H + 1)

    def test_retries_same_hour_then_succeeds(self):
        self.run_bf(FakeApi(), limit=1)            # history start found, newest hour stored
        api = FakeApi(fail_times=2)                # next two hour requests fail
        self.assertEqual(self.run_bf(api), 0)
        hours = [int(u.split("=")[1]) for u in api.calls if "timestamp=" in u]
        second_newest = bf.latest_complete_hour(NOW) - H
        self.assertEqual(hours[:3], [second_newest] * 3)  # retried the same hour, not skipped
        con = sqlite3.connect(str(self.db))
        self.assertEqual(con.execute("SELECT COUNT(*) FROM fetched").fetchone()[0],
                         (bf.latest_complete_hour(NOW) - START) // H + 1)

    def test_stops_after_repeated_failures(self):
        self.run_bf(FakeApi(), limit=1)
        api = FakeApi(fail_times=10**6)
        self.assertEqual(self.run_bf(api, max_failures=3), 1)
        self.assertEqual(sum("timestamp=" in u for u in api.calls), 3)

    def test_find_first_hour(self):
        first = bf.find_first_hour(bf.SEARCH_FROM, bf.latest_complete_hour(NOW), lambda ts: ts >= START)
        self.assertEqual(first, START)


if __name__ == "__main__":
    unittest.main()
