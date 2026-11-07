"""Offline tests for crypto-entry, -exit, -budget, -risk, -broker, -alerts and -news.

    python3 -m unittest discover -s tests -v
"""

import datetime
import importlib.util
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UTC = datetime.timezone.utc
sys.path.insert(0, os.path.join(ROOT, ".claude/skills/crypto-common"))
import cryptolib as L  # noqa: E402


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


entry = load("c_entry", ".claude/skills/crypto-entry/entry.py")
exitp = load("c_exit", ".claude/skills/crypto-exit/exit.py")
budget = load("c_budget", ".claude/skills/crypto-budget/size.py")
risk = load("c_risk", ".claude/skills/crypto-risk/check.py")
broker = load("c_broker", ".claude/skills/crypto-broker/ticket.py")
alerts = load("c_alerts", ".claude/skills/crypto-alerts/alerts.py")
news = load("c_news", ".claude/skills/crypto-news/news.py")

DAY = int(datetime.datetime(2026, 11, 7, tzinfo=UTC).timestamp())
CFG = dict(L.DEFAULTS, budget=1000, max_loss_per_trade_usd=10, max_order_usd=500, max_position_pct=50,
           cash_buffer_pct=10, fee_pct=0.0, min_reward_risk=1.0, max_daily_loss_usd=30)


def bars_5m(closes, start=DAY, hi_pad=0.1, lo_pad=0.1):
    return [(start + i * 300, c, c + hi_pad, c - lo_pad, c, 10.0) for i, c in enumerate(closes)]


class TestEntry(unittest.TestCase):
    def setUp(self):
        # 12 range bars around 100 (high 100.5), then 101 closes from bar 15 on
        self.bars = bars_5m([100.0] * 12 + [100.3, 100.4, 100.2] + [101.0] * 5, hi_pad=0.5)

    def test_waiting_while_range_forms(self):
        r = entry.evaluate(self.bars, DAY + 1800, DAY, 300)
        self.assertEqual(r["status"], "waiting")

    def test_trigger_on_first_close_above_high(self):
        r = entry.evaluate(self.bars, DAY + 20 * 300, DAY, 300)
        self.assertEqual(r["status"], "triggered")
        self.assertEqual(r["or_high"], 100.5)  # the first 12 bars (60 minutes): 100 + 0.5
        self.assertEqual(r["trigger_time"], "2026-11-07 01:20 UTC")
        self.assertEqual(r["price"], 101.0)

    def test_open_bar_does_not_count(self):
        r = entry.evaluate(self.bars, DAY + 15 * 300 + 60, DAY, 300)
        self.assertEqual(r["status"], "waiting")

    def test_no_data_when_range_missing(self):
        r = entry.evaluate(self.bars[3:], DAY + 20 * 300, DAY, 300)
        self.assertEqual(r["status"], "no-data")

    def test_level(self):
        r = entry.evaluate(self.bars, DAY + 20 * 300, DAY, 300, setup="level", level=100.35)
        self.assertEqual(r["status"], "triggered")
        self.assertEqual(r["price"], 100.4)

    def test_expired_after_cutoff(self):
        r = entry.evaluate(self.bars, DAY + 20 * 300, DAY, 300, no_after=60 + 10)  # 01:10 UTC
        self.assertEqual(r["status"], "expired")


class TestExit(unittest.TestCase):
    def test_or_mid_and_2r(self):
        p, why = exitp.make_plan(101.0, "or-mid", "2R", or_high=100.9, or_low=99.9, tick=0.01)
        self.assertIsNone(why)
        self.assertEqual(p["stop"], 100.4)
        self.assertEqual(p["target"], 102.2)
        self.assertAlmostEqual(p["R"], 2.0)

    def test_refuses_tight_stop(self):
        p, why = exitp.make_plan(100.0, "pct:0.1", "2R", tick=0.01)
        self.assertIsNone(p)
        self.assertIn("min_stop_pct", why)

    def test_refuses_stop_above(self):
        self.assertIsNone(exitp.make_plan(100.0, "price:101", "2R")[0])

    def test_fee_in_r(self):
        p, _ = exitp.make_plan(100.0, "pct:2", "1R", tick=0.01, fee_pct=1.0)
        self.assertAlmostEqual(p["fee_R"], 0.5)
        self.assertAlmostEqual(p["R_after_fees"], 0.5 / 1.5)

    def test_hold_until(self):
        p, _ = exitp.make_plan(100.0, "pct:2", "2R", entry_t=DAY, hold_hours=8)
        self.assertEqual(p["hold_until"], "2026-11-07 08:00 UTC")

    def test_atr(self):
        bars = [(i * 300, 100, 101, 99, 100, 1) for i in range(20)]
        self.assertAlmostEqual(exitp.atr(bars), 2.0)


