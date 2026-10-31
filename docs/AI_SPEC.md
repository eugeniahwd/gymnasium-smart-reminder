# AI_SPEC.md — Spesifikasi AI Gymnasium Smart Reminder & Follow-up

> **Dokumen ini mengikat dan melengkapi Fase 1, 2, dan 4.** Baca bersama `AGENTS.md`.

---

## A. Model ML: Prioritas Follow-up

### A1. Tugas

Klasifikasi **3 kelas** (`Low`, `Medium`, `High`) per customer pada suatu tanggal acuan (`reference_date`).

---

### A2. Fitur

Fitur dihitung **HANYA** dari data **sebelum** `reference_date` (cegah data leakage).

| Fitur | Tipe | Keterangan |
|-------|------|------------|
| `attendance_rate_30d` | Numerik | Proporsi kehadiran 30 hari terakhir |
| `attendance_rate_90d` | Numerik | Proporsi kehadiran 90 hari terakhir |
| `absent_count_30d` | Numerik | Jumlah absen 30 hari terakhir |
| `consecutive_absences` | Numerik | Jumlah absen berturut-turut terbaru |
| `reschedule_count_90d` | Numerik | Jumlah reschedule 90 hari terakhir |
| `reminder_response_rate` | Numerik | Proporsi reminder lalu berstatus `Responded` |
| `no_response_streak` | Numerik | Jumlah `No Response` berturut-turut |
| `avg_response_time_hours` | Numerik | Rata-rata waktu respons reminder (jam) |
| `days_since_last_attendance` | Numerik | Hari sejak kehadiran terakhir |
| `days_since_last_reminder` | Numerik | Hari sejak reminder terakhir |
| `tenure_days` | Numerik | Lama menjadi member (hari) |
| `persona` | Kategorikal | `ibu-ibu`, `lansia`, `menengah_atas` |
| `top_class_type` | Kategorikal | Tipe kelas paling sering diikuti |

> **Catatan missing value:** Customer baru belum punya riwayat respons; fitur seperti `reminder_response_rate`, `avg_response_time_hours`, `no_response_streak` akan bernilai `NaN` dan harus ditangani oleh imputer dalam pipeline.

---

### A3. Pembuatan Label (Cegah Leakage)

1. Buat **skor risiko laten** = kombinasi tertimbang dari sebagian fitur + **satu atau dua faktor tersembunyi** yang **TIDAK** menjadi fitur model (misal: "motivasi" atau "kesibukan") + noise Gaussian.
2. Ubah skor ke kelas lewat threshold/kuantil agar distribusi target kira-kira:
   - **50% Low**, **30% Medium**, **20% High**
   - Dokumentasikan target ini.
3. Flip acak **5–8% label** agar ada label "sulit".
4. Aturan baseline rule-based **HARUS berbeda** dari rumus label (misal: baseline hanya memakai `attendance_rate_30d` dan `consecutive_absences` dengan threshold sederhana).

> ⚠️ **Pernyataan wajib di docs:** Label berasal dari proses synthetic, bukan ground truth operasional.

---

### A4. Protokol Pelatihan & Evaluasi

#### Split & Cross-Validation
- Split **stratified 80/20** DAN **grouped per customer** (satu customer tidak boleh muncul di train sekaligus test).
- Jika satu customer punya banyak snapshot (beberapa `reference_date`), gunakan `GroupKFold` / `GroupShuffleSplit`.

#### Pipeline
```
ColumnTransformer(
    imputer + scaler  → numerik
    OneHotEncoder     → kategorikal
) → Model
```
Disimpan sebagai **satu artefak joblib** agar inference identik dengan training.

#### Model yang Dibandingkan
| Model | Keterangan |
|-------|------------|
| `DummyClassifier (most_frequent)` | Baseline naif |
| Baseline rule-based | Hanya `attendance_rate_30d` + `consecutive_absences`, threshold sederhana |
| Logistic Regression | `class_weight='balanced'` |
| Random Forest | `class_weight='balanced'` |

Gunakan **stratified/group k-fold CV** + tuning ringan (GridSearch/RandomizedSearch kecil).

#### Metrik
- Accuracy
- Precision / Recall / F1 per kelas
- Macro-F1
- Confusion matrix
- **Recall kelas `High`** → metrik prioritas (False Negative High = customer penting terlewat)

#### Kriteria Pemilihan Model
- **Macro-F1 tertinggi**, dengan recall `High` minimal tidak lebih rendah dari baseline.
- Tulis alasan pemilihan di `docs/MODEL_EVALUATION.md`.

#### Sanity Check
- Jika akurasi test > 97%: **curiga leakage** → selidiki dan perbaiki generator.
- Laporkan gap: train vs CV vs test.

#### Interpretabilitas
- Hitung **permutation importance** (Random Forest) atau **koefisien** (Logistic Regression).

---

### A5. Kontrak Inference (`src/ml/predict.py` dan endpoint `/predict`)

**Input:** `customer_id`

Backend menghitung fitur dari database menggunakan **fungsi yang sama** dengan yang dipakai saat training (satu modul `feature_engineering` bersama).

**Output JSON:**
```json
{
  "customer_id": "...",
  "priority": "High",
  "probabilities": {
    "Low": 0.10,
    "Medium": 0.25,
    "High": 0.65
  },
  "top_factors": [
    "3 absen berturut-turut",
    "tingkat kehadiran 30 hari: 25%",
    "2 reminder terakhir tidak direspons"
  ],
  "model_version": "..."
}
```

