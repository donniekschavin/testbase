---
name: crypto-news
description: >-
  Crypto News Monitor. Tracks breaking news on every coin you watch or hold:
  Yahoo Finance headlines per coin, CoinDesk and Cointelegraph stories that
  name the coin, and Coinbase's own status page (outages, paused coins,
  maintenance), plus each coin's 24-hour move. Shows only what is new since
  the last check, newest first, in UTC, tags each item (hack, listing,
  delisting, etf, regulatory, macro, liquidation, upgrade, unlock, outage,
  partnership, price) and never repeats one. Use when the user says "any
  news on BTC", "why is SOL moving", "crypto news on my watchlist", "is
  Coinbase down", "did anything break in crypto", or after /crypto-scanner
  finds setups.
---

# crypto-news

The crypto version of `/trader-news`. Coins move on headlines, hacks,
listings, regulators and exchange outages. This shows what is new, and what
it might be about. Headlines are leads, not facts.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/news.py"                                  # watchlist + plan + portfolio coins
python3 "${CLAUDE_SKILL_DIR}/news.py" --products BTC-USD SOL-USD
python3 "${CLAUDE_SKILL_DIR}/news.py" --products ZEC-USD --all --hours 72
python3 "${CLAUDE_SKILL_DIR}/news.py" --no-status --no-moves
```

## Sources

| source | what |
| --- | --- |
| `feeds.finance.yahoo.com` | Yahoo headlines per coin (`BTC-USD`) |
| `www.coindesk.com`, `cointelegraph.com` | all stories, kept when they name the coin (ticker like `ZEC`, or name like Zcash, from Coinbase's currency list) |
| `status.coinbase.com` | incidents and scheduled maintenance; exchange-wide ones show for every check |
| `api.exchange.coinbase.com` | the 24-hour move per coin |

The cloud environment must allow these hosts. Yahoo's per-coin feed mixes in
stories about mining stocks and the market: say which items are really about
the coin.

## What it shows

Only items new since the last check (`crypto/state/news.json` remembers 30
days; `--all` shows everything). Newest first, UTC. A future Coinbase
maintenance shows as SCHEDULED: it matters if a stop is at the exchange then.

## Steps

1. Before an entry: `news.py --products PAIR`. Sum it up in a few lines: what
   is new, which tags, and whether anything is exchange-wide.
2. Flag what can move the coin hard: a hack, a delisting, a regulator, an
   outage, a token unlock. A trade into one of those is a different trade.
3. Then `/crypto-entry PAIR`. Never decide for the user.

## Safety

- Education and tooling, not financial advice. A headline is not a reason to
  buy or sell: open the story first.
- Crypto news is full of rumours and paid promotion. Treat anything from a
  single unknown source with care, and say so.
