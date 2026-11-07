#!/usr/bin/env python3
"""Crypto Time Machine for crypto-timemachine. Standard library only.

Replays a planned crypto trade before you risk a dollar: 10,000 simulated
runs of the next --hours from your entry, built from the coin's own 5-minute
candles, plus the same entry, stop and target on every past day at the same
time of day.

    python3 timemachine.py run                           # the plan in crypto/plan.json (/crypto-exit)
    python3 timemachine.py run --product BTC-USD --stop-pct 1.5 --target-r 2
    python3 timemachine.py run --product SOL-USD --entry 90.02 --stop 88.50 --target 93.06
    python3 timemachine.py run --product ETH-USD --stop-pct 2 --hours 8 --fee-pct 1.2 --write
    python3 timemachine.py run --product BTC-USD --stop-pct 1 --at "2026-11-06 14:00" --json

How it works (the same method as trader-timemachine, adapted to 24/7 trading):
  1. Fetch --days (60) of 5-minute candles before the entry time (Coinbase,
     300 a request; Yahoo as the fallback). Coinbase leaves out a 5-minute bar
     when nothing traded, so a missing bar is filled flat at the last close
     (no trade = no price change).
  2. The pool: for every 5-minute slot of the UTC day (288 of them), each past
     day's bar as ratios to the previous bar's close: (open, high, low, close).
  3. One replay starts at the entry price and walks --hours ahead. For each
     bar it takes the slot of that time of day, plus or minus --window slots
     (2, so +-10 minutes), picks one past bar from it at random and scales it
     to the current price. The stop is checked before the target in every
     bar, so a bar that touches both counts as the stop (the conservative call).
  4. Outcomes: target first, stop first, or neither (still open after --hours).
     R = the target's R at the target, -1 at the stop, otherwise
     (price at the end - entry) / risk. --fee-pct (your round-trip fee, in %
     of the entry) is taken off every outcome, in R. A gap through the stop
     still counts -1R here; a real fill can be worse.
  5. History: the same entry time of day on every past day in the data, with
     the stop and the target at the same % distance, walked on the real bars.

The verdict compares target / (target + stop) among the replays that hit one
side with the share that breaks even after fees: (1 + fee) / (1 + R), in R.
Less than 5 points apart: "close to break-even" ("a coin flip" at 1R with no
fee); 5 to 15: "leans toward"; 15 or more: "strongly toward".

Long only (spot crypto). Same inputs and --seed give the same numbers on any
machine. A simulation from the coin's own last 60 days is not a prediction:
a listing, a hack, an exchange outage or a headline can do what those days
never did.
"""

import argparse
import datetime
import json
import os
import random
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UTC = datetime.timezone.utc
CB = "https://api.exchange.coinbase.com"
YAHOO_HOSTS = ("https://query2.finance.yahoo.com", "https://query1.finance.yahoo.com")
UA = "Mozilla/5.0 (compatible; testbase-crypto-skills/0.1)"
BAR = 300
SLOTS = 86400 // BAR  # 288
OUT_DIR = "crypto"
PAUSE = 0.12
MIN_DAYS = 20


# ---------------------------------------------------------------- clock

def parse_at(text):
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.datetime.strptime(text, fmt).replace(tzinfo=UTC)
        except ValueError:
            pass
    raise SystemExit("timemachine.py: --at wants 'YYYY-MM-DD HH:MM' in UTC, got %r" % text)


def utc(t):
    return datetime.datetime.fromtimestamp(t, UTC)


def stamp(t):
    return utc(t).strftime("%Y-%m-%d %H:%M UTC")


# ---------------------------------------------------------------- fetch

def _sleep(s):
    time.sleep(s)


def get_json(url, timeout=20):
    for attempt in range(3):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if attempt < 2 and (e.code == 429 or e.code >= 500):
                _sleep(5 if e.code == 429 else 2)
                continue
            raise
    raise RuntimeError("unreachable")