- `top_factors`: berasal dari fitur yang paling berpengaruh (aturan sederhana berbasis nilai fitur), dalam **Bahasa Indonesia**, untuk ditampilkan ke admin di UI sebagai alasan prioritas.
- Simpan hasil ke tabel `predictions`.
- **Muat model sekali saat startup**, bukan setiap request.
- **Cold start handling:** customer tanpa riwayat → kembalikan `Low`/`Medium` dengan catatan `"riwayat belum cukup"`.

---

## B. Generative AI: Draft Pesan

### B1. Input ke Prompt Builder

Input berupa **struktur data**, bukan teks mentah:

| Field | Keterangan |
|-------|------------|
| `nama_customer` | Panggilan |
| `persona` | `ibu-ibu` / `lansia` / `menengah_atas` |
| `priority` | `Low` / `Medium` / `High` |
| `top_factors` | Hanya untuk konteks internal (jangan bocor ke customer) |
| `nama_kelas` | Nama kelas yang dijadwalkan |
| `tanggal_jam` | Tanggal & jam kelas |
| `pelatih` | Nama pelatih |
| `tipe_pesan` | `reminder_kelas` / `follow_up_absen` / `follow_up_tidak_merespons` |
| `tanggal_pesan_terakhir` | Tanggal pesan reminder/follow-up terakhir |

---

### B2. Aturan Prompt (System Instruction)

#### Umum
- Bahasa Indonesia.
- Siap kirim lewat WhatsApp.
- Maksimal **~60–80 kata**, tanpa markdown.

#### Gaya per Persona
| Persona | Gaya |
|---------|------|
| `ibu-ibu` | Hangat, akrab, sapaan "Ibu"/"Bu", emoji maksimal 1–2 |
| `lansia` | Sangat sopan, kalimat pendek dan jelas, tanpa singkatan/jargon, tanpa emoji atau maksimal 1, hindari kesan terburu-buru |
| `menengah_atas` | Profesional, ringkas, sopan, tanpa emoji berlebihan |

#### Intensitas per Prioritas
| Prioritas | Isi Pesan |
|-----------|-----------|
| `Low` | Reminder ringan berisi detail kelas |
| `Medium` | Reminder + menanyakan kabar/kendala dengan ramah |
| `High` | Lebih personal dan proaktif (tanya kabar, tawarkan bantuan atau reschedule), tetap tidak menekan atau menyalahkan |

#### ⛔ Larangan Keras
1. Jangan menyebut label prioritas, "risiko", "model", "AI", skor, atau analisis apa pun kepada customer.
2. Jangan menyebut jumlah absen dengan nada menyalahkan/menghakimi.
3. Jangan mengarang fakta, harga, promo, diskon, atau jadwal selain yang diberikan.
4. Jangan memberi klaim kesehatan/medis, terutama untuk lansia.
5. Jangan memakai nada rasa bersalah atau urgensi palsu.

#### Ketentuan Data
- Gunakan **hanya** data yang diberikan. Jika data tidak ada, jangan disebut.
- Sertakan **1–2 contoh few-shot per persona** di prompt.

---

### B3. Perilaku Sistem

| Aspek | Ketentuan |
|-------|-----------|
| Pemanggilan | Gemini dipanggil **hanya dari backend** |
| Model | Dari env var `GEMINI_MODEL` |
| Temperature | Sedang (~0.7) |
| Timeout & retry | Terbatas, dengan exponential backoff |
| Caching draft | Draft disimpan ke `reminders.draft_message`; jika sudah ada, kembalikan yang tersimpan kecuali `regenerate=true` |
| Fallback | Jika Gemini gagal (429/timeout/respons kosong): kembalikan **template statis** per `persona × tipe_pesan` dengan flag `"source": "template_fallback"` dan pesan jelas di UI |
| Post-check validasi | Tolak/regenerate sekali jika output mengandung **kata terlarang** (mis. "prioritas", "risiko", "AI", "model", "skor"), kosong, atau terlalu panjang |
| Draft vs final | Admin selalu bisa mengedit; simpan `final_message` **terpisah** dari `draft_message` |

---

### B4. Evaluasi Kualitas Draft (`docs/PROMPT_ENGINEERING.md`)

#### Tabel Uji
Minimal **3 persona × 3 prioritas = 9 skenario**, tampilkan:
- Input
- Output
- Penilaian rubrik 1–5:
  - Kesesuaian nada
  - Kejelasan info kelas
  - Tidak ada kebocoran label
  - Tidak ada fakta karangan
  - Kesiapan kirim

#### Iterasi Prompt
Catat minimal **2 iterasi prompt** (v1 → v2) beserta masalah yang ditemukan dan perbaikannya.

#### Unit Test
- Test untuk **post-check kata terlarang**.
- Test untuk **fallback template**.

---

## C. Deliverable AI

| Kategori | File |
|----------|------|
| Notebooks | `notebooks/01_eda.ipynb`, `notebooks/02_modeling.ipynb` |
| ML modules | `src/ml/feature_engineering.py`, `src/ml/train.py`, `src/ml/evaluate.py`, `src/ml/predict.py` |
| Model artefak | Artefak joblib + metadata versi |
| API services | `src/api/services/prompt_builder.py`, `src/api/services/gemini_client.py`, `src/api/services/draft_service.py` |
| Dokumentasi | `docs/MODEL_EVALUATION.md`, `docs/PROMPT_ENGINEERING.md` |
| Tests | `tests/` untuk predict dan draft service |
