#!/usr/bin/env python3
"""Reels format "Round 1/4 - Dulu vs Sekarang" (1080x1920, 30fps).

Isi video diambil dari config.json (nama aplikasi, 4 kebiasaan, menit, hack).
  python3 make_reel.py                      # pakai config.json di folder ini
  python3 make_reel.py --config saya.json --out reel.mp4

Butuh: Python 3, Pillow, numpy, ffmpeg.
"""
import argparse
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1080, 1920, 30
HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = "/usr/share/fonts/opentype/inter"

NAVY = (20, 33, 61)
INK = (40, 48, 72)
MUTED = (120, 130, 155)
WHITE = (255, 255, 255)
GREEN = (22, 150, 72)
GREEN_BG = (230, 248, 236)
RED = (226, 54, 64)
LIME = (200, 245, 60)
CARD = (255, 255, 255)
LINE = (215, 222, 238)


def font(weight, size):
    p = os.path.join(FONT_DIR, f"Inter-{weight}.otf")
    return ImageFont.truetype(p if os.path.exists(p) else os.path.join(FONT_DIR, "Inter-Bold.otf"), size)


from functools import lru_cache


@lru_cache(maxsize=None)
def fz(weight, size):
    return font(weight, max(4, int(size)))


F = {k: font(*v) for k, v in {
    "brand": ("ExtraBold", 34), "head": ("ExtraBold", 66), "head_l": ("Medium", 66),
    "cap": ("ExtraBold", 56), "cap_l": ("SemiBold", 56),
    "pill": ("ExtraBold", 30), "pill_s": ("Bold", 22), "total": ("ExtraBold", 44),
    "tile": ("Bold", 26), "tile_v": ("ExtraBold", 34),
    "dial": ("Black", 210), "card_t": ("ExtraBold", 40), "card_s": ("Medium", 28),
    "big": ("Black", 120), "mid": ("ExtraBold", 48), "small": ("Bold", 30),
    "row": ("Bold", 34), "row_v": ("ExtraBold", 36),
}.items()}


# ---------- utils ----------
def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def eo(t):
    t = clamp(t)
    return 1 - (1 - t) ** 3


def eb(t):
    t = clamp(t)
    return 1 + 2.70158 * (t - 1) ** 3 + 1.70158 * (t - 1) ** 2


def rgba(c, a):
    return tuple(c[:3]) + (int(clamp(a, 0, 1) * 255),)


def make_bg():
    y = np.linspace(0, 1, H)[:, None, None]
    x = np.linspace(0, 1, W)[None, :, None]
    top = np.array([226, 234, 250])
    bot = np.array([246, 248, 253])
    g = top * (1 - y) + bot * y
    blob = np.exp(-(((x - 0.15) ** 2) / 0.05 + ((y - 0.62) ** 2) / 0.02))
    blob2 = np.exp(-(((x - 0.9) ** 2) / 0.04 + ((y - 0.3) ** 2) / 0.03))
    g = g - blob * np.array([40, 25, 0]) - blob2 * np.array([25, 15, 0])
    g = np.broadcast_to(g, (H, W, 3))
    return Image.fromarray(np.clip(g, 0, 255).astype(np.uint8), "RGB")


BG = make_bg()


def shadow_card(d, box, r=34, fill=CARD, a=1.0, outline=None, width=3):
    x0, y0, x1, y1 = box
    d.rounded_rectangle([x0 + 4, y0 + 12, x1 + 4, y1 + 16], r, fill=(60, 80, 140, int(28 * a)))
    d.rounded_rectangle(box, r, fill=rgba(fill, a), outline=rgba(outline, a) if outline else None,
                        width=width)


def pill(d, cx, cy, text, f, fill, color, a=1.0, padx=26, h=None):
    tw = d.textlength(text, font=f)
    hh = h or f.size + 26
    d.rounded_rectangle([cx - tw / 2 - padx, cy - hh / 2, cx + tw / 2 + padx, cy + hh / 2], hh / 2,
                        fill=rgba(fill, a))
    d.text((cx, cy), text, font=f, fill=rgba(color, a), anchor="mm")
    return tw + 2 * padx


def strike(d, x0, x1, y, a=1.0, color=RED, w=7):
    d.line([(x0 - 6, y + 6), (x1 + 6, y - 6)], fill=rgba(color, a), width=w)


