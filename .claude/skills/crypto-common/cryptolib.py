"""Shared code for the crypto-* skills. Standard library only.

Every crypto skill imports this file from ../crypto-common, so keep the
folders together. All times are UTC: crypto trades 24/7 and a "day" is a UTC
day, the same day Coinbase uses for its daily candles.

Working files, in crypto/ of the project (the --out folder):

  config.json      your rules (crypto-budget/config.example.json is the template)
  watchlist.json   crypto-scanner's hits
  entry.json       crypto-entry's trigger
  plan.json        crypto-exit's entry, stop, target and hold-until time
  timemachine.json crypto-timemachine's odds
  orders.json      crypto-budget's proposed order (Alpaca place_crypto_order shape)
  prices.json      crypto-alerts' quotes
  portfolio.json   cash and coins (crypto-broker updates it on fills)
  alerts.json      crypto-alerts' rules
  state/           risk.json, broker.json, alerts.json, news.json (logs and memory)
"""

import datetime
import hashlib
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request

UTC = datetime.timezone.utc
CB = "https://api.exchange.coinbase.com"
YAHOO_HOSTS = ("https://query2.finance.yahoo.com", "https://query1.finance.yahoo.com")
UA = "Mozilla/5.0 (compatible; testbase-crypto-skills/0.1)"
OUT_DIR = "crypto"
PAUSE = 0.12
FRESH_SECONDS = 15 * 60

DEFAULTS = {
    "budget": 1000,
    "cash_buffer_pct": 10,
    "max_position_pct": 50,
    "max_order_usd": 500,
    "min_order_usd": 10,
    "max_loss_per_trade_usd": 10,
    "max_daily_loss_usd": 30,
    "max_trades_per_day": 3,
    "max_orders_per_day": 10,
    "min_reward_risk": 1.0,
    "require_stop": True,
    "fee_pct": 0.0,
    "hold_hours": 24,
    "no_entries_before": None,
    "no_entries_after": None,
    "min_stop_pct": 0.2,
    "blocked": [],
    "allowed": [],
    "broker": "alpaca",
    "paper": True,
    "allow_margin": False,
    "allow_short": False,
}


# ---------------------------------------------------------------- clock

def now_utc(text=None):
    """'2026-11-07 09:30' (UTC) -> aware datetime; None -> the real clock."""
    if not text:
        return datetime.datetime.now(UTC)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(text, fmt).replace(tzinfo=UTC)
        except ValueError:
            pass
    raise SystemExit("--now wants 'YYYY-MM-DD HH:MM' in UTC, got %r" % text)


def ts(dt):
    return int(dt.timestamp())


def utc(t):
    return datetime.datetime.fromtimestamp(t, UTC)


def stamp(t):
    return utc(t).strftime("%Y-%m-%d %H:%M UTC")


def parse_stamp(text):
    """'2026-11-07 09:30 UTC' -> epoch seconds."""
    return ts(datetime.datetime.strptime(text.replace(" UTC", ""), "%Y-%m-%d %H:%M").replace(tzinfo=UTC))


def hhmm(text, flag="time"):
    try:
        h, m = text.split(":")
        h, m = int(h), int(m)
        if 0 <= h < 24 and 0 <= m < 60:
            return h * 60 + m
    except (ValueError, AttributeError):
        pass
    raise SystemExit("%s wants HH:MM (UTC), got %r" % (flag, text))


# ---------------------------------------------------------------- http

def _sleep(s):
    time.sleep(s)


def get_text(url, timeout=20, headers=None):
    """GET with a retry after 5 s on 429 and after 2 s on a 5xx (twice at most)."""
    h = {"User-Agent": UA}
    h.update(headers or {})
    for attempt in range(3):
        req = urllib.request.Request(url, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if attempt < 2 and (e.code == 429 or e.code >= 500):
                _sleep(5 if e.code == 429 else 2)
                continue
            raise
    raise RuntimeError("unreachable")


def get_json(url, timeout=20):
    return json.loads(get_text(url, timeout, {"Accept": "application/json"}))


# ---------------------------------------------------------------- market data

def cb_products():
    return get_json(CB + "/products")


def cb_product(pid):
    return get_json("%s/products/%s" % (CB, urllib.parse.quote(pid)))


def cb_stats():
    return get_json(CB + "/products/stats")


def cb_ticker(pid):
    """-> (price, time epoch) of the last trade on Coinbase."""
    d = get_json("%s/products/%s/ticker" % (CB, urllib.parse.quote(pid)))
    if "price" not in d:
        raise RuntimeError(d.get("message") or "no price")
    t = d.get("time") or ""
    try:
        when = ts(datetime.datetime.strptime(t[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC))
    except ValueError:
        when = int(time.time())
    return float(d["price"]), when


def cb_candles(pid, gran, start, end, progress=None):
    """Candles in [start, end) (epoch seconds), 300 a request, oldest first.
    Each bar: (t, open, high, low, close, volume); t is the bar's start."""
    out = {}
    step = 300 * gran
    a, n = start, 0
    while a < end:
        b = min(end, a + step)
        q = urllib.parse.urlencode({"granularity": gran,
                                    "start": utc(a).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                    "end": utc(b).strftime("%Y-%m-%dT%H:%M:%SZ")})
        rows = get_json("%s/products/%s/candles?%s" % (CB, urllib.parse.quote(pid), q))
        if isinstance(rows, dict):
            raise RuntimeError(rows.get("message") or "Coinbase error")
        for t, lo, hi, op, cl, v in rows:
            out[int(t)] = (int(t), float(op), float(hi), float(lo), float(cl), float(v))
        a, n = b, n + 1
        if progress and n % 10 == 0:
            progress("  %d requests" % n)
        if a < end:
            _sleep(PAUSE)
    return [out[k] for k in sorted(out) if start <= k < end]


def yahoo_candles(pid, gran, start, end):
    interval = {86400: "1d", 3600: "60m", 300: "5m", 60: "1m"}.get(gran)
    if not interval:
        raise RuntimeError("Yahoo has no %d-second bars" % gran)
    q = urllib.parse.urlencode({"period1": start, "period2": end, "interval": interval})
    last = None
    for host in YAHOO_HOSTS:
        try:
            doc = get_json("%s/v8/finance/chart/%s?%s" % (host, urllib.parse.quote(pid), q))
            break
        except Exception as e:  # noqa: BLE001 - try the other host
            last = e
    else:
        raise RuntimeError("Yahoo: %s" % last)
    res = ((doc.get("chart") or {}).get("result") or [None])[0]
    if not res or not res.get("timestamp"):
        raise RuntimeError("Yahoo: no data for %s" % pid)
    qd = res["indicators"]["quote"][0]
    out = {}
    for i, t in enumerate(res["timestamp"]):
        o, h, l, c, v = (qd[k][i] for k in ("open", "high", "low", "close", "volume"))
        if None in (o, h, l, c) or int(t) % gran:
            continue
        if start <= t < end:
            out[int(t)] = (int(t), float(o), float(h), float(l), float(c), float(v or 0))
    return [out[k] for k in sorted(out)]


def candles(pid, gran, start, end, progress=None):
    """Coinbase first, Yahoo second. -> (bars, source)."""
    try:
        return cb_candles(pid, gran, start, end, progress), "coinbase"
    except Exception as e:  # noqa: BLE001
        if progress:
            progress("%s: Coinbase failed (%s), trying Yahoo" % (pid, e))
    return yahoo_candles(pid, gran, start, end), "yahoo"


def read_bars(path):
    """Offline: a JSON list of [t, open, high, low, close, volume]."""
    with open(path) as f:
        rows = json.load(f)
    return sorted((int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]))
                  for r in rows)


