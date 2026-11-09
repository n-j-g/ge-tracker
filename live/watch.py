#!/usr/bin/env python3
"""Paper-trade "trap" sell offers against suspected GE gold transfers, live.

Runs forever on an always-on machine (see live/README.md). Every minute it reads the
Wiki price API's /latest (last trade per item, to the second) and /5m (5-minute
averages and volumes); every hour /1h, for each item's typical price.

A *transfer* is the research definition (research/transfer_scan.py and friends): a cheap
item trading at >= 20x its typical price (median of the past week's hourly prices) and
>= 50k each, with >= 10m gp above normal value, grouped into episodes 12h apart.

Paper strategies (no real offers are placed):
  newest  after each transfer, list that item for 7 days at half the price just seen,
          holding twice the units; 8 offers, the newest replacing the oldest.
  score   keep offers on the 8 items with the highest recency score (each past transfer
          counts exp(-days/7) x log10(gold), plus 0.05 per transfer in the past year).
An offer goes up ARM_DELAY after the transfer is detected (time to log in and list it).
It "fills" when a later 5-minute bucket on that item trades at or above our ask that
started after our offer was up, assuming the GE fills the cheapest waiting offer first.

Standard library only; Python 3.9+.

    python3 -m live.watch --data ~/paper-data            # run
    python3 -m live.watch --data ~/paper-data --once     # one pass (testing)

Set PAPER_PUSH_URL to an https git URL (with a token) to publish results to a repo.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sqlite3
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

API = "https://prices.runescape.wiki/api/v1/osrs"
USER_AGENT = os.environ.get("GE_PROFIT_USER_AGENT",
                            "ge-tracker paper-trader (+https://github.com/n-j-g/ge-tracker)")
HERE = Path(__file__).resolve().parent

FACTOR = 20                  # price at least this many times typical...
MIN_PRICE = 50_000           # ...and at least this much each
MIN_EXCESS = 10_000_000      # gold above normal value for an episode to count
EPISODE_GAP = 12 * 3600      # prints closer than this on one item are one episode
TYPICAL_HOURS = 168          # typical price = median hourly price over the past week
TYPICAL_MIN_POINTS = 6
ARM_DELAY = 600              # seconds from detection until a paper offer is up
DAY = 86400


def log(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


def ge_tax(price: float) -> int:
    """GE tax per item sold: 2%, rounded down, capped at 5m."""
    return min(int(price * 0.02), 5_000_000)


def flagged_sides(h, hv, l, lv, typical):
    """The sides of a price record that look like a transfer: [(side, price, volume)]."""
    out = []
    if not typical or typical <= 0:
        return out
    for side, p, v in (("high", h, hv), ("low", l, lv)):
        if p and v and p >= MIN_PRICE and p >= FACTOR * typical:
            out.append((side, p, v))
    return out


# ---------------------------------------------------------------- paper strategies

@dataclass
class Trap:
    item: int
    ask: float
    stock: int
    active_from: int
    expires: Optional[int]
    trigger: int              # id of the episode that set this offer


@dataclass
class Book:
    """One paper strategy: its offers, fills and counters."""
    name: str
    kind: str                 # "newest" or "score"
    slots: int = 8
    ask_frac: float = 0.5
    days: int = 7
    stock_mult: float = 2.0
    delay: int = ARM_DELAY
    traps: dict = field(default_factory=dict)      # item -> Trap
    fills: list = field(default_factory=list)
    seen: int = 0             # transfers confirmed since start
    on_trap: int = 0          # ... on an item with one of our offers up when it started

    # -- state
    def to_dict(self):
        d = asdict(self)
        d["traps"] = {str(k): asdict(t) for k, t in self.traps.items()}
        return d

    @classmethod
    def from_dict(cls, d):
        traps = {int(k): Trap(**t) for k, t in d.pop("traps", {}).items()}
        b = cls(**d)
        b.traps = traps
        return b

    # -- offers
    def active(self, item: int, ts: int) -> Optional[Trap]:
        t = self.traps.get(item)
        if t and t.active_from <= ts and (t.expires is None or ts < t.expires):
            return t
        return None

    def expire(self, now: int):
        for item in [i for i, t in self.traps.items() if t.expires is not None and t.expires <= now]:
            del self.traps[item]

    def _arm(self, item, price, units, now, trigger):
        old = self.traps.pop(item, None)
        self.traps[item] = Trap(
            item=item, ask=round(self.ask_frac * price), stock=max(1, int(self.stock_mult * units)),
            active_from=old.active_from if old and old.active_from <= now else now + self.delay,
            expires=now + self.days * DAY if self.kind == "newest" else None, trigger=trigger)

    def check(self, item, ts, price, vol, episode_id, name=""):
        """A transfer print: does it fill our offer? Returns the fill or None."""
        t = self.active(item, ts)
        if not t or price < t.ask or t.stock <= 0:
            return None
        qty = min(int(vol), t.stock)
        t.stock -= qty
        fill = dict(book=self.name, ts=ts, item=item, name=name, ask=t.ask, qty=qty,
                    net=qty * (t.ask - ge_tax(t.ask)), price_seen=price, episode=episode_id,
                    same_episode=episode_id == t.trigger)
        self.fills.append(fill)
        return fill

    def on_transfer(self, ep, now, history):
        """A newly confirmed transfer episode."""
        self.seen += 1
        if self.active(ep["item"], ep["start"]):
            self.on_trap += 1
        if self.kind == "newest":
            self._arm(ep["item"], ep["gold"] / ep["units"], ep["units"], now, ep["id"])
            while len(self.traps) > self.slots:
                oldest = min(self.traps.values(), key=lambda t: (t.active_from, t.item))
                del self.traps[oldest.item]
        else:
            self.rerank(now, history, just=ep)

    def rerank(self, now, history, just=None):
        if self.kind != "score":
            return
        top = sorted((i for i in history if history[i]), key=lambda i: (-score(history[i], now), i))[:self.slots]
        for item in list(self.traps):
            if item not in top:
                del self.traps[item]
        for item in top:
            fresh = just is not None and just["item"] == item
            if item not in self.traps or fresh:
                last = history[item][-1]
                self._arm(item, last["price"], last["units"], now, just["id"] if fresh else -1)


def score(episodes, now):
    s = 0.0
    for e in episodes:
        age = (now - e["ts"]) / DAY
        if age < 0:
            continue
        s += math.exp(-age / 7) * math.log10(max(e["gold"], 10))
        if age <= 365:
            s += 0.05
    return s


# ---------------------------------------------------------------- engine

SCHEMA = """
CREATE TABLE IF NOT EXISTS hourly (ts INTEGER, item INTEGER, mid REAL, PRIMARY KEY (ts, item)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS buckets (ts INTEGER, item INTEGER, high INTEGER, high_vol INTEGER,
    low INTEGER, low_vol INTEGER, PRIMARY KEY (ts, item)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS prints (ts INTEGER, item INTEGER, side TEXT, price INTEGER, volume INTEGER,
    typical REAL, source TEXT, seen_at INTEGER, PRIMARY KEY (source, ts, item, side)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS trades (item INTEGER, side TEXT, trade_ts INTEGER, price INTEGER, seen_at INTEGER,
    PRIMARY KEY (item, side, trade_ts)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS episodes (id INTEGER PRIMARY KEY, item INTEGER, start INTEGER, last INTEGER,
    units INTEGER, gold REAL, excess REAL, confirmed_at INTEGER, source TEXT);
CREATE TABLE IF NOT EXISTS fills (book TEXT, ts INTEGER, item INTEGER, ask REAL, qty INTEGER, net REAL,
    price_seen REAL, episode INTEGER, same_episode INTEGER);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT);
"""


class Engine:
    def __init__(self, data_dir: Path):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.dir / "paper.sqlite"))
        self.db.executescript(SCHEMA)
        self.typical: dict[int, float] = {}
        self.names: dict[int, str] = {}
        self.history: dict[int, list] = {}          # item -> [{ts, price, units, gold}]
        self.open: dict[int, dict] = {}             # item -> current episode
        self.books = [Book("newest", "newest"), Book("score", "score")]
        self.last_5m = self.last_1h = 0
        self.started = int(time.time())
        self.next_id = 1
        self.counts = dict(buckets=0, hours=0, latest=0, errors=0)
        self._load_seed()
        self._load_state()
        self.watched = set(self.history) | set(self.open)

    # -- persistence
    def _load_seed(self):
        seed = HERE / "transfer_history.json"
        if seed.exists():
            for k, v in json.loads(seed.read_text()).items():
                self.names[int(k)] = v["name"]
                self.history[int(k)] = [dict(ts=e[0], price=e[1], units=e[2], gold=e[3]) for e in v["episodes"]]

    def _load_state(self):
        row = self.db.execute("SELECT value FROM state WHERE key='engine'").fetchone()
        if not row:
            return
        s = json.loads(row[0])
        self.books = [Book.from_dict(b) for b in s["books"]]
        self.history = {int(k): v for k, v in s["history"].items()}
        self.open = {int(k): v for k, v in s["open"].items()}
        self.names.update({int(k): v for k, v in s.get("names", {}).items()})
        self.last_5m, self.last_1h = s["last_5m"], s["last_1h"]
        self.started, self.next_id = s["started"], s["next_id"]
        self.counts.update(s.get("counts", {}))
        self.recompute_typical()

    def save(self):
        s = dict(books=[b.to_dict() for b in self.books], history=self.history, open=self.open,
                 names=self.names, last_5m=self.last_5m, last_1h=self.last_1h, started=self.started,
                 next_id=self.next_id, counts=self.counts)
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO state VALUES ('engine', ?)", (json.dumps(s),))

    # -- typical prices
    def ingest_hour(self, ts: int, data: dict):
        rows = []
        for k, d in data.items():
            vals = [v for v in (d.get("avgHighPrice"), d.get("avgLowPrice")) if v]
            if vals:
                rows.append((ts, int(k), sum(vals) / len(vals)))
        with self.db:
            self.db.executemany("INSERT OR REPLACE INTO hourly VALUES (?,?,?)", rows)
            self.db.execute("DELETE FROM hourly WHERE ts < ?", (ts - 30 * DAY,))
        self.last_1h = max(self.last_1h, ts)
        self.counts["hours"] += 1

    def recompute_typical(self):
        cut = self.last_1h - TYPICAL_HOURS * 3600
        by: dict[int, list] = {}
        for item, mid in self.db.execute("SELECT item, mid FROM hourly WHERE ts > ?", (cut,)):
            by.setdefault(item, []).append(mid)
        self.typical = {k: statistics.median(v) for k, v in by.items() if len(v) >= TYPICAL_MIN_POINTS}

    def scan_hour_for_history(self, ts: int, data: dict):
        """Hourly detection, used only to fill history while catching up (no fills)."""
        for k, d in data.items():
            item = int(k)
            sides = flagged_sides(d.get("avgHighPrice"), d.get("highPriceVolume"), d.get("avgLowPrice"),
                                  d.get("lowPriceVolume"), self.typical.get(item))
            if not sides:
                continue
            excess = sum((p - self.typical[item]) * v for _, p, v in sides)
            if excess < MIN_EXCESS:
                continue
            hist = self.history.setdefault(item, [])
            if hist and abs(hist[-1]["ts"] - ts) < EPISODE_GAP:
                continue
            units = sum(v for _, _, v in sides)
            gold = sum(p * v for _, p, v in sides)
            hist.append(dict(ts=ts, price=gold / units, units=units, gold=gold))
            hist.sort(key=lambda e: e["ts"])
            self.watched.add(item)
            with self.db:
                self.db.execute("INSERT INTO episodes VALUES (?,?,?,?,?,?,?,?,?)",
                                (self.next_id, item, ts, ts, units, gold, excess, ts + 3600, "1h"))
            self.next_id += 1

    # -- 5-minute buckets: detection, fills, new offers
    def ingest_5m(self, ts: int, data: dict, now: int):
        rows, new_fills = [], []
        for k, d in data.items():
            item = int(k)
            h, hv, l, lv = d.get("avgHighPrice"), d.get("highPriceVolume"), d.get("avgLowPrice"), d.get("lowPriceVolume")
            if item in self.watched:
                rows.append((ts, item, h, hv, l, lv))
            typ = self.typical.get(item)
            sides = flagged_sides(h, hv, l, lv, typ)
            if not sides:
                continue
            if item not in self.watched:
                self.watched.add(item)
                rows.append((ts, item, h, hv, l, lv))
            with self.db:
                self.db.executemany("INSERT OR IGNORE INTO prints VALUES (?,?,?,?,?,?,'5m',?)",
                                    [(ts, item, s, p, v, typ, now) for s, p, v in sides])
            ep = self.open.get(item)
            if ep is None or ts - ep["last"] > EPISODE_GAP:
                ep = dict(id=self.next_id, item=item, start=ts, last=ts, units=0, gold=0.0, excess=0.0,
                          confirmed_at=None)
                self.next_id += 1
                self.open[item] = ep
            for _, p, v in sides:                      # fills first: offers set before this bucket
                for b in self.books:
                    f = b.check(item, ts, p, v, ep["id"], self.names.get(item, ""))
                    if f:
                        new_fills.append(f)
            ep["last"] = ts
            ep["units"] += sum(v for _, _, v in sides)
            ep["gold"] += sum(p * v for _, p, v in sides)
            ep["excess"] += sum((p - typ) * v for _, p, v in sides)
            if ep["confirmed_at"] is None and ep["excess"] >= MIN_EXCESS:
                ep["confirmed_at"] = now
                hist = self.history.setdefault(item, [])
                hist.append(dict(ts=ep["start"], price=ep["gold"] / ep["units"], units=ep["units"], gold=ep["gold"]))
                for b in self.books:
                    b.on_transfer(ep, now, self.history)
                log(f"transfer: {self.names.get(item, item)} {ep['units']:,} @ {ep['gold'] / ep['units']:,.0f}")
            elif ep["confirmed_at"] is not None:
                hist = self.history[item]
                if hist and hist[-1]["ts"] == ep["start"]:
                    hist[-1].update(price=ep["gold"] / ep["units"], units=ep["units"], gold=ep["gold"])
            with self.db:
                self.db.execute("INSERT OR REPLACE INTO episodes VALUES (?,?,?,?,?,?,?,?,?)",
                                (ep["id"], item, ep["start"], ep["last"], ep["units"], ep["gold"], ep["excess"],
                                 ep["confirmed_at"], "5m"))
        with self.db:
            self.db.executemany("INSERT OR REPLACE INTO buckets VALUES (?,?,?,?,?,?)", rows)
            self.db.executemany("INSERT INTO fills VALUES (?,?,?,?,?,?,?,?,?)",
                                [(f["book"], f["ts"], f["item"], f["ask"], f["qty"], f["net"], f["price_seen"],
                                  f["episode"], int(f["same_episode"])) for f in new_fills])
        for f in new_fills:
            log(f"paper fill [{f['book']}]: {f['name'] or f['item']} {f['qty']:,} @ {f['ask']:,.0f} = {f['net'] / 1e6:,.1f}m")
        for item in [i for i, e in self.open.items() if ts - e["last"] > EPISODE_GAP]:
            del self.open[item]
        self.last_5m = max(self.last_5m, ts)
        self.counts["buckets"] += 1
        return new_fills

    # -- minute-level last trades (for studying "tests" and reaction time)
    def ingest_latest(self, data: dict, now: int):
        trades, prints = [], []
        for k, d in data.items():
            item = int(k)
            typ = self.typical.get(item)
            for side in ("high", "low"):
                p, t = d.get(side), d.get(side + "Time")
                if not p or not t:
                    continue
                if item in self.watched:
                    trades.append((item, side, t, p, now))
                if typ and p >= MIN_PRICE and p >= FACTOR * typ:
                    prints.append((t, item, side, p, None, typ, "latest", now))
        with self.db:
            self.db.executemany("INSERT OR IGNORE INTO trades VALUES (?,?,?,?,?)", trades)
            self.db.executemany("INSERT OR IGNORE INTO prints VALUES (?,?,?,?,?,?,?,?)", prints)
        self.counts["latest"] += 1

    def housekeeping(self, now: int):
        for b in self.books:
            b.expire(now)
            b.rerank(now, self.history)
        with self.db:
            self.db.execute("DELETE FROM buckets WHERE ts < ?", (now - 120 * DAY,))
            self.db.execute("DELETE FROM trades WHERE trade_ts < ?", (now - 120 * DAY,))

    # -- results
    def status(self, now: int) -> dict:
        nm = lambda i: self.names.get(i, str(i))
        eps = self.db.execute("SELECT id, item, start, last, units, gold, confirmed_at FROM episodes "
                              "WHERE confirmed_at IS NOT NULL AND source='5m' ORDER BY start DESC LIMIT 100").fetchall()
        fills = self.db.execute("SELECT book, episode FROM fills").fetchall()
        caught = {}
        for book, epi in fills:
            caught.setdefault(epi, set()).add(book)
        books = []
        for b in self.books:
            books.append(dict(
                name=b.name, kind=b.kind, seen=b.seen, on_trap=b.on_trap,
                fills=len(b.fills), qty=sum(f["qty"] for f in b.fills), net=sum(f["net"] for f in b.fills),
                same_episode=sum(f["same_episode"] for f in b.fills),
                episodes_caught=len({f["episode"] for f in b.fills}),
                offers=[dict(item=t.item, name=nm(t.item), ask=t.ask, stock=t.stock, up=t.active_from <= now,
                             active_from=t.active_from, expires=t.expires) for t in
                        sorted(b.traps.values(), key=lambda t: -t.active_from)],
                recent_fills=[dict(f, name=nm(f["item"])) for f in b.fills[-20:]][::-1]))
        return dict(
            updated=now, started=self.started, last_5m=self.last_5m, last_1h=self.last_1h,
            counts=self.counts, typical_items=len(self.typical), watched=len(self.watched),
            transfers_total=self.db.execute(
                "SELECT COUNT(*) FROM episodes WHERE confirmed_at IS NOT NULL AND source='5m'").fetchone()[0],
            transfers_24h=sum(1 for e in eps if e[2] >= now - DAY),
            books=books,
            transfers=[dict(id=e[0], item=e[1], name=nm(e[1]), start=e[2], last=e[3], units=e[4], gold=e[5],
                            price=e[5] / e[4], detected=e[6], caught_by=sorted(caught.get(e[0], [])))
                       for e in eps[:50]],
            settings=dict(factor=FACTOR, min_price=MIN_PRICE, min_excess=MIN_EXCESS, arm_delay=ARM_DELAY))

    def export(self, out: Path, now: int):
        out.mkdir(parents=True, exist_ok=True)
        (out / "status.json").write_text(json.dumps(self.status(now), indent=1))
        nm = lambda i: self.names.get(i, "")
        with (out / "transfers.csv").open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "item_id", "name", "start_utc_ts", "last_ts", "units", "gold", "excess", "detected_ts", "source"])
            for r in self.db.execute("SELECT id, item, start, last, units, gold, excess, confirmed_at, source "
                                     "FROM episodes WHERE confirmed_at IS NOT NULL ORDER BY start"):
                w.writerow([r[0], r[1], nm(r[1])] + [round(x) if isinstance(x, float) else x for x in r[2:]])
        with (out / "fills.csv").open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["book", "ts", "item_id", "name", "ask", "qty", "net", "price_seen", "episode", "same_episode"])
            for r in self.db.execute("SELECT * FROM fills ORDER BY ts"):
                w.writerow([r[0], r[1], r[2], nm(r[2])] + list(r[3:]))
        with (out / "prints.csv").open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["source", "ts", "item_id", "name", "side", "price", "volume", "typical", "seen_at"])
            for r in self.db.execute("SELECT source, ts, item, side, price, volume, typical, seen_at FROM prints "
                                     "WHERE ts > ? ORDER BY ts", (now - 30 * DAY,)):
                w.writerow([r[0], r[1], r[2], nm(r[2]), r[3], r[4], r[5], round(r[6], 1) if r[6] else "", r[7]])


# ---------------------------------------------------------------- network and main loop

def get_json(path: str):
    req = urllib.request.Request(f"{API}/{path}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def publish(out: Path, url: str):
    """Commit the exported files and push them to the data repo."""
    def git(*a):
        return subprocess.run(["git", "-C", str(out), *a], capture_output=True, text=True, timeout=120)
    if not (out / ".git").exists():
        git("init", "-q", "-b", "main")
        git("config", "user.name", "ge-paper-bot")
        git("config", "user.email", "ge-paper-bot@users.noreply.github.com")
    git("remote", "remove", "origin")
    git("remote", "add", "origin", url)
    git("add", "-A")
    git("commit", "-q", "-m", "paper-trading update")
    r = git("push", "-q", "--force", "origin", "main")
    if r.returncode:
        log("push failed:", r.stderr.replace(url, "<repo>").strip()[:300])


def bootstrap(eng: Engine):
    """First run: a week of hourly prices for typical prices, scanning them for transfers."""
    if eng.last_1h:
        return
    latest = get_json("1h")["timestamp"]
    hours = list(range(latest - (TYPICAL_HOURS - 1) * 3600, latest + 1, 3600))
    raw = {}
    log(f"bootstrap: downloading {len(hours)} hours of prices (about {len(hours)} seconds)")
    for ts in hours:
        try:
            raw[ts] = get_json(f"1h?timestamp={ts}")["data"]
            eng.ingest_hour(ts, raw[ts])
        except Exception as e:
            log("bootstrap hour failed", ts, e)
        time.sleep(1)
    eng.recompute_typical()
    for ts in hours:
        if ts in raw:
            eng.scan_hour_for_history(ts, raw[ts])
    now = int(time.time())
    for b in eng.books:                       # warm start: offers for transfers seen in the past week
        if b.kind == "newest":
            recent = sorted(((e["ts"], item, e) for item, h in eng.history.items() for e in h
                             if e["ts"] >= now - b.days * DAY))
            for ts, item, e in recent:
                b._arm(item, e["price"], e["units"], ts, -1)
                b.traps[item].active_from = now
                b.traps[item].expires = ts + b.days * DAY
            while len(b.traps) > b.slots:
                del b.traps[min(b.traps.values(), key=lambda t: (t.expires, t.item)).item]
        b.rerank(now, eng.history)
    eng.save()
    log(f"bootstrap done: typical prices for {len(eng.typical):,} items, {len(eng.history)} items with past transfers")


def refresh_names(eng: Engine):
    eng.names.update({int(m["id"]): m["name"] for m in get_json("mapping")})


def run(data_dir: Path, once: bool = False, publish_every: int = 1800):
    eng = Engine(data_dir)
    push_url = os.environ.get("PAPER_PUSH_URL", "").strip()
    out = data_dir / "publish"
    try:
        refresh_names(eng)
    except Exception as e:
        log("names failed:", e)
    bootstrap(eng)
    last_names = last_hour_check = last_publish = last_house = 0
    backoff = 0
    while True:
        loop_start = time.time()
        now = int(loop_start)
        try:
            eng.ingest_latest(get_json("latest")["data"], now)
            r = get_json("5m")
            ts = r["timestamp"]
            if eng.last_5m and ts > eng.last_5m + 300:          # catch up on missed buckets (up to 2 hours)
                for missed in range(max(eng.last_5m + 300, ts - 24 * 300), ts, 300):
                    eng.ingest_5m(missed, get_json(f"5m?timestamp={missed}")["data"], now)
                    time.sleep(1)
            if ts > eng.last_5m:
                eng.ingest_5m(ts, r["data"], now)
            if now - last_hour_check >= 300:
                h = get_json("1h")
                if h["timestamp"] > eng.last_1h:
                    start = max(eng.last_1h + 3600, h["timestamp"] - 24 * 3600) if eng.last_1h else h["timestamp"]
                    for missed in range(start, h["timestamp"], 3600):
                        eng.ingest_hour(missed, get_json(f"1h?timestamp={missed}")["data"])
                        time.sleep(1)
                    eng.ingest_hour(h["timestamp"], h["data"])
                    eng.recompute_typical()
                last_hour_check = now
            if now - last_house >= 3600:
                eng.housekeeping(now)
                last_house = now
            if now - last_names >= DAY:
                refresh_names(eng)
                last_names = now
            eng.save()
            backoff = 0
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError) as e:
            eng.counts["errors"] += 1
            backoff = min(600, (backoff or 30) * 2)
            log("fetch error:", e, f"(waiting {backoff}s)")
            time.sleep(backoff)
        if now - last_publish >= publish_every or once:
            try:
                eng.export(out, now)
                if push_url:
                    publish(out, push_url)
            except Exception as e:
                log("export failed:", e)
            last_publish = now
        if once:
            return eng
        time.sleep(max(5, 60 - (time.time() - loop_start)))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", type=Path, default=Path.home() / "paper-data")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args(argv)
    run(a.data.expanduser(), once=a.once)


if __name__ == "__main__":
    sys.exit(main())
