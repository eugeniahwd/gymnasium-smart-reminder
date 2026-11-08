## Menjalankan backend (Fase 3)

```bash
pip install -r requirements.txt            # pastikan fastapi, uvicorn, httpx terpasang
uvicorn src.api.main:app --reload          # buka http://localhost:8000/docs
python -m src.data_generation.seed_demo    # opsional: data demo sampai hari ini
python -m pytest tests -q
```
