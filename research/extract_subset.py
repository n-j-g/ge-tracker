#!/usr/bin/env python3
"""Copy the hourly rows for the study's items out of the full history database
into a small file that's quick to move and analyse.

    python3 research/extract_subset.py              # run / resume (works in time-boxed chunks)
    python3 research/extract_subset.py --budget 0   # no time limit

Standard library only, so it runs on the machine holding the 4 GB database.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from research.chains import all_items  # noqa: E402

FULL = ROOT / "data" / "history" / "prices_1h.sqlite"
SUBSET = ROOT / "data" / "history" / "study_subset.sqlite"
CHUNK = 30 * 24 * 3600  # copy a month of hours at a time


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=float, default=150, help="stop after this many seconds (0 = no limit)")
    args = ap.parse_args(argv)
    t0 = time.time()

    src = sqlite3.connect(f"file:{FULL}?mode=ro", uri=True)
    names = {n.lower(): n for n in all_items()}
    found = {name.lower(): (iid, name) for iid, name in src.execute("SELECT item_id, name FROM items")}
    missing = [names[n] for n in names if n not in found]
    if missing:
        print("Not found in the item list:", missing, file=sys.stderr)
        return 1
    ids = sorted(found[n][0] for n in names)

    dst = sqlite3.connect(str(SUBSET))
    dst.execute("PRAGMA journal_mode=TRUNCATE")
    dst.executescript("""
        CREATE TABLE IF NOT EXISTS prices (ts INTEGER, item_id INTEGER, avg_high INTEGER, high_vol INTEGER,
                                           avg_low INTEGER, low_vol INTEGER, PRIMARY KEY (ts, item_id)) WITHOUT ROWID;
        CREATE TABLE IF NOT EXISTS items (item_id INTEGER PRIMARY KEY, name TEXT, buy_limit INTEGER,
                                          members INTEGER, value INTEGER, highalch INTEGER);
        CREATE TABLE IF NOT EXISTS fetched (ts INTEGER PRIMARY KEY, n_items INTEGER);
        CREATE TABLE IF NOT EXISTS progress (chunk_start INTEGER PRIMARY KEY);
    """)
    with dst:
        dst.executemany("INSERT OR REPLACE INTO items VALUES (?,?,?,?,?,?)",
                        src.execute(f"SELECT item_id, name, buy_limit, members, value, highalch FROM items "
                                    f"WHERE item_id IN ({','.join(map(str, ids))})"))
        dst.executemany("INSERT OR REPLACE INTO fetched VALUES (?,?)", src.execute("SELECT ts, n_items FROM fetched"))

    lo, hi = src.execute("SELECT MIN(ts), MAX(ts) FROM fetched").fetchone()
    done = {r[0] for r in dst.execute("SELECT chunk_start FROM progress")}
    chunks = [s for s in range(lo // CHUNK * CHUNK, hi + 1, CHUNK) if s not in done]
    id_list = ",".join(map(str, ids))
    for i, start in enumerate(chunks):
        if args.budget and time.time() - t0 > args.budget:
            print(f"Time budget reached: {len(chunks) - i} of {len(chunks) + len(done)} months left; rerun to continue.")
            return 2
        rows = src.execute(f"SELECT ts, item_id, avg_high, high_vol, avg_low, low_vol FROM prices "
                           f"WHERE ts >= ? AND ts < ? AND item_id IN ({id_list})", (start, start + CHUNK)).fetchall()
        with dst:
            dst.executemany("INSERT OR REPLACE INTO prices VALUES (?,?,?,?,?,?)", rows)
            dst.execute("INSERT INTO progress VALUES (?)", (start,))
    n = dst.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
    print(f"Done: {len(ids)} items, {n:,} rows in {SUBSET} ({SUBSET.stat().st_size / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