# ---------- rich text: *kata* = garis bawah, [kata] = kotak navy ----------
def tokens(s):
    out = []
    for m in re.finditer(r"\[([^\]]+)\]|\*([^*]+)\*|(\S+)", s):
        if m.group(1):
            for w in m.group(1).split():
                out.append((w, "box"))
        elif m.group(2):
            for w in m.group(2).split():
                out.append((w, "ul"))
        else:
            w = m.group(3)
            if out and re.fullmatch(r"[.,!?;:]+", w):
                out[-1] = (out[-1][0] + w, out[-1][1])
            else:
                out.append((w, "n"))
    return out


def rich(d, toks, cx, y, maxw, fb, fl, n_show=None, lh=None, a=1.0):
    """Gambar teks kaya, tengah, wrap. n_show = jumlah kata yang sudah muncul."""
    lh = lh or int(fb.size * 1.3)
    sp = d.textlength(" ", font=fb)
    lines, cur, curw = [], [], 0
    for t in toks:
        f = fb if t[1] != "n" or fl is None else fl
        w = d.textlength(t[0], font=f) + (24 if t[1] == "box" else 0)
        if cur and curw + sp + w > maxw:
            lines.append((cur, curw))
            cur, curw = [], 0
        curw += (sp if cur else 0) + w
        cur.append((t, w, f))
    if cur:
        lines.append((cur, curw))
    i = 0
    for li, (ln, lw) in enumerate(lines):
        x = cx - lw / 2
        yy = y + li * lh
        for (word, kind), w, f in ln:
            if n_show is not None and i >= n_show:
                return
            pa = a
            if n_show is not None and i == int(n_show):
                pa = a * (n_show - i)
            if kind == "box":
                d.rounded_rectangle([x, yy - 6, x + w, yy + f.size + 14], 10, fill=rgba(NAVY, pa))
                d.text((x + 12, yy), word, font=f, fill=rgba(WHITE, pa))
            else:
                d.text((x, yy), word, font=f, fill=rgba(NAVY, pa))
                if kind == "ul":
                    d.line([(x, yy + f.size + 10), (x + w, yy + f.size + 10)], fill=rgba(NAVY, pa), width=5)
            x += w + sp
            i += 1


# ---------- ikon sederhana ----------
def icon(d, kind, cx, cy, s, color, a=1.0):
    c = rgba(color, a)
    if kind == "alarm":
        d.ellipse([cx - s * .36, cy - s * .30, cx + s * .36, cy + s * .42], outline=c, width=int(s * .08))
        d.line([(cx, cy + .06 * s), (cx, cy - .14 * s)], fill=c, width=int(s * .07))
        d.line([(cx, cy + .06 * s), (cx + .14 * s, cy + .12 * s)], fill=c, width=int(s * .07))
        d.ellipse([cx - s * .44, cy - s * .44, cx - s * .18, cy - s * .2], fill=c)
        d.ellipse([cx + s * .18, cy - s * .44, cx + s * .44, cy - s * .2], fill=c)
    elif kind == "key":
        d.ellipse([cx - s * .42, cy - s * .2, cx - s * .02, cy + s * .2], outline=c, width=int(s * .09))
        d.rectangle([cx - s * .04, cy - s * .05, cx + s * .42, cy + s * .05], fill=c)
        d.rectangle([cx + s * .26, cy, cx + s * .34, cy + s * .2], fill=c)
        d.rectangle([cx + s * .36, cy, cx + s * .42, cy + s * .14], fill=c)
    elif kind == "shirt":
        d.polygon([(cx - s * .16, cy - s * .38), (cx - s * .44, cy - s * .22), (cx - s * .32, cy - s * .02),
                   (cx - s * .22, cy - s * .08), (cx - s * .22, cy + s * .4), (cx + s * .22, cy + s * .4),
                   (cx + s * .22, cy - s * .08), (cx + s * .32, cy - s * .02), (cx + s * .44, cy - s * .22),
                   (cx + s * .16, cy - s * .38), (cx, cy - s * .26)], fill=c)
    elif kind == "phone":
        d.rounded_rectangle([cx - s * .22, cy - s * .4, cx + s * .22, cy + s * .4], int(s * .08),
                            outline=c, width=int(s * .08))
        d.ellipse([cx - s * .04, cy + s * .24, cx + s * .04, cy + s * .32], fill=c)
    elif kind == "bulb":
        d.ellipse([cx - s * .3, cy - s * .42, cx + s * .3, cy + s * .16], fill=c)
        d.rounded_rectangle([cx - s * .15, cy + s * .12, cx + s * .15, cy + s * .36], int(s * .05), fill=c)
    else:  # titik
        d.ellipse([cx - s * .3, cy - s * .3, cx + s * .3, cy + s * .3], fill=c)


