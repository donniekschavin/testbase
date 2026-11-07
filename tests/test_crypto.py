"""Offline tests for crypto-scanner and crypto-timemachine (synthetic candles, no network).

    python3 -m unittest discover -s tests -v
"""

import datetime
import importlib.util
import os
import random
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UTC = datetime.timezone.utc


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


scan = load("crypto_scan", ".claude/skills/crypto-scanner/scan.py")
tm = load("crypto_tm", ".claude/skills/crypto-timemachine/timemachine.py")

DAY0 = int(datetime.datetime(2026, 9, 1, tzinfo=UTC).timestamp())


def daily_bars(closes):
    return [(DAY0 + i * 86400, c, c * 1.01, c * 0.99, c, 1000.0) for i, c in enumerate(closes)]


def walk_5m(days, seed=1, drift=0.0, vol=0.002, start=100.0):
    rnd = random.Random(seed)
    out, p = [], start
    for i in range(days * 288):
        o = p
        c = o * (1 + drift + rnd.gauss(0, vol))
        h = max(o, c) * (1 + abs(rnd.gauss(0, vol / 2)))
        lo = min(o, c) * (1 - abs(rnd.gauss(0, vol / 2)))
        out.append((DAY0 + i * 300, o, h, lo, c, 1.0))
        p = c
    return out


class TestUniverse(unittest.TestCase):
    def test_filters(self):
        prods = [
            {"id": "BTC-USD", "base_currency": "BTC", "quote_currency": "USD", "status": "online"},
            {"id": "BTC-EUR", "base_currency": "BTC", "quote_currency": "EUR", "status": "online"},
            {"id": "OLD-USD", "base_currency": "OLD", "quote_currency": "USD", "status": "delisted",
             "trading_disabled": True},
            {"id": "USDT-USD", "base_currency": "USDT", "quote_currency": "USD", "status": "online"},
            {"id": "EURC-USD", "base_currency": "EURC", "quote_currency": "USD", "status": "online",
             "fx_stablecoin": True},
            {"id": "AUC-USD", "base_currency": "AUC", "quote_currency": "USD", "status": "online",
             "auction_mode": True},
        ]
        keep, dropped = scan.build_universe(prods)
        self.assertEqual(keep, [("BTC-USD", "BTC")])
        self.assertEqual(dropped["stablecoin"], 2)


class TestDailyRules(unittest.TestCase):
    def test_breakout(self):
        tags, _ = scan.find_setups([100.0 + (i % 3) for i in range(40)] + [110.0])
        self.assertIn("breakout_20d", tags)

    def test_oversold(self):
        tags, nums = scan.find_setups([100.0 * 0.98 ** i for i in range(40)])
        self.assertIn("oversold", tags)
        self.assertLess(nums["rsi"], 30)

    def test_oversold_bounce(self):
        closes = [100.0 * 0.98 ** i for i in range(40)]
        tags, _ = scan.find_setups(closes + [closes[-1] * 1.01])
        self.assertIn("oversold_bounce", tags)

    def test_bull_flag(self):
        closes = [100.0] * 25 + [100.0 + 2 * i for i in range(1, 11)] + [120.0, 121, 120.5, 121.5, 121]
        self.assertIn("bull_flag", scan.find_setups(closes)[0])

    def test_today_left_out(self):
        bars = daily_bars([100.0] * 40)
        now = datetime.datetime.fromtimestamp(bars[-1][0] + 3600, UTC)  # 1 hour into the last day
        self.assertEqual(len(scan.complete_daily(bars, now)), 39)

    def test_scan_daily_counts(self):
        now = datetime.datetime.fromtimestamp(DAY0 + 60 * 86400, UTC)
        data = {"A-USD": daily_bars([100.0 + (i % 3) for i in range(40)] + [110.0]),
                "B-USD": daily_bars([100.0] * 10), "C-USD": None}
        hits, counts = scan.scan_daily(data, now)
        self.assertEqual(counts, {"fetched": 2, "short": 1, "scanned": 1})
        self.assertEqual(hits[0]["product"], "A-USD")