def cb_candles(pid, start, end, progress=None):
    out = {}
    step = 300 * BAR
    a, n = start, 0
    total = max(1, -(-(end - start) // step))
    while a < end:
        b = min(end, a + step)
        q = urllib.parse.urlencode({"granularity": BAR,
                                    "start": utc(a).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                    "end": utc(b).strftime("%Y-%m-%dT%H:%M:%SZ")})
        rows = get_json("%s/products/%s/candles?%s" % (CB, urllib.parse.quote(pid), q))
        if isinstance(rows, dict):
            raise RuntimeError(rows.get("message") or "Coinbase error")
        for t, lo, hi, op, cl, v in rows:
            out[int(t)] = (int(t), float(op), float(hi), float(lo), float(cl), float(v))
        a, n = b, n + 1
        if progress and n % 10 == 0:
            progress("  %d of %d requests" % (n, total))
        if a < end:
            _sleep(PAUSE)
    return [out[k] for k in sorted(out) if start <= k < end]


def yahoo_candles(pid, start, end):
    q = urllib.parse.urlencode({"period1": start, "period2": end, "interval": "5m"})
    last = None
    for host in YAHOO_HOSTS:
        try:
            doc = get_json("%s/v8/finance/chart/%s?%s" % (host, urllib.parse.quote(pid), q))
            break
        except Exception as e:  # noqa: BLE001
            last = e
    else:
        raise RuntimeError("Yahoo: %s" % last)
    res = ((doc.get("chart") or {}).get("result") or [None])[0]
    if not res or not res.get("timestamp"):
        raise RuntimeError("Yahoo: no data for %s" % pid)
    qd = res["indicators"]["quote"][0]
    out = {}
    for i, t in enumerate(res["timestamp"]):
        o, h, l, c, v = (qd[k][i] for k in ("open", "high", "low", "close", "volume"))
        if None in (o, h, l, c) or int(t) % BAR:
            continue
        if start <= t < end:
            out[int(t)] = (int(t), float(o), float(h), float(l), float(c), float(v or 0))
    return [out[k] for k in sorted(out)]


def fetch(pid, start, end, progress=None):
    try:
        return cb_candles(pid, start, end, progress), "coinbase"
    except Exception as e:  # noqa: BLE001
        if progress:
            progress("Coinbase failed (%s), trying Yahoo" % e)
    return yahoo_candles(pid, start, end), "yahoo"


def read_offline(path):
    """A JSON list of [t, open, high, low, close, volume] (oldest first or not)."""
    with open(path) as f:
        rows = json.load(f)
    return sorted((int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]))
                  for r in rows)


# ---------------------------------------------------------------- core (pure)

def fill_gaps(bars):
    """Insert flat bars where nothing traded: open = high = low = close = last close."""
    if not bars:
        return []
    out = [bars[0]]
    for b in bars[1:]:
        t = out[-1][0] + BAR
        c = out[-1][4]
        while t < b[0]:
            out.append((t, c, c, c, c, 0.0))
            t += BAR
        out.append(b)
    return out


def slot_of(t):
    return (t % 86400) // BAR


def build_pool(bars):
    """slot -> [(o, h, l, c) / previous close]. bars must be gap-filled."""
    pool = [[] for _ in range(SLOTS)]
    for prev, b in zip(bars, bars[1:]):
        pc = prev[4]
        if pc <= 0:
            continue
        pool[slot_of(b[0])].append((b[1] / pc, b[2] / pc, b[3] / pc, b[4] / pc))
    return pool


def pct(a, q):
    s = sorted(a)
    return s[min(len(s) - 1, int(q * len(s)))]


def simulate(pool, entry, stop, target, k, steps, replays=10000, seed=19, window=2):
    """k = slot of the entry bar (entry at its close). Long only."""
    rnd = random.Random(seed)
    counts = {"target": 0, "stop": 0, "neither": 0}
    finals, bars_to = [], {"target": [], "stop": []}
    for _ in range(replays):
        p = entry
        out = "neither"
        for i in range(steps):
            j = (k + 1 + i + rnd.randint(-window, window)) % SLOTS
            src = pool[j]
            if not src:
                continue
            ro, rh, rl, rc = rnd.choice(src)
            if p * rl <= stop:
                out = "stop"
                bars_to["stop"].append(i + 1)
                break
            if p * rh >= target:
                out = "target"
                bars_to["target"].append(i + 1)
                break
            p *= rc
        counts[out] += 1
        if out == "neither":
            finals.append(p)
    return counts, finals, bars_to


