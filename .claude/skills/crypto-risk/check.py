#!/usr/bin/env python3
"""Pre-trade risk check for crypto-risk. Standard library only.

Reads the proposed orders (crypto/orders.json) and checks every one against
your rules (crypto/config.json), your account (crypto/portfolio.json), prices
(crypto/prices.json) and what was placed today (crypto/state/broker.json).
Each order gets PASS or BLOCK with the reasons. Orders are checked in file
order as if each PASS had filled. Days are UTC days.

    python3 check.py                          # writes crypto/state/risk.json
    python3 check.py --now "2026-11-07 10:00" # pin the clock (UTC)
    python3 check.py --orders crypto/orders.json --json
    python3 check.py --no-write

Entries and exits. An ENTRY is a buy. An EXIT is a sell that only reduces
what you hold (a take-profit, a stop, a flatten). Getting out must always be
possible: an exit is checked for format, asset and short sales only; every
other rule turns into a warning for it.

What blocks an order (every order):
  format       no symbol or side, both or neither of qty / notional, a type
               that is not market / limit / stop_limit, a limit without a
               limit price, a stop_limit without both prices, a
               time_in_force that is not gtc / ioc (Alpaca crypto)
  asset        not a crypto pair quoted in USD (BTC/USD), a stablecoin, not
               on your "allowed" list when you keep one, delisted or
               trading-disabled on Coinbase
  short        selling more than you hold (spot crypto cannot go short)

What blocks an entry (on top):
  blocked      a pair on your "blocked" list
  size         under min_order_usd, over max_order_usd
  position     the coin would be over max_position_pct of the budget
  cash         the buy would dip into your cash buffer
  duplicate    the same pair bought twice in this batch, or already today
  daily limit  max_orders_per_day orders placed today
  stop         no stop while "require_stop": true; a stop at or above the entry;
               a fresh price already at or below the stop (or at the target)
  loss         qty x (entry - stop + fee) over max_loss_per_trade_usd (the fee
               is the higher of the plan's fee_pct and the config's). The
               entry is the limit price, else the HIGHER of the plan's entry
               and a fresh price (under 15 minutes old)
  reward:risk  after fees, under min_reward_risk
  daily loss   today's entries' max losses plus this one over max_daily_loss_usd
  trades       max_trades_per_day entries already placed today
  window       before no_entries_before or after no_entries_after (UTC), when set

Exit code 0 when every order passes, 1 when any order is blocked. The verdicts
go to crypto/state/risk.json with a fingerprint of each order, so
crypto-broker only shows an order as ready if THIS exact order passed today.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "crypto-common"))
import cryptolib as L  # noqa: E402

STABLE = {"USDT", "USDC", "DAI", "PYUSD", "GUSD", "EURC", "USDS", "FDUSD", "TUSD", "PAX",
          "USDP", "RLUSD", "BUSD", "UST", "USD1", "FRAX", "LUSD"}


def today_events(broker, day):
    return [e for e in (broker or {}).get("events", []) if e.get("date") == day]


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def check_orders(orders, cfg, *, portfolio=None, prices=None, broker=None, now_t, meta=None):
    """Pure. -> list of verdict dicts, one per order."""
    day = L.utc(now_t).date().isoformat()
    events = today_events(broker, day)
    placed = [e for e in events if e.get("type") == "placed"]
    entries_today = [e for e in placed if e.get("intent") == "entry"]
    loss_today = sum(float(e.get("max_loss_usd") or 0) for e in entries_today)
    bought_today = {e.get("symbol") for e in entries_today}
    held = {k: float(v.get("qty", 0)) for k, v in ((portfolio or {}).get("positions") or {}).items()}
    cash = _f((portfolio or {}).get("cash"))
    budget = float(cfg["budget"])
    buffer_usd = budget * cfg["cash_buffer_pct"] / 100.0
    held_value = sum(held[k] * float(((portfolio or {}).get("positions") or {})[k].get("cost") or 0)
                     for k in held)
    spendable = (cash if cash is not None else budget - held_value) - buffer_usd
    orders_count = len(placed)
    seen_batch = set()
    out = []
    for i, o in enumerate(orders, 1):
        reasons, warns = [], []
        sym = (o.get("symbol") or "").upper()
        side = o.get("side")
        pid = L.product_id(sym) if sym else ""
        typ = o.get("type")
        qty, notional = _f(o.get("qty")), _f(o.get("notional"))
        plan = o.get("plan") or {}
        # ---- format
        if not sym or side not in ("buy", "sell"):
            reasons.append("format: needs a symbol and a side (buy or sell)")
        if (qty is None) == (notional is None):
            reasons.append("format: give exactly one of qty or notional")
        elif (qty is not None and qty <= 0) or (notional is not None and notional <= 0):
            reasons.append("format: the amount must be above zero")
        if typ not in ("market", "limit", "stop_limit"):
            reasons.append("format: type must be market, limit or stop_limit (Alpaca crypto)")
        if typ in ("limit", "stop_limit") and _f(o.get("limit_price")) is None:
            reasons.append("format: a %s order needs a limit_price" % typ)
        if typ == "stop_limit" and _f(o.get("stop_price")) is None:
            reasons.append("format: a stop_limit order needs a stop_price")
        if o.get("time_in_force") not in ("gtc", "ioc"):
            reasons.append("format: time_in_force must be gtc or ioc for crypto")
        # ---- asset
        base, _, quote = pid.partition("-")
        if "/" not in sym or quote != "USD":
            reasons.append("asset: %r is not a crypto pair quoted in USD (like BTC/USD)" % sym)
        elif base in STABLE:
            reasons.append("asset: %s is a stablecoin" % base)
        if cfg.get("allowed") and pid not in [L.product_id(x) for x in cfg["allowed"]]:
            reasons.append("asset: %s is not on your allowed list" % pid)
        m = (meta or {}).get(pid)
        if m and (m.get("trading_disabled") or m.get("status") not in (None, "online", "unknown")):
            reasons.append("asset: %s is not trading on Coinbase (%s)" % (pid, m.get("status")))
        # ---- price used
        fresh = None
        row = (prices or {}).get(pid)
        if row and now_t - int(row.get("time", 0)) <= L.FRESH_SECONDS:
            fresh = float(row["price"])
        if typ in ("limit", "stop_limit") and _f(o.get("limit_price")):
            px = _f(o.get("limit_price"))
        else:
            cands = [x for x in (_f(plan.get("entry")), fresh) if x]
            px = max(cands) if cands else None
        amount = qty if qty is not None else ((notional or 0) / px if px else None)
        # ---- short / exit
        is_exit = side == "sell" and amount is not None and amount <= held.get(pid, 0) + 1e-12
        if side == "sell" and not is_exit:
            reasons.append("short: selling %s %s but you hold %s; spot crypto cannot go short"
                           % (L.fmt_qty(amount or 0), pid, L.fmt_qty(held.get(pid, 0))))
        entry_rules = []
        if side == "buy":
            fee_pct = max(float(plan.get("fee_pct") or 0), float(cfg["fee_pct"] or 0))
            if fresh is None and typ == "market":
                warns.append("no fresh price (under 15 minutes) for %s: checked at the plan's entry; "
                             "run crypto-alerts quote %s --write first" % (pid, pid))
            stop, target = _f(plan.get("stop")), _f(plan.get("target"))
            if fresh is not None and stop is not None and fresh <= stop:
                entry_rules.append("stop: the price is already %s, at or below the stop %s: the setup is gone"
                                   % (L.money(fresh), L.money(stop)))
            if fresh is not None and target is not None and fresh >= target:
                entry_rules.append("target: the price is already %s, at or above the target %s"
                                   % (L.money(fresh), L.money(target)))
            if pid in [L.product_id(x) for x in cfg.get("blocked", [])]:
                entry_rules.append("blocked: %s is on your blocked list" % pid)
            if px is None or amount is None:
                entry_rules.append("price: no entry price to check against (no plan entry, no fresh price)")
            else:
                usd = amount * px
                if usd < cfg["min_order_usd"]:
                    entry_rules.append("size: %s is under min_order_usd %s" % (L.money(usd), L.money(cfg["min_order_usd"])))
                if usd > cfg["max_order_usd"]:
                    entry_rules.append("size: %s is over max_order_usd %s" % (L.money(usd), L.money(cfg["max_order_usd"])))
                pos_usd = (held.get(pid, 0) + amount) * px
                cap = budget * cfg["max_position_pct"] / 100.0
                if pos_usd > cap + 0.005:
                    entry_rules.append("position: %s would be %s, over max_position_pct %g%% (%s)"
                                       % (pid, L.money(pos_usd), cfg["max_position_pct"], L.money(cap)))
                if usd > spendable + 0.005:
                    entry_rules.append("cash: %s would dip into the cash buffer (spendable %s)"
                                       % (L.money(usd), L.money(max(0, spendable))))
                if pid in seen_batch or sym in bought_today:
                    entry_rules.append("duplicate: %s already bought %s" % (pid, "in this batch" if pid in seen_batch else "today"))
                if orders_count >= cfg["max_orders_per_day"]:
                    entry_rules.append("daily limit: %d orders placed today (max_orders_per_day)" % orders_count)
                if stop is None:
                    if cfg["require_stop"]:
                        entry_rules.append("stop: no stop in the plan and require_stop is on")
                    max_loss = None
                elif stop >= px:
                    entry_rules.append("stop: the stop %s is at or above the entry %s" % (L.money(stop), L.money(px)))
                    max_loss = None
                else:
                    fee = px * fee_pct / 100.0
                    max_loss = amount * (px - stop + fee)
                    if max_loss > cfg["max_loss_per_trade_usd"] + 0.005:
                        entry_rules.append("loss: %s at the stop (fees in) is over max_loss_per_trade_usd %s"
                                           % (L.money(max_loss), L.money(cfg["max_loss_per_trade_usd"])))
                    if target is not None:
                        rr = (target - px - fee) / (px - stop + fee)
                        if rr < cfg["min_reward_risk"]:
                            entry_rules.append("reward:risk: %.2f after fees, under min_reward_risk %.2f"
                                               % (rr, cfg["min_reward_risk"]))
                    if loss_today + max_loss > cfg["max_daily_loss_usd"] + 0.005:
                        entry_rules.append("daily loss: %s already at risk today + %s is over max_daily_loss_usd %s"
                                           % (L.money(loss_today), L.money(max_loss), L.money(cfg["max_daily_loss_usd"])))
                if len(entries_today) >= cfg["max_trades_per_day"]:
                    entry_rules.append("trades: %d entries today (max_trades_per_day)" % len(entries_today))
                mins = L.utc(now_t).hour * 60 + L.utc(now_t).minute
                if cfg.get("no_entries_before") and mins < L.hhmm(cfg["no_entries_before"]):
                    entry_rules.append("window: before no_entries_before %s UTC" % cfg["no_entries_before"])
                if cfg.get("no_entries_after") and mins > L.hhmm(cfg["no_entries_after"]):
                    entry_rules.append("window: after no_entries_after %s UTC" % cfg["no_entries_after"])
        if is_exit:
            warns += entry_rules
        else:
            reasons += entry_rules
        v = {"index": i, "symbol": sym, "side": side, "fingerprint": L.fingerprint(o),
             "verdict": "BLOCK" if reasons else "PASS", "reasons": reasons, "warnings": warns,
             "kind": "exit" if is_exit else "entry", "checked_at": L.stamp(now_t), "date": day}
        if side == "buy" and not reasons:
            seen_batch.add(pid)
            loss_today += max_loss or 0
            spendable -= amount * px
            held[pid] = held.get(pid, 0) + amount
            orders_count += 1
        out.append(v)
    return out


def cmd(a):
    cfg, found = L.load_config(a.out)
    orders = L.read_json(a.orders or L.path(a.out, "orders.json"))
    if not orders:
        print("check.py: no orders in %s. Run /crypto-budget first." % (a.orders or L.path(a.out, "orders.json")))
        return 1
    now_t = L.ts(L.now_utc(a.now))
    meta = {}
    if not a.offline:
        for o in orders:
            pid = L.product_id(o.get("symbol") or "")
            meta[pid] = L.product_meta(pid, a.out)
    verdicts = check_orders(orders, cfg, portfolio=L.read_json(L.path(a.out, "portfolio.json")),
                            prices=L.read_json(L.path(a.out, "prices.json"), {}),
                            broker=L.read_json(L.path(a.out, "state", "broker.json")), now_t=now_t, meta=meta)
    if a.json:
        print(json.dumps(verdicts, indent=2))
    else:
        if not found:
            print("No %s: checking against the defaults." % L.path(a.out, "config.json"))
        for v, o in zip(verdicts, orders):
            print("#%d %s %s %s %s: %s" % (v["index"], o.get("side"), o.get("qty") or o.get("notional"),
                                           v["symbol"], o.get("type"), v["verdict"]))
            for r in v["reasons"]:
                print("    BLOCK  " + r)
            for w in v["warnings"]:
                print("    note   " + w + (" (an exit is never blocked by this)" if v["kind"] == "exit" else ""))
        print("A PASS is a rules check, not a recommendation.")
    if not a.no_write:
        L.write_json(L.path(a.out, "state", "risk.json"), {"checked_at": L.stamp(now_t), "verdicts": verdicts})
    return 0 if all(v["verdict"] == "PASS" for v in verdicts) else 1


def main(argv=None):
    p = argparse.ArgumentParser(description="Crypto pre-trade risk check.")
    p.add_argument("--orders")
    p.add_argument("--now")
    p.add_argument("--offline", action="store_true", help="skip the Coinbase listing check")
    p.add_argument("--out", default=L.OUT_DIR)
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-write", action="store_true")
    a = p.parse_args(argv)
    return cmd(a)


if __name__ == "__main__":
    sys.exit(main())
