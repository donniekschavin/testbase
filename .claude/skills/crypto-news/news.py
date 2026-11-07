#!/usr/bin/env python3
"""News monitor for crypto-news. Standard library only.

Watches headlines and the exchange's own status page for the coins you
watch or hold, prints only what is new since the last check, newest first,
with how far each coin moved in 24 hours and tags on what tends to move it.

    python3 news.py                              # watchlist + plan + portfolio coins
    python3 news.py --products BTC-USD SOL-USD
    python3 news.py --products ZEC-USD --all --hours 72   # everything in 3 days, seen or not
    python3 news.py --no-status                  # skip the Coinbase status page

Your coins, when --products is not given: every hit in crypto/watchlist.json
(crypto-scanner), the pair in crypto/plan.json (crypto-exit) and the
positions in crypto/portfolio.json.

Sources (free RSS, no key):
  - Yahoo Finance headlines per coin:
      https://feeds.finance.yahoo.com/rss/2.0/headline?s=<PAIR>&region=US&lang=en-US
  - CoinDesk and Cointelegraph, all stories, kept when they name your coin
    (its ticker, like ZEC, or its name, like Zcash, from Coinbase's currency list):
      https://www.coindesk.com/arc/outboundfeeds/rss
      https://cointelegraph.com/rss
  - Coinbase's status page: incidents and maintenance (an outage or a
    paused coin matters when your stop sits at the exchange):
      https://status.coinbase.com/history.rss
  - The move: Coinbase 24-hour stats (last price against 24 hours ago).

Tags (by keyword): hack, listing, delisting, etf, regulatory, macro,
liquidation, upgrade, unlock, outage, partnership, price.

Times print in UTC. crypto/state/news.json remembers what you have seen (30
days), so an item shows once. --offline DIR reads yahoo-<PAIR>.xml,
coindesk.xml, cointelegraph.xml, status.xml, currencies.json and stats.json
from DIR instead. Headlines are leads, not facts: open the story before
acting, and treat nothing here as advice.
"""

import argparse
import datetime
import email.utils
import hashlib
import html
import os
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "crypto-common"))
import cryptolib as L  # noqa: E402

YAHOO = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%s&region=US&lang=en-US"
FEEDS = {"coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss",
         "cointelegraph": "https://cointelegraph.com/rss"}
STATUS = "https://status.coinbase.com/history.rss"
KEEP_DAYS = 30

TAGS = [
    ("hack", r"\b(hack(ed|er|s)?|exploit(ed)?|drain(ed)?|stolen|breach|attack(er)?)\b"),
    ("delisting", r"\b(delist(s|ed|ing)?|suspend(s|ed)? trading)\b"),
    ("listing", r"\b(lists?|listed|listing|launch(es|ed)? trading|adds? support)\b"),
    ("etf", r"\b(etf|etfs|etp)\b"),
    ("regulatory", r"\b(sec|cftc|lawsuit|sues?|sued|regulat\w*|ban(s|ned)?|court|doj|sanction\w*|mica|compliance)\b"),
    ("macro", r"\b(fed|fomc|cpi|inflation|rate (cut|hike)s?|treasury|jobs report|tariffs?|recession)\b"),
    ("liquidation", r"\b(liquidat\w*|short squeeze|whales?|leverage)\b"),
    ("upgrade", r"\b(upgrade|hard fork|fork|mainnet|testnet|halving)\b"),
    ("unlock", r"\b(token unlock|unlocks?|vesting|airdrop)\b"),
    ("outage", r"\b(outage|degraded|maintenance|disabled|delayed|paused|halt(ed)?|incident)\b"),
    ("partnership", r"\b(partner(s|ship)?|acquir\w*|merger|deal)\b"),
    ("price", r"\b(rall(y|ies)|surg(e|es|ed)|plung(e|es|ed)|soar(s|ed)?|crash(es|ed)?|tumbl\w*|record high|all-time high|ath)\b"),
]
TAG_RE = [(t, re.compile(p, re.I)) for t, p in TAGS]


