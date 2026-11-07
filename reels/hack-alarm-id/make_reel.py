#!/usr/bin/env python3
"""Buat video Reels "Berhenti pasang 6 alarm" (1080x1920, 30fps, ~25 detik).

Contoh:
  python3 make_reel.py --app "NamaAplikasi" --hack1 "Taruh HP di seberang kamar" \
      --hack2 "Siapkan baju malam sebelumnya" --out reel.mp4

Butuh: Python 3, Pillow, numpy, ffmpeg.
"""
import argparse
import math
import os
import subprocess
import sys
import tempfile
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1080, 1920, 30
# Zona aman Instagram: hindari y<230, y>1440, dan 230px kanan.
CX = 455            # pusat horizontal area aman (60..850)
SAFE_L, SAFE_R = 60, 850

FONT_DIR = "/usr/share/fonts/opentype/inter"
YELLOW = (255, 210, 63)
WHITE = (255, 255, 255)
GREEN = (52, 199, 89)
GREY = (120, 124, 140)
DARK = (22, 24, 38)


def font(weight, size):
    for name in (f"Inter-{weight}.otf", "Inter-Bold.otf"):
        p = os.path.join(FONT_DIR, name)
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


F_CARD = font("Black", 92)
F_CAP = font("SemiBold", 46)
F_BIG = font("ExtraBold", 64)
F_MED = font("Bold", 44)
F_SM = font("Medium", 34)


# ---------- easing ----------
def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def ease_out(t):
    t = clamp(t)
    return 1 - (1 - t) ** 3


def ease_back(t):
    t = clamp(t)
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


# ---------- background ----------
def make_bg():
    y = np.linspace(0, 1, H)[:, None]
    top = np.array([30, 22, 64])
    bot = np.array([12, 14, 30])
    g = top * (1 - y[..., None]) + bot * y[..., None]
    g = np.repeat(g, W, axis=1)
    return Image.fromarray(g.astype(np.uint8), "RGB")


BG = make_bg()


def draw_glow(d, t):
    # lingkaran samar yang bergerak, supaya frame pertama sudah ada gerakan
    x = CX + 180 * math.sin(t * 0.6)
    y = 900 + 220 * math.cos(t * 0.45)
    for r, a in ((420, 18), (300, 22), (190, 26)):
        d.ellipse([x - r, y - r, x + r, y + r], fill=(120, 90, 255, a))


# ---------- text helpers ----------
def wrap(d, text, f, maxw):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if d.textlength(trial, font=f) <= maxw:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def card_text(d, text, lt):
    """Teks besar di atas (kartu on-screen). Muncul dari bawah + fade."""
    if not text:
        return
    p = ease_out(lt / 0.3)
    a = int(255 * p)
    dy = int(40 * (1 - p))
    lines = wrap(d, text, F_CARD, SAFE_R - SAFE_L)
    y = 300 + dy
    for ln in lines:
        tw = d.textlength(ln, font=F_CARD)
        x = CX - tw / 2
        # highlight kuning di belakang teks
        d.rounded_rectangle([x - 22, y - 8, x + tw + 22, y + 104], 18, fill=YELLOW + (a,))
        d.text((x, y), ln, font=F_CARD, fill=DARK + (a,))
        y += 122


def caption(d, text):
    """Subtitle ucapan (burned-in), di batas bawah area aman."""
    lines = wrap(d, text, F_CAP, SAFE_R - SAFE_L - 60)
    lh = 60
    total = lh * len(lines)
    y0 = 1420 - total
    maxw = max(d.textlength(l, font=F_CAP) for l in lines)
    d.rounded_rectangle([CX - maxw / 2 - 28, y0 - 18, CX + maxw / 2 + 28, y0 + total + 10],
                        22, fill=(0, 0, 0, 150))
    for i, ln in enumerate(lines):
        d.text((CX, y0 + i * lh), ln, font=F_CAP, fill=WHITE, anchor="mt")


