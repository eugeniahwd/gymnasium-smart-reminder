"""Test Fase 5: UI Streamlit.

- helpers & api_client dites langsung (tanpa Streamlit).
- Halaman dites dengan streamlit.testing.v1.AppTest melalui jalur sungguhan:
  halaman -> ApiClient -> FastAPI (SQLite in-memory, klien Gemini palsu). Tanpa jaringan.
"""
import socket
import sys
from datetime import date, datetime, time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote

import pytest
import requests
from fastapi.testclient import TestClient
from sklearn.linear_model import LogisticRegression
from streamlit.testing.v1 import AppTest

from src.api.config import Settings
from src.api.db.models import Base
from src.api.db.session import make_engine
from src.api.main import create_app
from src.ml.feature_engineering import FEATURE_COLUMNS
from src.ml.predict import LoadedModel
from src.ml.train import load_dataset, make_pipeline

UI_DIR = Path(__file__).resolve().parents[1] / "src" / "ui"
if str(UI_DIR) not in sys.path:  # sama seperti `streamlit run src/ui/app.py` (folder entrypoint ada di sys.path)
    sys.path.insert(0, str(UI_DIR))
import api_client as ui_api  # noqa: E402  (modul yang SAMA dengan yang dipakai halaman)
import helpers  # noqa: E402