def complete(bars, gran, now_t):
    """Only bars on the grid that have closed by now_t."""
    return [b for b in bars if b[0] % gran == 0 and b[0] + gran <= now_t]


# ---------------------------------------------------------------- files

def path(out, *parts):
    return os.path.join(out, *parts)


def read_json(p, default=None):
    try:
        with open(p) as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def write_json(p, doc):
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(doc, f, indent=2)
    os.replace(tmp, p)


def load_config(out):
    """crypto/config.json over the defaults. -> (config, found?)."""
    raw = read_json(path(out, "config.json"))
    cfg = dict(DEFAULTS)
    if raw:
        cfg.update(raw)
    return cfg, raw is not None


def fingerprint(order):
    """A stable hash of what an order DOES (not its notes), so a changed order is a new order."""
    keys = ("symbol", "side", "type", "qty", "notional", "limit_price", "stop_price", "time_in_force")
    core = {k: order.get(k) for k in keys}
    core["plan_stop"] = (order.get("plan") or {}).get("stop")
    return hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()[:16]


# ---------------------------------------------------------------- names and numbers

def alpaca_symbol(pid):
    """Coinbase BTC-USD -> Alpaca BTC/USD."""
    return pid.replace("-", "/")


def product_id(sym):
    """BTC/USD or btc-usd or BTC -> BTC-USD."""
    s = sym.strip().upper().replace("/", "-")
    return s if "-" in s else s + "-USD"


def money(x):
    if x is None:
        return "-"
    neg = x < 0
    x = abs(x)
    if x >= 1000:
        s = "$" + format(round(x, 2), ",.2f")
    elif x >= 1 or x == 0:
        s = "$%.2f" % x
    else:
        digits = 4 - int(math.floor(math.log10(x))) - 1
        s = "$%.*f" % (max(2, digits), x)
    return "-" + s if neg else s


def round_price(x, inc, down):
    """Round a price to the product's tick (quote_increment), down or up."""
    if not inc:
        inc = 10 ** -(8 if x < 1 else 2)
    n = x / inc
    n = math.floor(n + 1e-9) if down else math.ceil(n - 1e-9)
    dec = max(0, -int(math.floor(math.log10(inc))))
    return round(n * inc, dec)


def floor_qty(q, inc):
    """Floor a coin amount to the product's base_increment."""
    if not inc:
        inc = 1e-8
    dec = max(0, -int(math.floor(math.log10(inc))))
    return round(math.floor(q / inc + 1e-9) * inc, dec)


def fmt_qty(q):
    s = ("%.8f" % q).rstrip("0").rstrip(".")
    return s or "0"


def product_meta(pid, out=None):
    """quote_increment and base_increment for a pair, cached in crypto/state/products.json."""
    cache_p = path(out or OUT_DIR, "state", "products.json")
    cache = read_json(cache_p, {}) or {}
    if pid in cache:
        return cache[pid]
    try:
        d = cb_product(pid)
        meta = {"quote_increment": float(d.get("quote_increment") or 0.01),
                "base_increment": float(d.get("base_increment") or 1e-8),
                "status": d.get("status"), "trading_disabled": bool(d.get("trading_disabled"))}
    except Exception:  # noqa: BLE001 - offline or blocked: safe generic ticks
        return {"quote_increment": None, "base_increment": 1e-8, "status": "unknown"}
    cache[pid] = meta
    try:
        write_json(cache_p, cache)
    except OSError:
        pass
    return meta


SAFETY = ("Education and tooling, not financial advice. Crypto trades 24/7, can move 10 % in "
          "minutes and can gap through a stop.")
