#!/usr/bin/env python3
"""Download hourly GE price history for every item into a local SQLite database.

Uses the OSRS Wiki real-time price API's /1h endpoint with a timestamp, which
returns every item's average instant-buy/instant-sell price and volume for one
hour in a single request (the bulk-friendly way the Wiki recommends).

    python3 research/backfill_history.py            # run / resume the backfill
    python3 research/backfill_history.py --status   # show progress only

Keep a Mac awake while it runs with:  caffeinate -i python3 research/backfill_history.py

Polite by design: one request at a time, at most one per second by default,
descriptive User-Agent, backs off on errors and stops if the API keeps refusing.
Resumable: hours already stored are skipped, so it's safe to stop and restart.
Newest hours are fetched first, so recent history is usable early.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://prices.runescape.wiki/api/v1/osrs"
USER_AGENT = ("ge-tracker history backfill, one request/second "
              "(+https://github.com/n-j-g/ge-tracker)")
HOUR = 3600
# The API's hourly history starts in early 2021; empty hours before that are
# recorded as fetched with 0 items. We search from here for the first data.
SEARCH_FROM = int(datetime(2021, 1, 1, tzinfo=timezone.utc).timestamp())
DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "history" / "prices_1h.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    ts        INTEGER NOT NULL,   -- start of the hour, Unix seconds (UTC)
    item_id   INTEGER NOT NULL,
    avg_high  INTEGER,            -- average instant-buy price (NULL if no trades)
    high_vol  INTEGER NOT NULL,   -- items traded at the high side in the hour
    avg_low   INTEGER,            -- average instant-sell price (NULL if no trades)
    low_vol   INTEGER NOT NULL,
    PRIMARY KEY (ts, item_id)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS fetched (
    ts         INTEGER PRIMARY KEY,  -- hours already downloaded (even if empty)
    n_items    INTEGER NOT NULL,
    fetched_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS items (
    item_id INTEGER PRIMARY KEY, name TEXT, buy_limit INTEGER, members INTEGER,
    value INTEGER, highalch INTEGER, updated_at INTEGER
);
"""


# --------------------------------------------------------------------------- api

class ApiError(Exception):
    pass


def get_json(url: str, timeout: float = 60):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def fetch_hour(ts: int, getter=get_json) -> dict:
    """{item_id: row} for the hour starting at ts."""
    data = getter(f"{API}/1h?timestamp={ts}")
    if "data" not in data:
        raise ApiError(f"unexpected response for {ts}: {str(data)[:200]}")
    return data["data"]


def rows_for(ts: int, data: dict) -> list[tuple]:
    rows = []
    for item_id, v in data.items():
        rows.append((ts, int(item_id), v.get("avgHighPrice"), v.get("highPriceVolume") or 0,
                     v.get("avgLowPrice"), v.get("lowPriceVolume") or 0))
    return rows


# --------------------------------------------------------------------------- storage

def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.executescript(SCHEMA)
    return con


def store_hour(con: sqlite3.Connection, ts: int, data: dict) -> int:
    rows = rows_for(ts, data)
    with con:  # one transaction per hour: a crash never leaves half an hour stored
        con.executemany("INSERT OR REPLACE INTO prices VALUES (?,?,?,?,?,?)", rows)
        con.execute("INSERT OR REPLACE INTO fetched VALUES (?,?,?)", (ts, len(rows), int(time.time())))
    return len(rows)


def store_mapping(con: sqlite3.Connection, mapping: list[dict]) -> None:
    now = int(time.time())
    with con:
        con.executemany("INSERT OR REPLACE INTO items VALUES (?,?,?,?,?,?,?)",
                        [(m["id"], m.get("name"), m.get("limit"), int(bool(m.get("members"))),
                          m.get("value"), m.get("highalch"), now) for m in mapping])


def done_hours(con: sqlite3.Connection) -> set[int]:
    return {r[0] for r in con.execute("SELECT ts FROM fetched")}


# --------------------------------------------------------------------------- planning

def latest_complete_hour(now: float) -> int:
    """Start of the most recent hour that has fully ended."""
    return int(now) // HOUR * HOUR - HOUR


def find_first_hour(lo: int, hi: int, has_data) -> int:
    """Binary search for the first hour with data, given has_data(ts) is False
    before some point and True after it. lo/hi are hour starts."""
    while hi - lo > HOUR:
        mid = (lo + hi) // 2 // HOUR * HOUR
        if has_data(mid):
            hi = mid
        else:
            lo = mid
    return hi


