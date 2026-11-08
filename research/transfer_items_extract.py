#!/usr/bin/env python3
"""Copy every hourly row for items that ever had a suspected transfer (transfer_episodes.csv)
into data/history/transfer_items.sqlite, so lead-up activity can be studied quickly.
Resumable, month by month; pass --since YYYY-MM-DD and --budget seconds."""
from __future__ import annotations
import argparse, csv, sqlite3, sys, time, datetime as dt
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
FULL = ROOT / "data/history/prices_1h.sqlite"
OUT = Path.home() / "scratch" / "transfer_items.sqlite"
MONTH = 30 * 86400
ap = argparse.ArgumentParser(); ap.add_argument("--since", default="2024-01-01"); ap.add_argument("--budget", type=float, default=160)
a = ap.parse_args(); t0 = time.time()
ids = sorted({int(r["item_id"]) for r in csv.DictReader((ROOT / "data/history/results/transfer_episodes.csv").open())})
src = sqlite3.connect(f"file:{FULL}?mode=ro", uri=True)
out = sqlite3.connect(str(OUT)); out.execute("PRAGMA journal_mode=TRUNCATE")
out.executescript("""CREATE TABLE IF NOT EXISTS prices (ts INTEGER, item_id INTEGER, avg_high INTEGER, high_vol INTEGER,
  avg_low INTEGER, low_vol INTEGER, PRIMARY KEY (item_id, ts)) WITHOUT ROWID;
  CREATE TABLE IF NOT EXISTS progress (chunk INTEGER PRIMARY KEY);""")
done = {r[0] for r in out.execute("SELECT chunk FROM progress")}
lo = int(dt.datetime.fromisoformat(a.since).replace(tzinfo=dt.timezone.utc).timestamp())
hi = src.execute("SELECT MAX(ts) FROM fetched").fetchone()[0]
idset = set(ids)
chunks = [s for s in range(lo, hi + 1, MONTH) if s not in done]
for i, s in enumerate(chunks):
    if time.time() - t0 > a.budget:
        print(f"budget: {len(chunks) - i} chunks left"); sys.exit(2)
    rows = [r for r in src.execute("SELECT ts,item_id,avg_high,high_vol,avg_low,low_vol FROM prices WHERE ts>=? AND ts<?", (s, s + MONTH)) if r[1] in idset]
    with out:
        out.executemany("INSERT OR REPLACE INTO prices VALUES (?,?,?,?,?,?)", rows); out.execute("INSERT INTO progress VALUES (?)", (s,))
print("done", out.execute("SELECT COUNT(*) FROM prices").fetchone()[0], "rows")