TILE_COLORS = [(200, 245, 60), (255, 255, 255), (238, 242, 255), (255, 255, 255)]


def tile(d, cx, top, it, idx, a=1.0, scale=1.0, dim=False, show_new=False):
    s = 190 * scale
    x0, y0 = cx - s / 2, top
    fill = TILE_COLORS[idx % 4]
    aa = a * (0.45 if dim else 1)
    shadow_card(d, [x0, y0, x0 + s, y0 + s], r=int(s * .22), fill=fill, a=aa)
    icon(d, it.get("icon", "dot"), cx, y0 + s / 2, s * .62, NAVY, aa)
    d.text((cx, y0 + s + 26), it["name"], font=F["tile"], fill=rgba(INK, aa), anchor="mm")
    if show_new:
        d.text((cx, y0 + s + 66), f"{it['new']} mnt", font=F["tile_v"], fill=rgba(GREEN, a), anchor="mm")
    else:
        v = f"{it['old']} mnt"
        d.text((cx, y0 + s + 66), v, font=F["tile_v"], fill=rgba(NAVY, aa), anchor="mm")


# ---------- avatar orisinal sederhana ----------
def avatar(d, t, talking=True):
    bob = 6 * math.sin(t * 2.2)
    cx, cy = 540, 1470 + bob
    # badan
    d.rounded_rectangle([cx - 250, cy + 150, cx + 250, cy + 600], 120, fill=(34, 46, 84))
    d.polygon([(cx - 60, cy + 150), (cx, cy + 250), (cx + 60, cy + 150)], fill=(245, 245, 250))
    # leher + kepala
    d.rectangle([cx - 50, cy + 110, cx + 50, cy + 170], fill=(236, 186, 150))
    d.ellipse([cx - 205, cy - 30, cx - 150, cy + 60], fill=(236, 186, 150))
    d.ellipse([cx + 150, cy - 30, cx + 205, cy + 60], fill=(236, 186, 150))
    d.ellipse([cx - 175, cy - 190, cx + 175, cy + 170], fill=(246, 204, 170))
    # rambut
    d.chord([cx - 190, cy - 230, cx + 190, cy + 60], 180, 360, fill=(52, 38, 34))
    for k in range(-3, 4):
        d.ellipse([cx + k * 48 - 46, cy - 150, cx + k * 48 + 46, cy - 50], fill=(52, 38, 34))
    # mata (kedip tiap ~3 detik)
    blink = (t % 3.2) < 0.12
    for ex in (-70, 70):
        if blink:
            d.line([(cx + ex - 26, cy + 20), (cx + ex + 26, cy + 20)], fill=(40, 30, 30), width=8)
        else:
            d.ellipse([cx + ex - 28, cy - 14, cx + ex + 28, cy + 50], fill=(40, 30, 30))
            d.ellipse([cx + ex - 6, cy - 4, cx + ex + 12, cy + 14], fill=WHITE)
    # pipi
    d.ellipse([cx - 135, cy + 55, cx - 85, cy + 85], fill=(250, 160, 160, 140))
    d.ellipse([cx + 85, cy + 55, cx + 135, cy + 85], fill=(250, 160, 160, 140))
    # mulut
    m = (abs(math.sin(t * 13)) * 22 + 4) if talking else 4
    d.rounded_rectangle([cx - 30, cy + 92, cx + 30, cy + 92 + m], 12, fill=(150, 60, 70))


# ---------- adegan ----------
ORD = ["Pertama", "Kedua", "Ketiga", "Keempat"]


