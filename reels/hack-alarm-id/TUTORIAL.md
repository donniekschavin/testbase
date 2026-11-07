# Tutorial: Reels "Berhenti Pasang 6 Alarm"

Isi folder ini:

| file | isinya |
| --- | --- |
| `reel_hack_alarm_id.mp4` | Video Reels siap edit, 1080x1920, 25 detik, ada subtitle dan efek suara |
| `make_reel.py` | Script untuk membuat ulang video dengan nama aplikasi dan angka aslimu |
| `TUTORIAL.md` | File ini |

> **Penting:** semua angka di video (6 alarm, 20 menit, 10 menit, 15 menit)
> masih contoh. Ganti dengan angka aslimu sebelum posting. Jangan posting angka
> yang tidak benar atas namamu.

---

## 1. Naskah (bahasa Indonesia)

Ucapkan dengan santai, seperti ngobrol. Total sekitar 25 detik.

| waktu | yang diucapkan | teks di layar |
| --- | --- | --- |
| 0:00 | Berhenti pasang 6 alarm. Buka aplikasi ini saja. | HAPUS 6 ALARM-MU |
| 0:03 | Dulu aku snooze 20 menit dan tetap telat. | 20 MENIT SNOOZE |
| 0:06 | Ini [NAMA APLIKASI]. | (logo aplikasi) |
| 0:08 | Satu life hack tiap pagi. Satu aja. | 1 HACK SEHARI |
| 0:10 | Senin: [HACK 1]. Tiga puluh detik. | SENIN: 30 DETIK |
| 0:13 | Selasa, [HACK 2]. Hemat 10 menit. | SELASA: -10 MENIT |
| 0:15 | Bahkan sebelum aku nemu kunci. | (kunci) |
| 0:17 | Sebulan kemudian, aku berangkat 15 menit lebih awal. | 15 MENIT LEBIH AWAL |
| 0:20 | Komen HACK, nanti aku kirim 5 favoritku. | KOMEN "HACK" |
| 0:23 | Terus hapus 5 alarm itu. | (alarm dihapus satu per satu) |

Kalimat terakhir menyebut "alarm" lagi, sama seperti kalimat pertama. Jadi saat
video berulang (loop), sambungannya terasa mulus dan orang menonton dua kali.

---

## 2. Isi nama aplikasi dan angka aslimu

Video yang sekarang masih memakai `[NAMA APLIKASI]`, `[HACK 1]` dan `[HACK 2]`.
Buat ulang dengan satu perintah (butuh Python 3, Pillow, numpy dan ffmpeg):

```bash
python3 make_reel.py \
  --app "NamaAplikasimu" \
  --hack1 "Taruh HP di seberang kamar" \
  --hack2 "Siapkan baju dari malam" \
  --alarms 6 --snooze 20 --saved 10 --earlier 15 \
  --out reel_final.mp4
```

Ganti semua angka dengan angka aslimu. Contoh hack di atas hanya contoh. Pakai
hack yang benar-benar kamu dapat dari aplikasinya. Teks hack yang pendek (di
bawah 6 kata) paling enak dibaca di layar.

Kalau tidak bisa menjalankan Python, kirim saja ke Claude: nama aplikasi, 2
hack, dan angka aslimu. Nanti videonya dibuatkan ulang.

---

## 3. Tambahkan suaramu (CapCut, gratis)

Video ini belum ada suara orang, baru subtitle dan efek suara. Reels dengan
suara asli biasanya lebih dipercaya. Caranya:

1. Buka **CapCut**, pilih **Proyek baru**, lalu masukkan `reel_final.mp4`.
2. Ketuk **Audio > Rekam** (ikon mikrofon). Baca naskah di atas sambil
   melihat videonya. Ikuti subtitle di layar supaya pas waktunya.
3. Kecilkan efek suara bawaan: ketuk klip video, pilih **Volume**, turunkan
   ke sekitar 30.
4. Kalau ada bagian yang telat sedikit, geser klip suaramu. Jangan
   mempercepat suara lebih dari 1.1x, nanti terdengar aneh.
5. **Jangan tambah subtitle otomatis lagi.** Subtitle sudah ada di video,
   nanti dobel.
6. Ekspor: **1080p, 30fps**. Selesai.

**Tidak mau pakai suara?** Bisa juga. Tambahkan musik pelan dari pustaka
audio Instagram saat upload. Subtitle sudah menjelaskan semuanya.

---

## 4. Alternatif: rekam versi sendiri (lebih kuat)

