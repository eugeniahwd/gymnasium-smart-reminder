"""Komponen Streamlit kecil yang dipakai bersama oleh halaman-halaman admin."""
from __future__ import annotations

import time
from typing import Any, Callable

import streamlit as st

from api_client import COLD_START_HINT, ApiClient, ApiError, error_message
from helpers import DISCLAIMER, PRIORITY_STYLE, STATUS_HINT, STATUS_STYLE, resolve_api_base_url

CLIENT_OVERRIDE_KEY = "_api_client"  # tes menyuntik ApiClient lewat session_state
HEALTH_TTL_SECONDS = 120


def _secrets_get(key: str) -> str | None:
    if st.secrets.load_if_toml_exists():  # tidak menampilkan error bila secrets.toml tidak ada (lokal)
        return st.secrets.get(key)
    return None


def api_base_url() -> str:
    return resolve_api_base_url(_secrets_get)


@st.cache_resource(show_spinner=False)
def _client_for(base_url: str) -> ApiClient:
    return ApiClient(base_url)


def get_client() -> ApiClient:
    override = st.session_state.get(CLIENT_OVERRIDE_KEY)
    return override if override is not None else _client_for(api_base_url())


def call(label: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> tuple[bool, Any]:
    """Jalankan panggilan API dengan spinner. Error ditampilkan apa adanya (pesan backend) -> (ok, hasil)."""
    try:
        with st.spinner(f"{label}... (jika API baru dibuka: {COLD_START_HINT})"):
            return True, fn(*args, **kwargs)
    except ApiError as err:
        st.error(error_message(err), icon=":material/error:")
        return False, None


def flash(message: str, kind: str = "success") -> None:
    """Simpan pesan untuk ditampilkan setelah st.rerun()."""
    st.session_state.setdefault("_flash", []).append((kind, message))


def show_flash() -> None:
    for kind, message in st.session_state.pop("_flash", []):
        getattr(st, kind)(message)


def priority_badge(priority: str | None) -> None:
    color, _ = PRIORITY_STYLE.get(priority, PRIORITY_STYLE[None])
    st.badge(f"Prioritas {priority or 'belum ada'}", color=color)


def status_badge(status: str) -> None:
    st.badge(f"{status} ({STATUS_HINT.get(status, '')})", color=STATUS_STYLE.get(status, "gray"))


def page_header(title: str, caption: str | None = None) -> None:
    st.title(title)
    if caption:
        st.caption(caption)
    show_flash()


def ensure_api_awake() -> dict | None:
    """Panggil /health (cache singkat per sesi). Pada cold start Render, spinner menjelaskan bahwa API sedang bangun."""
    cached = st.session_state.get("_health")
    if cached and time.monotonic() - cached[0] < HEALTH_TTL_SECONDS:
        return cached[1]
    try:
        with st.spinner(f"Menghubungi API... {COLD_START_HINT}"):
            health = get_client().health()
    except ApiError as err:
        st.session_state.pop("_health", None)
        st.error(error_message(err), icon=":material/cloud_off:")
        return None
    st.session_state["_health"] = (time.monotonic(), health)
    return health


def render_sidebar() -> None:
    with st.sidebar:
        st.warning(DISCLAIMER, icon=":material/science:")
        st.subheader("Pengaturan")
        try:
            st.caption(f"API: `{api_base_url()}`")
        except ValueError as err:
            st.error(str(err))
            return
        health = ensure_api_awake()
        if health:
            db = "terhubung" if health.get("db_connected") else "TIDAK terhubung"
            model = health.get("model_version") if health.get("model_loaded") else "tidak dimuat"
            st.caption(f"Status API: {health.get('status')} · Database: {db} · Model: {model}")
        if st.button("Cek ulang koneksi API", icon=":material/refresh:"):
            st.session_state.pop("_health", None)
            st.rerun()
        st.caption("Draft dibuat AI dan selalu bisa diedit. Admin yang mengirim pesan lewat WhatsApp.")
