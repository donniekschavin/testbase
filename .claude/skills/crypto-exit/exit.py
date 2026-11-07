#!/usr/bin/env python3
"""Exit Planner for crypto-exit: sets the stop and the target BEFORE you
enter, so you know when to get out. Standard library only. Long side only.
It never places an order.

    python3 exit.py plan                                     # from crypto/entry.json: or-mid stop, 2R target
    python3 exit.py plan --stop or-low --target 1.5R --write
    python3 exit.py plan --product BTC-USD --entry 75900 --stop pct:1.5
    python3 exit.py plan --product SOL-USD --entry 90.04 --stop atr:2 --target price:93
    python3 exit.py show                                     # the current crypto/plan.json

Stops (rounded DOWN to the pair's price tick, away from the entry):
  or-mid     the opening-range midpoint (the default for an orb entry)
  or-low     the opening-range low
  price:X    your price
  pct:X      X percent under the entry
  atr:K      K times the 14-bar ATR of the 5-minute candles before the entry
  A level entry or a hand-typed entry has no range: give a stop.

Targets (rounded UP to the tick): 2R (default), 1R, 1.5R ... or price:X.

Refused, with the reason: a stop at or above the entry, a target at or below
it, a stop closer than min_stop_pct (default 0.2 %) of the price (too tight
for the spread and the fees), an entry.json that has not triggered (unless
you give --entry).

hold_until = the entry time + hold_hours (default 24, or "hold_hours" in
crypto/config.json): out by then, win or lose. Crypto never closes, so this
is your own deadline. When "fee_pct" is set the plan also shows the fee in R
and the reward:risk after fees; crypto-risk enforces min_reward_risk on it.

A stop is a plan, not a guarantee: crypto can gap through it.
Exit codes: plan 0 = a plan, 1 = refused or an error. show 0 = a plan exists.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "crypto-common"))
import cryptolib as L  # noqa: E402


def atr(bars, n=14):
    """Wilder-free simple ATR of the last n bars (true range). Needs >= 2 bars."""
    if len(bars) < 2:
        return None
    trs = []
    for prev, b in zip(bars, bars[1:]):
        trs.append(max(b[2] - b[3], abs(b[2] - prev[4]), abs(b[3] - prev[4])))
    trs = trs[-n:]
    return sum(trs) / len(trs)


def make_plan(entry, stop_rule, target_rule, *, or_high=None, or_low=None, atr_value=None,
              tick=None, min_stop_pct=0.2, fee_pct=0.0, hold_hours=24, entry_t=None,
              product=None, setup=None):
    """Pure. -> (plan dict, None) or (None, reason)."""
    kind, _, arg = stop_rule.partition(":")
    if kind in ("or-mid", "or-low"):
        if or_high is None or or_low is None:
            return None, "%s needs an opening range: give --stop price:X, pct:X or atr:K" % kind
        raw = (or_high + or_low) / 2 if kind == "or-mid" else or_low
    elif kind == "price":
        raw = float(arg)
    elif kind == "pct":
        raw = entry * (1 - float(arg) / 100)
    elif kind == "atr":
        if not atr_value:
            return None, "atr needs the candles before the entry"
        raw = entry - float(arg or 1.5) * atr_value
    else:
        return None, "unknown stop %r (or-mid, or-low, price:X, pct:X, atr:K)" % stop_rule
    stop = L.round_price(raw, tick, down=True)
    if stop >= entry:
        return None, "the stop %s is at or above the entry %s (long only)" % (L.money(stop), L.money(entry))
    risk = entry - stop
    if risk / entry * 100 < min_stop_pct:
        return None, ("the stop is %.3f%% under the entry, under min_stop_pct %.2f%%: too tight to survive "
                      "the spread and the fees" % (risk / entry * 100, min_stop_pct))
    if target_rule.upper().endswith("R"):
        r_mult = float(target_rule[:-1])
        target = L.round_price(entry + r_mult * risk, tick, down=False)
    elif target_rule.startswith("price:"):
        target = L.round_price(float(target_rule[6:]), tick, down=False)
    else:
        return None, "unknown target %r (2R, 1.5R, price:X)" % target_rule
    if target <= entry:
        return None, "the target %s is at or below the entry %s" % (L.money(target), L.money(entry))
    R = (target - entry) / risk
    fee_r = fee_pct / 100 * entry / risk
    plan = {"product": product, "side": "buy", "setup": setup, "entry": entry, "stop": stop,
            "target": target, "stop_rule": stop_rule, "target_rule": target_rule,
            "risk_per_coin": risk, "risk_pct": risk / entry * 100, "R": R,
            "fee_pct": fee_pct, "fee_R": fee_r, "R_after_fees": (R - fee_r) / (1 + fee_r),
            "or_high": or_high, "or_low": or_low}
    if entry_t:
        plan["entry_time"] = L.stamp(entry_t)
        plan["hold_until"] = L.stamp(entry_t + int(hold_hours * 3600))
    plan["hold_hours"] = hold_hours
    return plan, None


def describe(p):
    lines = ["Plan: %s long, entry %s%s." % (p["product"], L.money(p["entry"]),
                                             " at " + p["entry_time"] if p.get("entry_time") else ""),
             "  stop    %s  (%s, %.2f%% under, %s a coin at risk)" % (
                 L.money(p["stop"]), p["stop_rule"], p["risk_pct"], L.money(p["risk_per_coin"])),
             "  target  %s  (%.2fR)" % (L.money(p["target"]), p["R"])]
    if p.get("fee_pct"):
        lines.append("  fees    %.2f%% round trip = %.2fR; reward:risk after fees %.2f"
                     % (p["fee_pct"], p["fee_R"], p["R_after_fees"]))
    if p.get("hold_until"):
        lines.append("  out by  %s (%g hours), win or lose" % (p["hold_until"], p["hold_hours"]))
    return "\n".join(lines)


def cmd_plan(a):
    cfg, _ = L.load_config(a.out)
    entry_doc = None
    if a.entry is None:
        entry_doc = L.read_json(L.path(a.out, "entry.json"))
        if not entry_doc:
            print("exit.py: no %s. Run /crypto-entry, or give --product and --entry." % L.path(a.out, "entry.json"))
            return 1
        if entry_doc.get("status") != "triggered":
            print("exit.py: the entry has not triggered (%s). Give --entry to plan anyway." % entry_doc.get("status"))
            return 1
    pid = L.product_id(a.product or (entry_doc or {}).get("product") or "")
    if pid == "-USD":
        print("exit.py: give --product.")
        return 1
    entry = a.entry if a.entry is not None else entry_doc["price"]
    entry_t = None
    if entry_doc and entry_doc.get("trigger_time"):
        entry_t = L.parse_stamp(entry_doc["trigger_time"])
    elif a.now or a.entry is not None:
        n = L.ts(L.now_utc(a.now))
        entry_t = n - n % 300
    or_high = a.or_high if a.or_high is not None else (entry_doc or {}).get("or_high")
    or_low = a.or_low if a.or_low is not None else (entry_doc or {}).get("or_low")
    stop_rule = a.stop or ("or-mid" if or_high is not None else None)
    if not stop_rule:
        print("exit.py: no opening range here, so give a stop: --stop price:X, pct:X or atr:K.")
        return 1
    atr_value = None
    if stop_rule.startswith("atr"):
        try:
            if a.offline:
                bars = L.read_bars(a.offline)
            else:
                bars, _ = L.candles(pid, 300, entry_t - 20 * 300, entry_t)
            bars = [b for b in bars if b[0] + 300 <= entry_t]
            atr_value = atr(bars)
        except Exception as e:  # noqa: BLE001
            print("exit.py: could not fetch candles for the ATR: %s" % e)
            return 1
    meta = L.product_meta(pid, a.out) if not a.offline else {"quote_increment": None}
    plan, why = make_plan(entry, stop_rule, a.target, or_high=or_high, or_low=or_low,
                          atr_value=atr_value, tick=meta.get("quote_increment"),
                          min_stop_pct=cfg["min_stop_pct"], fee_pct=cfg["fee_pct"],
                          hold_hours=cfg["hold_hours"], entry_t=entry_t, product=pid,
                          setup=(entry_doc or {}).get("setup", "manual"))
    if not plan:
        print("Refused: %s." % why)
        return 1
    if atr_value:
        plan["atr"] = atr_value
    print(describe(plan))
    if plan["R_after_fees"] < cfg["min_reward_risk"]:
        print("Warning: reward:risk after fees %.2f is under min_reward_risk %.2f; crypto-risk will block it."
              % (plan["R_after_fees"], cfg["min_reward_risk"]))
    if a.write:
        L.write_json(L.path(a.out, "plan.json"), plan)
        print("Wrote %s. Next: /crypto-timemachine, then /crypto-budget." % L.path(a.out, "plan.json"))
    return 0


def cmd_show(a):
    p = L.read_json(L.path(a.out, "plan.json"))
    if not p:
        print("No plan yet: run exit.py plan --write.")
        return 1
    print(describe(p))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Crypto exit planner.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("plan")
    s.add_argument("--product")
    s.add_argument("--entry", type=float)
    s.add_argument("--or-high", type=float)
    s.add_argument("--or-low", type=float)
    s.add_argument("--stop", help="or-mid | or-low | price:X | pct:X | atr:K")
    s.add_argument("--target", default="2R", help="2R | 1.5R | price:X")
    s.add_argument("--now")
    s.add_argument("--offline")
    s.add_argument("--out", default=L.OUT_DIR)
    s.add_argument("--write", action="store_true")
    s2 = sub.add_parser("show")
    s2.add_argument("--out", default=L.OUT_DIR)
    a = ap.parse_args(argv)
    return {"plan": cmd_plan, "show": cmd_show}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
