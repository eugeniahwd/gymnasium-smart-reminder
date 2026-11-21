"""Entrypoint Streamlit Community Cloud: UI admin + API dalam SATU aplikasi (tanpa hosting API terpisah).

- Jika `API_BASE_URL` diisi (secrets/env), UI memakai API eksternal itu (mis. Render) dan API internal tidak dinyalakan.
- Jika kosong, API FastAPI dinyalakan sekali di thread latar (127.0.0.1) lalu UI memanggilnya lewat HTTP.

Secrets yang dibutuhkan (Streamlit Cloud -> App settings -> Secrets): DATABASE_URL, GEMINI_API_KEY, GEMINI_MODEL.
Dependensi: requirements.txt di root repo (file ini berada di root).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for path in (str(ROOT / "src" / "ui"), str(ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

import streamlit as st  # noqa: E402

import embedded_api  # noqa: E402
from app import main  # noqa: E402  (src/ui/app.py)


@st.cache_resource(show_spinner=False)
def _embedded_api_url() -> str:
    return embedded_api.start()


def prepare() -> None:
    st.secrets.load_if_toml_exists()  # secrets tingkat atas otomatis masuk ke os.environ (dibaca API)
    if os.environ.get("API_BASE_URL"):
        return  # pakai API eksternal
    try:
        with st.spinner("Menyalakan API... (setelah aplikasi bangun dari tidur bisa memakan sekitar 1 menit)"):
            os.environ["API_BASE_URL"] = _embedded_api_url()
    except RuntimeError as err:
        st.error(f"API internal gagal dinyalakan: {err}")
        st.stop()


main(prepare=prepare)
