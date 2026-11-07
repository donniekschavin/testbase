---
name: crypto-alerts
description: >-
  Crypto Price Alerts. Rings when a coin hits a price, your stop, your target,
  a percent move in 24 hours, or a time (like the plan's hold-until deadline,
  since crypto never closes). Turns the trade plan into three alerts in one
  go, rings each once so you are not spammed (or re-arms when asked), fetches
  free Coinbase quotes (Yahoo as the fallback) and writes crypto/prices.json
  for sizing and the risk check. Use when the user says "alert me when BTC
  hits", "watch my crypto stop", "tell me if SOL moves 5%", "remind me to get
  out by", "get me a price on ETH", or right after /crypto-exit writes a plan.
---

# crypto-alerts

The crypto version of `/trader-alerts`. Crypto moves while you sleep, so the
alerts are how the plan reaches you.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/alerts.py" quote BTC-USD ETH-USD --write    # -> crypto/prices.json
python3 "${CLAUDE_SKILL_DIR}/alerts.py" quote --holdings --write
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --from-plan                 # stop, target, hold-until
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --product BTC-USD --below 74000
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --product BTC-USD --above 80000 --rearm
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --product SOL-USD --pct 5 --direction down
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --at "2026-11-08 01:05" --label "out by"
python3 "${CLAUDE_SKILL_DIR}/alerts.py" check                            # rings what hit, once
python3 "${CLAUDE_SKILL_DIR}/alerts.py" list
python3 "${CLAUDE_SKILL_DIR}/alerts.py" reset btc-usd-below-74000        # or: reset all
```

## Rules

| type | rings when |
| --- | --- |
| `above` / `target` | the price is at or above the level |
| `below` / `stop` | the price is at or below the level |
| `pct_move` | the price moved `pct` % or more from 24 hours ago (up, down or both); once a UTC day |
| `time` | the UTC clock passed `at`; once |

A price alert rings ONCE and then stays quiet until reset, unless it was
added with `--rearm` (it re-arms when the price crosses back).

## Files

| file | what |
| --- | --- |
| `crypto/alerts.json` | the rules |
| `crypto/state/alerts.json` | what has rung |
| `crypto/prices.json` | quotes, written by `quote --write` and by `check` (crypto-budget and crypto-risk read it) |
| `crypto/plan.json` | read by `add --from-plan` |

## Steps

1. After `/crypto-exit`: `add --from-plan`.
2. Run `check` on a schedule while a trade is open (every few minutes; in a
   cloud session, a scheduled task or `/loop`). Say each ring in one line.
3. On the stop, the target or hold-until: point to `/crypto-broker flatten`,
   and remind the user to cancel the open stop order first. Never sell on
   the alert alone.
4. Before a market order: `quote PAIR --write`, so `/crypto-risk` checks a
   fresh price.

## Data and limits

Quotes are Coinbase's last trade (and its 24-hour open for `pct_move`), free
and delayed. They are for alerts and checks, never for timing an order. An
alert only rings when `check` runs: it is not a stop order.

## Safety

- Education and tooling, not financial advice.
- An alert is not a stop. The stop that protects the trade is the order at the
  broker (`/crypto-broker protect`).
