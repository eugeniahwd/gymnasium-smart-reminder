# Dokumentasi Data Synthetic

> **DISCLAIMER:** Seluruh data di proyek ini adalah **data synthetic**, bukan data operasional Gymnasium.
> Label prioritas berasal dari proses simulasi, **bukan ground truth operasional**. Hasil model hanya
> berstatus **prototype** dan bukan klaim performa di kondisi nyata. Semua nama dan nomor WhatsApp
> adalah fiktif (nomor dummy berformat `628990xxxxxx`).

## Cara menjalankan

```bash
python -m src.data_generation.generate              # default: 400 customer, seed 42
python -m src.data_generation.generate --n-customers 500 --seed 7
python -m src.data_generation.seed_db --dry-run     # validasi CSV
```

Dengan seed yang sama, hasil identik (diuji lintas pandas 2.2 dan 3.0).

## Ukuran dataset (seed 42, 400 customer)

| Tabel | Baris |
|---|---|
| customers | 400 |
| schedules | 1.993 |
| attendance | 23.452 |
| reschedules | 1.942 |
| reminders (histori) | 25.852 |
| reminder_status_history | 77.556 |
| training_dataset (snapshot) | 1.304 |

## Asumsi simulasi

**Periode.** Jadwal disimulasikan 5 Jan - 30 Sep 2026. Customer bergabung antara 1 Sep 2025 dan 25 Agu 2026,
sehingga sebagian customer punya riwayat pendek (sumber missing value alami).

**Persona** (proporsi): ibu-ibu 45%, lansia 25%, menengah_atas 30%. Tiap persona punya peluang dasar hadir
dan merespons yang berbeda (distribusi Beta), serta preferensi kelas berbeda.

**Jadwal.** 8 kelas grup mingguan (mis. Zumba Fun, Senam Ringan Lansia, Pilates Mat, Yoga Lembut) dan sesi
Private Coaching mingguan untuk sebagian customer (menengah_atas 35%, ibu-ibu 8%, lansia 10%). Tiap customer
mengikuti 1-3 kelas grup tetap.

**Perilaku kehadiran.** Peluang hadir tiap sesi = peluang dasar customer + pengaruh faktor tersembunyi
(motivasi, kesibukan) + tren naik/turun sepanjang periode + "lapse" (18% customer punya periode 3-8 minggu
dengan kehadiran sangat rendah). Jika tidak hadir, sebagian menjadi `reschedule` (dengan kelas pengganti
dalam 7 hari) dan sisanya `tidak_hadir`.

**Reminder.** 85% sesi mendapat `reminder_kelas` (H-1 sore). Sesi `tidak_hadir` mendapat `follow_up_absen`
dengan peluang 60%. Reminder tanpa respons mendapat `follow_up_tidak_merespons` dengan peluang 30%.
Respons ditentukan oleh kecenderungan merespons customer; waktu respons berdistribusi log-normal (median
sekitar 5 jam, maksimal 47 jam). Tanpa respons dalam **48 jam** = `No Response`.

**Zona waktu.** Semua waktu adalah waktu lokal tanpa zona (dianggap WIB).

## Pembuatan fitur (tanpa kebocoran)

Fitur dihitung oleh `src/ml/feature_engineering.py` (modul yang sama akan dipakai saat inference) hanya dari
data **sebelum** `reference_date`. Hasil reminder yang belum diketahui pada tanggal itu (belum direspons dan
belum lewat 48 jam) tidak dihitung. Setiap customer punya 3-4 snapshot `reference_date`
(rentang 4 Mei - 14 Sep 2026, jarak minimal 21 hari). Karena satu customer muncul di beberapa baris,
**split train/test wajib dikelompokkan per `customer_id`** (Fase 2).

Fitur: `attendance_rate_30d/90d`, `absent_count_30d`, `consecutive_absences`, `reschedule_count_90d`,
`reminder_response_rate`, `no_response_streak`, `avg_response_time_hours`, `days_since_last_attendance`,
`days_since_last_reminder`, `tenure_days`, `persona`, `favorite_class_type`.
Kolom `n_history_events` hanya untuk deteksi cold start, **bukan fitur model**.

## Pembuatan label

1. **Skor risiko laten** = kombinasi tertimbang sebagian fitur (kehadiran 30/90 hari, absen berturut-turut,
   no-response streak, hari sejak hadir terakhir, response rate)
   + **dua faktor tersembunyi yang tidak ada di dataset** (motivasi, kesibukan; dengan fluktuasi per snapshot)
   + **noise Gaussian** (std 0,55).
2. Skor di-threshold berdasarkan **kuantil** ke target **50% Low / 30% Medium / 20% High**.
3. **6% label di-flip** secara acak ke kelas lain (label "sulit").
4. Missing value acak (1,5% per kolom) disisipkan ke `avg_response_time_hours`, `days_since_last_reminder`,
   dan `reminder_response_rate` **setelah** label dibuat.

Karena faktor tersembunyi memengaruhi label, noise ditambahkan, dan label di-flip, **tidak ada aturan
sederhana yang bisa menghasilkan label sempurna**; model hanya bisa memperkirakannya dari fitur yang teramati.
Baseline rule-based di Fase 2 sengaja memakai aturan berbeda dari rumus label ini.

## Hasil aktual (seed 42)

Distribusi kelas: Low 48,3% / Medium 30,6% / High 21,1% (target 50/30/20; selisih akibat flip 6%).

Missing value per fitur: `attendance_rate_30d` dan `attendance_rate_90d` 0,6%; `reminder_response_rate` 2,8%;
`avg_response_time_hours` 4,3%; `days_since_last_attendance` 0,6%; `days_since_last_reminder` 1,8%; lainnya 0%.

**Sanity check awal** (split grouped per customer, hanya untuk memastikan tidak ada leakage; evaluasi resmi
ada di Fase 2): akurasi test sekitar 0,73-0,76 untuk Logistic Regression dan Random Forest, dan 0,64 untuk
aturan sederhana. Angka ini jauh di bawah ambang kecurigaan leakage (97%).

## Keterbatasan

- Data hasil simulasi; pola perilaku nyata member Gymnasium bisa berbeda.
- Label bukan hasil keputusan admin sungguhan, sehingga akurasi model tidak boleh dibaca sebagai akurasi di lapangan.
- Persona disederhanakan menjadi tiga kelompok.
- Ukuran kecil (1.304 baris, 400 customer): metrik per kelas, terutama recall High, memiliki varians cukup besar.
- Tidak mensimulasikan libur nasional, pembatalan kelas oleh gym, atau customer yang berhenti resmi.
