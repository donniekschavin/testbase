---
name: crypto-budget
description: >-
  Crypto Budget Manager. Sizes every crypto position to your budget and your
  max loss per trade, fees included. Reads the plan from crypto-exit (entry,
  stop, target), finds the fractional coin amount (floored to the pair's
  increment) that fits four limits (max loss with the round-trip fee,
  position cap, max order, cash after your buffer), says which limit decided
  it, and writes ONE buy order to crypto/orders.json in the exact shape of
  Alpaca's place_crypto_order. Refuses when the stop is already hit, the
  size is under your minimum, or reward:risk after fees is under your
  minimum. Nothing is placed. Use when the user says "how much BTC should I
  buy", "size this crypto trade", "I have $1,000", "I only want to risk $10",
  "set my crypto rules", or after /crypto-exit writes a plan.
---

# crypto-budget

The crypto version of `/trader-budget`. Its one job: never let a single trade
lose more than you decided, fees included.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
cp "${CLAUDE_SKILL_DIR}/config.example.json" crypto/config.json   # once, then edit
python3 "${CLAUDE_SKILL_DIR}/size.py"                    # crypto/plan.json + crypto/config.json
python3 "${CLAUDE_SKILL_DIR}/size.py" --write            # -> crypto/orders.json
python3 "${CLAUDE_SKILL_DIR}/size.py" --limit            # a limit order at the plan's entry
python3 "${CLAUDE_SKILL_DIR}/size.py" --limit 1335 --write
```

## How much

```
coins = floor (to the pair's base_increment) of the smallest of
  max loss      max_loss_per_trade_usd / (entry - stop + entry x fee_pct / 100)
  position cap  budget x max_position_pct / entry
  max order     max_order_usd / entry
  cash          (budget - cash buffer - what you already hold) / entry
                (and no more than the cash in crypto/portfolio.json)
```

`fee_pct` is your round-trip fee in % of the entry, counted in the loss at
the stop: a bigger fee means a smaller position. The entry it sizes at is the
limit price, or for a market order the plan's entry or a fresh price from
`crypto/prices.json` (under 15 minutes old) when that is higher.

Refused, no order written: the fresh price is already at or below the stop;
the size is under `min_order_usd`; reward:risk after fees is under
`min_reward_risk`.

## The config (`crypto/config.json`)

| key | default | meaning |
| --- | --- | --- |
| `budget` | 1000 | the money for crypto trading |
| `cash_buffer_pct` | 10 | always kept in cash |
| `max_position_pct` | 50 | most of the budget in one coin |
| `max_order_usd` / `min_order_usd` | 500 / 10 | order size bounds |
| `max_loss_per_trade_usd` | 10 | loss at the stop, fees in |
| `max_daily_loss_usd` | 30 | today's entries' max losses together (crypto-risk) |
| `max_trades_per_day` / `max_orders_per_day` | 3 / 10 | per UTC day (crypto-risk) |
| `min_reward_risk` | 1.0 | after fees |
| `fee_pct` | 0.5 in the example | your round-trip fee; check your exchange's fee tier |
| `min_stop_pct` | 0.2 | tightest stop crypto-exit accepts |
| `hold_hours` | 24 | the plan's deadline |
| `no_entries_before` / `no_entries_after` | none | an entry window, HH:MM UTC |
| `blocked` / `allowed` | [] | pairs never / only to trade |
| `broker`, `paper` | alpaca, true | paper trading by default |

## The order

```json
{"symbol": "SOL/USD", "side": "buy", "type": "market", "qty": "5", "time_in_force": "gtc",
 "intent": "entry", "plan": {"entry": 100, "stop": 98, "target": 104, "max_loss_usd": 10}}
```

Alpaca crypto orders cannot be brackets. The stop goes in as its own
`stop_limit` sell after the buy fills (`/crypto-broker protect`), and the
target is watched by `/crypto-alerts`. Tell the user this before they approve.

## Steps

1. If there is no `crypto/config.json`, ask for the budget, the max loss per
   trade and the round-trip fee, and write it from the example.
2. `size.py`. Say the amount, the dollars, which limit decided it, and the
   loss at the stop with fees.
3. `--write`, then `/crypto-risk`. Nothing has been placed.

## Safety

- Education and tooling, not financial advice. Never size up to "make it back".
- Paper trading by default. Going live is the user's own decision, in their own config.
- No leverage, margin or shorting.