Video animasi ini cocok untuk akun tanpa wajah. Kalau kamu berani tampil,
rekam versi asli dengan daftar shot ini, lalu pakai teks di layar yang sama:

| shot | yang direkam | tips |
| --- | --- | --- |
| 1 | Tanganmu menggeser daftar alarm di HP, alarm sedang bunyi | Langsung mulai dari aksi, jangan dari wajah diam |
| 2 | Kamu di balik selimut, menekan snooze | Boleh dibuat lucu |
| 3 | Close-up membuka aplikasinya | Rekam layar HP saja |
| 4 | Layar hack hari ini | Rekam layar |
| 5-6 | Kamu melakukan hack 1 dan hack 2 | Ganti sudut kamera tiap shot |
| 7 | Mengambil kunci, keluar pintu | |
| 8 | Pintu menutup, jam terlihat | |
| 9 | Bicara ke kamera: "Komen HACK" | Satu-satunya shot wajah yang wajib |
| 10 | Jempol menghapus alarm | Akhiri di layar alarm agar loop ke shot 1 |

Aturan penting:
- **Ganti gambar tiap 2-4 detik.** Gambar yang diam terlalu lama membuat orang
  scroll.
- **Teks di layar maksimal 6 kata.**
- **Zona aman:** di layar 1080x1920, jangan taruh teks di atas y=230, di bawah
  y=1440, atau di 230 piksel paling kanan. Bagian itu tertutup tombol dan
  caption Instagram. Video dari script ini sudah mengikuti aturan itu.

---

## 5. Caption (bahasa Indonesia)

```
Komen HACK dan aku DM kamu 5 life hack yang membereskan pagiku.

Dulu aku pasang 6 alarm, snooze 20 menit, dan tetap telat.

Sekarang aku buka [NAMA APLIKASI], aplikasi produktivitas gratis, sekali sehari. Isinya satu life hack. Tiga puluh detik, lalu aku bangun.

Sebulan kemudian, rutinitas pagiku mulai 15 menit lebih awal dan hampir semua alarm itu sudah kuhapus.

#lifehack #rutinitaspagi #produktivitas
```

Hapus kata "gratis" kalau aplikasinya berbayar. Ganti angka sesuai angka asli.

---

## 6. DM untuk yang komen HACK

Kirim secepatnya setelah mereka komen:

```
[nama], ini dia, 5 yang membereskan pagiku:

1. [HACK 1]
2. [HACK 2]
3. [HACK 3]
4. [HACK 4]
5. [HACK 5]

Semuanya dari [NAMA APLIKASI]. Coba nomor 1 besok pagi, cuma 30 detik.

Kamu sekarang pasang berapa alarm?
```

Follow-up (kirim manual, maksimal dua kali):
- **+4 hari** (hanya jika kamu punya hack ke-6):
  `[nama], ada satu yang ketinggalan: [HACK 6]. Ini yang akhirnya bikin aku berhenti snooze. Ada yang cocok dari 5 tadi?`
- **+10 hari**:
  `Ini pesan terakhir dariku, [nama]. Kalau ada hack yang berhasil, aku pengen tahu yang mana. Kalau belum, santai aja.`

Balasan otomatis untuk kata kunci boleh pakai fitur bawaan Instagram (akun
profesional). Jangan pakai tool yang mengirim DM massal ke orang yang tidak
berinteraksi. Itu melanggar aturan Instagram dan akunmu bisa dibatasi.

---

## 7. Cara posting

1. Instagram, tombol **+**, pilih **Reel**, lalu pilih video final.
2. Pilih **cover** dari frame pertama ("HAPUS 6 ALARM-MU").
3. Tempel caption dari bagian 5.
4. Posting sekitar **19.30 WIB**, saat orang sudah pulang kerja.
5. Di hari yang sama, posting **Story** polling: "Kamu pasang berapa alarm?"
   dengan pilihan "Cuma 1" / "Jangan tanya". DM orang yang memilih "Jangan
   tanya".
6. Siapkan daftar 5 hack sebelum posting. Orang yang komen HACK akan menunggu.

---

## Checklist sebelum posting

- [ ] Nama aplikasi sudah diganti
- [ ] Hack 1 dan Hack 2 adalah hack asli
- [ ] Semua angka (alarm, snooze, menit) adalah angka aslimu
- [ ] Angka di video, caption, DM dan story sama
- [ ] Daftar 5 hack untuk DM sudah siap
- [ ] Suara sudah direkam, atau musik sudah dipilih
