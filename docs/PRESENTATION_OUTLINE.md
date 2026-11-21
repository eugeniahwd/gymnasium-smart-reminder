# Kerangka Presentasi — Project Brief, Slide, dan Naskah Video 10 Menit

Semua angka di dokumen ini berasal dari hasil nyata di repo (`docs/MODEL_EVALUATION.md`,
`docs/PROMPT_ENGINEERING.md`). Isi bagian bertanda **[isi]** sebelum dipakai. Sebutkan selalu: **prototype, data
synthetic**.

## 1. Kerangka Project Brief

1. **Judul**: Gymnasium Smart Reminder & Follow-up — prioritas follow-up berbasis ML dan draft pesan berbasis GenAI
   untuk admin gym. ID tim DB15-I038, Eugenia Huwaida Imtinan (jalur Gen AI).
2. **Latar belakang**: Gymnasium (gym & private coaching; ibu-ibu, lansia, menengah atas) mengirim reminder dan
   follow-up secara manual lewat WhatsApp, tanpa panduan siapa yang perlu didahulukan; admin menulis setiap pesan
   dari nol.
3. **Tujuan**: (a) memprioritaskan follow-up Low/Medium/High dengan model yang dilatih sendiri; (b) membuat draft
   pesan sesuai persona dan prioritas; (c) mencatat status pengiriman — tanpa pengiriman otomatis.
4. **Research question**: apakah model ML lebih baik dari baseline sederhana, dan bagaimana GenAI mengubah hasil
   klasifikasi menjadi draft yang siap pakai admin?
5. **Data**: synthetic, reproducible (seed 42): 400 customer, 1.304 baris training; label dari skor laten + faktor
   tersembunyi yang bukan fitur + noise + 6% label dibalik agar tidak bocor. Fitur hanya dari data sebelum tanggal
   acuan.
6. **Metodologi ML**: split 80/20 grouped per customer; bandingkan Dummy, baseline rule-based, Logistic Regression,
   Random Forest; pilih dari macro-F1 cross-validation dengan syarat recall High ≥ baseline.
7. **Hasil ML**: Logistic Regression macro-F1 test 0,670 vs baseline 0,610; CV 5-fold 0,666 ± 0,019 vs 0,565 ±
   0,050; recall High 0,691 vs 0,673. Keunggulan moderat; kelas Medium paling lemah (F1 0,530).
8. **GenAI**: Gemini (`gemini-3.5-flash-lite`) dipanggil hanya dari backend; persona × intensitas prioritas;
   larangan keras; post-check otomatis; template cadangan. Evaluasi 9 skenario: rubrik rata-rata v1 4,40 → v2
   4,73 (dinilai asisten AI, indikatif).
9. **Produk**: FastAPI (Render) + Streamlit (Community Cloud) + PostgreSQL (Supabase); alur Scheduled → Sent →
   Responded/No Response; link `wa.me` dengan teks terisi.
10. **Keterbatasan**: data synthetic, keunggulan moderat, Medium lemah, API tanpa autentikasi, kuota/tidur free
    tier, post-check berbasis pola, evaluasi draft kecil.
11. **Rencana lanjutan**: validasi dengan data operasional sungguhan (dengan izin), penilaian draft oleh admin
    nyata, autentikasi sederhana, variasi few-shot (prompt v3).
12. **Tautan**: repo GitHub **[isi]**, UI **[isi]**, API `/docs` **[isi]**, video **[isi]**.

## 2. Kerangka slide (12 slide)

| # | Judul slide | Isi utama | Visual |
|---|---|---|---|
| 1 | Judul | Nama proyek, ID tim, nama, jalur Gen AI | Logo/ikon gym |
| 2 | Masalah | Reminder manual via WhatsApp, tanpa prioritas, pesan ditulis dari nol | Ilustrasi chat admin |
| 3 | Solusi | 3 kemampuan: prioritas ML, draft GenAI, pencatatan status; admin tetap mengirim sendiri | Diagram alur end-to-end (README) |
| 4 | Data synthetic | 400 customer, 1.304 baris; cara label dibuat tanpa leakage; disclaimer prototype | `docs/figures/eda_class_distribution.png` |
| 5 | Model & evaluasi | Tabel Dummy / baseline / LR / RF; kenapa LR dipilih (CV, recall High) | `docs/figures/model_comparison_cv.png` |
| 6 | Interpretasi | Confusion matrix (Medium lemah), fitur berpengaruh | `model_confusion_matrices.png`, `model_permutation_importance.png` |
| 7 | GenAI: desain prompt | Persona × prioritas, larangan keras, top_factors tidak dikirim ke Gemini | Potongan prompt dari PROMPT_ENGINEERING §3 |
| 8 | GenAI: keandalan | Post-check + 1x regenerasi + template cadangan; retry 429/5xx/timeout | Diagram alur PROMPT_ENGINEERING §1 |
| 9 | Iterasi prompt v1 → v2 | Masalah v1 (mengungkit pesan lama, "kendala serius"), perbaikan, rubrik 4,40 → 4,73 | Contoh draft #9 v1 vs v2 |
| 10 | Arsitektur & deploy | Streamlit → FastAPI → Supabase/Model/Gemini; Render + Community Cloud; tes tanpa jaringan | Diagram arsitektur README |
| 11 | Keterbatasan | Daftar jujur (lihat Project Brief poin 10) | — |
| 12 | Penutup | Jawaban research question, tautan live | QR ke URL UI **[isi]** |

