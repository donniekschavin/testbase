#!/usr/bin/env python3
"""Entry Timer for crypto-entry: watches a setup bar by bar and says the moment
to get in. Standard library only. Long side only. It never places an order.

    python3 entry.py check BTC-USD                         # opening-range breakout, 5-minute bars
    python3 entry.py check SOL-USD --setup level --level 92.50   # first close above a price
    python3 entry.py check ETH-USD --session 13:30 --or-minutes 30 --write
    python3 entry.py check BTC-USD --interval 1m --min-volume-x 1.5
    python3 entry.py watch BTC-USD --every 30 --hours 4    # one line per closed bar
    python3 entry.py watchlist                              # every hit in crypto/watchlist.json

Setups:
  orb    opening-range breakout. Crypto has no opening bell, so the session
         starts at --session (UTC, default 00:00) and the range is the high
         and low of the first --or-minutes (default 60). It triggers on the
         first COMPLETED bar after the range that CLOSES above the range high.
         A wick above the high is not a trigger.
  level  the first completed bar today that closes above --level.
  --min-volume-x X  the trigger bar also needs X times the average volume of
         the range bars.

A trigger's time is the trigger bar's CLOSE time and its price is that close.
A bar counts only once it has closed. Statuses: triggered; waiting (range
still forming, or no close above yet); expired (past no_entries_after in
crypto/config.json, UTC, if you set one); no-data.

Data: Coinbase 5-minute or 1-minute candles (Yahoo as the fallback).
--offline FILE reads saved candles ([t, o, h, l, c, v] rows); --now pins the
clock (UTC). Exit codes: check 0 = triggered, 1 otherwise; watch 0 on a
trigger; watchlist 0 when at least one pair triggered.
"""

import argparse
import datetime
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "crypto-common"))
import cryptolib as L  # noqa: E402

GRAN = {"5m": 300, "1m": 60}


def session_window(now, session_min):
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = day + datetime.timedelta(minutes=session_min)
    if start > now:
        start -= datetime.timedelta(days=1)
    return L.ts(start)


