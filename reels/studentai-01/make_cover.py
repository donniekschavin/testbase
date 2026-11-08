#!/usr/bin/env python3
"""Sampul TikTok StudentAi #01 (1080x1920). Dua versi: terang dan gelap.

Teks penting ditaruh di area tengah 3:4 (y 240..1680), karena grid profil
TikTok memotong sampul ke rasio itu.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_reel as R  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

BLK, YEL, PNK, WHT, RED = (17, 17, 17), (240, 240, 80), (255, 79, 154), (255, 255, 255), (226, 54, 64)


def centered(d, y, text, f, fill):
    d.text((540, y), text, font=f, fill=fill, anchor="mm")
    return d.textlength(text, font=f)


def cover(dark, out):
    cfg = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
    th = cfg["theme"]
    for k in ("bg_top", "bg_bot", "blob"):
        R.THEME[k] = th[k]
    if dark:
        R.THEME.update({"bg_top": [24, 24, 24], "bg_bot": [8, 8, 8], "blob": [-30, -30, -10]})
    img = R.make_bg()
    d = ImageDraw.Draw(img, "RGBA")
    ink = YEL if dark else BLK
    sub = WHT if dark else BLK

    # brand
    R.pill(d, 540, 330, "StudentAi", R.fz("ExtraBold", 40), BLK if not dark else YEL,
           YEL if not dark else BLK, padx=34, h=74)

    # baris 1-2
    centered(d, 500, "STOP KETIK", R.fz("Black", 150), ink)
    f2 = R.fz("Black", 86)
    t2 = '"buatkan makalah"'
    w2 = centered(d, 650, t2, f2, (150, 150, 150) if not dark else (170, 170, 170))
    d.line([(540 - w2 / 2 - 10, 665), (540 + w2 / 2 + 10, 635)], fill=RED, width=14)

    # kotak utama
    f3 = R.fz("Black", 112)
    t3 = "PAKAI 4 PROMPT"
    w3 = d.textlength(t3, font=f3)
    box = [540 - w3 / 2 - 44, 760, 540 + w3 / 2 + 44, 920]
    d.rounded_rectangle([box[0] + 10, box[1] + 14, box[2] + 10, box[3] + 14], 34, fill=PNK)
    d.rounded_rectangle(box, 34, fill=YEL if dark else BLK)
    d.text((540, 840), t3, font=f3, fill=BLK if dark else YEL, anchor="mm")

    # kata kunci pencarian
    R.pill(d, 540, 1015, "prompt AI buat tugas kuliah", R.fz("Bold", 46), WHT if not dark else (40, 40, 40),
           sub, padx=36, h=84)

    # stiker "gratis"
    d.ellipse([800, 1080, 990, 1270], fill=PNK)
    d.text((895, 1150), "GRATIS", font=R.fz("Black", 40), fill=WHT, anchor="mm")
    d.text((895, 1198), "4 prompt", font=R.fz("Bold", 30), fill=WHT, anchor="mm")

    # robot maskot (sama dengan di video)
    if dark:
        # kepala hitam di latar gelap butuh garis tepi
        cy = 1570 + 6 * __import__("math").sin(0.5 * 2.2)
        g = (70, 70, 70)
        d.rounded_rectangle([540 - 240, cy - 220, 540 + 240, cy + 180], 86, fill=g)
        d.polygon([(540 - 268, cy - 230), (540, cy - 346), (540 + 268, cy - 230), (540, cy - 136)], fill=g)
        d.line([(540, cy - 210), (540, cy - 290)], fill=g, width=26)
    R.robot(d, 0.5, talking=False)
    img.save(out)
    print("Selesai:", out)


if __name__ == "__main__":
    cover(False, os.path.join(HERE, "sampul_terang.png"))
    cover(True, os.path.join(HERE, "sampul_gelap.png"))
