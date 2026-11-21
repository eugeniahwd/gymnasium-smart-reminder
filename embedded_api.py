"""Menjalankan API FastAPI di thread latar, untuk deploy UI + API sebagai SATU aplikasi Streamlit Community Cloud.

Dipakai oleh `streamlit_app.py` bila tidak ada API eksternal (`API_BASE_URL` kosong). API tetap aplikasi FastAPI
yang sama (`src.api.main.create_app`) dan UI tetap memanggilnya lewat HTTP (127.0.0.1), sehingga pemisahan UI/API
tidak berubah; hanya prosesnya yang digabung agar tidak membutuhkan layanan hosting kedua.
Konfigurasi dibaca dari environment variable (DATABASE_URL, GEMINI_API_KEY, GEMINI_MODEL, ...).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable

import requests
import uvicorn

logger = logging.getLogger("gymnasium.embedded")

DEFAULT_PORT = 8000
STARTUP_TIMEOUT_SECONDS = 120

_lock = threading.Lock()
_server: uvicorn.Server | None = None
_thread: threading.Thread | None = None
_url: str | None = None


def is_healthy(url: str, timeout: float = 2.0) -> bool:
    try:
        return requests.get(f"{url}/health", timeout=timeout).status_code == 200
    except requests.exceptions.RequestException:
        return False


def _default_app() -> Any:
    from src.api.main import create_app  # impor di sini: modul ini juga dipakai tanpa backend saat tes UI

    return create_app()


def start(port: int | None = None, app_factory: Callable[[], Any] | None = None,
          timeout: float = STARTUP_TIMEOUT_SECONDS) -> str:
    """Nyalakan API (sekali per proses) lalu tunggu /health siap. Mengembalikan base URL, mis. http://127.0.0.1:8000."""
    global _server, _thread, _url
    with _lock:
        port = port or int(os.environ.get("EMBEDDED_API_PORT", DEFAULT_PORT))
        url = f"http://127.0.0.1:{port}"
        if _thread is not None and _thread.is_alive() and _url == url:
            return url
        if is_healthy(url):  # sudah berjalan (mis. skrip Streamlit dimuat ulang)
            _url = url
            return url
        app = (app_factory or _default_app)()
        _server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info"))
        _thread = threading.Thread(target=_server.run, name="gymnasium-api", daemon=True)
        _thread.start()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if is_healthy(url):
                _url = url
                logger.info("API internal siap di %s", url)
                return url
            if not _thread.is_alive():
                raise RuntimeError("API internal berhenti saat start. Periksa log aplikasi (DATABASE_URL, model).")
            time.sleep(0.5)
        raise RuntimeError(f"API internal tidak siap dalam {timeout:.0f} detik.")


def stop(timeout: float = 10.0) -> None:
    """Hentikan API internal (dipakai tes)."""
    global _server, _thread, _url
    with _lock:
        if _server is not None:
            _server.should_exit = True
        if _thread is not None:
            _thread.join(timeout)
        _server, _thread, _url = None, None, None
