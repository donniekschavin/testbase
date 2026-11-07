# Tutorial: Reels "4 Kesalahan Reels" (format Round 1/4)

| file | isinya |
| --- | --- |
| `reel_tips_reels.mp4` | Video siap edit, 1080x1920, 38 detik, teks kata demi kata, efek suara dan beat ringan |
| `config.json` | Semua teks di video. Ubah di sini, lalu render ulang |
| `make_reel.py` | Mesin pembuat video |

Format videonya terinspirasi dari Reels yang kamu kirim: label brand, kotak TOTAL,
4 ikon, lingkaran ROUND 1/4, kartu "Salah vs Benar", tabel ringkasan dan ajakan
komen. Avatar dan isinya buatan sendiri, bukan salinan akun lain.

---

## 1. Naskah

| waktu | yang diucapkan | di layar |
| --- | --- | --- |
| 0:00 | Reels-mu sepi? Mungkin karena empat hal ini. | "Reels-mu sepi penonton?" + 4 ikon |
| 0:04 | Padahal semuanya bisa diperbaiki hari ini. | TOTAL dicoret, jadi "4 perbaikan" |
| 0:07 | Pertama, hook. | ROUND 1/4 |
| 0:09 | Gantinya, langsung ke inti di 2 detik pertama. | 6 detik ✗ vs 2 detik ✓ |
| 0:13 | Kedua, durasi. | ROUND 2/4 |
| 0:15 | Satu ide saja, cukup 15 sampai 45 detik. | 90 detik ✗ vs 15-45 dtk ✓ |
| 0:19 | Ketiga, subtitle. | ROUND 3/4 |
| 0:21 | Pasang subtitle, banyak orang nonton tanpa suara. | Tanpa teks ✗ vs Ada teks ✓ |
| 0:25 | Keempat, hashtag. | ROUND 4/4 |
| 0:27 | Hashtag maksimal 5, aturan Instagram sejak Desember 2025. | 30 tag ✗ vs Maks 5 ✓ |
| 0:31 | Empat perbaikan, Reels-mu ditonton sampai habis. | Tabel ringkasan |
| 0:35 | Mau checklist lengkapnya? Komen REELS. | KOMEN "REELS" |

---

## 2. Mengubah teks

Buka `config.json`. Setiap tips punya:

- `name`: nama ronde ("Hook")
- `old` / `new`: angka besar di kartu Salah dan Benar
- `old_note`: keterangan kecil di kartu Salah
- `fix`: judul di kartu Benar
- `say_fix`: kalimat yang diucapkan (`*kata*` = garis bawah, `[kata]` = kotak gelap)
- `icon`: `bolt`, `clock`, `cc`, `hash`, `alarm`, `key`, `shirt`, `phone`, `bulb`

Lalu render ulang:

```bash
python3 make_reel.py --out reel_final.mp4
```

Kamu bisa membuat video lain dengan format yang sama cukup dengan mengganti
`config.json`. Contoh config life hack pagi ada di `../hack-pagi-round/`.

---

## 3. Suara dan avatar (CapCut)

1. **Suara:** buka CapCut, masukkan video, pilih **Audio > Rekam**, lalu baca naskah
   di atas mengikuti teks di layar. Turunkan volume video ke sekitar 30.
2. **Ganti avatar dengan wajahmu (opsional):** rekam dirimu bicara dengan latar
   polos, lalu pilih **Overlay > Tambah overlay**, ketuk klipmu, pilih
   **Hapus latar belakang**, dan letakkan di bagian bawah, menutupi avatar.
3. **Jangan tambah subtitle otomatis**, karena teks sudah ada di video.
4. Ekspor **1080p 30fps**.

---

## 4. Caption

```
Komen REELS dan aku kirim checklist lengkapnya ke DM.

Empat hal yang paling sering bikin Reels di-scroll: hook yang telat, video terlalu panjang, tanpa subtitle, dan hashtag kebanyakan.

#tipsreels #instagramtips #kontenkreator
```

Cuma satu ajakan, yaitu komen REELS. Dua ajakan sama saja dengan tidak ada.

---

## 5. Sebelum posting

- [ ] Checklist untuk dikirim ke yang komen REELS sudah siap
- [ ] Suara sudah direkam, atau musik sudah dipilih
- [ ] Nama brand di kiri atas sudah diganti (`brand` di config)
- [ ] Posting sekitar 19.30 WIB