PLAN = {"product": "SOL-USD", "entry": 100.0, "stop": 98.0, "target": 104.0, "fee_pct": 0.0,
        "hold_until": "2026-11-08 00:00 UTC"}


class TestBudget(unittest.TestCase):
    def test_max_loss_decides(self):
        res, why = budget.size(PLAN, CFG)
        self.assertIsNone(why)
        self.assertEqual(res["decided_by"], "max loss")
        self.assertAlmostEqual(res["qty"], 5.0)  # $10 / $2 a coin
        self.assertAlmostEqual(res["max_loss_usd"], 10.0)

    def test_fee_shrinks_position(self):
        res, _ = budget.size(PLAN, dict(CFG, fee_pct=1.0))
        self.assertAlmostEqual(res["qty"], 10 / 3.0, places=6)

    def test_cap_decides(self):
        res, _ = budget.size(PLAN, dict(CFG, max_loss_per_trade_usd=1000))
        self.assertEqual(res["decided_by"], "position cap")
        self.assertAlmostEqual(res["notional"], 500.0, places=4)

    def test_refuses_low_rr_after_fees(self):
        res, why = budget.size(PLAN, dict(CFG, fee_pct=2.0))
        self.assertIsNone(res)
        self.assertIn("reward:risk", why)

    def test_refuses_price_through_stop(self):
        res, why = budget.size(PLAN, CFG, fresh=97.5)
        self.assertIsNone(res)
        self.assertIn("setup is gone", why)

    def test_fresh_higher_price_used(self):
        res, _ = budget.size(PLAN, CFG, fresh=100.5)
        self.assertEqual(res["entry_used"], 100.5)

    def test_order_shape(self):
        res, _ = budget.size(PLAN, CFG)
        o = budget.build_order(PLAN, res)
        self.assertEqual(o["symbol"], "SOL/USD")
        self.assertEqual(o["time_in_force"], "gtc")
        self.assertEqual(o["qty"], "5")


def order(**kw):
    o = {"symbol": "SOL/USD", "side": "buy", "type": "market", "qty": "5", "time_in_force": "gtc",
         "intent": "entry", "plan": {"entry": 100.0, "stop": 98.0, "target": 104.0, "fee_pct": 0.0,
                                     "max_loss_usd": 10.0}}
    o.update(kw)
    return o


