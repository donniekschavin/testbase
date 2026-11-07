---
name: crypto-exit
description: >-
  Crypto Exit Planner. Sets your stop and your target BEFORE you enter, so
  you know when to get out. Reads the entry from crypto-entry (or a price you
  give), puts the stop at the opening-range midpoint by default (or the range
  low, your price, a percent, or a multiple of the 5-minute ATR), rounds it
  to the pair's tick, sets the target at 2R (or 1R, 1.5R, or your price), and
  sets a hold-until deadline since crypto never closes. Shows the fee in R.
  Refuses a stop at or above the entry, a target at or below it, or a stop
  too tight for the spread and fees. Writes crypto/plan.json for the Time
  Machine, the Budget Manager and the alerts. Long only. Use when the user
  says "where's my stop on BTC", "set my crypto stop and target", "plan the
  exit", "risk reward on this coin", or right after /crypto-entry triggers.
---

# crypto-exit

The crypto version of `/trader-exit`. The plan is made before the entry, so
the exit is never decided in the heat of the moment.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan                                  # from crypto/entry.json: or-mid, 2R
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --stop or-low --target 1.5R --write
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --product BTC-USD --entry 75900 --stop pct:1.5 --write
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --stop atr:2 --target price:93
python3 "${CLAUDE_SKILL_DIR}/exit.py" show
```

## Stops and targets

| stop | where |
| --- | --- |
| `or-mid` | the opening-range midpoint (default for an orb entry) |
| `or-low` | the opening-range low |
| `price:X` | your price |
| `pct:X` | X % under the entry |
| `atr:K` | K times the 14-bar ATR of the 5-minute candles before the entry |

A stop rounds DOWN to the pair's price tick (Coinbase `quote_increment`), a
target rounds UP. Targets: `2R` (default), `1R`, `1.5R` ... or `price:X`.

Refused, with the reason: a stop at or above the entry, a target at or below
it, a stop closer than `min_stop_pct` (default 0.2 %) of the price, an entry
that has not triggered (unless you give `--entry`).

## Hold-until and fees

Crypto never closes, so the plan gets a deadline: `hold_until` = the entry
time + `hold_hours` (default 24, in `crypto/config.json`). Out by then, win
or lose. `/crypto-alerts add --from-plan` rings at that time.

With `fee_pct` set (your ROUND-TRIP fee in % of the entry), the plan shows the
fee in R and the reward:risk after fees. A 0.5 % round trip on a 0.73 % stop
is 0.68R: a 2R target becomes 0.78 after fees, and `/crypto-risk` will block
it under `min_reward_risk`. Say so plainly: on a tight stop, fees eat the trade.

## Steps

1. After `/crypto-entry` triggers: `exit.py plan`. Show entry, stop, target,
   R, fee in R and hold-until.
2. If the user wants a different stop or target, re-run with `--stop` /
   `--target`. Never move a stop further away to make the size fit.
3. `--write`, then `/crypto-timemachine`, then `/crypto-budget`.

## Safety

- Education and tooling, not financial advice.
- A stop is a plan, not a guarantee: crypto can gap through it, and a
  stop_limit at the broker does not fill below its limit.
- Long only, spot only: no leverage, margin or shorting.
