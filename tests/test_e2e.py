"""Test Fase 6: alur end-to-end tingkat API + penanganan error akhir (SQLite, klien Gemini palsu, tanpa jaringan).

Alur: buat reminder -> prioritas -> generate-draft -> simpan pesan -> Sent -> Responded / No Response -> riwayat.
"""
import socket
from datetime import datetime, time

import pytest
from fastapi.testclient import TestClient
from sklearn.linear_model import LogisticRegression

from src.api.config import Settings
from src.api.db.models import Base
from src.api.db.session import make_engine
from src.api.errors import DB_UNAVAILABLE_DETAIL
from src.api.main import create_app
from src.api.services.gemini_client import GeminiError
from src.api.timeutil import today_wib
from src.ml.feature_engineering import FEATURE_COLUMNS
from src.ml.predict import LoadedModel
from src.ml.train import load_dataset, make_pipeline

TODAY = today_wib()
DRAFT = ("Halo Bu Sari, semoga sehat dan semangat selalu ya 😊 Kami mau mengingatkan jadwal kelas Yoga Lembut pukul "
         "09.00 WIB bersama Coach Sari. Kalau ada kendala atau ingin ganti jadwal, kabari kami saja lewat pesan ini "
         "ya. Kami tunggu kehadirannya, semoga latihannya menyenangkan. Salam hangat, Admin Gymnasium")
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


class FakeGenerator:
    def __init__(self, *outcomes):
        self.outcomes, self.calls = list(outcomes), 0

    def generate(self, system_instruction, prompt):
        self.calls += 1
        out = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(out, BaseException):
            raise out
        return out


@pytest.fixture(scope="module")
def ml_model():
    df = load_dataset()
    pipe = make_pipeline(LogisticRegression(max_iter=2000, class_weight="balanced"))
    pipe.fit(df[FEATURE_COLUMNS], df["priority"])
    return LoadedModel(pipeline=pipe, metadata={"model_version": "test-model"})


def _client(model, generator):
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    return TestClient(create_app(settings=Settings(database_url=None), engine=engine, model=model,
                                 draft_generator=generator))


def _ok(resp, status=200):
    assert resp.status_code == status, resp.text
    return resp.json()


