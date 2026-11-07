#!/usr/bin/env python3
"""Crypto Chart Scanner for crypto-scanner. Standard library only.

    python3 scan.py universe                      # Coinbase USD pairs -> crypto/universe.txt
    python3 scan.py daily                         # UTC daily closes -> crypto/watchlist.json
    python3 scan.py daily --products BTC-USD,ETH-USD,SOL-USD
    python3 scan.py orb                           # UTC-day opening-range breakouts so far
    python3 scan.py orb --session 13:30 --or-minutes 30   # range from the US open instead

Crypto trades 24/7, so there is no opening bell. Every "day" here is a UTC
day (00:00 to 24:00 UTC), the same day Coinbase uses for its daily candles,
and the opening range is the first --or-minutes after --session (default
00:00 UTC, 60 minutes). Change --session to anchor the range somewhere else.

Data: Coinbase Exchange public market data (no key, no account):
  https://api.exchange.coinbase.com/products                 the pairs
  https://api.exchange.coinbase.com/products/stats           24-hour volume, every pair, one request
  https://api.exchange.coinbase.com/products/<ID>/candles    [time, low, high, open, close, volume]
Yahoo Finance's chart (BTC-USD, same names) is the fallback for one pair's
candles when Coinbase fails. Both are free and can lag or rate-limit.

Rules (daily, on complete UTC daily closes; the same rules as trader-scanner):
  breakout_20d     last close above every close of the 20 days before it
  bull_flag        up more than 10 % over the 10 days before the last 5,
                   then the last 5 closes inside a 5 % range
  reclaim_ma20     the close before was under its 20-day average, the last above it
  oversold         RSI 14 (Wilder) under 30
  oversold_bounce  RSI 14 was under 30 the day before and the last close is up

Opening-range breakout (5-minute candles): range high = the highest high of the
range bars, low = the lowest low; a hit is the first COMPLETED 5-minute bar
after the range that closes above the range high.

Exit code 0 when the scan found something, 1 when it found nothing or could not run.
"""

import argparse
import math
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UTC = datetime.timezone.utc
CB = "https://api.exchange.coinbase.com"
YAHOO_HOSTS = ("https://query2.finance.yahoo.com", "https://query1.finance.yahoo.com")
UA = "Mozilla/5.0 (compatible; testbase-crypto-skills/0.1)"
STABLE = {"USDT", "USDC", "DAI", "PYUSD", "GUSD", "EURC", "USDS", "FDUSD", "TUSD", "PAX",
          "USDP", "RLUSD", "BUSD", "UST", "USD1", "FRAX", "LUSD", "GYEN", "EURT", "XSGD"}
MIN_DAILY_BARS = 30
OUT_DIR = "crypto"
PAUSE = 0.12


# ---------------------------------------------------------------- clock

def parse_now(text):
    """'2026-11-07 09:30' (UTC) -> aware datetime; None -> now."""
    if not text:
        return datetime.datetime.now(UTC)
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(text, fmt).replace(tzinfo=UTC)
        except ValueError:
            pass
    raise SystemExit("scan.py: --now wants 'YYYY-MM-DD HH:MM' in UTC, got %r" % text)


def parse_hhmm(text, flag):
    try:
        h, m = text.split(":")
        h, m = int(h), int(m)
        if 0 <= h < 24 and 0 <= m < 60:
            return h * 60 + m
    except ValueError:
        pass
    raise SystemExit("scan.py: %s wants HH:MM (UTC), got %r" % (flag, text))


def ts(dt):
    return int(dt.timestamp())


def utc(t):
    return datetime.datetime.fromtimestamp(t, UTC)


def hm(t):
    return utc(t).strftime("%H:%M")


# ---------------------------------------------------------------- fetch

def _sleep(s):
    time.sleep(s)