def plan(first: int, last: int, done: set[int]) -> list[int]:
    """Hours still to fetch, newest first."""
    return [ts for ts in range(last, first - 1, -HOUR) if ts not in done]


def fmt_ts(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:00 UTC")


def fmt_duration(seconds: float) -> str:
    h, m = divmod(int(seconds) // 60, 60)
    return f"{h}h {m:02d}m"


# --------------------------------------------------------------------------- main

def status(con: sqlite3.Connection, db: Path) -> None:
    n, lo, hi = con.execute("SELECT COUNT(*), MIN(ts), MAX(ts) FROM fetched WHERE n_items > 0").fetchone()
    size = db.stat().st_size / 1e9 if db.exists() else 0
    print(f"{n:,} hours with data stored" + (f", {fmt_ts(lo)} to {fmt_ts(hi)}" if n else "")
          + f"; database {size:.2f} GB at {db}")


def run(db: Path, delay: float, max_failures: int, limit: int | None, getter=get_json,
        sleep=time.sleep, now=time.time) -> int:
    con = connect(db)
    try:
        store_mapping(con, getter(f"{API}/mapping"))
    except (urllib.error.URLError, OSError, ValueError) as e:
        print(f"warning: couldn't refresh item names ({e}); continuing", file=sys.stderr)

    last = latest_complete_hour(now())
    known = con.execute("SELECT value FROM meta WHERE key = 'history_start'").fetchone()
    if known:
        first = int(known[0])
    else:
        print("Finding where the API's history begins...")

        def has_data(ts: int) -> bool:
            found = bool(fetch_hour(ts, getter))
            sleep(delay)
            return found

        first = find_first_hour(SEARCH_FROM, last, has_data)
        with con:
            con.execute("INSERT OR REPLACE INTO meta VALUES ('history_start', ?)", (str(first),))
        print(f"History starts at {fmt_ts(first)}")
    todo = plan(first, last, done_hours(con))
    if limit is not None:
        todo = todo[:limit]
    total = len(todo)
    print(f"{total:,} hours to download ({fmt_ts(first)} to {fmt_ts(last)}), "
          f"about {fmt_duration(total * max(delay, 0.5))} at this pace. Ctrl+C to stop; rerun to resume.")

    failures, start, done = 0, now(), 0
    for ts in todo:
        t0 = now()
        while True:  # retry this hour (with growing waits) until it works or we give up
            try:
                n = store_hour(con, ts, fetch_hour(ts, getter))
                failures = 0
                break
            except (urllib.error.URLError, OSError, ValueError, ApiError) as e:
                failures += 1
                wait = min(300, 5 * 2 ** (failures - 1))
                print(f"  {fmt_ts(ts)}: {e} (failure {failures}/{max_failures}, waiting {wait}s)",
                      file=sys.stderr)
                if failures >= max_failures:
                    print("Too many failures in a row; stopping. Rerun later to resume.", file=sys.stderr)
                    return 1
                sleep(wait)
                t0 = now()
        done += 1
        if done % 100 == 0 or done == total:
            rate = done / max(now() - start, 1e-9)
            print(f"  {done:,}/{total:,} hours  (now at {fmt_ts(ts)}, {n:,} items)  "
                  f"~{fmt_duration((total - done) / rate) if rate else '?'} left")
        elapsed = now() - t0
        if elapsed < delay:
            sleep(delay - elapsed)
    status(con, db)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Backfill hourly GE price history into SQLite.")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"database file (default {DEFAULT_DB})")
    ap.add_argument("--delay", type=float, default=1.0,
                    help="minimum seconds between requests (default 1.0; please don't go lower)")
    ap.add_argument("--max-failures", type=int, default=8, help="stop after this many errors in a row")
    ap.add_argument("--limit", type=int, help="only fetch this many hours (for a trial run)")
    ap.add_argument("--status", action="store_true", help="show what's stored and exit")
    args = ap.parse_args(argv)
    if args.status:
        status(connect(args.db), args.db)
        return 0
    if args.delay < 1.0:
        print("note: keeping at least 1 second between requests, as a courtesy to the Wiki", file=sys.stderr)
        args.delay = 1.0
    try:
        return run(args.db, args.delay, args.max_failures, args.limit)
    except KeyboardInterrupt:
        print("\nStopped. Everything downloaded so far is saved; rerun to resume.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
