# Deployment (draf - dilengkapi di Fase 6)

## API di Render (Web Service)

| Pengaturan | Nilai |
|---|---|
| Runtime | Python 3 (set env `PYTHON_VERSION=3.12.x`; samakan dengan versi lokal) |
| Build command | `pip install -r requirements.txt` |
| Start command | `uvicorn src.api.main:app --host 0.0.0.0 --port $PORT` |
| Health check path | `/health` |

Environment variable di dashboard Render (jangan di repo): `DATABASE_URL` (Session pooler Supabase),
`CORS_ORIGINS` (URL Streamlit), `GEMINI_API_KEY`, `GEMINI_MODEL` (Fase 4).

Catatan:
- File model `src/ml/artifacts/priority_model.joblib` **harus ikut ter-commit** (sudah dikecualikan dari `.gitignore`).
- Versi scikit-learn di `requirements.txt` harus sama dengan saat training. Jika berbeda, `/health` menampilkan
  `model_loaded=false`; jalankan ulang `python -m src.ml.train`, commit artefak, lalu deploy ulang.
- Free tier Render tidur setelah tidak aktif (cold start sekitar 1 menit): buka `/health` sebelum demo.
- Supabase free ter-pause setelah 1 minggu tidak aktif: cek project sebelum penilaian.

## Sebelum demo

```bash
python -m src.data_generation.seed_demo    # menyegarkan data "hari ini" (butuh DATABASE_URL)
```