@pytest.mark.parametrize("outcome", ["Responded", "No Response"])
def test_full_flow_from_reminder_to_final_status(ml_model, outcome):
    gen = FakeGenerator(DRAFT)
    with _client(ml_model, gen) as c:
        cust = _ok(c.post("/customers", json={"nama": "Ibu Sari", "no_whatsapp": "081234567890",
                                              "persona": "ibu-ibu"}), 201)
        sch = _ok(c.post("/schedules", json={"nama_kelas": "Yoga Lembut", "tipe": "group_class",
                                             "pelatih": "Coach Sari", "kapasitas": 15,
                                             "waktu_mulai": datetime.combine(TODAY, time(9, 0)).isoformat()}), 201)
        # 1. reminder dibuat -> status Scheduled + prioritas dari model
        rem = _ok(c.post("/reminders", json={"customer_id": cust["id"], "schedule_id": sch["id"],
                                             "message_type": "reminder_kelas"}), 201)
        rid = rem["id"]
        assert rem["status"] == "Scheduled" and rem["priority"] in ("Low", "Medium", "High")
        assert set(rem["priority_probabilities"]) == {"Low", "Medium", "High"}
        # 2. admin melihat daftar hari ini (berdasarkan tanggal kelas)
        listed = _ok(c.get("/reminders", params={"date": "today"}))
        assert [r["id"] for r in listed["items"]] == [rid]
        # 3. alasan prioritas (hanya admin)
        pred = _ok(c.post("/predict", json={"customer_id": cust["id"]}))
        assert pred["cold_start"] is True and pred["note"] == "riwayat belum cukup"
        # 4. generate draft (Gemini palsu), lalu cache
        draft = _ok(c.post("/generate-draft", json={"reminder_id": rid}))
        assert (draft["draft_source"], draft["cached"], draft["draft_message"]) == ("gemini", False, DRAFT)
        assert _ok(c.post("/generate-draft", json={"reminder_id": rid}))["cached"] is True and gen.calls == 1
        # 5. admin mengedit dan menyimpan pesan
        final = DRAFT.replace("Salam hangat", "Terima kasih. Salam hangat")
        assert _ok(c.patch(f"/reminders/{rid}/message", json={"final_message": final}))["final_message"] == final
        # 6. admin mengirim manual via WhatsApp lalu menandai Sent
        sent = _ok(c.patch(f"/reminders/{rid}/status", json={"status": "Sent"}))
        assert sent["status"] == "Sent" and sent["sent_at"] and sent["final_message"] == final
        # setelah Sent: pesan & draft terkunci
        assert c.patch(f"/reminders/{rid}/message", json={"final_message": "x"}).json()["code"] == "message_locked"
        assert c.post("/generate-draft", json={"reminder_id": rid}).json()["code"] == "draft_not_allowed"
        # 7. Responded / No Response
        done = _ok(c.patch(f"/reminders/{rid}/status", json={"status": outcome}))
        assert done["status"] == outcome and bool(done["responded_at"]) == (outcome == "Responded")
        assert c.patch(f"/reminders/{rid}/status", json={"status": "Sent"}).json()["code"] == \
            "invalid_status_transition"
        # 8. riwayat tersimpan
        history = _ok(c.get(f"/reminders/{rid}/history"))
        assert [h["to_status"] for h in history] == ["Scheduled", "Sent", outcome]
        per_customer = _ok(c.get(f"/customers/{cust['id']}/reminders"))["items"]
        assert per_customer[0]["id"] == rid and per_customer[0]["final_message"] == final
        assert per_customer[0]["draft_message"] == DRAFT  # draft asli tetap tersimpan terpisah


def test_flow_survives_gemini_quota_exhausted(ml_model):
    """429 dari Gemini -> draft tetap tersedia (template) dan alur tetap bisa diselesaikan."""
    with _client(ml_model, FakeGenerator(GeminiError("rate_limit", "HTTP 429", True, 429))) as c:
        cust = _ok(c.post("/customers", json={"nama": "Bambang Hartono", "no_whatsapp": "081200000002",
                                              "persona": "lansia"}), 201)
        rem = _ok(c.post("/reminders", json={"customer_id": cust["id"]}), 201)
        draft = _ok(c.post("/generate-draft", json={"reminder_id": rem["id"]}))
        assert draft["draft_source"] == "template_fallback" and "429" in draft["warning"]
        assert draft["draft_message"].startswith("Halo Bapak/Ibu Bambang")
        assert _ok(c.patch(f"/reminders/{rem['id']}/status", json={"status": "Sent"}))["final_message"] == \
            draft["draft_message"]  # draft dikirim apa adanya


def test_unreachable_database_returns_503_with_clear_message(tmp_path):
    """DATABASE_URL terisi tetapi database tidak bisa dihubungi (mis. Supabase ter-pause) -> 503, bukan 500."""
    engine = make_engine(f"sqlite:///{tmp_path / 'tidak-ada' / 'db.sqlite'}")  # folder tidak ada -> gagal konek
    with TestClient(create_app(settings=Settings(database_url=None), engine=engine, model=None,
                               draft_generator=None)) as c:
        assert c.get("/health").json()["status"] == "degraded"
        for method, path, body in (("GET", "/customers", None), ("GET", "/reminders", None),
                                   ("POST", "/generate-draft", {"reminder_id": 1})):
            r = c.request(method, path, json=body)
            assert r.status_code == 503, (path, r.text)
            assert r.json() == {"detail": DB_UNAVAILABLE_DETAIL, "code": "database_unavailable"}
