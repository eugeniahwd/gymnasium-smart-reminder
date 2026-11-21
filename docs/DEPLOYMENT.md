# Deployment

Urutan: **(1) Supabase siap → (2) API di Render → (3) UI di Streamlit Community Cloud → (4) sambungkan → (5) cek
sebelum demo.** Semua layanan memakai paket gratis. Secret hanya diisi di dashboard, tidak pernah di repo.

Prasyarat: repo sudah di-push ke GitHub dan `python -m pytest tests -q` lolos di lokal.

## 1. Database (Supabase)

1. Tabel dibuat dengan menjalankan isi `sql/migrations/001_init.sql` di **Supabase → SQL Editor** (sekali saja).
2. Isi data dari lokal (memakai `DATABASE_URL` di `.env`):
   ```powershell
   python -m src.data_generation.seed_db      # sekali: data synthetic 30 Jun - 30 Sep 2026
   python -m src.data_generation.seed_demo    # sebelum SETIAP demo: perpanjang data sampai hari ini
   ```
3. Ambil connection string **Session pooler** (port 5432): Supabase → Project Settings → Database → Connection
   string → *Session pooler*. Pooler mendukung IPv4, sedangkan koneksi langsung `db.<ref>.supabase.co` hanya
   IPv6. Kode otomatis memakai driver psycopg2 (`normalize_db_url`).
4. Supabase free **ter-pause setelah 1 minggu tidak aktif**. Jika ter-pause, buka dashboard project lalu klik
   *Restore*; API membalas 503 `database_unavailable` selama database tidak bisa dihubungi.

## 2. API di Render

### Cara A — Blueprint (disarankan)

`render.yaml` di root repo sudah berisi konfigurasi service:

| Pengaturan | Nilai |
|---|---|
| Runtime / plan / region | Python, `free`, `frankfurt` (dekat database Supabase `eu-west-1`) |
| Build command | `pip install -r requirements.txt` (dependensi API saja, versi dipin) |
| Start command | `uvicorn src.api.main:app --host 0.0.0.0 --port $PORT` |
| Health check | `/health` |
| `PYTHON_VERSION` | `3.12.10` — **wajib**: default Render untuk service baru adalah 3.14, sedangkan model dilatih dengan Python 3.12 + scikit-learn 1.9.1 |
| `GEMINI_MODEL`, `CORS_ORIGINS`, `LOG_LEVEL` | sudah terisi (bisa diubah di dashboard) |
| `DATABASE_URL`, `GEMINI_API_KEY` | `sync: false` → **diisi saat membuat Blueprint** |

Langkah:

1. Buka <https://render.com> → *Sign up* dengan akun GitHub.
2. Dashboard → **New → Blueprint** → pilih repo ini → Render membaca `render.yaml`.
3. Isi `DATABASE_URL` (sama dengan di `.env`) dan `GEMINI_API_KEY`. Klik **Apply** / **Deploy Blueprint**.
4. Tunggu build selesai (beberapa menit). URL service berbentuk `https://gymnasium-api-xxxx.onrender.com`.
5. Buka `https://<url-render>/health`. Harus tampil:
   `{"status": "ok", "db_connected": true, "model_loaded": true, "model_version": "lr-20261031-v1"}`.
   Dokumentasi interaktif ada di `https://<url-render>/docs`.

### Cara B — Web Service manual

Dashboard → **New → Web Service** → pilih repo → isi nilai yang sama seperti tabel di atas (Language *Python 3*,
Instance type *Free*), lalu tambahkan environment variable `PYTHON_VERSION=3.12.10`, `DATABASE_URL`,
`GEMINI_API_KEY`, `GEMINI_MODEL=gemini-3.5-flash-lite`, `CORS_ORIGINS`.

### Masalah umum

| Gejala | Penyebab dan solusi |
|---|---|
| Build gagal memasang scikit-learn/numpy | `PYTHON_VERSION` belum diisi (Render memakai 3.14). Isi `3.12.10`, lalu *Manual Deploy*. |
| `/health` → `model_loaded: false` | Versi scikit-learn runtime berbeda dari `model_metadata.json`. Jangan ubah versi di `requirements.txt`. |
| `/health` → `db_connected: false`, endpoint lain 503 | `DATABASE_URL` salah, bukan Session pooler, atau project Supabase ter-pause. |
| Draft selalu "template cadangan" | `GEMINI_API_KEY` kosong/salah atau kuota habis (warning di UI menjelaskan sebabnya). |
| Request pertama lama (±1 menit) | Normal: Render free tidur setelah 15 menit tanpa trafik. |

Setiap `git push` ke branch utama memicu deploy ulang otomatis (`autoDeployTrigger: commit`).

## 3. UI di Streamlit Community Cloud

1. Buka <https://share.streamlit.io> → masuk dengan akun GitHub.
2. **Create app** → *Yup, I have an app* → isi repository, branch `main`, file path **`src/ui/app.py`**.
3. Klik **Advanced settings**:
   - Python version: **3.12**.
   - Secrets (format TOML; URL tanpa garis miring di akhir):
     ```toml
     API_BASE_URL = "https://gymnasium-api-xxxx.onrender.com"
     ```
4. **Deploy**. Dependensi diambil dari `src/ui/requirements.txt` secara otomatis (Community Cloud mencari file
   dependensi di folder file utama lebih dulu, baru root repo), sehingga scikit-learn tidak ikut terpasang.
5. Setelah terbuka, sidebar harus menampilkan
   `Status API: ok · Database: terhubung · Model: lr-20261031-v1`. Jika API sedang tidur, spinner menampilkan
   "API sedang bangun, bisa memakan sekitar 1 menit".

Mengubah secret nanti: app → **⋮ → Settings → Secrets**.

## 4. Menyambungkan dan merapikan

1. Render → service → **Environment** → `CORS_ORIGINS` = `https://<nama-app>.streamlit.app` (pisahkan dengan koma
   bila lebih dari satu) → Save. UI memanggil API dari server Streamlit, jadi ini hanya relevan bila API diakses
   langsung dari browser.
2. Isi tabel URL di `README.md`, tambahkan tangkapan layar ke `docs/screenshots/`, commit, push.

## 5. Daftar periksa sebelum demo / penilaian

- [ ] Project Supabase aktif (tidak ter-pause).
- [ ] `python -m src.data_generation.seed_demo` dijalankan hari itu (agar "Reminder Hari Ini" berisi data).
- [ ] Buka `https://<url-render>/health` ±1 menit sebelum demo untuk membangunkan API.
- [ ] Buka UI, cek status di sidebar, coba satu kali *Generate Draft*.
- [ ] Jika Gemini membalas 429 (kuota habis), draft memakai template cadangan dengan warning — tetap bisa didemokan.
- [ ] Kelas hanya Senin–Sabtu: jika demo hari Minggu, pilih tanggal lain di pemilih tanggal.

## Keamanan

- `.env` dan `.streamlit/secrets.toml` ada di `.gitignore`. Audit 21 Nov 2026: tidak ada API key atau password di
  file maupun riwayat git (hanya placeholder di `.env.example`).
- Jika key bocor: hapus key di Google AI Studio dan buat yang baru; reset password database di Supabase; perbarui
  `.env` lokal dan environment variable di Render.
- **Risiko diketahui:** API publik tanpa autentikasi (sesuai spesifikasi admin-only tanpa login). Hanya gunakan
  data synthetic di deployment ini.
