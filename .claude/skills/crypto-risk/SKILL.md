---
name: crypto-risk
description: >-
  Crypto Risk Manager. Checks every crypto order against your limits and
  stops anything over them before it can reach the broker. For an entry: a
  stop is required, the loss at the stop with fees must fit your max loss
  per trade, reward:risk after fees must meet your minimum, the day's total
  risk must fit your daily loss limit, no more than your trades per day, no
  buy when the price has already gone through the stop, and an optional UTC
  entry window. Basics: crypto pairs quoted in USD only, no stablecoins, your
  blocked and allowed lists, order size, position cap, cash buffer, no short
  sales, Alpaca crypto order format (market, limit, stop_limit; gtc or ioc),
  duplicates and a daily order limit. Getting out is never blocked. Prints
  PASS or BLOCK with the reason and records the verdicts so crypto-broker
  only shows an order that passed. Use when the user says "check my crypto
  order", "is this safe", "risk check", "can I take this trade", or before
  /crypto-broker, always.
---

# crypto-risk

The crypto version of `/trader-risk`, and the gate in front of the broker.
Every order goes through it, every time. A PASS is a rules check, not a
recommendation.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/check.py"                          # crypto/orders.json -> crypto/state/risk.json
python3 "${CLAUDE_SKILL_DIR}/check.py" --now "2026-11-07 10:00" # pin the clock (UTC)
python3 "${CLAUDE_SKILL_DIR}/check.py" --json
```

## What it reads

| file | what |
| --- | --- |
| `crypto/orders.json` | the proposed orders (crypto-budget, or protect / flatten) |
| `crypto/config.json` | your limits (see crypto-budget) |
| `crypto/portfolio.json` | cash and coins |
| `crypto/prices.json` | fresh quotes from crypto-alerts (under 15 minutes old count) |
| `crypto/state/broker.json` | what was placed today (UTC) |

## What blocks

Every order: **format** (one of qty or notional, type market / limit /
stop_limit with the prices it needs, time_in_force gtc or ioc), **asset**
(a USD crypto pair like `BTC/USD`, not a stablecoin, on your `allowed` list
if you keep one, trading on Coinbase), **short** (selling more than you hold).

An entry (a buy), on top: **blocked**, **size** (min / max order),
**position** (max_position_pct), **cash** (the buffer), **duplicate** (same
pair twice in the batch or already bought today), **daily limit** (orders
today), **stop** (required; below the entry; a fresh price not already
through it), **loss** (amount x (entry - stop + fee) over the max; the fee is
the higher of the plan's and the config's; the entry is the limit price, or
the higher of the plan entry and a fresh price), **reward:risk** (after
fees), **daily loss** (today's entries' max losses plus this one), **trades**
(entries today), **window** (`no_entries_before` / `no_entries_after`, UTC).

An exit (a sell that only reduces what you hold) is checked for format, asset
and short sales only: getting out is never blocked, and the other rules are
shown as notes.

Orders are checked in file order as if each PASS had filled, so two buys that
are fine one by one but break a limit together are caught. Days are UTC days.

## Steps

1. After `/crypto-budget --write` (or `protect` / `flatten`): `check.py`.
2. Read each verdict to the user with the reasons. On a BLOCK, do not look
   for a way around it: change the plan (a closer stop is NOT a fix for a
   loss that is too big; a smaller size is), or skip the trade.
3. With no fresh price, it says so: run `/crypto-alerts quote PAIR --write`
   and check again before a market order.
4. Only a PASS goes on to `/crypto-broker`.

## Safety

- Education and tooling, not financial advice.
- Never edit `crypto/state/risk.json` by hand, and never change a limit in
  the config to turn a BLOCK into a PASS without the user asking for that
  change in plain words.