TODAY = helpers.today_wib()
SUNDAY = date(2026, 11, 15)
DRAFT = ("Halo Bu Sari, semoga sehat dan semangat selalu ya 😊 Kami mau mengingatkan jadwal kelas Yoga Lembut pukul "
         "09.00 WIB bersama Coach Sari. Kalau ada kendala atau ingin ganti jadwal, kabari kami saja lewat pesan ini "
         "ya. Kami tunggu kehadirannya, semoga latihannya menyenangkan. Salam hangat, Admin Gymnasium")
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Blokir koneksi keluar (loopback diizinkan untuk event loop asyncio di Windows)."""
    real_connect, real_create = socket.socket.connect, socket.create_connection

    def _host(address):
        return address[0] if isinstance(address, tuple) else str(address)

    def _connect(sock, address):
        if _host(address) not in _LOOPBACK:
            raise AssertionError(f"Tes mencoba mengakses jaringan: {address}")
        return real_connect(sock, address)

    def _create(address, *args, **kwargs):
        if _host(address) not in _LOOPBACK:
            raise AssertionError(f"Tes mencoba mengakses jaringan: {address}")
        return real_create(address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", _connect)
    monkeypatch.setattr(socket, "create_connection", _create)
    monkeypatch.setenv("GEMINI_API_KEY", "")


# ------------------------------------------------------------------ backend uji
class FakeGenerator:
    def __init__(self, text: str):
        self.text, self.calls = text, 0

    def generate(self, system_instruction: str, prompt: str) -> str:
        self.calls += 1
        return self.text


class ClientSessionAdapter:
    """Adaptor TestClient -> antarmuka requests.Session (httpx tidak menerima timeout 2-tuple)."""

    def __init__(self, tc: TestClient):
        self.tc, self.timeouts = tc, []

    def request(self, method, url, params=None, json=None, timeout=None):
        self.timeouts.append((method, url, timeout))
        return self.tc.request(method, url, params=params, json=json)


@pytest.fixture(scope="module")
def ml_model():
    df = load_dataset()
    pipe = make_pipeline(LogisticRegression(max_iter=2000, class_weight="balanced"))
    pipe.fit(df[FEATURE_COLUMNS], df["priority"])
    return LoadedModel(pipeline=pipe, metadata={"model_version": "test-model"})


def _backend(model):
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    gen = FakeGenerator(DRAFT)
    app = create_app(settings=Settings(database_url=None), engine=engine, model=model, draft_generator=gen)
    return app, gen


@pytest.fixture
def api(ml_model):
    app, gen = _backend(ml_model)
    with TestClient(app) as tc:
        session = ClientSessionAdapter(tc)
        yield SimpleNamespace(client=ui_api.ApiClient("http://testserver", session=session), gen=gen, session=session)


@pytest.fixture
def api_no_model():
    app, gen = _backend(None)
    with TestClient(app) as tc:
        yield SimpleNamespace(client=ui_api.ApiClient("http://testserver", session=ClientSessionAdapter(tc)), gen=gen)


def seed(client, when=None):
    cust = client.create_customer({"nama": "Ibu Sari", "no_whatsapp": "081234567890", "persona": "ibu-ibu"})
    sch = client.create_schedule({"nama_kelas": "Yoga Lembut", "tipe": "group_class", "pelatih": "Coach Sari",
                                  "kapasitas": 15, "waktu_mulai": (when or datetime.combine(TODAY, time(9, 0))).isoformat()})
    rem = client.create_reminder(cust["id"], sch["id"], "reminder_kelas")
    return cust, sch, rem


def run_page(api, page: str, **state) -> AppTest:
    at = AppTest.from_file(str(UI_DIR / page), default_timeout=60)
    at.session_state["_api_client"] = api.client
    for key, value in state.items():
        at.session_state[key] = value
    return at.run()


def _by_label(widgets, label):
    return next(w for w in widgets if w.label == label)


# ------------------------------------------------------------------ batasan arsitektur
def test_ui_never_imports_backend_database_or_gemini():
    import re

    forbidden = re.compile(r"^\s*(from|import)\s+(src\b|sqlalchemy|psycopg|google|sklearn|joblib)", re.MULTILINE)
    offenders = [p.name for p in UI_DIR.rglob("*.py") if forbidden.search(p.read_text(encoding="utf-8"))]
    assert offenders == [], f"UI hanya boleh memanggil FastAPI lewat api_client: {offenders}"
    lines = (UI_DIR / "requirements.txt").read_text(encoding="utf-8").lower().splitlines()
    packages = {ln.split("==")[0].strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")}
    assert {"streamlit", "requests", "pandas"} <= packages
    assert not packages & {"scikit-learn", "fastapi", "sqlalchemy", "google-genai", "psycopg2-binary"}


# ------------------------------------------------------------------ helpers
@pytest.mark.parametrize("number,text,expected", [
    ("6281234567890", "Halo Bu Sari", "https://wa.me/6281234567890?text=Halo%20Bu%20Sari"),
    ("081234567890", None, "https://wa.me/6281234567890"),
    ("+62 812-3456-7890", "  ", "https://wa.me/6281234567890"),
])
def test_wa_url(number, text, expected):
    assert helpers.wa_url(number, text) == expected


def test_wa_url_encodes_everything_and_roundtrips():
    text = "Halo Bu Sari 😊\nKelas & jadwal: 09.00 WIB?#"
    url = helpers.wa_url("6281234567890", text)
    query = url.split("?text=", 1)[1]
    assert " " not in query and "\n" not in query and "&" not in query and "#" not in query
    assert unquote(query) == text
    with pytest.raises(ValueError):
        helpers.wa_url("", "x")


def test_resolve_api_base_url_order_and_validation():
    assert helpers.resolve_api_base_url(lambda k: "https://api.example.org/", {"API_BASE_URL": "http://env"}) \
        == "https://api.example.org"
    assert helpers.resolve_api_base_url(lambda k: None, {"API_BASE_URL": "http://env:8000/"}) == "http://env:8000"
    assert helpers.resolve_api_base_url(None, {}) == "http://localhost:8000"

    def broken(_):
        raise FileNotFoundError("tidak ada secrets.toml")

    assert helpers.resolve_api_base_url(broken, {}) == "http://localhost:8000"
    with pytest.raises(ValueError, match="http"):
        helpers.resolve_api_base_url(None, {"API_BASE_URL": "api.example.org"})


def test_formatting_helpers():
    assert helpers.format_dt("2026-11-13T09:00:00") == "Jumat, 13 Nov 2026 09.00"
    assert helpers.format_dt(None) == "-" and helpers.format_time("2026-11-13T18:30:00") == "18.30"
    assert helpers.format_date("2026-11-15") == "Minggu, 15 Nov 2026"
    assert helpers.format_probabilities({"Low": 0.1, "High": 0.65, "Medium": 0.25}) == "High 65% · Medium 25% · Low 10%"
    assert helpers.format_probabilities(None) == "belum ada"
    assert helpers.priority_label("High") == "🔴 High" and helpers.priority_label(None) == "⚪ Belum ada"
    assert helpers.combine_wib(date(2026, 11, 13), 8, 30) == "2026-11-13T08:30:00"


def test_empty_day_message_explains_sunday():
    assert "hari Minggu" in helpers.empty_day_message(SUNDAY)
    assert "seed_demo" in helpers.empty_day_message(date(2026, 11, 16))


def test_reminder_rows_keep_api_order_and_editor_prefers_final_message():
    rems = [{"id": 2, "priority": "High", "priority_probabilities": {"High": 0.7}, "status": "Scheduled",
             "message_type": "follow_up_absen", "customer": {"nama": "B"}, "schedule": None, "draft_message": "d"},
            {"id": 1, "priority": None, "priority_probabilities": None, "status": "Sent",
             "message_type": "reminder_kelas", "customer": {"nama": "A"},
             "schedule": {"nama_kelas": "Zumba Fun", "waktu_mulai": "2026-11-13T09:00:00"}}]
    rows = helpers.reminder_rows(rems)
    assert [r["No"] for r in rows] == [2, 1] and rows[0]["Peluang High"] == "70%" and rows[0]["Draft"] == "✓"
    assert rows[1]["Jam"] == "09.00" and rows[1]["Prioritas"] == "⚪ Belum ada"
    assert "Zumba Fun 09.00" in helpers.reminder_option_label(rems[1])
    assert helpers.message_for_editor({"final_message": "akhir", "draft_message": "draft"}) == "akhir"
    assert helpers.message_for_editor({"final_message": None, "draft_message": "draft"}) == "draft"


# ------------------------------------------------------------------ api_client (sesi palsu)
class FakeResponse:
    def __init__(self, status, body=None, text=""):
        self.status_code, self._body, self.text = status, body, text

    def json(self):
        if self._body is None:
            raise ValueError("bukan JSON")
        return self._body


class FakeSession:
    def __init__(self, *outcomes):
        self.outcomes, self.calls = list(outcomes), []

    def request(self, method, url, params=None, json=None, timeout=None):
        self.calls.append((method, url, params, json, timeout))
        out = self.outcomes.pop(0)
        if isinstance(out, BaseException):
            raise out
        return out


@pytest.mark.parametrize("outcome,code,hint", [
    (requests.exceptions.ReadTimeout("lambat"), "timeout", "API sedang bangun"),
    (requests.exceptions.ConnectionError("tolak"), "connection", "API_BASE_URL"),
    (FakeResponse(502, None, "<html>Bad Gateway</html>"), "http_502", "HTTP 502"),
])
def test_api_client_maps_transport_errors(outcome, code, hint):
    client = ui_api.ApiClient("https://api.example.org", session=FakeSession(outcome))
    with pytest.raises(ui_api.ApiError) as exc:
        client.health()
    assert exc.value.code == code and hint in ui_api.error_message(exc.value)


def test_api_client_backend_error_detail_shown_as_is():
    body = {"detail": "Pesan tidak dapat diubah karena reminder sudah berstatus 'Sent'.", "code": "message_locked"}
    client = ui_api.ApiClient("https://api.example.org", session=FakeSession(FakeResponse(409, body)))
    with pytest.raises(ui_api.ApiError) as exc:
        client.update_message(1, "x")
    assert (exc.value.status, exc.value.code) == (409, "message_locked")
    assert ui_api.error_message(exc.value) == body["detail"]


def test_api_client_paginates_and_handles_204():
    pages = [FakeResponse(200, {"items": [{"id": i} for i in range(200)], "total": 250, "limit": 200, "offset": 0}),
             FakeResponse(200, {"items": [{"id": i} for i in range(200, 250)], "total": 250, "limit": 200,
                                "offset": 200}),
             FakeResponse(204)]
    session = FakeSession(*pages)
    client = ui_api.ApiClient("https://api.example.org/", session=session)
    assert len(client.list_customers()) == 250
    assert [c[2]["offset"] for c in session.calls] == [0, 200] and session.calls[0][1].endswith("/customers")
    assert client.delete_customer(5) is None
    assert session.calls[0][4] == ui_api.DEFAULT_TIMEOUT


def test_api_client_default_session_has_user_agent():
    client = ui_api.ApiClient("http://localhost:8000")
    assert "GymnasiumAdminUI" in client._session.headers["User-Agent"]


# ------------------------------------------------------------------ api_client <-> FastAPI sungguhan
def test_api_client_end_to_end_against_backend(api):
    c = api.client
    cust, sch, rem = seed(c)
    assert rem["status"] == "Scheduled" and rem["priority"] in ("Low", "Medium")  # cold start
    assert [r["id"] for r in c.list_reminders(TODAY.isoformat())] == [rem["id"]]
    draft = c.generate_draft(rem["id"])
    assert draft["draft_source"] == "gemini" and draft["draft_message"] == DRAFT
    assert api.session.timeouts[-1][2] == ui_api.DRAFT_TIMEOUT
    sent = c.mark_sent(rem["id"], DRAFT + " Sampai jumpa.")
    assert sent["status"] == "Sent" and sent["final_message"].endswith("Sampai jumpa.")
    with pytest.raises(ui_api.ApiError) as exc:
        c.update_message(rem["id"], "ubah setelah terkirim")
    assert exc.value.code == "message_locked" and "Sent" in exc.value.detail
    assert c.update_status(rem["id"], "Responded")["status"] == "Responded"
    assert [h["to_status"] for h in c.reminder_history(rem["id"])] == ["Scheduled", "Sent", "Responded"]
    assert [r["id"] for r in c.customer_reminders(cust["id"])] == [rem["id"]]
    assert c.predict(cust["id"])["note"] == "riwayat belum cukup"


# ------------------------------------------------------------------ halaman (AppTest)
def test_reminder_page_full_flow(api):
    _, _, rem = seed(api.client)
    rid = rem["id"]
    at = run_page(api, "pages/reminder_hari_ini.py")
    assert not at.exception, at.exception
    assert at.dataframe and "Ibu Sari" in at.selectbox[0].format_func(at.selectbox[0].value)

    at.button(key=f"gen_{rid}").click().run()  # Generate Draft
    assert not at.exception, at.exception
    assert at.text_area(key=f"msg_{rid}").value == DRAFT and api.gen.calls == 1
    assert any("Gemini" in s.value for s in at.success)
    assert at.link_button[0].proto.url == helpers.wa_url("6281234567890", DRAFT)

    edited = DRAFT.replace("Salam hangat", "Terima kasih. Salam hangat")
    at.text_area(key=f"msg_{rid}").input(edited).run()
    at.button(key=f"save_{rid}").click().run()  # Simpan pesan
    assert api.client.get_reminder(rid)["final_message"] == edited
    assert at.link_button[0].proto.url == helpers.wa_url("6281234567890", edited)

    assert at.button(key=f"sent_{rid}").disabled  # harus konfirmasi dulu
    at.checkbox(key=f"confirm_{rid}").check().run()
    at.button(key=f"sent_{rid}").click().run()  # Tandai Terkirim
    assert not at.exception, at.exception
    detail = api.client.get_reminder(rid)
    assert detail["status"] == "Sent" and detail["final_message"] == edited
    assert at.text_area(key=f"locked_{rid}").disabled and at.text_area(key=f"locked_{rid}").value == edited
    assert not [b for b in at.button if b.key == f"gen_{rid}"]  # tidak bisa generate setelah Sent

    at.button(key=f"Responded_{rid}").click().run()
    assert api.client.get_reminder(rid)["status"] == "Responded"
    assert not [b for b in at.button if b.key in (f"Responded_{rid}", f"No Response_{rid}")]


def test_reminder_page_shows_priority_reason_and_cold_start_note(api):
    _, _, rem = seed(api.client)
    at = run_page(api, "pages/reminder_hari_ini.py")
    at.button(key=f"why_{rem['id']}").click().run()
    assert not at.exception, at.exception
    texts = " ".join(m.value for m in at.markdown)
    assert "Hanya untuk admin" in " ".join(c.value for c in at.caption) and "riwayat belum cukup" in texts


def test_reminder_page_shows_backend_error_as_is(api_no_model):
    _, _, rem = seed(api_no_model.client)
    at = run_page(api_no_model, "pages/reminder_hari_ini.py")
    at.button(key=f"why_{rem['id']}").click().run()
    with pytest.raises(ui_api.ApiError) as exc:
        api_no_model.client.predict(rem["customer_id"])
    assert exc.value.status == 503 and exc.value.detail in [e.value for e in at.error]


def test_reminder_page_empty_sunday_explained(api):
    at = run_page(api, "pages/reminder_hari_ini.py")
    at.date_input(key="class_date").set_value(SUNDAY).run()
    assert not at.exception and "hari Minggu" in at.info[0].value


def test_reminder_page_create_reminder_form(api):
    cust = api.client.create_customer({"nama": "Bapak Joko", "no_whatsapp": "081200000001", "persona": "lansia"})
    sch = api.client.create_schedule({"nama_kelas": "Senam Sehat Lansia", "tipe": "group_class", "pelatih": "Coach Budi",
                                      "kapasitas": 20, "waktu_mulai": datetime.combine(TODAY, time(8, 0)).isoformat()})
    at = run_page(api, "pages/reminder_hari_ini.py")
    at.toggle(key="show_create").set_value(True).run()
    _by_label(at.selectbox, "Customer").set_value(cust["id"])
    _by_label(at.selectbox, f"Kelas pada {TODAY:%d/%m/%Y}").set_value(sch["id"])
    _by_label(at.button, "Buat reminder").click().run()
    assert not at.exception, at.exception
    rems = api.client.list_reminders(TODAY.isoformat())
    assert len(rems) == 1 and rems[0]["customer_id"] == cust["id"] and rems[0]["status"] == "Scheduled"
    assert any("dibuat" in s.value for s in at.success)


def test_customer_page_add_and_duplicate_error(api):
    at = run_page(api, "pages/customer.py")
    assert not at.exception, at.exception
    _by_label(at.text_input, "Nama").input("Bapak Bambang Hartono")
    _by_label(at.text_input, "Nomor WhatsApp").input("0812-3456-7890")
    _by_label(at.selectbox, "Persona").set_value("lansia")
    _by_label(at.button, "Tambah customer").click().run()
    assert not at.exception, at.exception
    customers = api.client.list_customers()
    assert [(c["nama"], c["no_whatsapp"], c["persona"]) for c in customers] == [
        ("Bapak Bambang Hartono", "6281234567890", "lansia")]

    _by_label(at.text_input, "Nama").input("Ibu Lain")
    _by_label(at.text_input, "Nomor WhatsApp").input("+6281234567890")
    _by_label(at.button, "Tambah customer").click().run()
    assert "Nomor WhatsApp sudah terdaftar pada customer lain." in [e.value for e in at.error]


def test_customer_page_edit_and_delete(api):
    cust, _, _ = seed(api.client)
    at = run_page(api, "pages/customer.py")
    at.selectbox(key="edit_customer_id").set_value(cust["id"]).run()
    name_inputs = [t for t in at.text_input if t.label == "Nama"]
    name_inputs[-1].input("Ibu Sari Wijaya")
    _by_label(at.button, "Simpan perubahan").click().run()
    assert api.client.list_customers()[0]["nama"] == "Ibu Sari Wijaya"

    assert at.button(key=f"delete_customer_{cust['id']}").disabled
    at.checkbox(key=f"confirm_delete_customer_{cust['id']}").check().run()
    at.button(key=f"delete_customer_{cust['id']}").click().run()
    assert not at.exception, at.exception
    assert api.client.list_customers() == [] and api.client.list_reminders(TODAY.isoformat()) == []


def test_jadwal_page_add_schedule(api):
    at = run_page(api, "pages/jadwal.py")
    assert not at.exception, at.exception
    _by_label(at.text_input, "Nama kelas").input("Zumba Fun")
    _by_label(at.text_input, "Pelatih").input("Coach Dina")
    _by_label(at.time_input, "Jam mulai (WIB)").set_value(time(18, 30))
    _by_label(at.button, "Tambah jadwal").click().run()
    assert not at.exception, at.exception
    schedules = api.client.list_schedules(TODAY.isoformat(), TODAY.isoformat())
    assert [(s["nama_kelas"], s["pelatih"], s["waktu_mulai"]) for s in schedules] == [
        ("Zumba Fun", "Coach Dina", f"{TODAY.isoformat()}T18:30:00")]


def test_riwayat_page_shows_reminders_and_status_history(api):
    cust, _, rem = seed(api.client)
    api.client.mark_sent(rem["id"], DRAFT)
    at = run_page(api, "pages/riwayat.py")
    assert not at.exception and at.info  # belum memilih customer
    at.selectbox[0].set_value(cust["id"]).run()
    assert not at.exception, at.exception
    assert at.text_area(key=f"history_msg_{rem['id']}").value == DRAFT
    assert len(at.dataframe) == 2  # daftar reminder + riwayat status


def test_app_entry_renders_sidebar_disclaimer_and_default_page(api):
    seed(api.client)
    at = AppTest.from_file(str(UI_DIR / "app.py"), default_timeout=60)
    at.session_state["_api_client"] = api.client
    at.run()
    assert not at.exception, at.exception
    assert any("PROTOTYPE" in w.value and "synthetic" in w.value for w in at.sidebar.warning)
    assert any("Database: terhubung" in c.value for c in at.sidebar.caption)
    assert at.title[0].value == "Reminder Hari Ini"