# ---------- props ----------
PHONE = (CX - 230, 560, CX + 230, 1230)


def phone(d):
    x0, y0, x1, y1 = PHONE
    d.rounded_rectangle([x0, y0, x1, y1], 56, fill=(8, 8, 14), outline=(70, 72, 96), width=6)
    d.rounded_rectangle([CX - 60, y0 + 18, CX + 60, y0 + 42], 12, fill=(30, 30, 40))


def alarm_row(d, i, y, on, dx=0, alpha=255):
    x0, _, x1, _ = PHONE
    x0 += 30 + dx
    x1 -= 30 - dx
    d.rounded_rectangle([x0, y, x1, y + 78], 18, fill=(34, 36, 52, alpha))
    t = f"06:{i * 5:02d}"
    d.text((x0 + 24, y + 39), t, font=F_MED, fill=(WHITE if on else GREY) + (alpha,), anchor="lm")
    tx = x1 - 110
    d.rounded_rectangle([tx, y + 20, tx + 84, y + 58], 19,
                        fill=(GREEN if on else (70, 72, 90)) + (alpha,))
    kx = tx + 64 if on else tx + 20
    d.ellipse([kx - 16, y + 23, kx + 16, y + 55], fill=WHITE + (alpha,))


def alarms_ringing(d, lt, n):
    phone(d)
    d.text((CX, PHONE[1] + 80), "Alarm", font=F_MED, fill=WHITE, anchor="mm")
    for i in range(n):
        shake = int(10 * math.sin(lt * 40 + i)) if (int(lt * 4) % 2 == 0) else 0
        appear = clamp((lt - i * 0.08) / 0.2)
        alarm_row(d, i, PHONE[1] + 130 + i * 90, True, dx=shake, alpha=int(255 * appear))


def alarms_deleting(d, lt, n, dur):
    phone(d)
    d.text((CX, PHONE[1] + 80), "Alarm", font=F_MED, fill=WHITE, anchor="mm")
    step = (dur - 0.6) / max(1, n - 1)
    for i in range(n):
        if i == 0:
            alarm_row(d, i, PHONE[1] + 130, True)
            continue
        k = n - i  # hapus dari bawah
        t0 = 0.1 + (k - 1) * step * 0.8
        p = clamp((lt - t0) / 0.35)
        if p >= 1:
            continue
        alarm_row(d, i, PHONE[1] + 130 + i * 90, p < 0.3,
                  dx=int(-500 * ease_out((p - 0.3) / 0.7)) if p > 0.3 else 0,
                  alpha=int(255 * (1 - clamp((p - 0.3) / 0.7))))


def snooze(d, lt, dur):
    pulse = 1 + 0.06 * math.sin(lt * 10)
    r = 190 * pulse
    cy = 860
    d.ellipse([CX - r, cy - r, CX + r, cy + r], fill=(255, 149, 0))
    d.text((CX, cy), "SNOOZE", font=F_BIG, fill=WHITE, anchor="mm")
    mins = int(round(20 * ease_out(lt / (dur * 0.85))))
    d.text((CX, cy + 270), f"+{mins} menit", font=F_BIG, fill=YELLOW, anchor="mm")
    for k in range(3):
        zt = (lt * 1.2 + k / 3) % 1
        d.text((CX + 160 + k * 40, cy - 200 - zt * 160), "z", font=F_MED,
               fill=(255, 255, 255, int(255 * (1 - zt))))


def app_icon(d, lt, name):
    s = 280 * ease_back(lt / 0.45)
    cy = 840
    if s > 2:
        d.rounded_rectangle([CX - s / 2, cy - s / 2, CX + s / 2, cy + s / 2], int(s * 0.22), fill=YELLOW)
        br = s * 0.22
        d.ellipse([CX - br, cy - br - s * 0.08, CX + br, cy + br - s * 0.08], fill=DARK)
        d.rounded_rectangle([CX - br * 0.5, cy + br * 0.7, CX + br * 0.5, cy + br * 1.3], 6, fill=DARK)
    a = int(255 * clamp((lt - 0.3) / 0.3))
    d.text((CX, cy + 230), name, font=F_BIG, fill=WHITE + (a,), anchor="mm")


