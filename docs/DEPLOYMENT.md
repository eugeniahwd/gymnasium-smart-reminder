# Deployment

Ada dua opsi. **Opsi A dipakai untuk proyek ini** karena Render meminta verifikasi kartu kredit/debit, sedangkan
Streamlit Community Cloud tidak.

| | Opsi A — satu aplikasi (dipakai) | Opsi B — dua layanan |
|---|---|---|
| UI | Streamlit Community Cloud | Streamlit Community Cloud |
| API | FastAPI yang sama, dijalankan di thread latar dalam aplikasi Streamlit (127.0.0.1) | Render (web service terpisah) |
| Entrypoint Streamlit | `streamlit_app.py` (root) | `src/ui/app.py` |
| Dependensi | `requirements.txt` (root) | `src/ui/requirements.txt` (UI) + `requirements.txt` (Render) |
| Butuh kartu | Tidak | Render meminta verifikasi kartu |
| Swagger `/docs` publik | Tidak (API hanya bisa diakses UI; `/docs` tersedia saat menjalankan lokal) | Ya |

Pada Opsi A, UI tetap memanggil API lewat HTTP (`api_client.py` → `http://127.0.0.1:8000`), jadi kode UI dan API
tidak berubah dan aturan "UI tidak mengakses database/Gemini langsung" tetap berlaku. Hanya prosesnya yang digabung
(`embedded_api.py`).

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
   *Restore*; aplikasi menampilkan "Database tidak dapat dihubungi" (503 `database_unavailable`) selama itu.

## 2. Opsi A — Streamlit Community Cloud (UI + API, tanpa kartu)

1. Buka <https://share.streamlit.io> → masuk dengan akun GitHub (izinkan akses ke repo).
2. **Create app** → *Yup, I have an app* → isi repository `eugeniahwd/gymnasium-smart-reminder`, branch `main`,
   file path **`streamlit_app.py`**.
3. Klik **Advanced settings**:
   - Python version: **3.12** (model dilatih dengan Python 3.12 + scikit-learn 1.9.1).
   - Secrets (format TOML; salin nilai dari `.env` lokal, beri tanda kutip):
     ```toml
     DATABASE_URL = "postgresql://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres"
     GEMINI_API_KEY = "<api-key-dari-google-ai-studio>"
     GEMINI_MODEL = "gemini-3.5-flash-lite"
     ```
     **Jangan** mengisi `API_BASE_URL` (jika diisi, aplikasi memakai API eksternal dan API internal tidak dinyalakan).
4. **Deploy**. Pemasangan dependensi dari `requirements.txt` memakan beberapa menit.
5. Setelah terbuka, muncul spinner "Menyalakan API..." (beberapa detik sampai ±1 menit), lalu sidebar harus
   menampilkan `API: http://127.0.0.1:8000` dan `Status API: ok · Database: terhubung · Model: lr-20261031-v1`.

Mengubah secret nanti: app → **⋮ → Settings → Secrets** (aplikasi dimulai ulang otomatis).

### Masalah umum (Opsi A)

| Gejala | Penyebab dan solusi |
|---|---|
| "API internal gagal dinyalakan" | Lihat log aplikasi (**Manage app** di pojok kanan bawah). Biasanya `DATABASE_URL` salah format di Secrets. |
| Sidebar: `Database: TIDAK terhubung` | `DATABASE_URL` salah/bukan Session pooler, atau project Supabase ter-pause. |
| Sidebar: `Model: tidak dimuat` | Versi Python bukan 3.12 atau versi scikit-learn berubah. Pilih Python 3.12 (hapus app lalu deploy ulang jika perlu). |
| Draft selalu "template cadangan" | `GEMINI_API_KEY` kosong/salah atau kuota habis (warning di UI menjelaskan sebabnya). |
| Halaman "This app has gone to sleep" | Normal setelah 12 jam tanpa pengunjung: klik **Yes, get this app back up!** lalu tunggu. |

## 3. Opsi B — API di Render + UI di Streamlit (butuh verifikasi kartu di Render)

`render.yaml` sudah berisi konfigurasi: Python, plan `free`, region `frankfurt`, build `pip install -r
requirements.txt`, start `uvicorn src.api.main:app --host 0.0.0.0 --port $PORT`, health check `/health`,
`PYTHON_VERSION=3.12.10` (wajib: default Render untuk service baru adalah 3.14), `DATABASE_URL` dan
`GEMINI_API_KEY` diisi saat pembuatan (`sync: false`).

1. Render → **New → Blueprint** (atau **New → Web Service**, Instance type *Free*, nilai sama) → pilih repo → isi
   secret → deploy → cek `https://<url-render>/health`.
2. Streamlit Community Cloud → file path **`src/ui/app.py`** → Secrets `API_BASE_URL = "https://<url-render>"`.
3. Render free tidur setelah 15 menit tanpa trafik (bangun ±1 menit); UI menampilkan "API sedang bangun".

## 4. Daftar periksa sebelum demo / penilaian

- [ ] Project Supabase aktif (tidak ter-pause).
- [ ] `python -m src.data_generation.seed_demo` dijalankan hari itu (agar "Reminder Hari Ini" berisi data).
- [ ] Buka URL aplikasi beberapa menit sebelum demo (bangunkan bila tidur), cek status di sidebar.
- [ ] Coba satu kali *Generate Draft*. Jika Gemini membalas 429 (kuota habis), draft memakai template cadangan
      dengan warning — tetap bisa didemokan.
- [ ] Kelas hanya Senin–Sabtu: jika demo hari Minggu, pilih tanggal lain di pemilih tanggal.
- [ ] Untuk menunjukkan Swagger (`/docs`), jalankan API lokal: `uvicorn src.api.main:app --reload`.

## Keamanan

- `.env` dan `.streamlit/secrets.toml` ada di `.gitignore`; secret hanya diisi di dashboard. Audit 21 Nov 2026:
  tidak ada API key atau password di file maupun riwayat git (hanya placeholder di `.env.example`).
- Jika key bocor: hapus key di Google AI Studio dan buat yang baru; reset password database di Supabase; perbarui
  `.env` lokal dan Secrets di Streamlit (atau env var di Render).
- **Risiko diketahui:** aplikasi admin tidak memakai login (sesuai spesifikasi admin-only tanpa autentikasi), jadi
  siapa pun yang tahu URL aplikasi bisa memakainya. Pada Opsi A, API tidak terbuka ke internet (hanya 127.0.0.1),
  tetapi UI-nya publik. Hanya gunakan data synthetic di deployment ini.
