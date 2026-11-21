"""Aplikasi admin Gymnasium Smart Reminder & Follow-up (Streamlit).

Jalankan lokal dari root repo (API harus sudah berjalan, default http://localhost:8000):
    streamlit run src/ui/app.py
Alamat API dibaca dari st.secrets["API_BASE_URL"] atau environment variable API_BASE_URL.
"""
from __future__ import annotations

import streamlit as st

from components import render_sidebar

st.set_page_config(page_title="Gymnasium Admin", page_icon=":material/fitness_center:", layout="wide")

PAGES = [
    st.Page("pages/reminder_hari_ini.py", title="Reminder Hari Ini", icon=":material/notifications_active:",
            default=True),
    st.Page("pages/customer.py", title="Customer", icon=":material/group:"),
    st.Page("pages/jadwal.py", title="Jadwal", icon=":material/calendar_month:"),
    st.Page("pages/riwayat.py", title="Riwayat Reminder", icon=":material/history:"),
]

navigation = st.navigation(PAGES)
render_sidebar()
navigation.run()
