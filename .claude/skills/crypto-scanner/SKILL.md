---
name: crypto-scanner
description: >-
  Crypto Chart Scanner. Scans every tradable Coinbase USD pair for setups:
  20-day closing-high breakouts, bull flags, a reclaimed 20-day average,
  oversold and oversold bounces on UTC daily closes, plus an opening-range
  breakout scan on 5-minute candles from a session start you choose (00:00 UTC
  by default, since crypto trades 24/7). Stablecoins and delisted pairs are
  left out, thin pairs are filtered by 24-hour USD volume, and the hits go to
  crypto/watchlist.json. Free Coinbase public data, Yahoo as the fallback. Use
  when the user says "scan crypto", "find crypto setups", "what coin is
  breaking out", "oversold coins", "crypto watchlist", "scan Coinbase", or
  wants the trader-scanner for crypto instead of stocks.
---

# crypto-scanner

The crypto version of `/trader-scanner`. It reads free Coinbase charts and
lists the ones that match a rule. A scan is a list of charts that match a
rule, not a list of coins to buy, and a setup is not a prediction. Crypto is
more volatile than stocks and trades around the clock. Most people who day
trade lose money; the scanner does not change that.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/scan.py" universe                          # -> crypto/universe.txt
python3 "${CLAUDE_SKILL_DIR}/scan.py" daily                             # UTC daily closes -> crypto/watchlist.json
python3 "${CLAUDE_SKILL_DIR}/scan.py" daily --products BTC-USD,ETH-USD,SOL-USD
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb                               # range = first 60 min after 00:00 UTC
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb --session 13:30 --or-minutes 30   # range from the US stock open
```

Flags: `--min-usd-volume` (24-hour USD volume floor, default 1,000,000),
`--limit N` (only the N most traded), `--now "2026-11-07 09:30"` (UTC) to pin
the clock, `--show N`, `--json`, `--no-write`, `--out DIR` (default
`crypto/`). Exit code 0 when the scan found something, 1 when it found
nothing or could not run (the reason is one plain line).

## Data

All free, no key, no account:

| what | from |
| --- | --- |
| the pairs | `api.exchange.coinbase.com/products` |
| 24-hour volume of every pair | `api.exchange.coinbase.com/products/stats` (one request) |
| daily and 5-minute candles | `api.exchange.coinbase.com/products/<ID>/candles`, 300 a request |
| fallback candles | Yahoo Finance chart, same names (`BTC-USD`) |

The cloud environment must allow `api.exchange.coinbase.com` (and the Yahoo
hosts for the fallback). Coinbase's public data can lag or rate-limit; the
tool pauses between requests and retries once on a 429.

## The universe

`universe` keeps a Coinbase pair when it is quoted in USD, online, not
trading-disabled, not cancel-only or in auction, and not a stablecoin
(Coinbase's `fx_stablecoin` flag, plus USDT, USDC, DAI, PYUSD, EURC and
others by name). On Nov 7 2026 that kept 401 of 846 products.

## The daily scan

A day is a UTC day, the same day Coinbase uses for its daily candles, so the
daily close is the price at 00:00 UTC. Today's still-forming candle is left
out. The rules are the same as trader-scanner's:

| setup | the rule on closes |
| --- | --- |
| `breakout_20d` | the last close is above every close of the 20 days before it |
| `bull_flag` | up more than 10 % over the 10 days before the last 5, then the last 5 closes inside a 5 % range |
| `reclaim_ma20` | the close before was under its 20-day average, the last close is above it |
| `oversold` | RSI 14 (Wilder) under 30 |
| `oversold_bounce` | RSI 14 was under 30 the day before and the last close is up |

Hits are listed most traded first (24-hour USD volume). Only pairs with at
least 30 days of candles are scanned. On Sat Nov 7 2026, 41 of the 401 pairs
had $1M+ of 24-hour volume, and 7 matched a rule.

## The opening-range breakout scan

Crypto has no opening bell, so the "session" starts at `--session` (UTC,
default 00:00) and the opening range is the first `--or-minutes` (default 60).
Range high = the highest high of the range bars, low = the lowest low. A hit
is the first COMPLETED 5-minute bar after the range that closes above the
range high. A pair missing any range bar (nothing traded) is counted as too
thin. Before the range plus one bar is done it says so and scans nothing;
before today's `--session` it uses yesterday's.

## Steps

1. Now and then: `scan.py universe`.
2. `scan.py daily`. Tell the user the counts (pairs, liquid, scanned, hits)
   and the top few by setup.
3. Intraday: `scan.py orb`, with the session the user cares about. Say how
   many usable charts broke their range and when; a later hit is closer to
   the price now.
4. The user picks one chart. Hand it on: `/crypto-news PAIR` (what is moving
   it), then `/crypto-entry PAIR` (the entry bar by bar). Never pick for them.

The whole crypto chain, one trade:

```
crypto-scanner -> crypto-news -> crypto-entry -> crypto-exit -> crypto-timemachine
  -> crypto-budget -> crypto-risk -> crypto-broker (buy, then protect = the stop)
crypto-alerts: stop, target, hold-until (while it is open)
```

## Rules

- Say what was scanned: how many pairs, how many were liquid, how many
  charts came back, and the time of the data (UTC).
- Say "matched a rule", never "a buy", "a winner" or "a good trade".
- Never print a P&L, a return or a profit figure.
- A hit is stale once the price has moved on. Re-run before acting on it.

## What it never does

It never places, sizes or checks an order, never says which coin to buy,
never calls the data real time, and never promises that a setup works. The
stock pack's `/trader-risk` and `/trader-broker` block crypto on purpose;
crypto orders go through `/crypto-risk` and `/crypto-broker` only.

## Safety

- Education and tooling, not financial advice.
- Crypto can move 10 % in minutes, trades through weekends and holidays, and
  can gap through a stop on news, a hack or an exchange outage.
- Never ask for, read or repeat exchange API keys in the chat.
