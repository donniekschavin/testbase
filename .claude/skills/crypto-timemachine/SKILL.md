---
name: crypto-timemachine
description: >-
  Crypto Time Machine. Replays a planned crypto trade before you risk a
  dollar: 10,000 simulated runs of the next N hours (24 by default) built
  from the coin's own 5-minute Coinbase candles over the last 60 days, drawn
  by time of day, plus the same entry, stop and target on every past day at
  the same UTC time. Prints the odds of target first, stop first or neither,
  how long each took, where the price ends, the average R after your fee, the
  history and one honest verdict. Long only. Use when the user says "run the
  time machine on BTC", "what are the odds on this crypto trade", "simulate
  this coin", "backtest SOL", "monte carlo ETH", or after /crypto-scanner
  finds a chart.
---

# crypto-timemachine

The crypto version of `/trader-timemachine`. Before you risk a dollar it
replays the next hours of a trade 10,000 times from the coin's own recent
5-minute candles, and re-runs the same entry, stop and target on every past
day at the same time. It tells you the honest odds. It is a simulation, not a
prediction.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --product BTC-USD --stop-pct 1.5 --target-r 2
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --product SOL-USD --entry 90.02 --stop 88.50 --target 93.06
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --product ETH-USD --stop-pct 2 --hours 8 --fee-pct 1.2 --write
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --product BTC-USD --stop-pct 1 --at "2026-11-06 14:00"
```

| flag | meaning |
| --- | --- |
| `--product` | the Coinbase pair, e.g. `BTC-USD` (required) |
| `--entry` | entry price (default: the last completed 5-minute close) |
| `--stop` / `--stop-pct` | stop price, or N % below the entry (one is required) |
| `--target` / `--target-r` | target price, or N times the risk (default 2R) |
| `--hours` | how long each replay runs (default 24); crypto has no close |
| `--at` | entry time, `YYYY-MM-DD HH:MM` UTC (default: now) |
| `--fee-pct` | your round-trip fee in % of the entry (default 0) |
| `--days`, `--replays`, `--seed`, `--window` | 60, 10,000, 19, 2 |
| `--write` | save `crypto/timemachine.json` |
| `--json`, `--offline FILE` | machine output; read saved candles instead |

## How it works

1. Fetch 60 days of 5-minute candles before the entry (Coinbase, 300 a
   request, about 58 requests and 15 seconds; Yahoo as the fallback).
   Coinbase leaves a bar out when nothing traded, so a missing bar is filled
   flat at the last close.
2. The pool: for each of the 288 five-minute slots of the UTC day, every past
   day's bar as ratios to the previous close.
3. A replay walks forward from the entry: each bar is drawn from the same time
   of day (plus or minus 10 minutes) and scaled to the current price. The stop
   is checked before the target in every bar, so a bar that touches both
   counts as the stop.
4. Outcomes: target first, stop first, or neither after `--hours`. R is the
   target's R, -1 at the stop, or the open result at the end, minus the fee
   in R.
5. History: the same UTC time on every past day, stop and target at the same
   % distance, walked on the real candles.

The verdict compares the target's share of the replays that hit a side with
the break-even share after fees, (1 + fee in R) / (1 + R): under 5 points
apart is "close to break-even" ("a coin flip" at 1R with no fee), 5 to 15
"leans toward", 15 or more "strongly toward".

## Fees matter

Ask the user for their round-trip fee and pass `--fee-pct`. Coinbase's taker
fees for small accounts can be well over 1 % for a round trip. With a 2 %
stop, a 1.2 % round-trip fee costs 0.6R on every trade, and a 1R target then
needs to win 80 % of the time just to break even. Say this whenever the fee
is large next to the stop.

## Example

Fri Nov 6 2026 14:00 UTC, SOL-USD at $90.25, stop 2 % below ($88.44), target
1R ($92.06), 8 hours, 1.2 % round-trip fee: target first 28.1 %, stop first
35.3 %, neither 36.6 %. Of the replays that hit a side, 44.3 % hit the target,
against 80.0 % to break even after fees. History: 13 target, 15 stop, 31
neither on 59 past days. Verdict: strongly toward the stop, and the fee is
why.

## Rules

- Always show the plan (entry, stop, target, R, hours, fee) above the odds.
- Say what data it used: the days, the source and the time range (UTC).
- Never call the odds a prediction or a promise, and never say "buy".
- If the user gives no fee, say the result ignores fees.
- Hand off: this pack has no crypto sizing, risk check or order step yet. The
  stock pack's `/trader-budget`, `/trader-risk` and `/trader-broker` do not
  handle crypto (risk blocks it on purpose). Do not route a crypto order
  through them.

## Safety

- Education and tooling, not financial advice.
- The future can do what the last 60 days never did: a listing, a hack, an
  exchange outage, a headline. Crypto can gap through a stop; a real fill can
  be worse than -1R.
- Long only, spot only: no leverage, margin, futures or shorting.
