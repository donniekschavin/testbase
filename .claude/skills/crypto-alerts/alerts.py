#!/usr/bin/env python3
"""Price alerts for crypto-alerts. Standard library only.

    python3 alerts.py quote BTC-USD ETH-USD --write     # last trades -> crypto/prices.json
    python3 alerts.py quote --holdings --write          # every pair in your portfolio and plan
    python3 alerts.py add --from-plan                   # stop, target and hold-until from crypto/plan.json
    python3 alerts.py add --product BTC-USD --below 74000
    python3 alerts.py add --product BTC-USD --above 80000 --rearm
    python3 alerts.py add --product SOL-USD --pct 5     # a 5 % move from 24 hours ago, either way
    python3 alerts.py add --at "2026-11-08 01:05" --label "out by"
    python3 alerts.py check                             # rings what hit, once; exit 1 if nothing rang
    python3 alerts.py list
    python3 alerts.py reset btc-usd-below-74000

Rule types:
  above / target  the price is at or above "price"
  below / stop    the price is at or below "price"
  pct_move        the price moved "pct" percent or more from 24 hours ago
                  ("direction": "up", "down" or "both"); rings at most once a UTC day
  time            the UTC clock passed "at" (YYYY-MM-DD HH:MM); rings once

An above / below alert rings ONCE and then stays quiet until you reset it,
unless it has "rearm": true (it re-arms when the price crosses back).

Crypto never closes, so there is no opening bell: the "time" alert is how a
plan's hold_until reaches you.

Quotes (free, delayed, for alerts only, never for timing an order):
  Coinbase  https://api.exchange.coinbase.com/products/<ID>/ticker  (last trade)
            https://api.exchange.coinbase.com/products/<ID>/stats   (24-hour open, for pct_move)
  Yahoo     the chart meta for the same name, when Coinbase fails
--offline FILE reads {"BTC-USD": {"price": 75900, "open24h": 76000, "time": 1794043800}, ...}.
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "crypto-common"))
import cryptolib as L  # noqa: E402


def quote(pid):
    """-> {"price", "time", "open24h", "source"}."""
    try:
        price, t = L.cb_ticker(pid)
        row = {"price": price, "time": t, "source": "coinbase"}
        try:
            st = L.get_json("%s/products/%s/stats" % (L.CB, pid))
            row["open24h"] = float(st["open"])
        except Exception:  # noqa: BLE001
            pass
        return row
    except Exception:  # noqa: BLE001
        pass
    doc = L.get_json("%s/v8/finance/chart/%s?range=1d&interval=5m" % (L.YAHOO_HOSTS[0], pid))
    meta = doc["chart"]["result"][0]["meta"]
    return {"price": float(meta["regularMarketPrice"]), "time": int(meta.get("regularMarketTime") or 0),
            "open24h": float(meta.get("chartPreviousClose") or meta.get("previousClose") or 0) or None,
            "source": "yahoo"}


def rule_id(r):
    if r["type"] == "time":
        base = "time-" + r["at"].replace(" ", "-").replace(":", "")
    elif r["type"] == "pct_move":
        base = "%s-pct-%g" % (r["product"], r["pct"])
    else:
        base = "%s-%s-%s" % (r["product"], r["type"], ("%g" % r["price"]).replace(".", "_"))
    return re.sub(r"[^a-z0-9_-]+", "-", base.lower())


def evaluate(rules, state, quotes, now_t):
    """Pure. -> (rung list, new state). state = {id: {"rung": bool, "day": "YYYY-MM-DD"}}."""
    day = L.utc(now_t).date().isoformat()
    state = {k: dict(v) for k, v in (state or {}).items()}
    rung = []
    for r in rules:
        rid = r["id"]
        st = state.setdefault(rid, {"rung": False})
        if r["type"] == "time":
            if not st["rung"] and now_t >= L.parse_stamp(r["at"] + " UTC"):
                st["rung"] = True
                rung.append((r, "it is %s UTC%s" % (r["at"], " (" + r["label"] + ")" if r.get("label") else "")))
            continue
        q = quotes.get(r["product"])
        if not q:
            continue
        p = q["price"]
        if r["type"] in ("above", "target", "below", "stop"):
            up = r["type"] in ("above", "target")
            hit = p >= r["price"] if up else p <= r["price"]
            if hit and not st["rung"]:
                st["rung"] = True
                rung.append((r, "%s at %s, %s %s%s" % (r["product"], L.money(p), "at or above" if up else
                                                       "at or below", L.money(r["price"]),
                                                       " (" + r["label"] + ")" if r.get("label") else "")))
            elif not hit and st["rung"] and r.get("rearm"):
                st["rung"] = False
        elif r["type"] == "pct_move":
            ref = r.get("ref") or q.get("open24h")
            if not ref:
                continue
            move = (p / ref - 1) * 100
            d = r.get("direction", "both")
            ok = (d in ("up", "both") and move >= r["pct"]) or (d in ("down", "both") and move <= -r["pct"])
            if ok and st.get("day") != day:
                st["day"] = day
                rung.append((r, "%s moved %+.2f%% in 24 hours (to %s)" % (r["product"], move, L.money(p))))
    return rung, state


def load_rules(out):
    return L.read_json(L.path(out, "alerts.json"), []) or []


def save_rules(out, rules):
    L.write_json(L.path(out, "alerts.json"), rules)


def add_rule(rules, r):
    r["id"] = rule_id(r)
    rules = [x for x in rules if x["id"] != r["id"]]
    rules.append(r)
    return rules, r["id"]


def pairs_for(a):
    if a.products:
        return [L.product_id(p) for p in a.products]
    out = set()
    if a.holdings:
        pf = L.read_json(L.path(a.out, "portfolio.json")) or {}
        out |= set((pf.get("positions") or {}).keys())
        plan = L.read_json(L.path(a.out, "plan.json")) or {}
        if plan.get("product"):
            out.add(plan["product"])
    return sorted(out)


def get_quotes(a, pids):
    if a.offline:
        return L.read_json(a.offline, {})
    out = {}
    for pid in pids:
        try:
            out[pid] = quote(pid)
        except Exception as e:  # noqa: BLE001
            print("  %s: no quote (%s)" % (pid, e), file=sys.stderr)
        L._sleep(L.PAUSE)
    return out


def cmd_quote(a):
    pids = pairs_for(a)
    if not pids:
        print("alerts.py: name the pairs (quote BTC-USD) or use --holdings.")
        return 1
    qs = get_quotes(a, pids)
    for pid in pids:
        q = qs.get(pid)
        if q:
            ch = "" if not q.get("open24h") else ", %+.2f%% in 24 hours" % ((q["price"] / q["open24h"] - 1) * 100)
            print("%-10s %s at %s (%s%s)" % (pid, L.money(q["price"]), L.stamp(q["time"]), q.get("source"), ch))
    if a.write and qs:
        prices = L.read_json(L.path(a.out, "prices.json"), {}) or {}
        prices.update(qs)
        L.write_json(L.path(a.out, "prices.json"), prices)
        print("Wrote %s. Quotes are for alerts and the risk check, not for timing an order." % L.path(a.out, "prices.json"))
    return 0 if qs else 1


def cmd_add(a):
    rules = load_rules(a.out)
    added = []
    if a.from_plan:
        plan = L.read_json(L.path(a.out, "plan.json"))
        if not plan:
            print("alerts.py: no %s. Run /crypto-exit first." % L.path(a.out, "plan.json"))
            return 1
        pid = plan["product"]
        for typ, price, label in (("stop", plan["stop"], "plan stop"), ("target", plan["target"], "plan target")):
            rules, rid = add_rule(rules, {"type": typ, "product": pid, "price": price, "label": label})
            added.append(rid)
        if plan.get("hold_until"):
            rules, rid = add_rule(rules, {"type": "time", "at": plan["hold_until"].replace(" UTC", ""),
                                          "label": "out by: close %s, win or lose" % pid})
            added.append(rid)
    else:
        pid = L.product_id(a.product) if a.product else None
        for typ, val in (("above", a.above), ("below", a.below), ("stop", a.stop), ("target", a.target)):
            if val is not None:
                if not pid:
                    raise SystemExit("alerts.py: --%s needs --product" % typ)
                rules, rid = add_rule(rules, {"type": typ, "product": pid, "price": val, "label": a.label,
                                              "rearm": a.rearm})
                added.append(rid)
        if a.pct is not None:
            if not pid:
                raise SystemExit("alerts.py: --pct needs --product")
            rules, rid = add_rule(rules, {"type": "pct_move", "product": pid, "pct": a.pct,
                                          "direction": a.direction, "label": a.label})
            added.append(rid)
        if a.at:
            L.now_utc(a.at)  # validates
            rules, rid = add_rule(rules, {"type": "time", "at": a.at, "label": a.label})
            added.append(rid)
    if not added:
        print("alerts.py: nothing to add (see --help).")
        return 1
    save_rules(a.out, rules)
    print("Added: %s. %d alerts in %s." % (", ".join(added), len(rules), L.path(a.out, "alerts.json")))
    print("Run alerts.py check on a schedule (every few minutes) to ring them.")
    return 0


def cmd_check(a):
    rules = load_rules(a.out)
    if not rules:
        print("No alerts. Add some: alerts.py add --from-plan.")
        return 1
    now_t = L.ts(L.now_utc(a.now))
    pids = sorted({r["product"] for r in rules if r.get("product")})
    qs = get_quotes(a, pids)
    st_p = L.path(a.out, "state", "alerts.json")
    rung, state = evaluate(rules, L.read_json(st_p, {}), qs, now_t)
    L.write_json(st_p, state)
    if qs and not a.offline:
        prices = L.read_json(L.path(a.out, "prices.json"), {}) or {}
        prices.update(qs)
        L.write_json(L.path(a.out, "prices.json"), prices)
    for r, msg in rung:
        print("RING  " + msg)
        if r["type"] in ("stop", "target") or (r["type"] == "time" and "out by" in (r.get("label") or "")):
            print("      To get out: /crypto-broker flatten (cancel the open stop order first).")
    if not rung:
        print("Nothing rang at %s (%d alerts, %d quotes)." % (L.stamp(now_t), len(rules), len(qs)))
    return 0 if rung else 1


def cmd_list(a):
    rules = load_rules(a.out)
    state = L.read_json(L.path(a.out, "state", "alerts.json"), {}) or {}
    if not rules:
        print("No alerts.")
        return 0
    for r in rules:
        what = {"time": lambda: "at %s UTC" % r["at"],
                "pct_move": lambda: "%s moves %g%% (%s)" % (r["product"], r["pct"], r.get("direction", "both"))
                }.get(r["type"], lambda: "%s %s %s" % (r["product"], r["type"], L.money(r["price"])))()
        print("%-36s %s%s%s" % (r["id"], what, "  [rung]" if (state.get(r["id"]) or {}).get("rung") else "",
                                "  " + r["label"] if r.get("label") else ""))
    return 0


def cmd_reset(a):
    st_p = L.path(a.out, "state", "alerts.json")
    state = L.read_json(st_p, {}) or {}
    if a.id == "all":
        state = {}
    elif a.id in state:
        state.pop(a.id)
    else:
        print("alerts.py: no rung alert %r." % a.id)
        return 1
    L.write_json(st_p, state)
    print("Reset %s." % a.id)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Crypto price alerts.")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name):
        s = sub.add_parser(name)
        s.add_argument("--out", default=L.OUT_DIR)
        return s

    s = add("quote")
    s.add_argument("products", nargs="*")
    s.add_argument("--holdings", action="store_true")
    s.add_argument("--write", action="store_true")
    s.add_argument("--offline")
    s = add("add")
    s.add_argument("--from-plan", action="store_true")
    s.add_argument("--product")
    for k in ("above", "below", "stop", "target", "pct"):
        s.add_argument("--" + k, type=float)
    s.add_argument("--direction", choices=("up", "down", "both"), default="both")
    s.add_argument("--at", help="'YYYY-MM-DD HH:MM' UTC")
    s.add_argument("--label")
    s.add_argument("--rearm", action="store_true")
    s = add("check")
    s.add_argument("--now")
    s.add_argument("--offline")
    add("list")
    s = add("reset")
    s.add_argument("id")
    a = p.parse_args(argv)
    return {"quote": cmd_quote, "add": cmd_add, "check": cmd_check, "list": cmd_list, "reset": cmd_reset}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