def http_get(url, timeout=20):
    """GET with one retry after 5 s on 429 and one on a 5xx. Returns text."""
    for attempt in range(3):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if attempt < 2 and (e.code == 429 or e.code >= 500):
                _sleep(5 if e.code == 429 else 2)
                continue
            raise
    raise RuntimeError("unreachable")


def get_json(url):
    return json.loads(http_get(url))


def cb_products():
    return get_json(CB + "/products")


def cb_stats():
    return get_json(CB + "/products/stats")


def cb_candles(pid, gran, start, end):
    """Candles in [start, end) (epoch seconds), paged 300 at a time, oldest first.
    Each bar: (t, open, high, low, close, volume)."""
    out = {}
    step = 300 * gran
    a = start
    while a < end:
        b = min(end, a + step)
        q = urllib.parse.urlencode({"granularity": gran,
                                    "start": utc(a).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                    "end": utc(b).strftime("%Y-%m-%dT%H:%M:%SZ")})
        rows = get_json("%s/products/%s/candles?%s" % (CB, urllib.parse.quote(pid), q))
        if isinstance(rows, dict):
            raise RuntimeError(rows.get("message") or "Coinbase error")
        for t, lo, hi, op, cl, v in rows:
            out[int(t)] = (int(t), float(op), float(hi), float(lo), float(cl), float(v))
        a = b
        if a < end:
            _sleep(PAUSE)
    return [out[k] for k in sorted(out) if start <= k < end]


def yahoo_candles(pid, gran, start, end):
    """Fallback: Yahoo chart for the same name (BTC-USD). Daily or 5-minute only."""
    interval = {86400: "1d", 300: "5m"}.get(gran)
    if not interval:
        raise RuntimeError("Yahoo fallback only has 1d and 5m")
    q = urllib.parse.urlencode({"period1": start, "period2": end, "interval": interval})
    last = None
    for host in YAHOO_HOSTS:
        try:
            doc = get_json("%s/v8/finance/chart/%s?%s" % (host, urllib.parse.quote(pid), q))
            break
        except Exception as e:  # noqa: BLE001 - try the other host
            last = e
    else:
        raise RuntimeError("Yahoo: %s" % last)
    res = ((doc.get("chart") or {}).get("result") or [None])[0]
    if not res or not res.get("timestamp"):
        raise RuntimeError("Yahoo: no data for %s" % pid)
    qd = res["indicators"]["quote"][0]
    out = []
    for i, t in enumerate(res["timestamp"]):
        o, h, l, c, v = (qd[k][i] for k in ("open", "high", "low", "close", "volume"))
        if None in (o, h, l, c):
            continue
        t = int(t) - int(t) % gran
        if start <= t < end:
            out.append((t, float(o), float(h), float(l), float(c), float(v or 0)))
    return out


def candles(pid, gran, start, end, a=None):
    """Coinbase first, Yahoo second. Returns (bars, source)."""
    try:
        return cb_candles(pid, gran, start, end), "coinbase"
    except Exception as e:  # noqa: BLE001
        progress(a, "  %s: Coinbase failed (%s), trying Yahoo" % (pid, e))
    return yahoo_candles(pid, gran, start, end), "yahoo"


# ---------------------------------------------------------------- universe

def build_universe(products):
    """Coinbase /products -> sorted [(id, base)] of tradable USD spot pairs, stablecoins out."""
    keep, dropped = [], {}

    def drop(why):
        dropped[why] = dropped.get(why, 0) + 1

    for p in products:
        if p.get("quote_currency") != "USD":
            drop("not quoted in USD")
            continue
        if p.get("status") != "online" or p.get("trading_disabled"):
            drop("delisted or disabled")
            continue
        if p.get("cancel_only") or p.get("auction_mode"):
            drop("cancel-only or auction")
            continue
        base = (p.get("base_currency") or "").upper()
        if p.get("fx_stablecoin") or base in STABLE:
            drop("stablecoin")
            continue
        keep.append((p["id"], base))
    keep.sort()
    return keep, dropped


