#!/usr/bin/env python3
"""Order tickets and the decision log for crypto-broker. Standard library only.

This tool never talks to a broker and never places anything. It does its
work around the one moment that matters, your yes:

  show      renders each proposed order as a plain ticket plus the JSON for
            Alpaca's place_crypto_order. An order is READY only if
            crypto-risk passed THIS exact order today (matched by
            fingerprint) and nobody has decided on it yet.
  approve   records your explicit yes for ONE order, word for word. It
            refuses "yes to all", "sure", "ok", a yes that names a different
            coin or amount, and any order that is not READY.
  decline   records a no.
  result    records what happened after the Allow once / Deny card: placed
            (with the broker's order id, and the fill if you have it),
            denied, or failed.
  fill      records a fill in crypto/portfolio.json (cash and coins).
  protect   after a buy fills: builds the stop-loss sell (a stop_limit for
            the filled amount at the plan's stop). Alpaca crypto has no
            brackets, so the stop is its own order. It goes through
            crypto-risk and your yes like any order.
  flatten   builds a market sell that closes a position (by hold_until, at
            the target, or whenever you want out). Cancel the open stop
            order first, or the broker will refuse the sell for lack of coins.
  log       prints today's decisions.

    python3 ticket.py show
    python3 ticket.py approve --index 1 --reply "yes"
    python3 ticket.py result --index 1 --status placed --broker-id 61e6... --filled-qty 0.374 --filled-price 1336.9
    python3 ticket.py protect --product ZEC-USD
    python3 ticket.py flatten --product ZEC-USD
    python3 ticket.py fill --product ZEC-USD --side sell --qty 0.374 --price 1355.80 --fee 1.20
    python3 ticket.py log

Everything is written to crypto/state/broker.json (append only). Days are UTC
days; --now "2026-11-07 10:00" pins the clock.
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "crypto-common"))
import cryptolib as L  # noqa: E402

YES = re.compile(r"^\s*(yes|ya|iya|y)\b", re.I)
VAGUE = re.compile(r"\b(all|semua|everything|sure|ok|okay|oke|fine|whatever|go ahead|terserah)\b", re.I)


def load_broker(out):
    return L.read_json(L.path(out, "state", "broker.json"), {"events": []}) or {"events": []}


def log_event(out, ev):
    doc = load_broker(out)
    doc["events"].append(ev)
    L.write_json(L.path(out, "state", "broker.json"), doc)


def status_of(order, i, risk, broker, day):
    fp = L.fingerprint(order)
    passed = [v for v in (risk or {}).get("verdicts", [])
              if v.get("fingerprint") == fp and v.get("date") == day]
    if not passed:
        return "NOT CHECKED", "run /crypto-risk on this exact order first"
    if passed[-1]["verdict"] != "PASS":
        return "BLOCKED", "; ".join(passed[-1]["reasons"])
    decided = [e for e in broker.get("events", []) if e.get("fingerprint") == fp and e.get("date") == day
               and e.get("type") in ("approve", "decline", "placed", "denied", "failed")]
    if decided:
        return "DECIDED", "already %s today" % decided[-1]["type"]
    return "READY", ""


def tool_args(o):
    """The arguments of place_crypto_order in alpacahq/alpaca-mcp-server (checked 2026-11-07 against
    src/alpaca_mcp_server/overrides.py): symbol, side, qty | notional, type, time_in_force,
    limit_price, stop_price, client_order_id. The client_order_id comes from the order's fingerprint,
    so a retry after a timeout cannot place the same order twice."""
    args = {"symbol": o["symbol"], "side": o["side"], "type": o["type"],
            "time_in_force": o["time_in_force"]}
    for k in ("qty", "notional", "limit_price", "stop_price"):
        if o.get(k) is not None:
            args[k] = str(o[k])
    args["client_order_id"] = "tb-crypto-" + L.fingerprint(o)
    return args


def ticket_text(o, i, st, why):
    p = o.get("plan") or {}
    pid = L.product_id(o["symbol"])
    what = {"market": "at the market", "limit": "limit %s" % L.money(float(o.get("limit_price", 0))),
            "stop_limit": "stop %s, limit %s" % (L.money(float(o.get("stop_price", 0))),
                                                 L.money(float(o.get("limit_price", 0))))}[o["type"]]
    lines = ["Ticket #%d  [%s]%s" % (i, st, "  " + why if why else ""),
             "  %s %s %s %s (%s), good till cancelled." % (
                 o["side"].upper(), o.get("qty") or ("$" + str(o.get("notional"))), pid, what,
                 o.get("intent", "entry"))]
    if p.get("stop") and o["side"] == "buy":
        lines.append("  Plan: stop %s, target %s, out by %s. Max loss at the stop: %s (fees in)." % (
            L.money(p["stop"]), L.money(p["target"]), p.get("hold_until") or "-", L.money(p.get("max_loss_usd"))))
        lines.append("  The stop is NOT part of this order: after it fills, run protect and approve the stop.")
    lines.append("  Alpaca place_crypto_order: " + json.dumps(tool_args(o)))
    return "\n".join(lines)


def ctx(a):
    now_t = L.ts(L.now_utc(a.now))
    day = L.utc(now_t).date().isoformat()
    orders = L.read_json(L.path(a.out, "orders.json")) or []
    risk = L.read_json(L.path(a.out, "state", "risk.json"))
    return now_t, day, orders, risk, load_broker(a.out)


def pick(orders, index):
    if not 1 <= index <= len(orders):
        raise SystemExit("ticket.py: no order #%d (there are %d)" % (index, len(orders)))
    return orders[index - 1]


def cmd_show(a):
    now_t, day, orders, risk, broker = ctx(a)
    if not orders:
        print("No orders in %s. Run /crypto-budget (or protect / flatten) first." % L.path(a.out, "orders.json"))
        return 1
    cfg, _ = L.load_config(a.out)
    print("Broker: %s, %s account." % (cfg["broker"], "PAPER" if cfg["paper"] else "LIVE (real money)"))
    ready = 0
    for i, o in enumerate(orders, 1):
        if a.index and i != a.index:
            continue
        st, why = status_of(o, i, risk, broker, day)
        ready += st == "READY"
        print(ticket_text(o, i, st, why))
    print("Only a READY ticket can be approved, one at a time, with an explicit yes.")
    return 0 if ready else 1


def check_reply(reply, o):
    """-> None if the reply is a clear yes for THIS order, else the reason."""
    if not YES.search(reply or ""):
        return "that is not an explicit yes"
    if VAGUE.search(reply):
        return "a yes must be for one order, in plain words: no 'all', 'sure' or 'ok'"
    base = o["symbol"].split("/")[0]
    for tok in re.findall(r"\b[A-Z]{2,10}\b", reply):
        if tok not in (base, "USD", "YES", "YA", "IYA") and tok != base + "USD":
            return "the reply names %s, but this order is %s" % (tok, base)
    amount = float(o.get("qty") or o.get("notional") or 0)
    for num in re.findall(r"\d+(?:[.,]\d+)?", reply):
        n = float(num.replace(",", "."))
        if amount and abs(n - amount) / amount > 0.01:
            return "the reply says %s, but this order is for %s" % (num, L.fmt_qty(amount))
    return None


def cmd_approve(a):
    now_t, day, orders, risk, broker = ctx(a)
    o = pick(orders, a.index)
    st, why = status_of(o, a.index, risk, broker, day)
    if st != "READY":
        print("Not approved: ticket #%d is %s (%s)." % (a.index, st, why))
        return 1
    bad = check_reply(a.reply, o)
    if bad:
        print("Not approved: %s. Ask again for this one order." % bad)
        return 1
    log_event(a.out, {"type": "approve", "time": L.stamp(now_t), "date": day, "index": a.index,
                      "fingerprint": L.fingerprint(o), "symbol": o["symbol"], "side": o["side"],
                      "qty": o.get("qty"), "intent": o.get("intent", "entry"), "reply": a.reply,
                      "max_loss_usd": (o.get("plan") or {}).get("max_loss_usd")})
    print("Approved #%d, reply recorded word for word. Now call place_crypto_order with exactly:" % a.index)
    print(json.dumps(tool_args(o)))
    print("Claude's own Allow once / Deny card asks one more time. Then record it: ticket.py result.")
    return 0


def cmd_decline(a):
    now_t, day, orders, _, _ = ctx(a)
    o = pick(orders, a.index)
    log_event(a.out, {"type": "decline", "time": L.stamp(now_t), "date": day, "index": a.index,
                      "fingerprint": L.fingerprint(o), "symbol": o["symbol"], "side": o["side"],
                      "reply": a.reply})
    print("Declined #%d. Nothing was sent." % a.index)
    return 0


def apply_fill(out, pid, side, qty, price, fee=0.0):
    pf = L.read_json(L.path(out, "portfolio.json"))
    if pf is None:
        cfg, _ = L.load_config(out)
        pf = {"cash": float(cfg["budget"]), "positions": {}}
    pos = pf.setdefault("positions", {}).get(pid, {"qty": 0.0, "cost": 0.0})
    if side == "buy":
        newq = pos["qty"] + qty
        pos["cost"] = (pos["qty"] * pos["cost"] + qty * price) / newq
        pos["qty"] = newq
        pf["cash"] = float(pf.get("cash", 0)) - qty * price - fee
    else:
        if qty > pos["qty"] + 1e-12:
            raise SystemExit("ticket.py: selling %s %s but the portfolio holds %s"
                             % (L.fmt_qty(qty), pid, L.fmt_qty(pos["qty"])))
        pos["qty"] = round(pos["qty"] - qty, 12)
        pf["cash"] = float(pf.get("cash", 0)) + qty * price - fee
    if pos["qty"] <= 1e-12:
        pf["positions"].pop(pid, None)
    else:
        pf["positions"][pid] = pos
    L.write_json(L.path(out, "portfolio.json"), pf)
    return pf


def cmd_result(a):
    now_t, day, orders, risk, broker = ctx(a)
    o = pick(orders, a.index)
    approved = [e for e in broker["events"] if e.get("fingerprint") == L.fingerprint(o)
                and e.get("date") == day and e.get("type") == "approve"]
    if a.status == "placed" and not approved:
        print("ticket.py: #%d was never approved today; an order without a yes is not recorded as placed." % a.index)
        return 1
    ev = {"type": a.status, "time": L.stamp(now_t), "date": day, "index": a.index,
          "fingerprint": L.fingerprint(o), "symbol": o["symbol"], "side": o["side"], "qty": o.get("qty"),
          "intent": o.get("intent", "entry"), "broker_id": a.broker_id, "note": a.note,
          "max_loss_usd": (o.get("plan") or {}).get("max_loss_usd")}
    log_event(a.out, ev)
    print("Recorded #%d as %s." % (a.index, a.status))
    if a.status == "placed" and a.filled_qty:
        pf = apply_fill(a.out, L.product_id(o["symbol"]), o["side"], a.filled_qty, a.filled_price, a.fee)
        log_event(a.out, {"type": "fill", "time": L.stamp(now_t), "date": day, "symbol": o["symbol"],
                          "side": o["side"], "qty": a.filled_qty, "price": a.filled_price, "fee": a.fee})
        print("Fill recorded: cash now %s." % L.money(pf["cash"]))
        if o["side"] == "buy":
            print("Next: ticket.py protect --product %s, so the stop is at the broker." % L.product_id(o["symbol"]))
    return 0


def cmd_fill(a):
    now_t, day, _, _, _ = ctx(a)
    pid = L.product_id(a.product)
    pf = apply_fill(a.out, pid, a.side, a.qty, a.price, a.fee)
    log_event(a.out, {"type": "fill", "time": L.stamp(now_t), "date": day, "symbol": L.alpaca_symbol(pid),
                      "side": a.side, "qty": a.qty, "price": a.price, "fee": a.fee})
    print("Recorded %s %s %s at %s (fee %s). Cash %s; %s held: %s." % (
        a.side, L.fmt_qty(a.qty), pid, L.money(a.price), L.money(a.fee), L.money(pf["cash"]), pid,
        L.fmt_qty(pf["positions"].get(pid, {}).get("qty", 0))))
    return 0


def held(out, pid):
    pf = L.read_json(L.path(out, "portfolio.json")) or {}
    return float(((pf.get("positions") or {}).get(pid) or {}).get("qty", 0))


def cmd_protect(a):
    pid = L.product_id(a.product)
    plan = L.read_json(L.path(a.out, "plan.json")) or {}
    stop = a.stop if a.stop is not None else (plan.get("stop") if plan.get("product") == pid else None)
    if stop is None:
        print("ticket.py: no stop for %s: give --stop or plan it with /crypto-exit." % pid)
        return 1
    qty = a.qty or held(a.out, pid)
    if qty <= 0:
        print("ticket.py: the portfolio holds no %s. Record the fill first (result or fill)." % pid)
        return 1
    meta = L.product_meta(pid, a.out)
    limit = L.round_price(stop * (1 - a.slip_pct / 100.0), meta.get("quote_increment"), down=True)
    order = {"symbol": L.alpaca_symbol(pid), "side": "sell", "type": "stop_limit", "qty": L.fmt_qty(qty),
             "stop_price": str(stop), "limit_price": str(limit), "time_in_force": "gtc", "intent": "stop",
             "plan": {"product": pid, "stop": stop, "target": plan.get("target"),
                      "hold_until": plan.get("hold_until")}}
    L.write_json(L.path(a.out, "orders.json"), [order])
    print("Stop-loss ticket: SELL %s %s, stop %s, limit %s (%.1f%% below the stop, so it can still fill in a "
          "fast drop; below the limit it will NOT fill)." % (L.fmt_qty(qty), pid, L.money(stop), L.money(limit),
                                                            a.slip_pct))
    print("Wrote %s. Next: /crypto-risk, then show and your yes." % L.path(a.out, "orders.json"))
    return 0


def cmd_flatten(a):
    pid = L.product_id(a.product)
    qty = a.qty or held(a.out, pid)
    if qty <= 0:
        print("ticket.py: the portfolio holds no %s." % pid)
        return 1
    order = {"symbol": L.alpaca_symbol(pid), "side": "sell", "type": "market", "qty": L.fmt_qty(qty),
             "time_in_force": "gtc", "intent": "flatten"}
    L.write_json(L.path(a.out, "orders.json"), [order])
    print("Flatten ticket: SELL %s %s at the market." % (L.fmt_qty(qty), pid))
    print("First cancel the open stop order for %s (cancel_order_by_id, Needs approval), or the broker "
          "holds those coins and refuses the sell." % pid)
    print("Wrote %s. Next: /crypto-risk (an exit always passes the limits), then show and your yes."
          % L.path(a.out, "orders.json"))
    return 0


def cmd_log(a):
    now_t, day, _, _, broker = ctx(a)
    evs = [e for e in broker["events"] if e.get("date") == day]
    if not evs:
        print("Nothing recorded today (%s UTC)." % day)
        return 0
    for e in evs:
        print("%s  %-8s %s %s %s%s" % (e["time"][11:], e["type"], e.get("side", ""), e.get("qty", ""),
                                       e.get("symbol", ""), ("  reply: %r" % e["reply"]) if e.get("reply") else ""))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Crypto order tickets and decision log.")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name):
        s = sub.add_parser(name)
        s.add_argument("--out", default=L.OUT_DIR)
        s.add_argument("--now")
        return s

    s = add("show")
    s.add_argument("--index", type=int)
    s = add("approve")
    s.add_argument("--index", type=int, required=True)
    s.add_argument("--reply", required=True, help="the user's reply, word for word")
    s = add("decline")
    s.add_argument("--index", type=int, required=True)
    s.add_argument("--reply", default="")
    s = add("result")
    s.add_argument("--index", type=int, required=True)
    s.add_argument("--status", choices=("placed", "denied", "failed"), required=True)
    s.add_argument("--broker-id")
    s.add_argument("--filled-qty", type=float)
    s.add_argument("--filled-price", type=float)
    s.add_argument("--fee", type=float, default=0.0)
    s.add_argument("--note")
    s = add("fill")
    s.add_argument("--product", required=True)
    s.add_argument("--side", choices=("buy", "sell"), required=True)
    s.add_argument("--qty", type=float, required=True)
    s.add_argument("--price", type=float, required=True)
    s.add_argument("--fee", type=float, default=0.0)
    s = add("protect")
    s.add_argument("--product", required=True)
    s.add_argument("--stop", type=float)
    s.add_argument("--qty", type=float)
    s.add_argument("--slip-pct", type=float, default=1.0, help="limit this %% under the stop (default 1)")
    s = add("flatten")
    s.add_argument("--product", required=True)
    s.add_argument("--qty", type=float)
    add("log")
    a = p.parse_args(argv)
    return {"show": cmd_show, "approve": cmd_approve, "decline": cmd_decline, "result": cmd_result,
            "fill": cmd_fill, "protect": cmd_protect, "flatten": cmd_flatten, "log": cmd_log}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
