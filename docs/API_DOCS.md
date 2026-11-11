# Dokumentasi API

Backend: FastAPI. Dokumentasi interaktif otomatis (Swagger/OpenAPI): **`/docs`** (ReDoc: `/redoc`, skema: `/openapi.json`).

> **PROTOTYPE.** Model prioritas dilatih pada data synthetic. Pesan **tidak dikirim otomatis**: admin mengirim
> lewat WhatsApp lalu memperbarui status secara manual.

## Menjalankan lokal

```bash
# .env berisi DATABASE_URL (Supabase, Session pooler). Model dimuat dari src/ml/artifacts/.
uvicorn src.api.main:app --reload          # http://localhost:8000/docs
python -m src.data_generation.seed_demo    # opsional: lanjutkan data synthetic sampai hari ini (untuk demo)
python -m pytest tests -q
```

Konfigurasi lewat environment variable: `DATABASE_URL`, `CORS_ORIGINS` (pisahkan koma), `LOG_LEVEL`,
`APP_TIMEZONE`, `GEMINI_API_KEY`, `GEMINI_MODEL` (kosong → default di `config.py`), serta opsional
`GEMINI_TEMPERATURE` (0,7), `GEMINI_TIMEOUT_SECONDS` (20), `GEMINI_MAX_RETRIES` (2).

## Konvensi

- Waktu = waktu lokal **WIB** tanpa zona (ISO 8601, mis. `2026-11-02T09:00:00`). Waktu ber-zona dikonversi ke WIB.
- Daftar memakai pagination: `?limit=` (1-200, default 50) dan `?offset=`; respons `{items, total, limit, offset}`.
- Semua error berformat `{"detail": "<pesan Indonesia>", "code": "<kode_mesin>"}`.
- Nomor WhatsApp diterima sebagai `08...`, `+628...`, atau `628...` dan disimpan sebagai `628...`.

## Endpoint

| Method | Path | Fungsi |
|---|---|---|
| GET | `/health` | Status layanan: `status`, `db_connected`, `model_loaded`, `model_version` |
| GET / POST | `/customers` | Daftar (`q`, `persona`) / tambah customer |
| GET / PATCH / DELETE | `/customers/{id}` | Detail / ubah / hapus (beserta riwayatnya) |
| GET | `/customers/{id}/reminders` | Riwayat reminder customer (terbaru dulu) |
| GET / POST | `/schedules` | Daftar (`date_from`, `date_to`, `tipe`) / tambah jadwal |
| GET / PATCH / DELETE | `/schedules/{id}` | Detail / ubah / hapus jadwal |
| GET | `/reminders` | Daftar: `date` (`today` atau `YYYY-MM-DD`, **tanggal kelas**), `status`, `priority`, `customer_id` |
| POST | `/reminders` | Buat reminder (status `Scheduled`; prioritas terisi otomatis bila model tersedia) |
| GET | `/reminders/{id}` | Detail reminder (termasuk ringkasan customer dan jadwal) |
| GET | `/reminders/{id}/history` | Riwayat perubahan status |
| PATCH | `/reminders/{id}/status` | Ubah status (divalidasi, lihat alur di bawah) |
| PATCH | `/reminders/{id}/message` | Simpan `final_message` (hanya saat `Scheduled`) |
| POST | `/reminders/{id}/refresh-priority` | Hitung ulang prioritas dengan model ML |
| POST | `/predict` | Prediksi prioritas satu customer, hasil disimpan di tabel `predictions` |
| POST | `/generate-draft` | Draft pesan WhatsApp (Gemini, dengan template cadangan); lihat bagian di bawah |

Urutan `GET /reminders`: prioritas **High, Medium, Low, lalu tanpa prioritas**; pada prioritas sama, kelas yang
paling dekat waktunya lebih dulu.

## Alur status reminder

```mermaid
stateDiagram-v2
    [*] --> Scheduled : POST /reminders
    Scheduled --> Sent : admin mengirim via WhatsApp
    Sent --> Responded : customer membalas
    Sent --> No_Response : tidak ada balasan
    Responded --> [*]
    No_Response --> [*]
```

