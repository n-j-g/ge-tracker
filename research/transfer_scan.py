#!/usr/bin/env python3
"""Find suspected gold transfers in the hourly price history: hours where an item
traded far above its normal price (the pattern in poignanttech's "Virtual Markets
part two", e.g. Agility mix(1) selling at 500k).

Standard library only; runs where the full history database lives.

    python3 research/transfer_scan.py             # resumable, works in time-boxed chunks

For each month, each item's typical price is its median hourly price that month.
Flags every hour where an item's average instant-sell ("low") or instant-buy
("high") price was at least FACTOR x typical and at least MIN_PRICE gp.
Output: data/history/results/transfer_events.csv
"""
from __future__ import annotations

import argparse
import csv
import sqlite3
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FULL = ROOT / "data" / "history" / "prices_1h.sqlite"
WORK = ROOT / "data" / "history" / "transfer_scan_v2.sqlite"
OUT = ROOT / "data" / "history" / "results" / "transfer_events.csv"
FACTOR = 20          # this many times the item's typical price
MIN_PRICE = 50_000   # and at least this much per item
MONTH = 30 * 24 * 3600


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=float, default=150)
    args = ap.parse_args(argv)
    t0 = time.time()
    src = sqlite3.connect(f"file:{FULL}?mode=ro", uri=True)
    work = sqlite3.connect(str(WORK))
    work.execute("PRAGMA journal_mode=TRUNCATE")
    work.executescript("""
        CREATE TABLE IF NOT EXISTS events (ts INTEGER, item_id INTEGER, side TEXT, price INTEGER, volume INTEGER,
                                           other_price INTEGER, typical REAL, PRIMARY KEY (ts, item_id, side));
        CREATE TABLE IF NOT EXISTS progress (chunk_start INTEGER PRIMARY KEY);
    """)
    lo, hi = src.execute("SELECT MIN(ts), MAX(ts) FROM fetched WHERE n_items > 0").fetchone()

    # pass 2: month by month, compare each hour with the item's median for that month
    # (an item's normal price can move a lot over five years; transfers are rare spikes)
    done = {r[0] for r in work.execute("SELECT chunk_start FROM progress")}
    chunks = [s for s in range(lo // MONTH * MONTH, hi + 1, MONTH) if s not in done]
    for n, start in enumerate(chunks):
        if args.budget and time.time() - t0 > args.budget:
            print(f"time budget reached: {len(chunks) - n} of {len(chunks) + len(done)} months left; rerun to continue")
            return 2
        rows = src.execute(
            "SELECT ts, item_id, avg_high, high_vol, avg_low, low_vol FROM prices WHERE ts >= ? AND ts < ?",
            (start, start + MONTH)).fetchall()
        sides: dict[int, list[float]] = {}
        for ts, item_id, h, hv, l, lv in rows:
            for v in (h, l):
                if v:
                    sides.setdefault(item_id, []).append(v)
        month_median = {k: statistics.median(v) for k, v in sides.items() if len(v) >= 20}
        found = []
        for ts, item_id, h, hv, l, lv in rows:
            typical = month_median.get(item_id)
            if not typical:
                continue
            if l and lv and l >= MIN_PRICE and l >= FACTOR * typical:
                found.append((ts, item_id, "low", l, lv, h, typical))
            if h and hv and h >= MIN_PRICE and h >= FACTOR * typical:
                found.append((ts, item_id, "high", h, hv, l, typical))
        with work:
            work.executemany("INSERT OR REPLACE INTO events VALUES (?,?,?,?,?,?,?)", found)
            work.execute("INSERT INTO progress VALUES (?)", (start,))

    names = dict(src.execute("SELECT item_id, name FROM items"))
    values = dict(src.execute("SELECT item_id, value FROM items"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "item_id", "name", "store_value", "typical", "side", "price", "volume", "other_side_price"])
        for ts, item_id, side, price, vol, other, typical in work.execute("SELECT * FROM events ORDER BY ts"):
            w.writerow([ts, item_id, names.get(item_id, ""), values.get(item_id), round(typical, 1),
                        side, price, vol, other])
    n = work.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    print(f"done: {n:,} suspicious item-hours -> {OUT} ({time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
