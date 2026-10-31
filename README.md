# Gymnasium Smart Reminder & Follow-up

> ⚠️ **DISCLAIMER:** Aplikasi ini adalah **PROTOTYPE** yang dikembangkan dengan **data synthetic**. Model ML dan semua hasil prediksi **BUKAN** representasi kondisi nyata dan tidak boleh digunakan sebagai dasar keputusan bisnis tanpa validasi data operasional sesungguhnya.

---

## Deskripsi

Aplikasi web untuk **admin Gymnasium** (gym & private coaching) untuk mengelola customer, jadwal kelas, reminder, dan status follow-up. Fitur utama:

- 📋 **Manajemen Customer** — data member, persona, riwayat kehadiran
- 📅 **Jadwal Kelas** — manajemen jadwal dan kehadiran
- 🔔 **Reminder & Follow-up** — daftar reminder harian dengan status
- 🤖 **Prioritas ML** — klasifikasi Low / Medium / High per customer (Logistic Regression / Random Forest)
- ✍️ **Draft Pesan AI** — Gemini API menghasilkan draft WhatsApp sesuai persona dan prioritas
- 📤 **Pengiriman Manual** — admin mengedit dan mengirim via WhatsApp (tidak ada pengiriman otomatis)

---

## Tech Stack

| Layer | Teknologi |
|-------|-----------|
| Data & ML | Python, Pandas, NumPy, Scikit-learn, Joblib |
| Backend | FastAPI + Uvicorn |
| UI | Streamlit |
| Database | PostgreSQL (Supabase) |
| Generative AI | Google Gemini API |
| Deployment | Render (API) + Streamlit Community Cloud (UI) |

---

## Struktur Repo

```
gymnasium-smart-reminder/
├── AGENTS.md               # Aturan proyek (mengikat semua fase)
├── README.md
├── LICENSE
├── .gitignore
├── .env.example
├── requirements.txt
├── data/
│   ├── raw/                # Dataset synthetic mentah
│   └── processed/          # Data yang sudah diproses
├── notebooks/              # Eksperimen Jupyter
├── src/
│   ├── data_generation/    # Generator dataset synthetic
│   ├── ml/                 # Feature engineering, training, evaluasi, inferensi
│   ├── api/                # FastAPI backend
│   └── ui/                 # Streamlit frontend
├── docs/                   # Dokumentasi lengkap
├── sql/migrations/         # Migrasi database
└── tests/                  # Unit & integration tests
```

---

## Quick Start (akan diperbarui per fase)

```bash
# 1. Clone repo
git clone <repo-url>
cd gymnasium-smart-reminder

# 2. Salin dan isi environment variables
cp .env.example .env
# Edit .env dengan nilai yang sesuai

# 3. Install dependencies
pip install -r requirements.txt
```

---

## Dokumentasi

Lihat folder [`docs/`](docs/) untuk:
- [`AI_SPEC.md`](docs/AI_SPEC.md) — Spesifikasi model ML dan Generative AI
- [`ARCHITECTURE.md`](docs/ARCHITECTURE.md) — Arsitektur sistem
- [`DATABASE_SCHEMA.md`](docs/DATABASE_SCHEMA.md) — Skema database
- [`DEPLOYMENT.md`](docs/DEPLOYMENT.md) — Panduan deployment

---

## Lisensi

MIT — lihat [`LICENSE`](LICENSE).