def evaluate(bars, now_t, start, gran, setup="orb", or_minutes=60, level=None,
             min_volume_x=None, no_after=None):
    """Pure. bars: candles of this session (any order). -> result dict."""
    bars = sorted(b for b in L.complete(bars, gran, now_t) if b[0] >= start and b[0] < start + 86400)
    res = {"setup": setup, "session_start": L.stamp(start), "as_of": L.stamp(now_t - now_t % gran),
           "interval": "%dm" % (gran // 60)}
    rng_end = start + or_minutes * 60
    if setup == "orb":
        need = or_minutes * 60 // gran
        rng = [b for b in bars if b[0] < rng_end]
        if now_t < rng_end:
            res.update(status="waiting", reason="the opening range is still forming (until %s)"
                       % L.utc(rng_end).strftime("%H:%M UTC"))
            return res
        if len(rng) < need:
            res.update(status="no-data", reason="missing range bars (%d of %d): thin trading or no data"
                       % (len(rng), need))
            return res
        hi, lo = max(b[2] for b in rng), min(b[3] for b in rng)
        res.update(or_high=hi, or_low=lo)
        trigger_at, after = hi, [b for b in bars if b[0] >= rng_end]
        avg_vol = sum(b[5] for b in rng) / len(rng)
    else:
        if level is None:
            raise SystemExit("entry.py: --setup level needs --level PRICE")
        trigger_at, after, avg_vol = level, bars, None
        if bars:
            avg_vol = sum(b[5] for b in bars) / len(bars)
        res["level"] = level
    if setup == "level" and not bars:
        res.update(status="no-data", reason="no candles this session yet")
        return res
    cut = None
    if no_after is not None:
        cut = start - start % 86400 + no_after * 60
        if cut <= start:
            cut += 86400
    for b in after:
        if cut is not None and b[0] + gran > cut:
            break
        if b[4] > trigger_at:
            if min_volume_x and avg_vol and b[5] < min_volume_x * avg_vol:
                continue
            res.update(status="triggered", price=b[4], trigger_time=L.stamp(b[0] + gran),
                       over_pct=(b[4] / trigger_at - 1) * 100, bar_volume=b[5])
            return res
    last = after[-1][4] if after else (bars[-1][4] if bars else None)
    if cut is not None:
        if now_t >= cut:
            res.update(status="expired", reason="no trigger before no_entries_after (%s UTC)"
                       % L.utc(cut).strftime("%H:%M"), last=last)
            return res
    res.update(status="waiting", last=last,
               reason="no close above %s yet%s" % (L.money(trigger_at), "" if last is None else
                                                    ", last close %s (%.2f%% away)"
                                                    % (L.money(last), (trigger_at / last - 1) * 100)))
    return res


def fetch_session(a, pid, start, now_t, gran):
    if a.offline:
        return L.read_bars(a.offline)
    bars, _ = L.candles(pid, gran, start, now_t)
    return bars


def line(pid, r):
    if r["status"] == "triggered":
        return "%s TRIGGERED at %s: close %s, %+.2f%% over %s." % (
            pid, r["trigger_time"], L.money(r["price"]), r["over_pct"],
            "the range high " + L.money(r["or_high"]) if r["setup"] == "orb" else L.money(r["level"]))
    rng = " Range %s to %s." % (L.money(r["or_low"]), L.money(r["or_high"])) if "or_high" in r else ""
    return "%s %s: %s.%s" % (pid, r["status"], r.get("reason", ""), rng)


def run_check(a, pid, now):
    gran = GRAN[a.interval]
    cfg, _ = L.load_config(a.out)
    no_after = L.hhmm(cfg["no_entries_after"], "no_entries_after") if cfg.get("no_entries_after") else None
    start = session_window(now, L.hhmm(a.session, "--session"))
    now_t = L.ts(now)
    try:
        bars = fetch_session(a, pid, start, now_t, gran)
    except Exception as e:  # noqa: BLE001
        return {"status": "no-data", "reason": "could not fetch candles: %s" % e, "setup": a.setup}
    r = evaluate(bars, now_t, start, gran, a.setup, a.or_minutes, a.level, a.min_volume_x, no_after)
    r["product"] = pid
    return r


def cmd_check(a):
    pid = L.product_id(a.product)
    r = run_check(a, pid, L.now_utc(a.now))
    print(line(pid, r))
    if a.write and r["status"] == "triggered":
        L.write_json(L.path(a.out, "entry.json"), r)
        print("Wrote %s. Next: /crypto-exit to set the stop and the target." % L.path(a.out, "entry.json"))
    elif r["status"] == "triggered":
        print("Next: --write, then /crypto-exit. A trigger is a rule firing, not a reason to buy.")
    return 0 if r["status"] == "triggered" else 1


def cmd_watch(a):
    pid = L.product_id(a.product)
    gran = GRAN[a.interval]
    simulated = bool(a.now)
    now = L.now_utc(a.now)
    end = now + datetime.timedelta(hours=a.hours)
    seen = None
    while now <= end:
        r = run_check(a, pid, now)
        if r.get("as_of") != seen:
            seen = r.get("as_of")
            print("%s  %s" % (now.strftime("%H:%M:%S UTC"), line(pid, r)), flush=True)
        if r["status"] == "triggered":
            L.write_json(L.path(a.out, "entry.json"), r)
            print("Wrote %s. Next: /crypto-exit." % L.path(a.out, "entry.json"))
            return 0
        if r["status"] == "expired":
            return 1
        if simulated:
            now += datetime.timedelta(seconds=gran)
        else:
            nxt = L.ts(now) - L.ts(now) % gran + gran + 5
            wait = max(a.every, nxt - time.time()) if seen == r.get("as_of") else a.every
            time.sleep(min(wait, max(1, (end - now).total_seconds())))
            now = L.now_utc()
    print("Stopped watching after %g hours without a trigger." % a.hours)
    return 1


def cmd_watchlist(a):
    wl = L.read_json(L.path(a.out, "watchlist.json"))
    if not wl or not wl.get("hits"):
        print("entry.py: no hits in %s. Run /crypto-scanner first." % L.path(a.out, "watchlist.json"))
        return 1
    now = L.now_utc(a.now)
    hit = 0
    for h in wl["hits"][:a.max]:
        r = run_check(a, h["product"], now)
        print(line(h["product"], r))
        hit += r["status"] == "triggered"
        L._sleep(L.PAUSE)
    print("%d of %d triggered. Pick one and run check PRODUCT --write; never pick for the user." %
          (hit, min(a.max, len(wl["hits"]))))
    return 0 if hit else 1


def main(argv=None):
    p = argparse.ArgumentParser(description="Crypto entry timer (Coinbase public data).")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("check", "watch", "watchlist"):
        s = sub.add_parser(name)
        if name != "watchlist":
            s.add_argument("product", help="e.g. BTC-USD")
        s.add_argument("--setup", choices=("orb", "level"), default="orb")
        s.add_argument("--level", type=float)
        s.add_argument("--session", default="00:00", help="session start HH:MM UTC")
        s.add_argument("--or-minutes", type=int, default=60)
        s.add_argument("--interval", choices=("5m", "1m"), default="5m")
        s.add_argument("--min-volume-x", type=float)
        s.add_argument("--now", help="pin the clock, 'YYYY-MM-DD HH:MM' UTC")
        s.add_argument("--offline", help="saved candles JSON")
        s.add_argument("--out", default=L.OUT_DIR)
        s.add_argument("--write", action="store_true")
        if name == "watch":
            s.add_argument("--every", type=float, default=30)
            s.add_argument("--hours", type=float, default=4)
        if name == "watchlist":
            s.add_argument("--max", type=int, default=20)
    a = p.parse_args(argv)
    return {"check": cmd_check, "watch": cmd_watch, "watchlist": cmd_watchlist}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
