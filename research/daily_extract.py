#!/usr/bin/env python3
"""Turn the full hourly price history into daily prices: a small file to share.

    python3 research/daily_extract.py

Step 1 (slow the first time, a few minutes; resumable): add up every item's
trades per day into data/history/daily.sqlite (all items, kept for later studies).
Step 2 (seconds): write data/history/daily_prices.csv.gz for the price-index
basket plus the most-traded items, one row per item per day:

    date, item, price, volume

price = average traded price that day (gold spent / items traded, both sides of
the market); volume = items traded. Standard library only, so it runs on the
machine that holds the 4 GB database. On a Mac it shows the file in Finder at the end.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from research.basket import basket_items  # noqa: E402

FULL = ROOT / "data" / "history" / "prices_1h.sqlite"
DAILY = ROOT / "data" / "history" / "daily.sqlite"
OUT = ROOT / "data" / "history" / "daily_prices.csv.gz"
DAY = 86400
CHUNK = 30 * DAY  # a multiple of a day, so no day is split between chunks
TOP_N = 250       # most-traded items (by gold traded) exported besides the basket

SCHEMA = """
CREATE TABLE IF NOT EXISTS daily (
    day     INTEGER NOT NULL,   -- days since 1970-01-01 (UTC)
    item_id INTEGER NOT NULL,
    gp      INTEGER NOT NULL,   -- gold spent: sum of hourly average price x items traded
    vol     INTEGER NOT NULL,   -- items traded (only hours with a price)
    PRIMARY KEY (day, item_id)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS days (day INTEGER PRIMARY KEY, hours INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS items (item_id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE IF NOT EXISTS progress (chunk_start INTEGER PRIMARY KEY);
"""

AGGREGATE = """
SELECT ts / 86400 AS day, item_id,
       SUM(CASE WHEN avg_high IS NOT NULL THEN avg_high * high_vol ELSE 0 END)
     + SUM(CASE WHEN avg_low  IS NOT NULL THEN avg_low  * low_vol  ELSE 0 END) AS gp,
       SUM(CASE WHEN avg_high IS NOT NULL THEN high_vol ELSE 0 END)
     + SUM(CASE WHEN avg_low  IS NOT NULL THEN low_vol  ELSE 0 END) AS vol
FROM prices WHERE ts >= ? AND ts < ?
GROUP BY day, item_id
HAVING vol > 0
"""


def build_daily(full: Path, daily: Path, budget: float = 0, log=print) -> bool:
    """Fill the daily table, a month at a time. Returns True when complete."""
    t0 = time.time()
    src = sqlite3.connect(f"file:{full}?mode=ro", uri=True)
    dst = sqlite3.connect(str(daily))
    dst.execute("PRAGMA journal_mode=TRUNCATE")
    dst.executescript(SCHEMA)
    with dst:
        dst.executemany("INSERT OR REPLACE INTO items VALUES (?,?)", src.execute("SELECT item_id, name FROM items"))
        dst.execute("DELETE FROM days")
        dst.executemany("INSERT INTO days VALUES (?,?)",
                        src.execute("SELECT ts / 86400, COUNT(*) FROM fetched WHERE n_items > 0 GROUP BY 1"))
    lo, hi = src.execute("SELECT MIN(ts), MAX(ts) FROM fetched WHERE n_items > 0").fetchone()
    if lo is None:
        raise SystemExit(f"No price history found in {full}")
    done = {r[0] for r in dst.execute("SELECT chunk_start FROM progress")}
    chunks = [s for s in range(lo // CHUNK * CHUNK, hi + 1, CHUNK) if s not in done]
    for i, start in enumerate(chunks):
        if budget and time.time() - t0 > budget:
            log(f"Time budget reached; {len(chunks) - i} months left. Run again to continue.")
            src.close(), dst.close()
            return False
        rows = src.execute(AGGREGATE, (start, start + CHUNK)).fetchall()
        with dst:
            dst.executemany("INSERT OR REPLACE INTO daily VALUES (?,?,?,?)", rows)
            if start + CHUNK <= hi:  # the newest month is redone next time, as it fills up
                dst.execute("INSERT INTO progress VALUES (?)", (start,))
        log(f"  {fmt_day(start // DAY)}: {len(rows):,} item-days  ({i + 1}/{len(chunks)}, "
            f"{time.time() - t0:.0f}s)")
    src.close(), dst.close()
    return True


def fmt_day(day: int) -> str:
    return datetime.fromtimestamp(day * DAY, tz=timezone.utc).strftime("%Y-%m-%d")


def export(daily: Path, out: Path, top_n: int = TOP_N, log=print) -> int:
    con = sqlite3.connect(f"file:{daily}?mode=ro", uri=True)
    names = dict(con.execute("SELECT item_id, name FROM items"))
    by_name = {(n or "").lower(): i for i, n in names.items()}
    wanted = set()
    missing = []
    for name in basket_items():
        if name.lower() in by_name:
            wanted.add(by_name[name.lower()])
        else:
            missing.append(name)
    if missing:
        log("Not in the item list (left out): " + ", ".join(missing))
    top = [r[0] for r in con.execute("SELECT item_id FROM daily GROUP BY item_id ORDER BY SUM(gp) DESC LIMIT ?",
                                     (top_n,))]
    wanted.update(top)
    full_days = {d for d, h in con.execute("SELECT day, hours FROM days") if h >= 12}
    ids = ",".join(map(str, sorted(wanted)))
    n = 0
    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out, "wt", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "item", "price", "volume"])
        for day, iid, gp, vol in con.execute(
                f"SELECT day, item_id, gp, vol FROM daily WHERE item_id IN ({ids}) ORDER BY day, item_id"):
            if day not in full_days:  # skip days with under 12 hours of data (e.g. today)
                continue
            w.writerow([fmt_day(day), names[iid], round(gp / vol, 2), vol])
            n += 1
    con.close()
    log(f"Wrote {n:,} rows for {len(wanted)} items to {out} ({out.stat().st_size / 1e6:.1f} MB)")
    return n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--budget", type=float, default=0, help="stop step 1 after this many seconds (0 = no limit)")
    ap.add_argument("--top", type=int, default=TOP_N, help="most-traded items to export besides the basket")
    args = ap.parse_args(argv)
    if not FULL.exists():
        print(f"Can't find the price history at {FULL}", file=sys.stderr)
        return 1
    print("Step 1: daily totals (a few minutes the first time)...")
    if not build_daily(FULL, DAILY, args.budget):
        return 2
    print("Step 2: writing the file...")
    export(DAILY, OUT, args.top)
    if sys.platform == "darwin":
        subprocess.run(["open", "-R", str(OUT)], check=False)  # show it in Finder
        print("Done. Finder now shows the file: drag it into the chat with Claude.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