def tags_for(text):
    return [t for t, rx in TAG_RE if rx.search(text)]


def strip_html(s):
    s = html.unescape(s or "")
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def parse_rss(text, source):
    """-> [{"id", "title", "link", "time", "summary", "source"}]."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    out = []
    for it in root.iter("item"):
        title = strip_html(it.findtext("title"))
        link = (it.findtext("link") or "").strip()
        pub = it.findtext("pubDate")
        try:
            t = int(email.utils.parsedate_to_datetime(pub).timestamp()) if pub else None
        except (TypeError, ValueError):
            t = None
        guid = (it.findtext("guid") or link or title).strip()
        out.append({"id": hashlib.sha1((source + guid).encode()).hexdigest()[:16], "title": title,
                    "link": link, "time": t, "summary": strip_html(it.findtext("description"))[:400],
                    "source": source})
    return out


def coin_matcher(base, name):
    """Ticker (case-sensitive, 3+ letters) or the coin's name (case-insensitive)."""
    parts = []
    if len(base) >= 3:
        parts.append(r"(?<![A-Za-z$])\$?%s(?![A-Za-z])" % re.escape(base))
    rx_t = re.compile("|".join(parts)) if parts else None
    rx_n = re.compile(r"\b%s\b" % re.escape(name), re.I) if name and len(name) >= 3 else None

    def match(text):
        return bool((rx_t and rx_t.search(text)) or (rx_n and rx_n.search(text)))
    return match


def collect(coins, names, fetch, hours, now_t, status=True):
    """Pure given fetch(kind, key) -> text|None. -> list of items with "coins" and "tags"."""
    since = now_t - int(hours * 3600)
    items = {}

    def keep(it, coin_list):
        if it["time"] is not None and it["time"] < since:
            return
        if it["time"] is not None and it["time"] > now_t + 86400 and it["source"] != "coinbase-status":
            return
        cur = items.setdefault(it["id"], dict(it, coins=[]))
        for c in coin_list:
            if c not in cur["coins"]:
                cur["coins"].append(c)

    for pid in coins:
        for it in parse_rss(fetch("yahoo", pid) or "", "yahoo"):
            keep(it, [pid])
    matchers = {pid: coin_matcher(pid.split("-")[0], names.get(pid.split("-")[0])) for pid in coins}
    for src in FEEDS:
        for it in parse_rss(fetch("feed", src) or "", src):
            hit = [pid for pid, m in matchers.items() if m(it["title"] + " " + it["summary"])]
            if hit:
                keep(it, hit)
    if status:
        for it in parse_rss(fetch("status", "status") or "", "coinbase-status"):
            hit = [pid for pid, m in matchers.items() if m(it["title"])]
            it["exchange"] = True
            keep(it, hit)
    out = []
    for it in items.values():
        it["tags"] = tags_for(it["title"] + " " + it["summary"])
        if it.get("exchange") and "outage" not in it["tags"]:
            it["tags"].append("outage")
        out.append(it)
    out.sort(key=lambda x: -(x["time"] or 0))
    return out


def coins_from_files(out):
    pids = set()
    wl = L.read_json(L.path(out, "watchlist.json")) or {}
    pids |= {h["product"] for h in wl.get("hits", [])[:20]}
    plan = L.read_json(L.path(out, "plan.json")) or {}
    if plan.get("product"):
        pids.add(plan["product"])
    pf = L.read_json(L.path(out, "portfolio.json")) or {}
    pids |= set((pf.get("positions") or {}).keys())
    return sorted(pids)


def make_fetch(a):
    if a.offline:
        def fetch(kind, key):
            name = {"yahoo": "yahoo-%s.xml" % key, "feed": "%s.xml" % key, "status": "status.xml"}[kind]
            p = os.path.join(a.offline, name)
            return open(p).read() if os.path.exists(p) else None
        return fetch

    def fetch(kind, key):
        url = {"yahoo": lambda: YAHOO % key, "feed": lambda: FEEDS[key], "status": lambda: STATUS}[kind]()
        try:
            text = L.get_text(url, timeout=20)
        except Exception as e:  # noqa: BLE001
            print("  %s: could not read (%s)" % (url.split("/")[2], e), file=sys.stderr)
            return None
        L._sleep(L.PAUSE)
        return text
    return fetch