def read_universe(path):
    if not os.path.exists(path):
        raise SystemExit("scan.py: no %s yet. Run: python3 scan.py universe" % path)
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                out.append(line.split("|")[0])
    return out


# ---------------------------------------------------------------- daily rules

def rsi(closes, n=14):
    """Wilder's RSI on closes (same math as trader-scanner)."""
    if len(closes) < n + 1:
        return None
    g = [max(0.0, closes[i] - closes[i - 1]) for i in range(1, len(closes))]
    lo = [max(0.0, closes[i - 1] - closes[i]) for i in range(1, len(closes))]
    ag, al = sum(g[:n]) / n, sum(lo[:n]) / n
    for i in range(n, len(g)):
        ag = (ag * (n - 1) + g[i]) / n
        al = (al * (n - 1) + lo[i]) / n
    return 100 - 100 / (1 + ag / al) if al else 100.0


def find_setups(c):
    """closes (oldest first, >= 30) -> (setup keys, numbers). Same rules as trader-scanner."""
    last = c[-1]
    hi20 = max(c[-21:-1])
    ma20 = sum(c[-20:]) / 20.0
    ma20_prev = sum(c[-21:-1]) / 20.0
    run = c[-6] / c[-16] - 1
    rng5 = (max(c[-5:]) - min(c[-5:])) / last
    r = rsi(c)
    r_prev = rsi(c[:-1])
    tags = []
    if last > hi20:
        tags.append("breakout_20d")
    if run > 0.10 and rng5 < 0.05:
        tags.append("bull_flag")
    if c[-2] < ma20_prev and last > ma20:
        tags.append("reclaim_ma20")
    if r is not None and r < 30:
        tags.append("oversold")
    if r_prev is not None and r_prev < 30 and last > c[-2]:
        tags.append("oversold_bounce")
    return tags, {"rsi": r, "high20": hi20, "ma20": ma20,
                  "run_pct": run * 100, "range5_pct": rng5 * 100}


def complete_daily(bars, now_utc):
    """Drop today's still-forming UTC day (and anything in the future)."""
    cut = ts(now_utc)
    return [b for b in bars if b[0] + 86400 <= cut]


def usd_volume(stat):
    """Coinbase stats row -> (last price, 24h volume in USD) or (None, None)."""
    s = (stat or {}).get("stats_24hour") or {}
    try:
        last = float(s["last"])
        return last, float(s["volume"]) * last
    except (KeyError, TypeError, ValueError):
        return None, None


def scan_daily(daily, now_utc):
    """Pure. daily = {PID: [bars]} -> (hits, counts)."""
    hits = []
    counts = {"fetched": 0, "short": 0, "scanned": 0}
    for pid, bars in daily.items():
        if bars is None:
            continue
        counts["fetched"] += 1
        bars = complete_daily(bars, now_utc)
        if len(bars) < MIN_DAILY_BARS:
            counts["short"] += 1
            continue
        counts["scanned"] += 1
        closes = [b[4] for b in bars]
        tags, nums = find_setups(closes)
        if tags:
            hits.append({"product": pid, "setups": tags, "price": closes[-1],
                         "close_date": utc(bars[-1][0]).date().isoformat(),
                         "rsi": None if nums["rsi"] is None else round(nums["rsi"], 1)})
    return hits, counts


# ---------------------------------------------------------------- opening range

def orb_window(now_utc, session_min, or_minutes):
    """-> (session start epoch, range end epoch, cutoff epoch) or a reason string."""
    day = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    start = day + datetime.timedelta(minutes=session_min)
    if start > now_utc:
        start -= datetime.timedelta(days=1)  # today's session has not started: use yesterday's
    rng_end = start + datetime.timedelta(minutes=or_minutes)
    cutoff = min(now_utc, start + datetime.timedelta(days=1))
    cutoff = cutoff.replace(second=0, microsecond=0)
    cutoff -= datetime.timedelta(minutes=cutoff.minute % 5)
    if cutoff < rng_end + datetime.timedelta(minutes=5):
        return "the opening range (%d min from %s UTC) is not done yet plus one 5-minute bar; " \
               "try after %s UTC" % (or_minutes, start.strftime("%H:%M"),
                                     (rng_end + datetime.timedelta(minutes=5)).strftime("%H:%M"))
    return ts(start), ts(rng_end), ts(cutoff)