def notif(d, lt):
    phone(d)
    p = ease_out(lt / 0.5)
    y = PHONE[1] + 90 + int(-120 * (1 - p))
    x0, _, x1, _ = PHONE
    d.rounded_rectangle([x0 + 24, y, x1 - 24, y + 230], 28, fill=(245, 245, 250, int(255 * p)))
    d.rounded_rectangle([x0 + 50, y + 30, x0 + 110, y + 90], 14, fill=YELLOW)
    d.text((x0 + 130, y + 60), "Hack hari ini", font=F_MED, fill=DARK, anchor="lm")
    d.text((x0 + 50, y + 130), "1 trik. 30 detik.", font=F_SM, fill=(60, 60, 80), anchor="lm")
    d.text((x0 + 50, y + 180), "Ketuk untuk buka", font=F_SM, fill=(120, 120, 140), anchor="lm")


def checklist(d, lt, day, item, badge):
    p = ease_out(lt / 0.35)
    x0, x1 = SAFE_L + 40, SAFE_R - 40
    y0 = 640 + int(60 * (1 - p))
    a = int(255 * p)
    d.rounded_rectangle([x0, y0, x1, y0 + 470], 36, fill=(245, 245, 250, a))
    d.text((x0 + 44, y0 + 70), day, font=F_BIG, fill=DARK + (a,), anchor="lm")
    lines = wrap(d, item, F_MED, x1 - x0 - 170)[:3]
    for i, ln in enumerate(lines):
        d.text((x0 + 130, y0 + 175 + i * 58), ln, font=F_MED, fill=(40, 40, 60, a), anchor="lm")
    # kotak centang + animasi centang
    bx, by = x0 + 44, y0 + 150
    d.rounded_rectangle([bx, by, bx + 54, by + 54], 12, outline=GREEN + (a,), width=5)
    c = clamp((lt - 0.6) / 0.4)
    if c > 0:
        pts = [(bx + 12, by + 28), (bx + 24, by + 42), (bx + 44, by + 14)]
        if c < 0.5:
            q = c / 0.5
            d.line([pts[0], (pts[0][0] + (pts[1][0] - pts[0][0]) * q,
                             pts[0][1] + (pts[1][1] - pts[0][1]) * q)], fill=GREEN, width=8)
        else:
            q = (c - 0.5) / 0.5
            d.line([pts[0], pts[1], (pts[1][0] + (pts[2][0] - pts[1][0]) * q,
                                     pts[1][1] + (pts[2][1] - pts[1][1]) * q)], fill=GREEN, width=8)
    ba = int(255 * clamp((lt - 0.9) / 0.3))
    bw = d.textlength(badge, font=F_MED) + 60
    d.rounded_rectangle([x1 - bw - 40, y0 + 370, x1 - 40, y0 + 440], 35, fill=GREEN + (ba,))
    d.text((x1 - 40 - bw / 2, y0 + 405), badge, font=F_MED, fill=WHITE + (ba,), anchor="mm")


def key(d, lt):
    p = ease_back(lt / 0.5)
    cx = CX - 260 + 260 * p
    cy = 860
    rot = math.radians(-20 + 20 * p)
    d.ellipse([cx - 110, cy - 110, cx + 110, cy + 110], outline=YELLOW, width=34)

    def R(x, y):
        return (cx + x * math.cos(rot) - y * math.sin(rot), cy + x * math.sin(rot) + y * math.cos(rot))
    shaft = [R(95, -22), R(360, -22), R(360, 22), R(95, 22)]
    d.polygon(shaft, fill=YELLOW)
    for tx in (280, 330):
        d.polygon([R(tx, 22), R(tx + 28, 22), R(tx + 28, 80), R(tx, 80)], fill=YELLOW)
    a = int(255 * clamp((lt - 0.5) / 0.3))
    d.text((CX, 1100), "Ketemu.", font=F_BIG, fill=WHITE + (a,), anchor="mm")


