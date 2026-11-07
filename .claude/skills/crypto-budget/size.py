#!/usr/bin/env python3
"""Position sizing for crypto-budget. Standard library only.

Sizes ONE crypto trade from crypto/plan.json (written by crypto-exit) to your
budget and your max loss per trade, fees included, and writes one buy order
to crypto/orders.json in the shape of Alpaca's place_crypto_order. It never
places anything: crypto-risk checks the order and crypto-broker asks you yes
or no.

    python3 size.py                          # crypto/plan.json + crypto/config.json
    python3 size.py --write                  # write crypto/orders.json
    python3 size.py --limit                  # a limit order at the plan's entry
    python3 size.py --limit 1335.00 --write  # a limit order at 1335.00
    python3 size.py --json

How much. Fractional coins, floored to the pair's base_increment on Coinbase:

    qty = the smallest of
      max loss       max_loss_per_trade_usd / (entry - stop + entry x fee_pct / 100)
      position cap   budget x max_position_pct / entry
      max order      max_order_usd / entry
      cash           (budget minus the cash buffer, minus what you already hold) / entry
                     (and no more than the cash in crypto/portfolio.json, if you have one)

fee_pct is your ROUND-TRIP fee in % of the entry; it is counted in the loss at
the stop, so a big fee means a smaller position. The entry it sizes at: a
limit order's limit price; for a market order the plan's entry or the price in
crypto/prices.json if that is fresh (under 15 minutes) and higher. A size
under min_order_usd, or a reward:risk after fees under min_reward_risk, is a
plain refusal: no order is written.

Alpaca crypto orders cannot be brackets: the stop goes in as its own order
after the buy fills (crypto-broker builds it), and the target is watched by
crypto-alerts. Exit codes: 0 = an order, 1 = refused or an error.
"""

import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "crypto-common"))
import cryptolib as L  # noqa: E402


def fresh_price(prices, pid, now_t):
    row = (prices or {}).get(pid)
    if not row:
        return None
    if now_t - int(row.get("time", 0)) > L.FRESH_SECONDS:
        return None
    return float(row["price"])


def size(plan, cfg, *, portfolio=None, fresh=None, limit=None, base_inc=1e-8):
    """Pure. -> (result dict, None) or (None, reason)."""
    if limit is not None:
        entry, basis = limit, "the limit price"
    elif fresh is not None and fresh > plan["entry"]:
        entry, basis = fresh, "the fresh price, above the plan's entry"
    else:
        entry, basis = plan["entry"], "the plan's entry"
    stop, target = plan["stop"], plan["target"]
    if fresh is not None and fresh <= stop:
        return None, "the price is already %s, at or below the stop %s: the setup is gone" % (
            L.money(fresh), L.money(stop))
    if stop >= entry:
        return None, "the price %s is at or under the stop %s: the setup is gone" % (L.money(entry), L.money(stop))
    if target <= entry:
        return None, "the price %s is at or over the target %s: nothing left to win" % (
            L.money(entry), L.money(target))
    fee_coin = entry * cfg["fee_pct"] / 100
    loss_coin = entry - stop + fee_coin
    rr = (target - entry - fee_coin) / loss_coin
    if rr < cfg["min_reward_risk"]:
        return None, ("reward:risk after fees at %s is %.2f, under min_reward_risk %.2f"
                      % (L.money(entry), rr, cfg["min_reward_risk"]))
    budget = float(cfg["budget"])
    holdings = 0.0
    cash = None
    if portfolio:
        cash = portfolio.get("cash")
        for p, q in (portfolio.get("positions") or {}).items():
            holdings += float(q.get("qty", 0)) * float(q.get("price") or q.get("cost") or 0)
    spendable = budget * (1 - cfg["cash_buffer_pct"] / 100.0) - holdings
    if cash is not None:
        spendable = min(spendable, float(cash) - budget * cfg["cash_buffer_pct"] / 100.0)
    limits = {
        "max loss": cfg["max_loss_per_trade_usd"] / loss_coin,
        "position cap": budget * cfg["max_position_pct"] / 100.0 / entry,
        "max order": cfg["max_order_usd"] / entry,
        "cash": max(0.0, spendable) / entry,
    }
    decider = min(limits, key=limits.get)
    qty = L.floor_qty(limits[decider], base_inc)
    notional = qty * entry
    if qty <= 0 or notional < cfg["min_order_usd"]:
        return None, ("%s allows only %s coins (%s), under min_order_usd %s"
                      % (decider, L.fmt_qty(qty), L.money(notional), L.money(cfg["min_order_usd"])))
    res = {"qty": qty, "entry_used": entry, "basis": basis, "decided_by": decider,
           "limits": {k: v for k, v in limits.items()}, "notional": notional,
           "max_loss_usd": qty * loss_coin, "fee_usd": qty * fee_coin,
           "loss_at_stop_ex_fees": qty * (entry - stop), "win_at_target_usd": qty * (target - entry - fee_coin),
           "rr_after_fees": rr}
    return res, None


