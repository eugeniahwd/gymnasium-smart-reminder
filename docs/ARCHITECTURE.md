# Arsitektur Sistem

```mermaid
flowchart LR
    Admin([Admin]) --> UI[Streamlit UI<br/>Streamlit Community Cloud]
    UI -->|HTTP/JSON| API[FastAPI<br/>Render]
    API -->|SQLAlchemy| DB[(PostgreSQL<br/>Supabase)]
    API -->|joblib, dimuat sekali saat startup| ML[Model prioritas<br/>Logistic Regression]
    API -.->|Fase 4, hanya dari backend| GEM[Gemini API]
    Admin -->|kirim manual| WA[WhatsApp]
```

## Prinsip desain

- **UI tidak pernah mengakses database atau Gemini langsung**; semuanya lewat FastAPI.
- **Satu modul fitur** (`src/ml/feature_engineering.py`) dipakai untuk training dan inference, sehingga tidak ada
  train-serve skew. `/predict` menghitung fitur dari database dengan fungsi yang sama.
- **Model dimuat sekali** saat startup. Jika artefak hilang atau tidak cocok, API tetap hidup: `/health` melaporkan
  `model_loaded=false` dan `/predict` membalas 503.
- **Admin tetap mengendalikan**: pesan tidak dikirim otomatis, tidak ada integrasi API WhatsApp/Rezerv.
- **Validasi alur status di backend**, bukan hanya di UI (`src/api/services/status_flow.py`).
- **Rahasia lewat environment variable** (`.env` tidak di-commit).

## Struktur kode backend

```
src/api/
├── main.py            # create_app(), CORS, lifespan (muat model), middleware log
├── config.py          # Settings dari env
├── errors.py          # APIError + handler ({"detail","code"})
├── deps.py            # get_db, get_model
├── timeutil.py        # waktu WIB, masking nomor di log
├── db/                # engine & session (driver psycopg2), model ORM
├── schemas/           # skema Pydantic (request/response)
├── routers/           # health, customers, schedules, reminders, predict, drafts
└── services/          # status_flow (transisi), prediction_service (fitur + prediksi)
```

## Data demo

Data synthetic berakhir 30 Sep 2026. `python -m src.data_generation.seed_demo` melanjutkan timeline sampai hari
ini (jadwal, kehadiran, reminder, dan reminder `Scheduled` berprioritas) sehingga fitur dan halaman "Reminder
Hari Ini" bermakna. Skrip ini idempotent: menghapus data setelah 30 Sep lalu membuatnya ulang.