def build(cfg):
    items = cfg["items"]
    tot_old = sum(i["old"] for i in items)
    tot_new = sum(i["new"] for i in items)
    saved = tot_old - tot_new
    app = cfg["app"]
    brand = cfg.get("brand", "LIFE HACK HARIAN")
    sc = []

    def dur_for(text, base=0.9):
        return max(1.6, len(tokens(text)) / 2.7 + base)

    def header(d):
        d.text((60, 238), brand.upper(), font=F["brand"], fill=NAVY)

    # 1. hook
    cap1 = f"Berapa menit pagimu habis buat *empat* hal ini?"

    def s1(d, lt, dur):
        header(d)
        rich(d, tokens(f"Habis *{tot_old} menit* tiap pagi?"), 540, 330, 960, F["head"], F["head_l"],
             a=eo(lt / .3))
        pill(d, 540, 470, f"TOTAL   {tot_old} menit /pagi", F["total"], WHITE, NAVY, a=eo((lt - .2) / .3))
        for k, it in enumerate(items):
            p = eb((lt - .3 - k * .12) / .4)
            if p > 0:
                tile(d, 165 + k * 250, 610 + 40 * (1 - p), it, k, a=clamp(p))
    sc.append((dur_for(cap1, 1.4), cap1, s1, [0.0, 0.3, 0.42, 0.54, 0.66]))

    # 2. twist
    cap2 = f"Padahal semuanya bisa *dipangkas*, satu hack tiap pagi."

    def s2(d, lt, dur):
        header(d)
        rich(d, tokens(f"Habis *{tot_old} menit* tiap pagi?"), 540, 330, 960, F["head"], F["head_l"])
        w = pill(d, 540, 470, f"TOTAL   {tot_old} menit /pagi", F["total"], WHITE, NAVY)
        p = eo((lt - .5) / .4)
        if p > 0:
            strike(d, 540 - w / 2 + 30, 540 - w / 2 + 30 + (w - 60) * p, 470)
        q = eb((lt - .9) / .4)
        if q > 0:
            pill(d, 540, 548, f"jadi {tot_new} menit", F["pill"], GREEN, WHITE, a=clamp(q))
        for k, it in enumerate(items):
            tile(d, 165 + k * 250, 610, it, k, dim=lt > 1.1, show_new=lt > 1.1)
    sc.append((dur_for(cap2, 1.0), cap2, s2, [0.0, 0.5, 0.9, 1.1]))

    # 3. aplikasi
    cap3 = f"Pakai *{app}*. Satu hack, cuma *30 detik*."

    def s3(d, lt, dur):
        header(d)
        p = eb(lt / .45)
        box = [140, 420 + 60 * (1 - p), 940, 820 + 60 * (1 - p)]
        shadow_card(d, box, a=clamp(p))
        d.rounded_rectangle([box[0] + 50, box[1] + 50, box[0] + 190, box[1] + 190], 32, fill=rgba(LIME, p))
        icon(d, "bulb", box[0] + 120, box[1] + 125, 110, NAVY, clamp(p))
        d.text((box[0] + 220, box[1] + 70), app, font=F["mid"], fill=rgba(NAVY, p))
        d.text((box[0] + 220, box[1] + 140), "1 life hack / hari", font=F["card_s"], fill=rgba(MUTED, p))
        pill(d, box[0] + 170, box[1] + 290, "30 detik", F["pill"], GREEN_BG, GREEN, a=clamp((lt - .5) / .3))
        pill(d, box[0] + 430, box[1] + 290, "tiap pagi", F["pill"], (238, 242, 255), NAVY,
             a=clamp((lt - .65) / .3))
    sc.append((dur_for(cap3, 1.0), cap3, s3, [0.0, 0.5, 0.65]))

    # 4. ronde
    n = len(items)
    for k, it in enumerate(items):
        capd = f"[{ORD[k] if k < 4 else 'Lalu'},] {it['name'].lower()}."

        def dial(d, lt, dur, k=k, it=it):
            header(d)
            cx, cy, r = 540, 630, 200
            pill(d, cx, 330, f"ROUND {k + 1} / {n}", F["pill_s"], WHITE, NAVY, padx=22, h=46)
            d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(205, 214, 236), width=6)
            p = eo(lt / .8)
            start = -90
            end = start + 360 * ((k + p) / n)
            d.arc([cx - r, cy - r, cx + r, cy + r], start, end, fill=NAVY, width=12)
            ang = math.radians(end)
            d.ellipse([cx + r * math.cos(ang) - 16, cy + r * math.sin(ang) - 16,
                       cx + r * math.cos(ang) + 16, cy + r * math.sin(ang) + 16], fill=WHITE, outline=NAVY, width=6)
            q = eb(lt / .35)
            d.text((cx, cy), f"#{k + 1}", font=fz("Black", 210 * max(q, .01)), fill=NAVY, anchor="mm")
            pill(d, cx, cy + r + 70, it["name"].upper(), F["pill"], NAVY, WHITE, a=clamp((lt - .3) / .3))
        sc.append((max(1.7, dur_for(capd, .9)), capd, dial, [0.0, 0.3]))

        capc = f"Gantinya: *{it['hack']}*."

        def cmp_(d, lt, dur, k=k, it=it):
            header(d)
            pill(d, 540, 330, f"ROUND {k + 1} · {it['name'].upper()}", F["pill_s"], NAVY, WHITE, padx=22, h=46)
            rich(d, tokens("*Dulu* vs *Sekarang*"), 540, 370, 900, F["mid"], None)
            # kartu lama (kiri, lebih kecil, pudar)
            p = eo(lt / .4)
            lx = 60 - 80 * (1 - p)
            box = [lx, 520, lx + 400, 800]
            shadow_card(d, box, r=28, a=.92 * clamp(p))
            icon(d, it.get("icon", "dot"), box[0] + 60, box[1] + 60, 60, MUTED, clamp(p))
            d.text((box[0] + 110, box[1] + 42), it["name"], font=F["small"], fill=rgba(INK, p))
            d.text((box[0] + 30, box[1] + 110), "dulu", font=F["card_s"], fill=rgba(MUTED, p))
            val = f"{it['old']} mnt"
            d.text((box[0] + 30, box[1] + 160), val, font=fz("Black", 88), fill=rgba((150, 150, 170), p))
            sw = d.textlength(val, font=fz("Black", 88))
            sp_ = eo((lt - .5) / .3)
            if sp_ > 0:
                strike(d, box[0] + 30, box[0] + 30 + sw * sp_, box[1] + 210, w=10)
            # VS
            v = eb((lt - .3) / .3)
            if v > 0:
                r = 52 * v
                d.ellipse([470 - r, 660 - r, 470 + r, 660 + r], fill=NAVY, outline=WHITE, width=6)
                d.text((470, 660), "VS", font=F["small"], fill=WHITE, anchor="mm")
            # kartu baru (kanan, besar, hijau)
            q = eo((lt - .45) / .45)
            if q > 0:
                rx = 500 + 120 * (1 - q)
                box2 = [rx, 440, rx + 520, 900]
                shadow_card(d, box2, r=34, a=clamp(q), outline=(170, 225, 190), width=4)
                pill(d, box2[0] + 120, box2[1] + 50, "SEKARANG", F["pill_s"], GREEN_BG, GREEN, a=clamp(q),
                     padx=18, h=42)
                hl = tokens(it["hack"])
                rich(d, [(w_, "n") for w_, _ in hl], box2[0] + 260, box2[1] + 100, 440, F["card_t"], None,
                     lh=50, a=clamp(q))
                g = eb((lt - 1.0) / .4)
                if g > 0:
                    d.text((box2[0] + 40, box2[1] + 290), f"{it['new']}", font=fz("Black", 140 * g),
                           fill=GREEN)
                    d.text((box2[0] + 60 + d.textlength(str(it['new']), font=F["big"]) * 1.15, box2[1] + 360),
                           "menit", font=F["mid"], fill=rgba(GREEN, g))
        sc.append((max(3.0, dur_for(capc, 1.4)), capc, cmp_, [0.0, 0.3, 0.45, 1.0]))

    # 5. ringkasan
    capS = f"Total, pagiku hemat *{saved} menit*."

    def summ(d, lt, dur):
        header(d)
        box = [60, 290, 1020, 380 + 105 * n + 120]
        shadow_card(d, box, a=eo(lt / .3))
        for k, it in enumerate(items):
            p = eo((lt - .15 - k * .15) / .3)
            y = box[1] + 50 + k * 105
            icon(d, it.get("icon", "dot"), box[0] + 70, y + 30, 54, NAVY, p)
            d.text((box[0] + 120, y + 30), it["name"], font=F["row"], fill=rgba(INK, p), anchor="lm")
            ov = f"{it['old']} mnt"
            ox = box[0] + 520
            d.text((ox, y + 30), ov, font=F["row"], fill=rgba(MUTED, p), anchor="lm")
            strike(d, ox, ox + d.textlength(ov, font=F["row"]), y + 30, a=p, w=5)
            d.text((ox + 170, y + 30), "→", font=F["row"], fill=rgba(MUTED, p), anchor="lm")
            d.text((box[2] - 50, y + 30), f"{it['new']} mnt", font=F["row_v"], fill=rgba(GREEN, p), anchor="rm")
            d.line([(box[0] + 40, y + 78), (box[2] - 40, y + 78)], fill=rgba(LINE, p), width=2)
        p = eb((lt - .9) / .4)
        if p > 0:
            y = box[1] + 50 + n * 105 + 20
            d.rounded_rectangle([box[0] + 30, y - 10, box[2] - 30, y + 90], 24, fill=rgba(GREEN_BG, clamp(p)))
            d.text((box[0] + 70, y + 40), "TOTAL", font=F["row"], fill=rgba(NAVY, p), anchor="lm")
            d.text((box[2] - 70, y + 40), f"hemat {saved} menit", font=F["row_v"], fill=rgba(GREEN, p), anchor="rm")
    sc.append((max(3.2, dur_for(capS, 1.6)), capS, summ, [0.0, 0.15, 0.3, 0.45, 0.6, 0.9]))

    # 6. CTA
    kw = cfg.get("keyword", "HACK")
    capC = f"Mau *{cfg.get('list_size', 5)} hack* lengkapnya? Komen [{kw}]."

    def cta(d, lt, dur):
        header(d)
        p = eb(lt / .4)
        pill(d, 540, 470, f'KOMEN "{kw}"', fz("Black", 80 * max(p, .01)), NAVY, WHITE)
        q = eo((lt - .5) / .4)
        if q > 0:
            y = 640 + 40 * (1 - q)
            d.ellipse([170, y, 260, y + 90], fill=rgba((150, 120, 255), q))
            shadow_card(d, [290, y - 10, 910, y + 110], r=40, a=clamp(q))
            n_ = int(clamp((lt - .8) / .6) * len(kw))
            d.text((330, y + 50), kw[:n_], font=F["mid"], fill=rgba(NAVY, q), anchor="lm")
    sc.append((max(2.8, dur_for(capC, 1.4)), capC, cta, [0.0, 0.5]))
    return sc