class TestRisk(unittest.TestCase):
    NOW = DAY + 3600

    def check(self, orders, **kw):
        kw.setdefault("now_t", self.NOW)
        return risk.check_orders(orders, kw.pop("cfg", CFG), **kw)

    def test_pass(self):
        v = self.check([order()])[0]
        self.assertEqual(v["verdict"], "PASS", v["reasons"])

    def test_loss_over_limit(self):
        v = self.check([order(qty="6")])[0]
        self.assertTrue(any(r.startswith("loss") for r in v["reasons"]))

    def test_fee_from_config_counts(self):
        v = self.check([order()], cfg=dict(CFG, fee_pct=1.0))[0]
        self.assertEqual(v["verdict"], "BLOCK")

    def test_daily_loss_across_batch(self):
        o2 = order(symbol="ETH/USD", qty="0.05",
                   plan={"entry": 2000.0, "stop": 1600.0, "target": 3000.0, "fee_pct": 0})
        vs = self.check([order(), o2], cfg=dict(CFG, max_daily_loss_usd=25, max_loss_per_trade_usd=30))
        self.assertEqual(vs[0]["verdict"], "PASS")
        self.assertTrue(any(r.startswith("daily loss") for r in vs[1]["reasons"]))

    def test_duplicate_in_batch(self):
        vs = self.check([order(), order(qty="4")])
        self.assertTrue(any(r.startswith("duplicate") for r in vs[1]["reasons"]))

    def test_exit_always_passes_limits(self):
        pf = {"cash": 0, "positions": {"SOL-USD": {"qty": 5, "cost": 100}}}
        sell = {"symbol": "SOL/USD", "side": "sell", "type": "market", "qty": "5", "time_in_force": "gtc"}
        v = self.check([sell], portfolio=pf, cfg=dict(CFG, max_trades_per_day=0))[0]
        self.assertEqual(v["verdict"], "PASS")
        self.assertEqual(v["kind"], "exit")

    def test_short_blocked(self):
        sell = {"symbol": "SOL/USD", "side": "sell", "type": "market", "qty": "5", "time_in_force": "gtc"}
        v = self.check([sell])[0]
        self.assertTrue(any(r.startswith("short") for r in v["reasons"]))

    def test_stablecoin_and_format(self):
        v = self.check([order(symbol="USDT/USD")])[0]
        self.assertTrue(any("stablecoin" in r for r in v["reasons"]))
        v = self.check([order(time_in_force="day")])[0]
        self.assertTrue(any("time_in_force" in r for r in v["reasons"]))
        v = self.check([order(symbol="AAPL")])[0]
        self.assertTrue(any(r.startswith("asset") for r in v["reasons"]))

    def test_fresh_price_through_stop(self):
        prices = {"SOL-USD": {"price": 97.0, "time": self.NOW - 60}}
        v = self.check([order()], prices=prices)[0]
        self.assertTrue(any("setup is gone" in r for r in v["reasons"]))

    def test_trades_per_day(self):
        b = {"events": [{"type": "placed", "intent": "entry", "date": "2026-11-07", "symbol": "X/USD",
                         "max_loss_usd": 1}] * 3}
        v = self.check([order()], broker=b)[0]
        self.assertTrue(any(r.startswith("trades") for r in v["reasons"]))


class TestBroker(unittest.TestCase):
    def setUp(self):
        self.o = order()

    def test_replies(self):
        self.assertIsNone(broker.check_reply("yes", self.o))
        self.assertIsNone(broker.check_reply("ya, beli 5 SOL", self.o))
        self.assertIsNotNone(broker.check_reply("sure", self.o))
        self.assertIsNotNone(broker.check_reply("yes to all", self.o))
        self.assertIsNotNone(broker.check_reply("yes BTC", self.o))
        self.assertIsNotNone(broker.check_reply("yes 50", self.o))
        self.assertIsNotNone(broker.check_reply("no", self.o))

    def test_tool_args_match_alpaca(self):
        args = broker.tool_args(self.o)
        self.assertEqual(set(args), {"symbol", "side", "type", "time_in_force", "qty", "client_order_id"})

    def test_ready_needs_todays_pass(self):
        fp = L.fingerprint(self.o)
        r = {"verdicts": [{"fingerprint": fp, "date": "2026-11-07", "verdict": "PASS", "reasons": []}]}
        self.assertEqual(broker.status_of(self.o, 1, r, {"events": []}, "2026-11-07")[0], "READY")
        self.assertEqual(broker.status_of(self.o, 1, r, {"events": []}, "2026-11-08")[0], "NOT CHECKED")
        changed = order(qty="4")
        self.assertEqual(broker.status_of(changed, 1, r, {"events": []}, "2026-11-07")[0], "NOT CHECKED")

    def test_fills(self):
        d = tempfile.mkdtemp()
        try:
            L.write_json(os.path.join(d, "portfolio.json"), {"cash": 1000, "positions": {}})
            broker.apply_fill(d, "SOL-USD", "buy", 5, 100, fee=1)
            pf = broker.apply_fill(d, "SOL-USD", "sell", 5, 104, fee=1)
            self.assertAlmostEqual(pf["cash"], 1018.0)
            self.assertEqual(pf["positions"], {})
            with self.assertRaises(SystemExit):
                broker.apply_fill(d, "SOL-USD", "sell", 1, 100)
        finally:
            shutil.rmtree(d)