class TestOpeningRange(unittest.TestCase):
    def setUp(self):
        self.start = DAY0
        self.rng_end = DAY0 + 3600
        bars = []
        for i in range(24):  # 2 hours of 5-minute bars, range 99..101 for the first hour
            t = DAY0 + i * 300
            c = 100.0 if i < 12 else (100.5 if i < 15 else 101.5)
            bars.append((t, 100.0, 101.0 if i < 12 else c + 0.2, 99.0, c, 1.0))
        self.bars = bars

    def test_hit_on_first_close_above(self):
        r = scan.orb_hit(self.bars, self.start, self.rng_end, DAY0 + 7200)
        self.assertTrue(r["hit"])
        self.assertEqual(r["range_high"], 101.0)
        self.assertEqual(r["bar_close_utc"], "01:20")  # bar 15 (01:15) closes at 01:20

    def test_incomplete_bar_does_not_count(self):
        r = scan.orb_hit(self.bars, self.start, self.rng_end, DAY0 + 15 * 300 + 120)
        self.assertFalse(r["hit"])

    def test_thin_range(self):
        r = scan.orb_hit(self.bars[2:], self.start, self.rng_end, DAY0 + 7200)
        self.assertIn("reason", r)

    def test_window_too_early(self):
        now = datetime.datetime(2026, 11, 7, 0, 30, tzinfo=UTC)
        self.assertIsInstance(scan.orb_window(now, 0, 60), str)

    def test_window_uses_yesterday_before_session(self):
        now = datetime.datetime(2026, 11, 7, 10, 0, tzinfo=UTC)
        start, _, cutoff = scan.orb_window(now, 13 * 60 + 30, 30)
        self.assertEqual(scan.utc(start), datetime.datetime(2026, 11, 6, 13, 30, tzinfo=UTC))
        self.assertEqual(scan.utc(cutoff), datetime.datetime(2026, 11, 7, 10, 0, tzinfo=UTC))


class TestTimeMachine(unittest.TestCase):
    def test_fill_gaps_flat(self):
        bars = [(0, 1, 1, 1, 10.0, 1), (900, 11, 11, 11, 11.0, 1)]
        out = tm.fill_gaps(bars)
        self.assertEqual([b[0] for b in out], [0, 300, 600, 900])
        self.assertEqual(out[1][1:5], (10.0, 10.0, 10.0, 10.0))

    def test_reproducible_and_counts(self):
        bars = walk_5m(30)
        entry_t = bars[-1][0] + 300
        e = bars[-1][4]
        a = tm.time_machine(bars, e, e * 0.99, e * 1.02, entry_t, 12, replays=2000)
        b = tm.time_machine(bars, e, e * 0.99, e * 1.02, entry_t, 12, replays=2000)
        self.assertEqual(a["counts"], b["counts"])
        self.assertEqual(sum(a["counts"].values()), 2000)
        self.assertAlmostEqual(a["R"], 2.0)
        self.assertEqual(sum(a["history"].values()), 29)  # one per past day that ends before entry

    def test_drift_moves_the_odds(self):
        up = walk_5m(30, seed=3, drift=0.0004)
        down = walk_5m(30, seed=3, drift=-0.0004)
        res = []
        for bars in (up, down):
            e = bars[-1][4]
            res.append(tm.time_machine(bars, e, e * 0.98, e * 1.02, bars[-1][0] + 300, 24, replays=2000))
        self.assertGreater(res[0]["pct"]["target"], res[1]["pct"]["target"])
        self.assertIn("target", res[0]["lean"])
        self.assertIn("stop", res[1]["lean"])

    def test_fee_raises_breakeven(self):
        bars = walk_5m(25)
        e = bars[-1][4]
        a = tm.time_machine(bars, e, e * 0.99, e * 1.01, bars[-1][0] + 300, 6, replays=500)
        b = tm.time_machine(bars, e, e * 0.99, e * 1.01, bars[-1][0] + 300, 6, replays=500, fee_pct=0.5)
        self.assertAlmostEqual(a["breakeven_share"], 0.5)
        self.assertAlmostEqual(b["breakeven_share"], 0.75, places=6)  # fee 0.5R: 1.5 / 2
        doc = dict(a, lean="close")
        self.assertEqual(tm.verdict(doc), "Close to a coin flip.")
        self.assertEqual(tm.verdict(dict(b, lean="close")), "Close to break-even.")

    def test_refuses_bad_plans(self):
        bars = walk_5m(25)
        e = bars[-1][4]
        t = bars[-1][0] + 300
        with self.assertRaises(ValueError):
            tm.time_machine(bars, e, e * 1.01, e * 1.02, t, 6, replays=10)
        with self.assertRaises(ValueError):
            tm.time_machine(bars, e, e * 0.99, e * 0.995, t, 6, replays=10)
        with self.assertRaises(ValueError):
            tm.time_machine(walk_5m(5), e, e * 0.99, e * 1.02, DAY0 + 5 * 86400, 6, replays=10)

    def test_stop_checked_first(self):
        pool = [[(1.0, 1.05, 0.95, 1.0)] for _ in range(tm.SLOTS)]
        counts, _, _ = tm.simulate(pool, 100.0, 97.0, 103.0, 0, 5, replays=50)
        self.assertEqual(counts["stop"], 50)


if __name__ == "__main__":
    unittest.main()
