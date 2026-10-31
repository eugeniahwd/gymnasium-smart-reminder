# AGENTS.md — Aturan Proyek Gymnasium Smart Reminder & Follow-up

> **Dokumen ini mengikat untuk semua fase pengerjaan proyek.** Setiap agen/engineer yang bekerja pada repo ini wajib membaca dan mematuhi aturan di bawah.

---

## 1. Ringkasan

Aplikasi web untuk **ADMIN Gymnasium** (gym & private coaching, target ibu-ibu, lansia, segmen menengah ke atas) untuk mengelola customer, jadwal kelas, reminder, dan status follow-up. Model ML yang dilatih sendiri mengklasifikasikan prioritas follow-up customer (Low/Medium/High). Generative AI (Gemini API) membuat draft pesan reminder/follow-up sesuai prioritas dan persona customer. Admin mengedit dan mengirim pesan sendiri lewat WhatsApp, lalu memperbarui status secara manual.

**Alur end-to-end:**
Reminder dibuat dengan status `Scheduled` → Admin melihat daftar reminder hari ini beserta prioritas dari AI → Admin klik "Generate Draft" → mengedit pesan → mengirimnya lewat WhatsApp → mengubah status menjadi `Sent` → setelah itu status menjadi `Responded` atau `No Response` → riwayatnya tersimpan.

---

## 2. Batasan (WAJIB Dipatuhi)

- Pengguna hanya **admin**. Customer tidak login. Tidak perlu sistem auth customer.
- Pesan **TIDAK dikirim otomatis**. Tidak ada integrasi API WhatsApp maupun Rezerv.
  - Tombol link `wa.me` yang membuka WhatsApp dengan teks terisi boleh, tetapi pengiriman tetap manual oleh admin.
- Data jadwal dikelola di aplikasi ini.
- Data **synthetic**, jadi hasil model diposisikan sebagai **PROTOTYPE**, bukan klaim akurasi kondisi nyata. Tulis ini jelas di README, dokumentasi evaluasi, dan UI (disclaimer kecil).
- Kode dibuat **dari nol** (bukan fork). Lisensi MIT.
- **Side quest** (UI responsif, filter/search, RAG panduan layanan, model generasi open-source lokal) **HANYA** dikerjakan jika MVP sudah stabil dan diminta eksplisit.

---

## 3. Tech Stack (Jangan Diganti)

| Layer | Teknologi |
|-------|-----------|
| Data & ML | Python, Pandas, NumPy, Scikit-learn, Matplotlib/Seaborn, Jupyter Notebook, Joblib |
| Backend | FastAPI (REST API + Swagger/OpenAPI otomatis) |
| UI | Streamlit |
| Database | PostgreSQL via Supabase |
| Generative AI | Gemini API (dipanggil **HANYA** dari backend) |
| Deployment | Render (API) + Streamlit Community Cloud (UI) |
| Version Control | Git/GitHub |

---

## 4. Keamanan & Kualitas

- API key (Gemini, Supabase) **hanya** lewat environment variable. Buat `.env.example`, tambahkan `.env` ke `.gitignore`, **JANGAN hardcode secret apa pun**.
- Nama model Gemini dibaca dari env var `GEMINI_MODEL`, jangan di-hardcode.
- Validasi input dengan **Pydantic**. Penanganan error dengan pesan jelas.
- Tulis kode **bersih, modular, type hints, dan docstring singkat**.

---

## 5. Struktur Repo yang Diharapkan

```
gymnasium-smart-reminder/
├── README.md
├── LICENSE (MIT)
├── .gitignore
├── .env.example
├── requirements.txt
├── AGENTS.md
├── data/
│   ├── raw/
│   └── processed/
├── notebooks/
│   ├── 01_eda.ipynb
│   └── 02_modeling.ipynb
├── src/
│   ├── data_generation/
│   ├── ml/
│   │   └── (feature_engineering, train, evaluate, predict, artefak model)
│   ├── api/
│   │   └── (main.py, routers, schemas, services, db)
│   └── ui/
│       └── (app Streamlit + pages)
├── docs/
│   ├── AI_SPEC.md
│   ├── ARCHITECTURE.md
│   ├── DATABASE_SCHEMA.md
│   ├── SYNTHETIC_DATA.md
│   ├── MODEL_EVALUATION.md
│   ├── PROMPT_ENGINEERING.md
│   ├── API_DOCS.md
│   ├── ADMIN_GUIDE.md
│   ├── ASSUMPTIONS.md
│   ├── CREDITS_AND_LICENSES.md
│   └── DEPLOYMENT.md
├── sql/
│   └── migrations/
└── tests/
```

---

## 6. Definition of Done per Fase

Di akhir setiap fase:
1. Tampilkan **checklist** item yang selesai, yang belum, dan asumsi yang diambil.
2. **Jangan klaim selesai tanpa bukti** — jalankan kode/test dan tunjukkan hasilnya.
3. Laporkan **angka metrik aktual**, jangan mengarang.
4. Setelah fase selesai, **BERHENTI** dan tunggu perintah fase berikutnya.

---

## 7. Rencana Fase (Konteks Saja — Jangan Dikerjakan Sebelum Diminta)

| Fase | Deskripsi |
|------|-----------|
| Fase 1 | Skema DB + dataset synthetic |
| Fase 2 | Preprocessing, EDA, model ML |
| Fase 3 | Backend FastAPI + Supabase |
| Fase 4 | Integrasi Gemini + persona |
| Fase 5 | UI Streamlit |
| Fase 6 | Testing, deployment, dokumentasi |

---

## 8. Aturan Ambiguitas

Jika ada hal yang ambigu:
1. Tulis asumsimu di `docs/ASSUMPTIONS.md`.
2. Lanjut kerjakan.
3. Jangan berhenti untuk bertanya **kecuali benar-benar buntu**.