class TestAlerts(unittest.TestCase):
    def rules(self):
        rs = []
        for r in ({"type": "stop", "product": "SOL-USD", "price": 98.0},
                  {"type": "above", "product": "SOL-USD", "price": 105.0, "rearm": True},
                  {"type": "pct_move", "product": "SOL-USD", "pct": 5},
                  {"type": "time", "at": "2026-11-07 12:00"}):
            rs, _ = alerts.add_rule(rs, r)
        return rs

    def test_rings_once(self):
        q = {"SOL-USD": {"price": 97.0, "open24h": 100.0}}
        rung, st = alerts.evaluate(self.rules(), {}, q, DAY)
        self.assertEqual([r["type"] for r, _ in rung], ["stop"])
        rung, _ = alerts.evaluate(self.rules(), st, q, DAY + 60)
        self.assertEqual(rung, [])

    def test_rearm_and_pct_and_time(self):
        rs = self.rules()
        rung, st = alerts.evaluate(rs, {}, {"SOL-USD": {"price": 106.0, "open24h": 100.0}}, DAY + 13 * 3600)
        self.assertEqual(sorted(r["type"] for r, _ in rung), ["above", "pct_move", "time"])
        _, st = alerts.evaluate(rs, st, {"SOL-USD": {"price": 104.0, "open24h": 100.0}}, DAY + 13 * 3600 + 60)
        rung, _ = alerts.evaluate(rs, st, {"SOL-USD": {"price": 106.0, "open24h": 100.0}}, DAY + 13 * 3600 + 120)
        self.assertEqual([r["type"] for r, _ in rung], ["above"])  # re-armed; pct already rang today


RSS = """<?xml version="1.0"?><rss><channel>
<item><title>%s</title><link>https://x/%d</link><guid>g%d</guid><pubDate>%s</pubDate>
<description>%s</description></item></channel></rss>"""


def rss(title, n, when, desc=""):
    return RSS % (title, n, n, datetime.datetime.fromtimestamp(when, UTC).strftime("%a, %d %b %Y %H:%M:%S +0000"), desc)


class TestNews(unittest.TestCase):
    def test_collect(self):
        now = DAY + 12 * 3600
        feeds = {
            ("yahoo", "SOL-USD"): rss("Solana rallies 8%", 1, now - 3600),
            ("feed", "coindesk"): rss("Exchange hacked, SOL drained", 2, now - 7200),
            ("feed", "cointelegraph"): rss("Ethereum upgrade ships", 3, now - 600),
            ("status", "status"): rss("Disabled Sends / Receives - SOL", 4, now - 300),
        }
        items = news.collect(["SOL-USD"], {"SOL": "Solana"}, lambda k, key: feeds.get((k, key)), 24, now)
        titles = [i["title"] for i in items]
        self.assertNotIn("Ethereum upgrade ships", titles)
        self.assertEqual(titles[0], "Disabled Sends / Receives - SOL")
        tags = {i["title"]: i["tags"] for i in items}
        self.assertIn("hack", tags["Exchange hacked, SOL drained"])
        self.assertIn("outage", tags["Disabled Sends / Receives - SOL"])
        self.assertIn("price", tags["Solana rallies 8%"])

    def test_old_items_dropped(self):
        now = DAY + 12 * 3600
        feeds = {("yahoo", "SOL-USD"): rss("Old Solana story", 1, now - 3 * 86400)}
        self.assertEqual(news.collect(["SOL-USD"], {}, lambda k, key: feeds.get((k, key)), 24, now), [])

    def test_matcher_no_false_hits(self):
        m = news.coin_matcher("ONE", "Harmony")
        self.assertFalse(m("Bitcoin is one of the best"))
        self.assertTrue(m("ONE token jumps"))


class TestLib(unittest.TestCase):
    def test_rounding(self):
        self.assertEqual(L.round_price(100.456, 0.01, down=True), 100.45)
        self.assertEqual(L.round_price(100.451, 0.01, down=False), 100.46)
        self.assertEqual(L.floor_qty(1.23456789, 0.001), 1.234)
        self.assertEqual(L.fmt_qty(5.0), "5")
        self.assertEqual(L.product_id("btc/usd"), "BTC-USD")
        self.assertEqual(L.alpaca_symbol("BTC-USD"), "BTC/USD")


if __name__ == "__main__":
    unittest.main()