def orb_hit(bars, start, rng_end, cutoff):
    """bars: 5-minute bars, oldest first. Only bars that are complete by cutoff count.
    -> dict(hit...) | dict(reason=...)"""
    bars = [b for b in bars if start <= b[0] and b[0] + 300 <= cutoff and b[0] % 300 == 0]
    rng = [b for b in bars if b[0] < rng_end]
    need = (rng_end - start) // 300
    if len(rng) < need:
        return {"reason": "missing range bars (%d of %d): thin trading" % (len(rng), need)}
    hi = max(b[2] for b in rng)
    lo = min(b[3] for b in rng)
    for b in bars:
        if b[0] >= rng_end and b[4] > hi:
            return {"hit": True, "range_high": hi, "range_low": lo, "close": b[4],
                    "bar_close_utc": hm(b[0] + 300), "over_pct": (b[4] / hi - 1) * 100}
    return {"hit": False, "range_high": hi, "range_low": lo}


# ---------------------------------------------------------------- io

def progress(a, msg):
    if a is None or not getattr(a, "json", False):
        print(msg, file=sys.stderr)


def write_json(path, doc):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(doc, f, indent=2)
    os.replace(tmp, path)


def money(x):
    if x >= 1000:
        return "$%s" % format(round(x, 2), ",.2f")
    if x >= 1:
        return "$%.2f" % x
    digits = 4 - int(math.floor(math.log10(x))) - 1 if x > 0 else 2
    return "$%.*f" % (max(2, digits), x)


def big(x):
    for div, s in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if x >= div:
            return "$%.1f%s" % (x / div, s)
    return "$%.0f" % x


def pick_products(a):
    if a.products:
        return [p.strip().upper() for p in a.products.split(",") if p.strip()]
    return read_universe(os.path.join(a.out, "universe.txt"))


def liquid(pids, stats, min_usd, a):
    """-> ([(pid, last, usd_vol)] most traded first, illiquid count)."""
    rows, bad = [], 0
    for pid in pids:
        last, vol = usd_volume(stats.get(pid))
        if last is None or vol < min_usd:
            bad += 1
            continue
        rows.append((pid, last, vol))
    rows.sort(key=lambda r: -r[2])
    if a.limit:
        rows = rows[:a.limit]
    return rows, bad


SETUP_NAMES = {"breakout_20d": "20-day closing-high breakout", "bull_flag": "bull flag",
               "reclaim_ma20": "reclaimed the 20-day average", "oversold": "oversold (RSI under 30)",
               "oversold_bounce": "oversold bounce"}


# ---------------------------------------------------------------- commands

