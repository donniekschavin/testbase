---
name: crypto-broker
description: >-
  Crypto Order Executor. Sends approved crypto orders to your broker, paper
  trading by default, never without your yes. Shows each order as a plain
  ticket plus the exact arguments for Alpaca's place_crypto_order, records
  your yes word for word, then Claude's own Allow once / Deny card asks
  again. Since Alpaca crypto has no bracket orders, it builds the stop-loss
  as its own stop_limit order after the buy fills (protect), builds the sell
  that closes the trade by your hold-until time or at the target (flatten),
  records fills and logs each trade's max loss so crypto-risk can hold the
  daily limit. Covers setting up Alpaca's MCP server for crypto (paper by
  default, keys never in chat) and setting order tools to "Needs approval".
  Use when the user says "buy the BTC", "place the crypto order", "execute",
  "set my stop at the broker", "sell my SOL", "get me out", "close the
  crypto position", or after /crypto-risk passes.
argument-hint: "[order number]"
---

# crypto-broker

The crypto version of `/trader-broker`, and the only crypto skill that can
lead to a real order, so it is the strictest. An order reaches the market only
after three gates, every time, for every order:

1. **crypto-risk passed this exact order today** (matched by fingerprint).
2. **The user typed an explicit yes for this one order** in the chat.
3. **The user clicked Allow once** on Claude's own permission card, because
   the order tool is set to "Needs approval".

No yes, no order.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/ticket.py" show
python3 "${CLAUDE_SKILL_DIR}/ticket.py" approve --index 1 --reply "yes"
python3 "${CLAUDE_SKILL_DIR}/ticket.py" result --index 1 --status placed --broker-id ID --filled-qty 5 --filled-price 100.02 --fee 0.25
python3 "${CLAUDE_SKILL_DIR}/ticket.py" protect --product SOL-USD          # the stop, after the buy fills
python3 "${CLAUDE_SKILL_DIR}/ticket.py" flatten --product SOL-USD          # get out
python3 "${CLAUDE_SKILL_DIR}/ticket.py" fill --product SOL-USD --side sell --qty 5 --price 104 --fee 0.26
python3 "${CLAUDE_SKILL_DIR}/ticket.py" log
```

`ticket.py` never talks to a broker. It renders tickets, checks that a reply
is a real yes for that order, builds the stop and flatten tickets, and keeps
the log in `crypto/state/broker.json`.

## Setup: Alpaca (official MCP server)

Alpaca's own server (github.com/alpacahq/alpaca-mcp-server) has a
`place_crypto_order` tool. Its arguments, checked against its source on
2026-11-07: `symbol` ("BTC/USD"), `side`, `qty` or `notional`, `type`
("market", "limit", "stop_limit"), `time_in_force` ("gtc" or "ioc"; crypto
has no "day"), `limit_price`, `stop_price`, `client_order_id`. Set it up the
same way as in `/trader-broker` (Claude Desktop config, **paper** keys typed
into the config file, never into the chat; `ALPACA_PAPER_TRADE` true), with
the crypto toolsets enabled, then set the permissions:

- `place_crypto_order`: **Needs approval**. Never Always allow.
- `cancel_order_by_id`, `replace_order_by_id`, `close_position`: Needs approval.
- `close_all_positions`, `cancel_all_orders`, options and stock order tools:
  Blocked unless the user has a reason and says so.
- read-only tools (account, positions, orders, crypto quotes): Always allow is fine.

Alpaca does not list every coin Coinbase does. If Alpaca refuses a pair, say
so; do not route it anywhere else. In Claude Code, keep the tool on ask:
`"permissions": {"ask": ["mcp__alpaca__place_crypto_order"]}`.

## Steps: the entry

1. `ticket.py show`. Only a READY ticket goes to the user. Say whether the
   account is PAPER or LIVE.
2. Show the ticket in plain words: buy how much of which coin, market or
   limit, the stop and target in the plan, the max loss at the stop with
   fees, and that the stop is NOT in this order (Alpaca crypto has no brackets).
3. Ask: "Do you want me to place this order? Reply yes to place it." Wait.
4. `ticket.py approve --index N --reply "<their words>"`. It refuses "ok",
   "sure", "yes to all", a yes naming another coin or amount, and anything
   not READY. On a refusal, ask again for that one order.
5. Call `place_crypto_order` with exactly the arguments `approve` printed
   (they include a `client_order_id`, so a retry cannot double the order).
   Claude's Allow once / Deny card appears; the user decides.
6. `ticket.py result` with placed / denied / failed, the broker's order id,
   and the fill if known.

## Steps: the stop (right after the buy fills)

7. `ticket.py protect --product PAIR`. It writes a `stop_limit` sell for the
   filled amount at the plan's stop, with the limit 1 % under it
   (`--slip-pct`). Say plainly: if the price falls through the limit too, the
   stop does NOT fill, and the loss can be larger than planned.
8. `/crypto-risk` (an exit always passes), then steps 1 to 6 for the stop.
9. `/crypto-alerts add --from-plan` for the target and the hold-until time.

## Steps: getting out

10. At the target, at hold-until, or whenever the user wants out: first
    cancel the open stop order (`cancel_order_by_id`, Needs approval, the
    user's yes), because the broker holds those coins for it. Then
    `ticket.py flatten --product PAIR`, `/crypto-risk`, and steps 1 to 6.
11. Record the sell's fill (`result` or `fill`).

## Rules

- One order, one yes. Never batch, never infer a yes, never place an order
  the user did not see as a ticket.
- Never call `place_crypto_order` for an order that is not READY, and never
  change its arguments after the yes.
- Never ask for, read, store or repeat API keys or passwords. If the user
  pastes a key, tell them to delete the message and make new keys.
- Never call `close_all_positions` or `cancel_all_orders` on its own.

## Safety

- Education and tooling, not financial advice. Most people who day trade lose money.
- Paper trading by default (`"paper": true`). Going live is the user's own decision.
- Long only, spot only: no leverage, margin, futures or shorting.