def clock(d, lt):
    cy, r = 860, 250
    d.ellipse([CX - r, cy - r, CX + r, cy + r], fill=(245, 245, 250), outline=YELLOW, width=14)
    for k in range(12):
        ang = math.radians(k * 30)
        d.line([(CX + (r - 40) * math.sin(ang), cy - (r - 40) * math.cos(ang)),
                (CX + (r - 18) * math.sin(ang), cy - (r - 18) * math.cos(ang))], fill=DARK, width=8)
    p = ease_out(lt / 1.6)
    m = 30 - 15 * p   # jarum menit mundur 15 menit
    am = math.radians(m * 6)
    ah = math.radians((7 + m / 60) * 30)
    d.line([(CX, cy), (CX + 140 * math.sin(ah), cy - 140 * math.cos(ah))], fill=DARK, width=16)
    d.line([(CX, cy), (CX + 210 * math.sin(am), cy - 210 * math.cos(am))], fill=(255, 80, 80), width=10)
    d.ellipse([CX - 18, cy - 18, CX + 18, cy + 18], fill=DARK)


def comment(d, lt):
    y = 780
    x0 = SAFE_L + 30
    d.ellipse([x0, y, x0 + 110, y + 110], fill=(150, 120, 255))
    n = int(clamp((lt - 0.3) / 0.8) * 4)
    txt = "HACK"[:n] + ("|" if int(lt * 3) % 2 == 0 and n < 4 else "")
    d.rounded_rectangle([x0 + 140, y - 10, SAFE_R - 30, y + 160], 36, fill=(245, 245, 250))
    d.text((x0 + 180, y + 30), "kamu", font=F_SM, fill=(110, 110, 130))
    d.text((x0 + 180, y + 80), txt, font=F_BIG, fill=DARK)
    hp = ease_back((lt - 1.4) / 0.4)
    if hp > 0:
        hx, hy, s = SAFE_R - 110, y + 200, 50 * hp
        d.ellipse([hx - s, hy - s * 0.6, hx, hy + s * 0.4], fill=(255, 59, 92))
        d.ellipse([hx, hy - s * 0.6, hx + s, hy + s * 0.4], fill=(255, 59, 92))
        d.polygon([(hx - s * 0.95, hy), (hx + s * 0.95, hy), (hx, hy + s * 1.1)], fill=(255, 59, 92))


# ---------- scenes ----------
def build_scenes(a):
    return [
        # (durasi, kartu on-screen, ucapan/subtitle, fungsi visual)
        (3.0, f"HAPUS {a.alarms} ALARM-MU", f"Berhenti pasang {a.alarms} alarm. Buka aplikasi ini saja.",
         lambda d, lt, dur: alarms_ringing(d, lt, a.alarms)),
        (3.0, f"{a.snooze} MENIT SNOOZE", f"Dulu aku snooze {a.snooze} menit dan tetap telat.",
         lambda d, lt, dur: snooze(d, lt, dur)),
        (1.8, "", f"Ini {a.app}.", lambda d, lt, dur: app_icon(d, lt, a.app)),
        (2.4, "1 HACK SEHARI", "Satu life hack tiap pagi. Satu aja.", lambda d, lt, dur: notif(d, lt)),
        (2.4, "SENIN: 30 DETIK", f"Senin: {a.hack1}. Tiga puluh detik.",
         lambda d, lt, dur: checklist(d, lt, "SENIN", a.hack1, "30 detik")),
        (2.4, f"SELASA: -{a.saved} MENIT", f"Selasa, {a.hack2}. Hemat {a.saved} menit.",
         lambda d, lt, dur: checklist(d, lt, "SELASA", a.hack2, f"-{a.saved} menit")),
        (2.0, "", "Bahkan sebelum aku nemu kunci.", lambda d, lt, dur: key(d, lt)),
        (3.0, f"{a.earlier} MENIT LEBIH AWAL", f"Sebulan kemudian, aku berangkat {a.earlier} menit lebih awal.",
         lambda d, lt, dur: clock(d, lt)),
        (2.8, 'KOMEN "HACK"', "Komen HACK, nanti aku kirim 5 favoritku.", lambda d, lt, dur: comment(d, lt)),
        (2.6, "", f"Terus hapus {a.alarms - 1} alarm itu.",
         lambda d, lt, dur: alarms_deleting(d, lt, a.alarms, dur)),
    ]