def cmd_universe(a):
    try:
        prods = cb_products()
    except Exception as e:  # noqa: BLE001
        print("scan.py: could not reach Coinbase: %s" % e)
        return 1
    keep, dropped = build_universe(prods)
    path = os.path.join(a.out, "universe.txt")
    os.makedirs(a.out, exist_ok=True)
    with open(path, "w") as f:
        f.write("# Coinbase USD spot pairs, stablecoins out, %s\n" %
                datetime.datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"))
        for pid, base in keep:
            f.write("%s|%s\n" % (pid, base))
    print("Coinbase products: %d. Kept %d tradable USD pairs (stablecoins out)." % (len(prods), len(keep)))
    print("Dropped: " + ", ".join("%d %s" % (n, k) for k, n in sorted(dropped.items(), key=lambda x: -x[1])) + ".")
    print("Wrote %s (one PRODUCT|BASE a line)." % path)
    return 0


def cmd_daily(a):
    now = parse_now(a.now)
    pids = pick_products(a)
    try:
        stats = cb_stats()
    except Exception as e:  # noqa: BLE001
        print("scan.py: could not read Coinbase 24-hour stats: %s" % e)
        return 1
    rows, illiquid = liquid(pids, stats, a.min_usd_volume, a)
    progress(a, "Fetching daily candles for %d pairs (%d under %s of 24-hour volume left out)..."
             % (len(rows), illiquid, big(a.min_usd_volume)))
    end = ts(now) - ts(now) % 86400 + 86400
    start = end - 120 * 86400
    daily, failed, sources = {}, 0, {}
    for i, (pid, _, _) in enumerate(rows, 1):
        try:
            bars, src = candles(pid, 86400, start, end, a)
            daily[pid] = bars
            sources[src] = sources.get(src, 0) + 1
        except Exception:  # noqa: BLE001
            failed += 1
        if i % 50 == 0:
            progress(a, "  %d of %d" % (i, len(rows)))
        _sleep(PAUSE)
    hits, counts = scan_daily(daily, now)
    vol = {r[0]: r[2] for r in rows}
    for h in hits:
        h["usd_volume_24h"] = round(vol.get(h["product"], 0))
    hits.sort(key=lambda h: -h["usd_volume_24h"])
    last_day = max((h["close_date"] for h in hits), default=None)
    doc = {"mode": "daily", "as_of": now.strftime("%Y-%m-%d %H:%M UTC"), "universe": len(pids),
           "liquid": len(rows), "scanned": counts["scanned"], "failed": failed,
           "sources": sources, "min_usd_volume": a.min_usd_volume, "hits": hits}
    if a.json:
        print(json.dumps(doc, indent=2))
    else:
        print("Crypto daily scan, %s, UTC daily closes through %s (Coinbase candles)."
              % (doc["as_of"], last_day or "nothing"))
        part = "" if not failed else " (%d failed)" % failed
        print("%d pairs in the list; %d had %s+ of 24-hour volume; fetched %d%s; %d had under %d days; %d scanned."
              % (len(pids), len(rows), big(a.min_usd_volume), counts["fetched"], part,
                 counts["short"], MIN_DAILY_BARS, counts["scanned"]))
        if not hits:
            print("No setups.")
        else:
            by = {}
            for h in hits:
                for s in h["setups"]:
                    by[s] = by.get(s, 0) + 1
            print("%d charts matched a setup: %s." % (len(hits), ", ".join(
                "%d %s" % (by[k], SETUP_NAMES[k]) for k in SETUP_NAMES if k in by)))
            print("Most traded first (24-hour USD volume):")
            for h in hits[:a.show]:
                print("  %-12s %12s  vol %8s  RSI %5s  %s" % (
                    h["product"], money(h["price"]), big(h["usd_volume_24h"]),
                    "-" if h["rsi"] is None else "%.1f" % h["rsi"],
                    ", ".join(SETUP_NAMES[s] for s in h["setups"])))
            if len(hits) > a.show:
                print("  ... and %d more in the watchlist (--show N for more)." % (len(hits) - a.show))
    if not a.no_write and hits:
        write_json(os.path.join(a.out, "watchlist.json"), doc)
        if not a.json:
            print("Wrote %s (mode daily, %d hits)." % (os.path.join(a.out, "watchlist.json"), len(hits)))
    if not a.json:
        print("A scan is a list of charts that match a rule, not a list of coins to buy.")
    return 0 if hits else 1


def cmd_orb(a):
    now = parse_now(a.now)
    win = orb_window(now, parse_hhmm(a.session, "--session"), a.or_minutes)
    if isinstance(win, str):
        print("No scan: %s." % win)
        return 1
    start, rng_end, cutoff = win
    pids = pick_products(a)
    try:
        stats = cb_stats()
    except Exception as e:  # noqa: BLE001
        print("scan.py: could not read Coinbase 24-hour stats: %s" % e)
        return 1
    rows, illiquid = liquid(pids, stats, a.min_usd_volume, a)
    progress(a, "Fetching 5-minute candles since %s UTC for %d pairs..." % (hm(start), len(rows)))
    hits, failed, usable, thin = [], 0, 0, 0
    for i, (pid, _, vol) in enumerate(rows, 1):
        try:
            bars, _src = candles(pid, 300, start, cutoff, a)
        except Exception:  # noqa: BLE001
            failed += 1
            continue
        r = orb_hit(bars, start, rng_end, cutoff)
        if "reason" in r:
            thin += 1
        else:
            usable += 1
            if r["hit"]:
                r.update(product=pid, usd_volume_24h=round(vol))
                r.pop("hit")
                hits.append(r)
        if i % 50 == 0:
            progress(a, "  %d of %d" % (i, len(rows)))
        _sleep(PAUSE)
    hits.sort(key=lambda h: (h["bar_close_utc"], -h["usd_volume_24h"]))
    doc = {"mode": "orb", "as_of": utc(cutoff).strftime("%Y-%m-%d %H:%M UTC"),
           "session_start_utc": hm(start), "or_minutes": a.or_minutes,
           "universe": len(pids), "liquid": len(rows), "usable": usable, "thin": thin,
           "failed": failed, "hits": hits}
    if a.json:
        print(json.dumps(doc, indent=2))
    else:
        print("Opening range: %d minutes from %s UTC (%s). Data through %s."
              % (a.or_minutes, hm(start), utc(start).date().isoformat(), doc["as_of"]))
        print("%d pairs with %s+ of 24-hour volume; %d usable charts, %d too thin (missing bars), %d failed."
              % (len(rows), big(a.min_usd_volume), usable, thin, failed))
        print("%d of %d usable charts closed a 5-minute bar above their opening-range high:" % (len(hits), usable))
        for h in hits[:a.show]:
            print("  %s UTC  %-12s %12s  range %s to %s  +%.2f%% over" % (
                h["bar_close_utc"], h["product"], money(h["close"]), money(h["range_low"]),
                money(h["range_high"]), h["over_pct"]))
        if len(hits) > a.show:
            print("  ... and %d more (--show N)." % (len(hits) - a.show))
        print("A later hit is closer to the price now; an early one may have moved on. Re-run before acting.")
    if not a.no_write and hits:
        write_json(os.path.join(a.out, "watchlist.json"), doc)
        if not a.json:
            print("Wrote %s (mode orb, %d hits)." % (os.path.join(a.out, "watchlist.json"), len(hits)))
    return 0 if hits else 1


def main(argv=None):
    p = argparse.ArgumentParser(description="Crypto chart scanner (Coinbase public data).")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("universe", "daily", "orb"):
        s = sub.add_parser(name)
        s.add_argument("--out", default=OUT_DIR, help="output folder (default crypto/)")
        if name == "universe":
            continue
        s.add_argument("--products", help="comma list, e.g. BTC-USD,ETH-USD (default: crypto/universe.txt)")
        s.add_argument("--min-usd-volume", type=float, default=1e6,
                       help="24-hour USD volume floor (default 1,000,000)")
        s.add_argument("--limit", type=int, default=0, help="scan only the N most traded")
        s.add_argument("--now", help="pin the clock, 'YYYY-MM-DD HH:MM' UTC")
        s.add_argument("--show", type=int, default=12)
        s.add_argument("--json", action="store_true")
        s.add_argument("--no-write", action="store_true")
        if name == "orb":
            s.add_argument("--session", default="00:00", help="range start, HH:MM UTC (default 00:00)")
            s.add_argument("--or-minutes", type=int, default=60, choices=(15, 30, 60, 120, 240))
    a = p.parse_args(argv)
    return {"universe": cmd_universe, "daily": cmd_daily, "orb": cmd_orb}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