# ---------- audio ----------
def make_audio(scenes, path, sr=44100):
    total = sum(s[0] for s in scenes)
    out = np.zeros(int(sr * (total + 0.3)))

    def tone(t0, dur, f, vol, decay=0.0, f2=None):
        n = int(sr * dur)
        t = np.arange(n) / sr
        freq = f if f2 is None else f + (f2 - f) * t / dur
        ph = 2 * np.pi * np.cumsum(freq) / sr
        env = (np.exp(-decay * t) if decay else 1) * np.minimum(1, t / .004) * np.minimum(1, (dur - t) / .01)
        i = int(sr * t0)
        seg = np.sin(ph) * env * vol
        out[i:i + n] += seg[:max(0, len(out) - i)]

    acc = 0.0
    for k, (dur, _, _, cues) in enumerate(scenes):
        tone(acc, .18, 300, .10, decay=18, f2=900)  # whoosh pendek per adegan
        for c in cues[1:]:
            tone(acc + c, .09, 880, .09, decay=40)  # pop
        acc += dur
    # beat ringan 100 bpm
    beat = 60 / 100
    t = 0.0
    while t < total:
        tone(t, .12, 70, .16, decay=25, f2=45)
        tone(t + beat / 2, .03, 4000, .015, decay=120)
        t += beat
    pcm = (np.clip(out, -1, 1) * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return total


def render(cfg, out):
    scenes = build(cfg)
    with tempfile.TemporaryDirectory() as td:
        wav = os.path.join(td, "a.wav")
        total = make_audio(scenes, wav)
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", wav,
               "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", out]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        tg = 0.0
        for dur, cap, fn, _ in scenes:
            toks = tokens(cap)
            for f in range(int(round(dur * FPS))):
                lt = f / FPS
                img = BG.copy()
                d = ImageDraw.Draw(img, "RGBA")
                fn(d, lt, dur)
                n_show = clamp((lt - .1) * 3.2, 0, len(toks))
                rich(d, toks, 500, 1060, 860, F["cap"], F["cap_l"], n_show=n_show)
                avatar(d, tg + lt, talking=n_show < len(toks) or (lt % 1) < .5)
                proc.stdin.write(img.tobytes())
            tg += dur
        proc.stdin.close()
        if proc.wait():
            sys.exit("ffmpeg gagal")
    print(f"Selesai: {out}  ({total:.1f} detik)")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", default=os.path.join(HERE, "config.json"))
    p.add_argument("--out", default="reel_round_id.mp4")
    a = p.parse_args()
    with open(a.config, encoding="utf-8") as fh:
        render(json.load(fh), a.out)


if __name__ == "__main__":
    main()