Aturan: hanya `Scheduled → Sent` dan `Sent → Responded | No Response`. Transisi lain (termasuk ke status yang
sama atau keluar dari status final) ditolak dengan **409** `invalid_status_transition`. `sent_at` dan
`responded_at` terisi otomatis, setiap perubahan dicatat di `reminder_status_history`. Saat menjadi `Sent`,
jika `final_message` kosong dan ada `draft_message`, draft disalin menjadi `final_message` (dikirim apa adanya).

## Draft pesan: `POST /generate-draft`

Request: `{"reminder_id": 12, "regenerate": false}`. Respons 200:

```json
{"reminder_id": 12, "draft_message": "Halo Bu Sari, ...", "draft_source": "gemini",
 "cached": false, "message_type": "reminder_kelas", "warning": null}
```

- Hanya untuk reminder berstatus `Scheduled`; selain itu **409** `draft_not_allowed`. Reminder tidak ada → **404**.
- Draft tersimpan + `regenerate=false` → draft tersimpan dikembalikan (`cached: true`) tanpa memanggil Gemini.
- Gemini gagal (429/5xx/timeout, setelah retry terbatas), `GEMINI_API_KEY` kosong, atau draft tidak lolos
  post-check setelah 1 regenerasi → tetap **200** dengan `draft_source: "template_fallback"` dan `warning`.
- Draft disimpan ke `draft_message`/`draft_source`; `final_message` tidak pernah diubah oleh endpoint ini.
  Admin menyimpan editan lewat `PATCH /reminders/{id}/message`, lalu mengirim manual lewat WhatsApp.
- Detail prompt, post-check, dan fallback: `docs/PROMPT_ENGINEERING.md`.

> Contoh di atas ilustrasi format. Respons nyata dari Gemini belum direkam karena pengujian memakai klien palsu.

## Contoh (respons nyata dari server lokal)

`GET /health`
```json
{"status": "ok", "db_connected": true, "model_loaded": true, "model_version": "lr-20261031-v1"}
```

`POST /predict` dengan `{"customer_id": 1, "reference_date": "2026-11-02"}`
```json
{
  "customer_id": 1, "reference_date": "2026-11-02", "priority": "Low",
  "probabilities": {"Low": 0.6079, "Medium": 0.3001, "High": 0.092},
  "top_factors": ["5 reminder terakhir tidak direspons", "jarang merespons reminder (30% direspons)"],
  "model_version": "lr-20261031-v1", "cold_start": false, "note": null, "prediction_id": 263
}
```
`top_factors` untuk **admin** (alasan prioritas), jangan diteruskan ke customer. Customer dengan riwayat < 3
kejadian: `cold_start: true`, `note: "riwayat belum cukup"`, prioritas dibatasi Low/Medium.

`PATCH /reminders/{id}/status` dengan `{"status": "Responded"}` saat masih `Scheduled` → **409**
```json
{"detail": "Transisi 'Scheduled' → 'Responded' tidak diizinkan. Dari 'Scheduled' hanya boleh ke 'Sent'. Alur yang valid: Scheduled → Sent → Responded / No Response.",
 "code": "invalid_status_transition"}
```

## Kode error

| HTTP | `code` | Arti |
|---|---|---|
| 404 | `not_found` | Data atau endpoint tidak ada |
| 409 | `invalid_status_transition` | Transisi status tidak valid |
| 409 | `message_locked` | Pesan tidak bisa diubah setelah `Sent` |
| 409 | `duplicate_whatsapp` | Nomor WhatsApp sudah terdaftar |
| 409 | `duplicate_reminder` | Reminder aktif yang sama (customer + kelas + jenis pesan) sudah ada |
| 409 | `draft_not_allowed` | Draft hanya bisa dibuat saat reminder berstatus `Scheduled` |
| 422 | `validation_error` | Input tidak valid (pesan merinci field) |
| 422 | `invalid_date` | Parameter `date` bukan `today` / `YYYY-MM-DD` |
| 503 | `model_unavailable` | Artefak model tidak termuat; API tetap hidup |
| 503 | `database_unavailable` | `DATABASE_URL` kosong / database tidak terjangkau |
| 500 | `internal_error` | Kesalahan tak terduga (detail hanya di log server) |