def coin_names(a):
    if a.offline:
        p = os.path.join(a.offline, "currencies.json")
        rows = L.read_json(p, []) or []
    else:
        cache = L.path(a.out, "state", "currencies.json")
        rows = L.read_json(cache)
        if not rows:
            try:
                rows = L.get_json(L.CB + "/currencies")
                L.write_json(cache, rows)
            except Exception:  # noqa: BLE001
                rows = []
    return {r["id"]: r.get("name") for r in rows if r.get("id")}


def moves(a, coins):
    stats = L.read_json(os.path.join(a.offline, "stats.json")) if a.offline else None
    if stats is None and not a.offline:
        try:
            stats = L.cb_stats()
        except Exception:  # noqa: BLE001
            stats = {}
    out = {}
    for pid in coins:
        s = ((stats or {}).get(pid) or {}).get("stats_24hour") or {}
        try:
            out[pid] = (float(s["last"]), (float(s["last"]) / float(s["open"]) - 1) * 100)
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            pass
    return out


def cmd(a):
    coins = [L.product_id(p) for p in a.products] if a.products else coins_from_files(a.out)
    if not coins:
        print("news.py: no coins. Give --products BTC-USD, or run /crypto-scanner first.")
        return 1
    now_t = L.ts(L.now_utc(a.now))
    items = collect(coins, coin_names(a), make_fetch(a), a.hours, now_t, status=not a.no_status)
    st_p = L.path(a.out, "state", "news.json")
    seen = L.read_json(st_p, {}) or {}
    seen = {k: v for k, v in seen.items() if v > now_t - KEEP_DAYS * 86400}
    new = items if a.all else [i for i in items if i["id"] not in seen]
    print("News for %s, last %g hours, as of %s." % (", ".join(coins), a.hours, L.stamp(now_t)))
    if not a.no_moves:
        mv = moves(a, coins)
        if mv:
            print("24-hour moves: " + ", ".join("%s %s (%+.2f%%)" % (pid, L.money(p), ch)
                                                 for pid, (p, ch) in sorted(mv.items())))
    if not new:
        print("Nothing new%s." % ("" if a.all else " since the last check (--all shows everything)"))
    for it in new[:a.max]:
        when = L.stamp(it["time"]) if it["time"] else "time unknown"
        if it["time"] and it["time"] > now_t:
            when = "SCHEDULED " + when
        coin = ", ".join(it["coins"]) or "exchange-wide"
        tg = (" [" + ", ".join(it["tags"]) + "]") if it["tags"] else ""
        print("- %s  %s  (%s; %s)%s" % (when, it["title"], it["source"], coin, tg))
        if it["link"]:
            print("    " + it["link"])
    if len(new) > a.max:
        print("... and %d more (--max N)." % (len(new) - a.max))
    for it in items:
        seen[it["id"]] = now_t
    if not a.no_write:
        L.write_json(st_p, seen)
    print("Headlines are leads, not facts: open the story before acting.")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Crypto news monitor.")
    p.add_argument("--products", nargs="+")
    p.add_argument("--hours", type=float, default=24)
    p.add_argument("--all", action="store_true", help="show seen items too")
    p.add_argument("--max", type=int, default=25)
    p.add_argument("--no-status", action="store_true")
    p.add_argument("--no-moves", action="store_true")
    p.add_argument("--no-write", action="store_true")
    p.add_argument("--now")
    p.add_argument("--offline")
    p.add_argument("--out", default=L.OUT_DIR)
    a = p.parse_args(argv)
    return cmd(a)


if __name__ == "__main__":
    sys.exit(main())
