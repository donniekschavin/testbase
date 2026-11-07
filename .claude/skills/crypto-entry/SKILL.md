---
name: crypto-entry
description: >-
  Crypto Entry Timer. Watches a crypto setup bar by bar on Coinbase 5-minute
  or 1-minute candles and tells you the moment to get in: an opening-range
  breakout from a UTC session start you choose (crypto has no opening bell;
  00:00 UTC and a 60-minute range by default), or the first close above a
  level you give it, with an optional volume check. Says waiting and how far,
  triggered with the time and the price, expired, or no-data, and writes
  crypto/entry.json for /crypto-exit. Long only. It never places an order.
  Use when the user says "tell me when to buy BTC", "watch SOL", "has ETH
  broken out", "time my crypto entry", "check my crypto watchlist", or after
  /crypto-scanner and /crypto-news.
---

# crypto-entry

The crypto version of `/trader-entry`. It answers one question, bar by bar:
has the rule fired yet? A trigger is a rule firing, not a reason to buy.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/entry.py" check BTC-USD                     # orb, 5-minute candles
python3 "${CLAUDE_SKILL_DIR}/entry.py" check SOL-USD --setup level --level 92.50
python3 "${CLAUDE_SKILL_DIR}/entry.py" check ETH-USD --session 13:30 --or-minutes 30 --write
python3 "${CLAUDE_SKILL_DIR}/entry.py" check BTC-USD --interval 1m --min-volume-x 1.5
python3 "${CLAUDE_SKILL_DIR}/entry.py" watch BTC-USD --every 30 --hours 4 # one line per closed bar
python3 "${CLAUDE_SKILL_DIR}/entry.py" watchlist                           # every hit in crypto/watchlist.json
```

## The rules

- **orb**: the session starts at `--session` (UTC, default 00:00); the range
  is the high and low of the first `--or-minutes` (default 60). It triggers on
  the first COMPLETED bar after the range that CLOSES above the range high.
  A wick above it is not a trigger. Before today's session start it uses
  yesterday's session.
- **level**: the first completed bar this session that closes above `--level`
  (for example a 20-day closing high from `/crypto-scanner`).
- `--min-volume-x X`: the trigger bar also needs X times the average volume
  of the range bars.

A trigger's time is the trigger bar's close time; its price is that close. A
bar counts only once it has closed. `no_entries_after` in
`crypto/config.json` (HH:MM UTC, optional) turns a late session into
"expired". A pair missing range bars (nothing traded) is "no-data".

## Files

| file | what |
| --- | --- |
| `crypto/watchlist.json` | read by `watchlist` (crypto-scanner's hits) |
| `crypto/entry.json` | written on a trigger with `--write` (and by `watch`): price, time, range |
| `crypto/config.json` | `no_entries_after` (optional) |

## Steps

1. The user picks a pair (from `/crypto-scanner`, after `/crypto-news`).
2. `entry.py check PAIR`. Say the status in one line: waiting and how far,
   or triggered at what time and price.
3. To wait for it: `entry.py watch PAIR`, or schedule `check` every few minutes.
4. On a trigger: `check PAIR --write`, then `/crypto-exit`. Never pick the pair
   for the user, and re-check before acting: a trigger from an hour ago is stale.

## Data and limits

Coinbase public candles (Yahoo as the fallback). Free, can lag, bars not
single trades. 1-minute candles are noisier; 5-minute is the default.

## Safety

- Education and tooling, not financial advice. Crypto trades 24/7, can move
  10 % in minutes and can gap through a stop.
- It never places, sizes or checks an order. Only `/crypto-broker` can lead
  to one, after `/crypto-risk` passes it and the user says yes.