def build_order(plan, res, limit=None):
    pid = plan["product"]
    order = {"symbol": L.alpaca_symbol(pid), "side": "buy", "type": "limit" if limit is not None else "market",
             "qty": L.fmt_qty(res["qty"]), "time_in_force": "gtc"}
    if limit is not None:
        order["limit_price"] = str(limit)
    order["plan"] = {"product": pid, "entry": res["entry_used"], "stop": plan["stop"],
                     "target": plan["target"], "hold_until": plan.get("hold_until"),
                     "max_loss_usd": round(res["max_loss_usd"], 2), "fee_pct": plan.get("fee_pct", 0),
                     "rr_after_fees": round(res["rr_after_fees"], 3)}
    order["intent"] = "entry"
    return order


def cmd(a):
    cfg, found = L.load_config(a.out)
    plan = L.read_json(L.path(a.out, "plan.json"))
    if not plan:
        print("size.py: no %s. Run /crypto-exit first." % L.path(a.out, "plan.json"))
        return 1
    now_t = L.ts(L.now_utc(a.now))
    prices = L.read_json(L.path(a.out, "prices.json"), {})
    fresh = fresh_price(prices, plan["product"], now_t)
    limit = None
    if a.limit is not None:
        limit = plan["entry"] if a.limit == "plan" else float(a.limit)
    meta = L.product_meta(plan["product"], a.out) if not a.offline else {"base_increment": 1e-8}
    res, why = size(plan, cfg, portfolio=L.read_json(L.path(a.out, "portfolio.json")), fresh=fresh,
                    limit=limit, base_inc=meta.get("base_increment") or 1e-8)
    if not res:
        print("Refused: %s. No order written." % why)
        return 1
    order = build_order(plan, res, limit)
    if a.json:
        print(json.dumps({"sizing": res, "order": order}, indent=2))
    else:
        if not found:
            print("No %s: using the defaults (budget %s, max loss %s a trade). Copy config.example.json to set yours."
                  % (L.path(a.out, "config.json"), L.money(cfg["budget"]), L.money(cfg["max_loss_per_trade_usd"])))
        print("%s %s of %s at %s (%s) = %s." % (
            "Limit buy" if limit is not None else "Market buy", L.fmt_qty(res["qty"]), plan["product"],
            L.money(res["entry_used"]), res["basis"], L.money(res["notional"])))
        print("Decided by: %s. Limits in coins: %s." % (res["decided_by"], ", ".join(
            "%s %s" % (k, L.fmt_qty(v)) for k, v in res["limits"].items())))
        print("At the stop %s: loss %s (%s price + %s fees). At the target %s: %s after fees. Reward:risk %.2f."
              % (L.money(plan["stop"]), L.money(res["max_loss_usd"]), L.money(res["loss_at_stop_ex_fees"]),
                 L.money(res["fee_usd"]), L.money(plan["target"]), L.money(res["win_at_target_usd"]),
                 res["rr_after_fees"]))
        print("The stop is placed as its own order after the buy fills (Alpaca has no crypto brackets).")
    if a.write:
        L.write_json(L.path(a.out, "orders.json"), [order])
        if not a.json:
            print("Wrote %s. Next: /crypto-risk. Nothing has been placed." % L.path(a.out, "orders.json"))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Crypto position sizing.")
    p.add_argument("--limit", nargs="?", const="plan", help="a limit order (at the plan's entry, or PRICE)")
    p.add_argument("--now")
    p.add_argument("--offline", action="store_true", help="no network (generic 1e-8 coin increment)")
    p.add_argument("--out", default=L.OUT_DIR)
    p.add_argument("--write", action="store_true")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    return cmd(a)


if __name__ == "__main__":
    sys.exit(main())
