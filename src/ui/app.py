"""Aplikasi admin Gymnasium Smart Reminder & Follow-up (Streamlit).

Jalankan lokal dari root repo (API harus sudah berjalan, default http://localhost:8000):
    streamlit run src/ui/app.py
Alamat API dibaca dari st.secrets["API_BASE_URL"] atau environment variable API_BASE_URL.
Deploy satu-aplikasi (UI + API) di Streamlit Community Cloud memakai `streamlit_app.py` di root repo.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import streamlit as st

from components import render_sidebar

PAGES_DIR = Path(__file__).resolve().parent / "pages"  # path absolut: bisa dipanggil dari entrypoint lain


def main(prepare: Callable[[], None] | None = None) -> None:
    """Konfigurasi halaman, (opsional) siapkan API, lalu jalankan navigasi multipage."""
    st.set_page_config(page_title="Gymnasium Admin", page_icon=":material/fitness_center:", layout="wide")
    if prepare is not None:
        prepare()
    pages = [
        st.Page(PAGES_DIR / "reminder_hari_ini.py", title="Reminder Hari Ini", icon=":material/notifications_active:",
                default=True),
        st.Page(PAGES_DIR / "customer.py", title="Customer", icon=":material/group:"),
        st.Page(PAGES_DIR / "jadwal.py", title="Jadwal", icon=":material/calendar_month:"),
        st.Page(PAGES_DIR / "riwayat.py", title="Riwayat Reminder", icon=":material/history:"),
    ]
    navigation = st.navigation(pages)
    render_sidebar()
    navigation.run()


if __name__ == "__main__":  # `streamlit run src/ui/app.py` menjalankan file ini sebagai __main__
    main()