## 3. Naskah video 10 menit

**Persiapan sebelum merekam:** jalankan `python -m src.data_generation.seed_demo`; buka `<url-render>/health`
±1 menit sebelumnya; buka UI dan pastikan sidebar "Database: terhubung"; pilih hari Senin–Sabtu. Nomor WhatsApp di
data synthetic (`628990…`) fiktif, jadi untuk langkah WhatsApp buat dulu **satu customer demo dengan nomormu
sendiri** (halaman Customer, mis. "Ibu Demo", persona ibu-ibu) lalu reminder untuk kelas hari ini (Reminder Hari
Ini → Buat reminder baru).

| Waktu | Segmen | Yang ditampilkan | Naskah (inti yang diucapkan) |
|---|---|---|---|
| 0:00–0:40 | Pembuka | Slide 1–2 | "Halo, saya Eugenia, ID tim DB15-I038. Admin Gymnasium mengingatkan kelas dan follow-up member lewat WhatsApp secara manual, tanpa tahu siapa yang perlu didahulukan dan harus menulis setiap pesan dari nol." |
| 0:40–1:30 | Solusi | Slide 3 | "Aplikasi ini khusus admin: model ML memprioritaskan follow-up Low, Medium, High; Gemini membuat draft pesan sesuai persona dan prioritas; admin tetap mengedit dan mengirim sendiri, lalu mencatat statusnya. Tidak ada pengiriman otomatis." |
| 1:30–2:30 | Data | Slide 4 | "Ini prototype dengan data synthetic: 400 customer, 1.304 baris training. Label dibuat dari skor laten plus faktor tersembunyi dan noise, lalu 6% dibalik, supaya model tidak bisa menebak label dari rumusnya. Fitur hanya diambil dari data sebelum tanggal acuan." |
| 2:30–3:50 | Model | Slide 5–6 | "Saya bandingkan empat model dengan split per customer. Logistic Regression mencapai macro-F1 0,670 di test, dibanding baseline 0,610; di cross-validation 0,666 dibanding 0,565. Random Forest sedikit lebih tinggi di satu split test, tetapi tidak di cross-validation dan recall High-nya sama dengan baseline, jadi saya pilih Logistic Regression. Jawaban jujurnya: lebih baik dari baseline, tetapi moderat, dan kelas Medium paling lemah." |
| 3:50–5:00 | GenAI | Slide 7–9 | "Prompt menerima data terstruktur: sapaan, persona, arahan sesuai prioritas, kelas, jam, pelatih. Alasan prioritas tidak pernah dikirim ke Gemini. Setiap draft diperiksa otomatis — kata seperti prioritas, risiko, AI, promo, klaim kesehatan, atau jadwal karangan ditolak; jika gagal setelah satu regenerasi atau kuota habis, sistem memakai template cadangan. Dari evaluasi v1 saya menemukan draft mengungkit pesan lama dan berasumsi 'kendala serius'; setelah perbaikan v2, rata-rata rubrik naik dari 4,40 ke 4,73 — dinilai dengan bantuan AI, jadi indikatif." |
| 5:00–8:30 | **Demo live** | UI | Lihat langkah demo di bawah. |
| 8:30–9:15 | Teknis | Slide 10 | "Backend FastAPI di Render, UI Streamlit di Community Cloud, database Supabase. Gemini hanya dipanggil dari backend. Ada 215 tes otomatis yang berjalan tanpa jaringan, memakai database SQLite dan klien Gemini palsu." |
| 9:15–10:00 | Penutup | Slide 11–12 | "Keterbatasannya: data synthetic, keunggulan model moderat, API tanpa login, dan kuota free tier. Jadi jawaban research question: model ML membantu memprioritaskan lebih baik dari aturan sederhana, dan GenAI mengubah prioritas itu menjadi draft yang hampir siap kirim — dengan admin tetap memegang kendali. Terima kasih." |

### Langkah demo (5:00–8:30)

1. **Sidebar**: tunjukkan disclaimer PROTOTYPE dan status "Database: terhubung · Model: lr-20261031-v1".
2. **Reminder Hari Ini**: tunjukkan daftar urut High dulu, badge warna, dan peluang. Pilih reminder High teratas.
3. Klik **Lihat alasan prioritas** → jelaskan faktor (mis. absen berturut) dan bahwa ini hanya untuk admin.
4. Klik **Generate Draft** → bacakan draft; tunjukkan sumber "Gemini (AI)" dan bahwa alasan prioritas tidak
   muncul di pesan. (Jika muncul "template cadangan" karena kuota, jelaskan bahwa ini fitur fallback.)
5. **Edit** satu kalimat → **Simpan pesan** → **Buka WhatsApp** (teks terisi; kirim ke nomor sendiri).
6. Centang konfirmasi → **Tandai Terkirim** → tunjukkan pesan terkunci; klik **Responded**.
7. Buka **Riwayat status** (Scheduled → Sent → Responded) dan halaman **Riwayat Reminder**.
8. (Opsional, 20 detik) Pilih reminder persona lain (lansia/menengah atas) → Generate Draft untuk menunjukkan beda
   gaya bahasa.
9. (Opsional, 15 detik) Buka `<url-render>/docs` untuk menunjukkan Swagger.

**Tips rekaman:** tutup tab berisi `.env`/dashboard secret; perbesar zoom browser 110–125%; jika API lambat di awal,
katakan "server gratis sedang bangun" lalu lanjutkan.