def walk(bars, i0, stop, target, steps):
    """Real bars after index i0 -> (outcome, price at the end)."""
    for b in bars[i0 + 1:i0 + 1 + steps]:
        if b[3] <= stop:
            return "stop", stop
        if b[2] >= target:
            return "target", target
    return "neither", bars[min(len(bars) - 1, i0 + steps)][4]


def history(bars, k, stop_frac, target_frac, steps, at_t):
    """Same slot every past day, same % stop and target, real bars, only runs that end before at_t."""
    rows = []
    for i, b in enumerate(bars):
        if slot_of(b[0]) != k or b[0] + BAR + steps * BAR > at_t or i + steps >= len(bars):
            continue
        e = b[4]
        out, end = walk(bars, i, e * stop_frac, e * target_frac, steps)
        rows.append({"day": utc(b[0]).date().isoformat(), "entry": e, "outcome": out, "end": end})
    return rows


def lean(share, be):
    gap = (share - be) * 100
    if abs(gap) < 5:
        return gap, "close"
    side = "target" if gap > 0 else "stop"
    return gap, ("strongly toward the " if abs(gap) >= 15 else "leans toward the ") + side


def time_machine(bars, entry, stop, target, entry_t, hours, replays=10000, seed=19, window=2,
                 fee_pct=0.0):
    if stop >= entry:
        raise ValueError("the stop must be below the entry (long only)")
    if target <= entry:
        raise ValueError("the target must be above the entry (long only)")
    bars = fill_gaps([b for b in bars if b[0] + BAR <= entry_t])
    if not bars:
        raise ValueError("no candles before the entry time")
    days = len({utc(b[0]).date() for b in bars})
    if days < MIN_DAYS:
        raise ValueError("only %d days of 5-minute candles; need %d" % (days, MIN_DAYS))
    steps = int(hours * 3600) // BAR
    k = slot_of(entry_t - BAR)  # the entry bar is the one that closed at entry_t
    pool = build_pool(bars)
    risk = entry - stop
    R = (target - entry) / risk
    fee_r = fee_pct / 100.0 * entry / risk
    counts, finals, bars_to = simulate(pool, entry, stop, target, k, steps, replays, seed, window)
    rs = ([R - fee_r] * counts["target"] + [-1 - fee_r] * counts["stop"] +
          [(p - entry) / risk - fee_r for p in finals])
    hit = counts["target"] + counts["stop"]
    share = counts["target"] / hit if hit else None
    be = (1 + fee_r) / (1 + R)
    gap, how = lean(share, be) if share is not None else (None, "no replay hit either side")
    hist = history(bars, k, stop / entry, target / entry, steps, entry_t)
    hc = {"target": 0, "stop": 0, "neither": 0}
    for h in hist:
        hc[h["outcome"]] += 1
    every = finals + [target] * counts["target"] + [stop] * counts["stop"]
    return {
        "entry": entry, "stop": stop, "target": target, "entry_time": stamp(entry_t),
        "hours": hours, "risk_pct": risk / entry * 100, "R": R, "fee_pct": fee_pct, "fee_R": fee_r,
        "data_from": stamp(bars[0][0]), "data_to": stamp(bars[-1][0] + BAR), "days": days,
        "pool_bars": sum(len(p) for p in pool), "flat_filled": sum(1 for b in bars if b[5] == 0.0),
        "replays": replays, "seed": seed, "window": window,
        "counts": counts, "pct": {k2: v * 100.0 / replays for k2, v in counts.items()},
        "median_hours_to": {k2: statistics.median(v) * BAR / 3600 for k2, v in bars_to.items() if v},
        "end_price": {"p5": pct(every, 0.05), "median": pct(every, 0.5), "p95": pct(every, 0.95)},
        "avg_R": sum(rs) / len(rs), "target_share": share, "breakeven_share": be,
        "gap_points": gap, "lean": how, "history": hc, "history_runs": hist,
    }


