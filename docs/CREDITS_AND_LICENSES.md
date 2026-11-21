# Kredit dan Lisensi

Kode proyek ini ditulis dari nol (bukan fork) dan dirilis dengan **lisensi MIT** (`LICENSE`).
Lisensi library di bawah diverifikasi dari metadata paket yang terpasang (`importlib.metadata`, 21 Nov 2026).

## Library Python

| Library | Versi | Lisensi | Dipakai untuk |
|---|---|---|---|
| [FastAPI](https://github.com/fastapi/fastapi) | 0.162.0 | MIT | REST API + Swagger/OpenAPI |
| [Starlette](https://github.com/Kludex/starlette) | 1.10.0 | BSD-3-Clause | Fondasi FastAPI, TestClient |
| [Uvicorn](https://uvicorn.dev/) | 0.54.0 | BSD-3-Clause | Server ASGI |
| [Pydantic](https://github.com/pydantic/pydantic) | 2.14.2 | MIT | Validasi input/output |
| [SQLAlchemy](https://www.sqlalchemy.org) | 2.1.6 | MIT | ORM dan koneksi database |
| [psycopg2-binary](https://psycopg.org/) | 2.9.13 | LGPL (dengan pengecualian) | Driver PostgreSQL (dipakai sebagai dependensi, tidak dimodifikasi) |
| [python-dotenv](https://github.com/theskumar/python-dotenv) | 1.2.4 | BSD-3-Clause | Membaca `.env` lokal |
| [HTTPX](https://github.com/encode/httpx) | 0.28.1 | BSD-3-Clause | Klien HTTP (SDK Gemini, tes) |
| [google-genai](https://github.com/googleapis/python-genai) | 2.34.0 | Apache-2.0 | SDK Gemini API |
| [pandas](https://pandas.pydata.org) | 3.1.0 | BSD-3-Clause | Pengolahan data, fitur |
| [NumPy](https://numpy.org) | 2.5.4 | BSD-3-Clause (beserta komponen 0BSD, MIT, Zlib, CC0-1.0) | Komputasi numerik |
| [scikit-learn](https://scikit-learn.org) | 1.9.1 | BSD-3-Clause | Model prioritas, evaluasi |
| [joblib](https://joblib.readthedocs.io) | 1.6.0 | BSD-3-Clause | Menyimpan/memuat artefak model |
| [tzdata](https://github.com/python/tzdata) | 2026.6 | Apache-2.0 | Zona waktu Asia/Jakarta |
| [Streamlit](https://streamlit.io) | 1.66.1 | Apache-2.0 | UI admin, AppTest |
| [Requests](https://github.com/psf/requests) | 2.34.2 | Apache-2.0 | Klien HTTP UI → API |
| [Matplotlib](https://matplotlib.org) | 3.11.2 | PSF-based (Matplotlib License) | Grafik EDA dan evaluasi |
| [seaborn](https://github.com/mwaskom/seaborn) | 0.13.2 | BSD-3-Clause | Grafik EDA |
| [Jupyter](https://jupyter.org) | 1.1.1 | BSD-3-Clause | Notebook |
| [pytest](https://docs.pytest.org) | 9.2.0 | MIT | Pengujian |

Ikon di UI memakai Material Symbols bawaan Streamlit (Google, Apache-2.0).

## Model dan data

| Komponen | Sumber | Ketentuan |
|---|---|---|
| Model prioritas (Logistic Regression, `lr-20261031-v1`) | Dilatih sendiri di proyek ini dengan scikit-learn | Bagian dari proyek (MIT) |
| Model generatif `gemini-3.5-flash-lite` (atau `GEMINI_MODEL`) | Google, diakses lewat Gemini API | [Gemini API Terms of Service](https://ai.google.dev/gemini-api/terms); free tier dapat memakai input untuk perbaikan produk Google, sehingga hanya data synthetic yang dikirim |
| Dataset | **Synthetic**, dibuat oleh `src/data_generation/generate.py` (seed 42) | Bagian dari proyek (MIT). Nama customer adalah kombinasi acak nama Indonesia umum dan nomor WhatsApp berformat fiktif `628990…`; tidak ada data pribadi sungguhan |

Tidak ada dataset, model pra-latih, atau kode pihak ketiga lain yang disalin ke repo ini.

## Layanan

| Layanan | Dipakai untuk | Paket |
|---|---|---|
| [Supabase](https://supabase.com) | PostgreSQL terkelola | Free |
| [Render](https://render.com) | Opsional: hosting API terpisah (`render.yaml`) | Free web service (meminta verifikasi kartu) |
| [Streamlit Community Cloud](https://streamlit.io/cloud) | Hosting aplikasi (UI + API internal) | Gratis |
| [Google AI Studio](https://aistudio.google.com) | API key Gemini | Free tier |
| [GitHub](https://github.com) | Version control | Gratis |
| WhatsApp (`wa.me`) | Link pembuka chat dengan teks terisi; pengiriman manual oleh admin | Tanpa integrasi API |

## Referensi

- Dokumentasi resmi FastAPI, SQLAlchemy, Pydantic, scikit-learn, Streamlit (multipage `st.navigation`, AppTest,
  dependensi Community Cloud), SDK `google-genai` (generate_content, error, HttpOptions), Gemini API (daftar model,
  thinking dan `max_output_tokens`), Render (Blueprint, versi Python, free tier), dan Supabase (connection pooler).
- Pedoman *permutation importance* dan *StratifiedGroupKFold* dari dokumentasi scikit-learn.