# ---------- audio ----------
def make_audio(scenes, path, sr=44100):
    total = sum(s[0] for s in scenes)
    out = np.zeros(int(sr * (total + 0.1)))

    def tone(t0, dur, f, vol, decay=0.0):
        n = int(sr * dur)
        t = np.arange(n) / sr
        env = np.exp(-decay * t) if decay else np.ones(n)
        att = np.minimum(1, t / 0.005)
        rel = np.minimum(1, (dur - t) / 0.01)
        sig = np.sin(2 * np.pi * f * t) * env * att * rel * vol
        i = int(sr * t0)
        out[i:i + n] += sig[:len(out) - i]

    # bunyi alarm di scene pertama
    t = 0.0
    while t < scenes[0][0] - 0.2:
        tone(t, 0.12, 1760, 0.18)
        tone(t + 0.18, 0.12, 1760, 0.18)
        t += 0.6
    # pop kecil tiap ganti scene
    acc = 0.0
    for i, s in enumerate(scenes):
        if i:
            tone(acc, 0.12, 660, 0.12, decay=30)
        acc += s[0]
    # ding di scene "lebih awal"
    tone(sum(s[0] for s in scenes[:7]) + 1.6, 0.8, 1318, 0.16, decay=5)
    pcm = (np.clip(out, -1, 1) * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return total


def render(a):
    scenes = build_scenes(a)
    with tempfile.TemporaryDirectory() as td:
        wav = os.path.join(td, "a.wav")
        total = make_audio(scenes, wav)
        cmd = ["ffmpeg", "-y", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
               "-i", wav, "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", a.out]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        t_global = 0.0
        for dur, card, said, fn in scenes:
            nf = int(round(dur * FPS))
            for f in range(nf):
                lt = f / FPS
                img = BG.copy()
                d = ImageDraw.Draw(img, "RGBA")
                draw_glow(d, t_global + lt)
                fn(d, lt, dur)
                card_text(d, card, lt)
                caption(d, said)
                proc.stdin.write(img.tobytes())
            t_global += dur
        proc.stdin.close()
        if proc.wait() != 0:
            sys.exit("ffmpeg gagal")
    print(f"Selesai: {a.out}  ({total:.1f} detik, {W}x{H}, {FPS}fps)")


def main():
    p = argparse.ArgumentParser(description="Render Reels 'Berhenti pasang 6 alarm'")
    p.add_argument("--app", default="[NAMA APLIKASI]")
    p.add_argument("--hack1", default="[HACK 1]")
    p.add_argument("--hack2", default="[HACK 2]")
    p.add_argument("--alarms", type=int, default=6, help="jumlah alarm (angka aslimu)")
    p.add_argument("--snooze", type=int, default=20, help="menit snooze (angka aslimu)")
    p.add_argument("--saved", type=int, default=10, help="menit yang dihemat hack 2")
    p.add_argument("--earlier", type=int, default=15, help="berangkat X menit lebih awal")
    p.add_argument("--out", default="reel_hack_alarm_id.mp4")
    render(p.parse_args())


if __name__ == "__main__":
    main()