def verdict(doc):
    if doc["target_share"] is None:
        return "No replay touched the stop or the target in %g hours: both are far away." % doc["hours"]
    if doc["lean"] == "close":
        coin = doc["R"] == 1 and doc["fee_R"] == 0
        return "Close to a coin flip." if coin else "Close to break-even."
    return doc["lean"][0].upper() + doc["lean"][1:] + "."


# ---------------------------------------------------------------- output

def money(x):
    if x >= 1000:
        return "$%s" % format(round(x, 2), ",.2f")
    if x >= 1:
        return "$%.2f" % x
    return "$%.6f" % x


def report(doc, pid, source):
    c, p = doc["counts"], doc["pct"]
    lines = [
        "Time Machine: %s, long, entry %s at %s." % (pid, money(doc["entry"]), doc["entry_time"]),
        "Stop %s (%.2f%% below, 1R), target %s (%.2fR). Window: the next %g hours." % (
            money(doc["stop"]), doc["risk_pct"], money(doc["target"]), doc["R"], doc["hours"]),
        "Data: %d days of 5-minute candles (%s, %s to %s), %s bars in the pool, %d flat-filled."
        % (doc["days"], source, doc["data_from"], doc["data_to"], format(doc["pool_bars"], ","),
           doc["flat_filled"]),
        "",
        "%s replays (seed %d):" % (format(doc["replays"], ","), doc["seed"]),
        "  target first   %5.1f %%  (%s)" % (p["target"], format(c["target"], ",")),
        "  stop first     %5.1f %%  (%s)" % (p["stop"], format(c["stop"], ",")),
        "  neither        %5.1f %%  (still open after %g hours)" % (p["neither"], doc["hours"]),
    ]
    mh = doc["median_hours_to"]
    if mh:
        lines.append("  median time to the target %s, to the stop %s" % (
            "%.1f h" % mh["target"] if "target" in mh else "-",
            "%.1f h" % mh["stop"] if "stop" in mh else "-"))
    e = doc["end_price"]
    lines.append("  price at the end: median %s, 5th to 95th percentile %s to %s" % (
        money(e["median"]), money(e["p5"]), money(e["p95"])))
    lines.append("  average %+.2fR per trade%s" % (
        doc["avg_R"], " after a %.2f%% round-trip fee (%.2fR)" % (doc["fee_pct"], doc["fee_R"])
        if doc["fee_pct"] else " (no fees counted: add --fee-pct)"))
    h = doc["history"]
    n = sum(h.values())
    lines += ["", "History: the same entry time on %d past days, same %% stop and target: "
              "%d hit the target, %d the stop, %d neither." % (n, h["target"], h["stop"], h["neither"])]
    lines.append("")
    if doc["target_share"] is not None:
        lines.append("Of the replays that hit a side, %.1f %% hit the target; break-even at %.2fR%s is %.1f %%."
                     % (doc["target_share"] * 100, doc["R"], " after fees" if doc["fee_pct"] else "",
                        doc["breakeven_share"] * 100))
    lines.append("Verdict: " + verdict(doc))
    if p["neither"] > 40:
        lines.append("Note: %.0f %% of the replays hit neither side, so the price after %g hours decides "
                     "most outcomes." % (p["neither"], doc["hours"]))
    lines.append("A simulation from the coin's own last %d days, not a prediction. Crypto can gap through "
                 "a stop on news or an exchange outage." % doc["days"])
    return "\n".join(lines)


# ---------------------------------------------------------------- command

def resolve(a, bars, entry_t):
    entry = a.entry if a.entry is not None else bars[-1][4]
    if a.stop is not None:
        stop = a.stop
    elif a.stop_pct is not None:
        stop = entry * (1 - a.stop_pct / 100.0)
    else:
        raise SystemExit("timemachine.py: give --stop PRICE or --stop-pct N")
    if a.target is not None:
        target = a.target
    else:
        target = entry + (entry - stop) * a.target_r
    return entry, stop, target


