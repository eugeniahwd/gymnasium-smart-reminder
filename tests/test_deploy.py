"""Test deploy satu-aplikasi (Streamlit Community Cloud): API internal di thread + entrypoint streamlit_app.py.

Server uvicorn sungguhan + model asli + SQLite file; hanya loopback (127.0.0.1), tanpa jaringan luar.
"""
import socket
import sys
from pathlib import Path

import pytest
import requests
import streamlit as st
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

import embedded_api
from src.api.config import Settings
from src.api.db.models import Base
from src.api.db.session import make_engine
from src.api.main import create_app

ROOT = Path(__file__).resolve().parents[1]
UI_DIR = ROOT / "src" / "ui"
if str(UI_DIR) not in sys.path:
    sys.path.insert(0, str(UI_DIR))
import api_client as ui_api  # noqa: E402

_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    real_connect = socket.socket.connect

    def _connect(sock, address):
        host = address[0] if isinstance(address, tuple) else str(address)
        if host not in _LOOPBACK:
            raise AssertionError(f"Tes mencoba mengakses jaringan: {address}")
        return real_connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", _connect)
    monkeypatch.setenv("GEMINI_API_KEY", "")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def sqlite_env(tmp_path, monkeypatch):
    """Lingkungan seperti Streamlit Cloud: konfigurasi dari env, tanpa API_BASE_URL."""
    db_url = f"sqlite:///{(tmp_path / 'demo.db').as_posix()}"
    Base.metadata.create_all(make_engine(db_url))
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("EMBEDDED_API_PORT", str(_free_port()))
    monkeypatch.delenv("API_BASE_URL", raising=False)
    yield db_url
    embedded_api.stop()
    st.cache_resource.clear()


def test_embedded_api_serves_real_app_and_is_idempotent(sqlite_env):
    url = embedded_api.start(timeout=90)
    health = requests.get(f"{url}/health", timeout=10).json()
    assert health["status"] == "ok" and health["db_connected"] and health["model_loaded"]
    assert health["model_version"] == "lr-20261031-v1"  # artefak model asli termuat
    assert embedded_api.start() == url  # tidak menyalakan server kedua
    client = ui_api.ApiClient(url)
    cust = client.create_customer({"nama": "Ibu Demo", "no_whatsapp": "081277778888", "persona": "ibu-ibu"})
    assert [c["id"] for c in client.list_customers()] == [cust["id"]]
    draft = client.generate_draft(client.create_reminder(cust["id"], None, "reminder_kelas")["id"])
    assert draft["draft_source"] == "template_fallback"  # GEMINI_API_KEY kosong -> template


def test_embedded_api_reports_startup_failure(monkeypatch):
    def broken_app():
        raise RuntimeError("gagal membuat app")

    monkeypatch.setenv("EMBEDDED_API_PORT", str(_free_port()))
    with pytest.raises(RuntimeError, match="gagal membuat app"):
        embedded_api.start(app_factory=broken_app)


def test_streamlit_app_starts_internal_api_and_renders(sqlite_env):
    """Mode Streamlit Cloud tanpa API eksternal: entrypoint menyalakan API lalu UI memakainya lewat HTTP."""
    at = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=120).run()
    assert not at.exception, at.exception
    assert at.title[0].value == "Reminder Hari Ini"
    captions = " ".join(c.value for c in at.sidebar.caption)
    assert "Database: terhubung" in captions and "lr-20261031-v1" in captions
    assert f"127.0.0.1:{embedded_api._url.rsplit(':', 1)[1]}" in captions


def test_streamlit_app_uses_external_api_when_configured(monkeypatch):
    """API_BASE_URL terisi (mis. API di Render) -> API internal tidak dinyalakan."""
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    app = create_app(settings=Settings(database_url=None), engine=engine, model=None, draft_generator=None)
    monkeypatch.setenv("API_BASE_URL", "https://api-eksternal.example.org")

    class Session:
        def __init__(self, tc):
            self.tc = tc

        def request(self, method, url, params=None, json=None, timeout=None):
            return self.tc.request(method, url.replace("https://api-eksternal.example.org", ""), params=params,
                                   json=json)

    with TestClient(app) as tc:
        at = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=60)
        at.session_state["_api_client"] = ui_api.ApiClient("https://api-eksternal.example.org", session=Session(tc))
        at.run()
    assert not at.exception, at.exception
    assert embedded_api._thread is None
    assert any("api-eksternal.example.org" in c.value for c in at.sidebar.caption)