def from_plan(a):
    """No --product: take the pair, entry, stop, target, time and hours from crypto/plan.json."""
    try:
        with open(os.path.join(a.out, "plan.json")) as f:
            plan = json.load(f)
    except FileNotFoundError:
        raise SystemExit("timemachine.py: give --product, or write a plan first with /crypto-exit")
    a.product = plan["product"]
    for k in ("entry", "stop", "target"):
        if getattr(a, k) is None:
            setattr(a, k, plan[k])
    if not a.at and plan.get("entry_time"):
        a.at = plan["entry_time"].replace(" UTC", "")
    if a.hours_given is None:
        a.hours = plan.get("hold_hours", a.hours)
    if not a.fee_pct and plan.get("fee_pct"):
        a.fee_pct = plan["fee_pct"]


def cmd_run(a):
    if not a.product:
        from_plan(a)
    pid = a.product.upper()
    now = int(time.time())
    at = parse_at(a.at)
    entry_t = int(at.timestamp()) if at else now - now % BAR
    entry_t -= entry_t % BAR
    log = (lambda m: print(m, file=sys.stderr)) if not a.json else None
    start = entry_t - a.days * 86400
    if a.offline:
        bars, source = read_offline(a.offline), "offline"
    else:
        if log:
            log("Fetching %d days of 5-minute candles for %s..." % (a.days, pid))
        try:
            bars, source = fetch(pid, start, entry_t, log)
        except Exception as e:  # noqa: BLE001
            print("timemachine.py: could not fetch candles for %s: %s" % (pid, e))
            return 1
    bars = [b for b in bars if b[0] + BAR <= entry_t]
    if not bars:
        print("timemachine.py: no candles for %s before %s." % (pid, stamp(entry_t)))
        return 1
    if not at:
        entry_t = bars[-1][0] + BAR  # the last completed bar
    entry, stop, target = resolve(a, bars, entry_t)
    try:
        doc = time_machine(bars, entry, stop, target, entry_t, a.hours, a.replays, a.seed,
                           a.window, a.fee_pct)
    except ValueError as e:
        print("timemachine.py: %s." % e)
        return 1
    doc["product"], doc["source"] = pid, source
    if a.json:
        out = dict(doc)
        out.pop("history_runs")
        print(json.dumps(out, indent=2))
    else:
        print(report(doc, pid, source))
    if a.write:
        path = os.path.join(a.out, "timemachine.json")
        os.makedirs(a.out, exist_ok=True)
        with open(path, "w") as f:
            json.dump(doc, f, indent=2)
        if not a.json:
            print("Wrote %s." % path)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Crypto Time Machine (Coinbase public data).")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("run")
    s.add_argument("--product", help="Coinbase pair, e.g. BTC-USD (default: crypto/plan.json)")
    s.add_argument("--entry", type=float, help="entry price (default: the last 5-minute close)")
    s.add_argument("--stop", type=float, help="stop price")
    s.add_argument("--stop-pct", type=float, help="stop N %% below the entry")
    s.add_argument("--target", type=float, help="target price")
    s.add_argument("--target-r", type=float, default=2.0, help="target in R when no --target (default 2)")
    s.add_argument("--hours", type=float, dest="hours_given", help="how long a replay runs (default 24)")
    s.add_argument("--at", help="entry time 'YYYY-MM-DD HH:MM' UTC (default: the last completed bar)")
    s.add_argument("--days", type=int, default=60)
    s.add_argument("--replays", type=int, default=10000)
    s.add_argument("--seed", type=int, default=19)
    s.add_argument("--window", type=int, default=2)
    s.add_argument("--fee-pct", type=float, default=0.0, help="round-trip fee in %% of the entry")
    s.add_argument("--offline", help="read candles from a JSON file instead")
    s.add_argument("--out", default=OUT_DIR)
    s.add_argument("--write", action="store_true", help="save crypto/timemachine.json")
    s.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    a.hours = a.hours_given if a.hours_given is not None else 24.0
    return cmd_run(a)


if __name__ == "__main__":
    sys.exit(main())
