"""Test Fase 3: REST API (SQLite in-memory + TestClient; tidak menyentuh Supabase)."""
from datetime import datetime, time, timedelta

import pytest
from fastapi.testclient import TestClient
from sklearn.linear_model import LogisticRegression
from sqlalchemy import func, select

from src.api.db.models import Attendance, Base, Prediction, Reminder, ReminderStatusHistory, Schedule
from src.api.db.session import make_engine
from src.api.main import create_app
from src.api.timeutil import now_wib, today_wib
from src.ml.feature_engineering import FEATURE_COLUMNS
from src.ml.predict import LoadedModel
from src.ml.train import load_dataset, make_pipeline


@pytest.fixture(scope="module")
def ml_model():
    """Model kecil (LR) yang dilatih cepat dari dataset training, hanya untuk tes."""
    df = load_dataset()
    pipe = make_pipeline(LogisticRegression(max_iter=2000, class_weight="balanced"))
    pipe.fit(df[FEATURE_COLUMNS], df["priority"])
    return LoadedModel(pipeline=pipe, metadata={"model_version": "test-model"})


def _make_client(model):
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    return TestClient(create_app(engine=engine, model=model))


@pytest.fixture
def client(ml_model):
    with _make_client(ml_model) as c:
        yield c


@pytest.fixture
def client_no_model():
    with _make_client(None) as c:
        yield c


def db_session(client):
    return client.app.state.session_factory()


def new_customer(client, nama="Ibu Sari", wa="081234567890", persona="ibu-ibu", **extra):
    r = client.post("/customers", json={"nama": nama, "no_whatsapp": wa, "persona": persona, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def new_schedule(client, when=None, nama="Yoga Lembut"):
    when = when or (now_wib() + timedelta(days=1))
    r = client.post("/schedules", json={"nama_kelas": nama, "tipe": "group_class",
                                        "waktu_mulai": when.isoformat(), "pelatih": "Coach Sari", "kapasitas": 15})
    assert r.status_code == 201, r.text
    return r.json()


def new_reminder(client, cid, sid=None, mtype="reminder_kelas"):
    r = client.post("/reminders", json={"customer_id": cid, "schedule_id": sid, "message_type": mtype})
    assert r.status_code == 201, r.text
    return r.json()


# ------------------------------------------------------------------ health
def test_health_with_model(client):
    body = client.get("/health").json()
    assert body == {"status": "ok", "db_connected": True, "model_loaded": True, "model_version": "test-model"}


def test_health_without_model(client_no_model):
    body = client_no_model.get("/health").json()
    assert body["model_loaded"] is False and body["model_version"] is None and body["db_connected"] is True


def test_unknown_route_uses_standard_error_format(client):
    r = client.get("/tidak-ada")
    assert r.status_code == 404 and r.json()["code"] == "not_found" and "detail" in r.json()


# ------------------------------------------------------------------ customers
def test_customer_crud_and_whatsapp_normalization(client):
    c = new_customer(client, wa="0812-3456-7890")
    assert c["no_whatsapp"] == "6281234567890" and c["join_date"] == today_wib().isoformat()
    assert client.get(f"/customers/{c['id']}").json()["nama"] == "Ibu Sari"
    r = client.patch(f"/customers/{c['id']}", json={"nama": "Ibu Sari W", "persona": "lansia"})
    assert r.status_code == 200 and r.json()["persona"] == "lansia"
    assert client.delete(f"/customers/{c['id']}").status_code == 204
    r = client.get(f"/customers/{c['id']}")
    assert r.status_code == 404 and r.json()["code"] == "not_found"


@pytest.mark.parametrize("payload", [
    {"nama": "A", "no_whatsapp": "12345", "persona": "ibu-ibu"},
    {"nama": "A", "no_whatsapp": "081234567890", "persona": "alien"},
    {"nama": "  ", "no_whatsapp": "081234567890", "persona": "lansia"},
    {"no_whatsapp": "081234567890", "persona": "lansia"},
])
def test_customer_validation_errors(client, payload):
    r = client.post("/customers", json=payload)
    assert r.status_code == 422 and r.json()["code"] == "validation_error"
    assert r.json()["detail"].startswith("Validasi gagal")


def test_duplicate_whatsapp_rejected(client):
    new_customer(client, wa="081234567890")
    r = client.post("/customers", json={"nama": "B", "no_whatsapp": "+6281234567890", "persona": "lansia"})
    assert r.status_code == 409 and r.json()["code"] == "duplicate_whatsapp"


def test_customer_list_pagination_search_filter(client):
    for i in range(5):
        new_customer(client, nama=f"Peserta {i}", wa=f"08123456780{i}", persona="lansia" if i % 2 else "ibu-ibu")
    page = client.get("/customers", params={"limit": 2, "offset": 0}).json()
    assert page["total"] == 5 and len(page["items"]) == 2 and page["limit"] == 2
    assert client.get("/customers", params={"q": "peserta 3"}).json()["total"] == 1
    assert client.get("/customers", params={"persona": "lansia"}).json()["total"] == 2
    assert client.get("/customers", params={"limit": 999}).status_code == 422


def test_delete_customer_removes_dependents(client):
    c = new_customer(client)
    rem = new_reminder(client, c["id"])
    client.post("/predict", json={"customer_id": c["id"]})
    assert client.delete(f"/customers/{c['id']}").status_code == 204
    with db_session(client) as db:
        assert db.scalar(select(func.count()).select_from(Reminder)) == 0
        assert db.scalar(select(func.count()).select_from(ReminderStatusHistory)) == 0
        assert db.scalar(select(func.count()).select_from(Prediction)) == 0


# ------------------------------------------------------------------ schedules
def test_schedule_crud(client):
    s = new_schedule(client)
    assert client.get(f"/schedules/{s['id']}").json()["nama_kelas"] == "Yoga Lembut"
    r = client.patch(f"/schedules/{s['id']}", json={"kapasitas": 20, "pelatih": "Coach Dina"})
    assert r.json()["kapasitas"] == 20 and r.json()["pelatih"] == "Coach Dina"
    assert client.get("/schedules").json()["total"] == 1
    assert client.delete(f"/schedules/{s['id']}").status_code == 204
    assert client.get(f"/schedules/{s['id']}").status_code == 404


def test_schedule_validation_and_filters(client):
    bad = {"nama_kelas": "X", "tipe": "group_class", "waktu_mulai": "2026-11-01T08:00:00", "pelatih": "C", "kapasitas": 0}
    assert client.post("/schedules", json=bad).status_code == 422
    new_schedule(client, datetime(2026, 11, 3, 9, 0))
    new_schedule(client, datetime(2026, 11, 10, 9, 0))
    r = client.get("/schedules", params={"date_from": "2026-11-05", "date_to": "2026-11-10"}).json()
    assert r["total"] == 1
    assert client.get("/schedules", params={"tipe": "private"}).json()["total"] == 0


def test_delete_schedule_keeps_reminder_with_null_schedule(client):
    c, s = new_customer(client), new_schedule(client)
    rem = new_reminder(client, c["id"], s["id"])
    assert client.delete(f"/schedules/{s['id']}").status_code == 204
    after = client.get(f"/reminders/{rem['id']}").json()
    assert after["schedule_id"] is None and after["schedule"] is None


# ------------------------------------------------------------------ reminders & status flow
def test_create_reminder_defaults_history_and_auto_priority(client):
    c, s = new_customer(client), new_schedule(client)
    rem = new_reminder(client, c["id"], s["id"])
    assert rem["status"] == "Scheduled" and rem["sent_at"] is None and rem["responded_at"] is None
    assert rem["priority"] in ("Low", "Medium")  # customer baru = cold start -> dibatasi Low/Medium
    assert set(rem["priority_probabilities"]) == {"Low", "Medium", "High"}
    assert rem["customer"]["nama"] == "Ibu Sari" and rem["schedule"]["nama_kelas"] == "Yoga Lembut"
    hist = client.get(f"/reminders/{rem['id']}/history").json()
    assert [(h["from_status"], h["to_status"]) for h in hist] == [(None, "Scheduled")]


def test_create_reminder_without_model_has_no_priority(client_no_model):
    c = new_customer(client_no_model)
    rem = new_reminder(client_no_model, c["id"])
    assert rem["priority"] is None and rem["status"] == "Scheduled"


def test_create_reminder_foreign_keys_and_duplicates(client):
    c, s = new_customer(client), new_schedule(client)
    assert client.post("/reminders", json={"customer_id": 999}).status_code == 404
    assert client.post("/reminders", json={"customer_id": c["id"], "schedule_id": 999}).status_code == 404
    new_reminder(client, c["id"], s["id"])
    r = client.post("/reminders", json={"customer_id": c["id"], "schedule_id": s["id"]})
    assert r.status_code == 409 and r.json()["code"] == "duplicate_reminder"
    # jenis pesan berbeda diperbolehkan
    new_reminder(client, c["id"], s["id"], mtype="follow_up_absen")


@pytest.mark.parametrize("path", [["Sent"], ["Sent", "Responded"], ["Sent", "No Response"]])
def test_valid_status_transitions_and_history(client, path):
    c = new_customer(client)
    rem = new_reminder(client, c["id"])
    prev = "Scheduled"
    for target in path:
        r = client.patch(f"/reminders/{rem['id']}/status", json={"status": target})
        assert r.status_code == 200 and r.json()["status"] == target
        prev = target
    body = client.get(f"/reminders/{rem['id']}").json()
    assert body["sent_at"] is not None
    assert (body["responded_at"] is not None) == (path[-1] == "Responded")
    hist = client.get(f"/reminders/{rem['id']}/history").json()
    assert len(hist) == 1 + len(path)  # Scheduled awal + satu entri per transisi
    assert [h["to_status"] for h in hist] == ["Scheduled"] + path
    assert [h["from_status"] for h in hist] == [None, "Scheduled"] + path[:-1]


INVALID = [
    ("Scheduled", ["Responded"]), ("Scheduled", ["No Response"]), ("Scheduled", ["Scheduled"]),
    ("Sent", ["Scheduled"]), ("Sent", ["Sent"]),
    ("Responded", ["Sent"]), ("Responded", ["Scheduled"]), ("Responded", ["No Response"]), ("Responded", ["Responded"]),
    ("No Response", ["Sent"]), ("No Response", ["Responded"]), ("No Response", ["Scheduled"]),
]


def _advance(client, rid, state):
    chain = {"Scheduled": [], "Sent": ["Sent"], "Responded": ["Sent", "Responded"], "No Response": ["Sent", "No Response"]}
    for s in chain[state]:
        assert client.patch(f"/reminders/{rid}/status", json={"status": s}).status_code == 200


@pytest.mark.parametrize("start,attempts", INVALID)
def test_invalid_status_transitions_rejected(client, start, attempts):
    c = new_customer(client)
    rem = new_reminder(client, c["id"])
    _advance(client, rem["id"], start)
    before = len(client.get(f"/reminders/{rem['id']}/history").json())
    for target in attempts:
        r = client.patch(f"/reminders/{rem['id']}/status", json={"status": target})
        assert r.status_code == 409, f"{start}->{target}"
        assert r.json()["code"] == "invalid_status_transition" and len(r.json()["detail"]) > 15
    assert client.get(f"/reminders/{rem['id']}").json()["status"] == start  # tidak berubah
    assert len(client.get(f"/reminders/{rem['id']}/history").json()) == before  # tidak tercatat


def test_invalid_transition_message_is_indonesian_and_explains_flow(client):
    rem = new_reminder(client, new_customer(client)["id"])
    detail = client.patch(f"/reminders/{rem['id']}/status", json={"status": "Responded"}).json()["detail"]
    assert "tidak diizinkan" in detail and "Scheduled → Sent → Responded / No Response" in detail


def test_status_unknown_value_is_validation_error(client):
    rem = new_reminder(client, new_customer(client)["id"])
    r = client.patch(f"/reminders/{rem['id']}/status", json={"status": "Selesai"})
    assert r.status_code == 422 and r.json()["code"] == "validation_error"
    assert client.patch("/reminders/9999/status", json={"status": "Sent"}).status_code == 404


def test_message_editable_only_before_sent(client):
    rem = new_reminder(client, new_customer(client)["id"])
    r = client.patch(f"/reminders/{rem['id']}/message", json={"final_message": "  Halo Bu, kelas besok ya.  "})
    assert r.status_code == 200 and r.json()["final_message"] == "Halo Bu, kelas besok ya."
    assert client.patch(f"/reminders/{rem['id']}/status", json={"status": "Sent"}).status_code == 200
    r = client.patch(f"/reminders/{rem['id']}/message", json={"final_message": "ubah lagi"})
    assert r.status_code == 409 and r.json()["code"] == "message_locked"
    assert client.get(f"/reminders/{rem['id']}").json()["final_message"] == "Halo Bu, kelas besok ya."
    rem2 = new_reminder(client, new_customer(client, wa="081234567891")["id"])
    assert client.patch(f"/reminders/{rem2['id']}/message", json={"final_message": ""}).status_code == 422


def test_sent_uses_draft_as_final_message_when_not_edited(client):
    rem = new_reminder(client, new_customer(client)["id"])
    with db_session(client) as db:
        db.get(Reminder, rem["id"]).draft_message = "Draft dari AI"
        db.commit()
    body = client.patch(f"/reminders/{rem['id']}/status", json={"status": "Sent"}).json()
    assert body["final_message"] == "Draft dari AI"


# ------------------------------------------------------------------ list, filter, urutan
def _set_priority(client, rid, priority):
    with db_session(client) as db:
        db.get(Reminder, rid).priority = priority
        db.commit()


def test_filter_today_and_priority_ordering(client):
    today = datetime.combine(today_wib(), time(8, 0))
    s_early = new_schedule(client, today.replace(hour=8), "Pagi")
    s_late = new_schedule(client, today.replace(hour=17), "Sore")
    s_tomorrow = new_schedule(client, today + timedelta(days=1), "Besok")
    cs = [new_customer(client, nama=f"C{i}", wa=f"0812000000{i}") for i in range(4)]
    r_low_early = new_reminder(client, cs[0]["id"], s_early["id"])
    r_high_late = new_reminder(client, cs[1]["id"], s_late["id"])
    r_med_early = new_reminder(client, cs[2]["id"], s_early["id"])
    r_tomorrow = new_reminder(client, cs[3]["id"], s_tomorrow["id"])
    for r, p in [(r_low_early, "Low"), (r_high_late, "High"), (r_med_early, "Medium"), (r_tomorrow, "High")]:
        _set_priority(client, r["id"], p)

    data = client.get("/reminders", params={"date": "today"}).json()
    assert data["total"] == 3  # reminder untuk kelas besok tidak ikut
    assert [i["id"] for i in data["items"]] == [r_high_late["id"], r_med_early["id"], r_low_early["id"]]  # High dulu
    assert client.get("/reminders", params={"date": "today", "priority": "High"}).json()["total"] == 1
    assert client.get("/reminders", params={"date": (today + timedelta(days=1)).date().isoformat()}).json()["total"] == 1
    assert client.get("/reminders", params={"status": "Sent"}).json()["total"] == 0
    assert client.get("/reminders", params={"customer_id": cs[0]["id"]}).json()["total"] == 1
    assert client.get("/reminders", params={"date": "bukan-tanggal"}).json()["code"] == "invalid_date"


def test_same_priority_ordered_by_nearest_class_time(client):
    today = datetime.combine(today_wib(), time(0, 0))
    s1, s2 = new_schedule(client, today.replace(hour=18)), new_schedule(client, today.replace(hour=7))
    c1, c2 = new_customer(client, wa="081200000001"), new_customer(client, wa="081200000002")
    a, b = new_reminder(client, c1["id"], s1["id"]), new_reminder(client, c2["id"], s2["id"])
    _set_priority(client, a["id"], "High")
    _set_priority(client, b["id"], "High")
    ids = [i["id"] for i in client.get("/reminders", params={"date": "today"}).json()["items"]]
    assert ids == [b["id"], a["id"]]


def test_customer_reminder_history_endpoint(client):
    c = new_customer(client)
    new_reminder(client, c["id"])
    new_reminder(client, c["id"], mtype="follow_up_absen")
    page = client.get(f"/customers/{c['id']}/reminders").json()
    assert page["total"] == 2
    assert client.get("/customers/9999/reminders").status_code == 404


def test_list_reminders_uses_constant_number_of_queries(client):
    """Tidak ada N+1: jumlah query tidak bertambah seiring jumlah reminder."""
    from sqlalchemy import event

    s = new_schedule(client)
    for i in range(6):
        new_reminder(client, new_customer(client, nama=f"C{i}", wa=f"0812999999{i}")["id"], s["id"])
    counter = {"n": 0}
    engine = client.app.state.engine
    event.listen(engine, "before_cursor_execute", lambda *a, **k: counter.__setitem__("n", counter["n"] + 1))
    assert len(client.get("/reminders").json()["items"]) == 6
    assert counter["n"] <= 3  # count + select (+ toleransi)


# ------------------------------------------------------------------ predict
def _add_history(client, customer_id, statuses):
    with db_session(client) as db:
        base = datetime.combine(today_wib(), time(9, 0)) - timedelta(days=len(statuses) * 3)
        for i, st in enumerate(statuses):
            sch = Schedule(nama_kelas="Zumba", tipe="group_class", waktu_mulai=base + timedelta(days=i * 3),
                           pelatih="Coach Dina", kapasitas=20)
            db.add(sch)
            db.flush()
            db.add(Attendance(customer_id=customer_id, schedule_id=sch.id, status=st))
        db.commit()


def test_predict_with_history_returns_contract_and_saves_prediction(client):
    c = new_customer(client)
    _add_history(client, c["id"], ["hadir", "hadir", "tidak_hadir", "tidak_hadir", "tidak_hadir", "tidak_hadir"])
    r = client.post("/predict", json={"customer_id": c["id"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["priority"] in ("Low", "Medium", "High") and body["cold_start"] is False
    assert abs(sum(body["probabilities"].values()) - 1) < 0.01 and body["model_version"] == "test-model"
    assert any("absen berturut-turut" in f for f in body["top_factors"]) and len(body["top_factors"]) <= 3
    assert body["prediction_id"] is not None and body["reference_date"] == today_wib().isoformat()
    with db_session(client) as db:
        row = db.get(Prediction, body["prediction_id"])
        assert row.customer_id == c["id"] and row.priority == body["priority"] and row.top_factors == body["top_factors"]


def test_predict_cold_start(client):
    c = new_customer(client)
    body = client.post("/predict", json={"customer_id": c["id"]}).json()
    assert body["cold_start"] is True and body["note"] == "riwayat belum cukup"
    assert body["priority"] in ("Low", "Medium") and body["top_factors"] == []


def test_predict_unknown_customer_404(client):
    r = client.post("/predict", json={"customer_id": 12345})
    assert r.status_code == 404 and r.json()["code"] == "not_found"


def test_predict_without_model_503(client_no_model):
    c = new_customer(client_no_model)
    r = client_no_model.post("/predict", json={"customer_id": c["id"]})
    assert r.status_code == 503 and r.json()["code"] == "model_unavailable"
    rem = new_reminder(client_no_model, c["id"])
    assert client_no_model.post(f"/reminders/{rem['id']}/refresh-priority").status_code == 503


def test_predict_respects_reference_date_no_future_leak(client):
    c = new_customer(client)
    _add_history(client, c["id"], ["hadir"] * 6)
    past = (today_wib() - timedelta(days=400)).isoformat()  # sebelum semua riwayat -> cold start
    assert client.post("/predict", json={"customer_id": c["id"], "reference_date": past}).json()["cold_start"] is True


def test_refresh_priority_updates_reminder(client):
    c = new_customer(client)
    _add_history(client, c["id"], ["tidak_hadir"] * 6)
    rem = new_reminder(client, c["id"])
    _set_priority(client, rem["id"], None)
    out = client.post(f"/reminders/{rem['id']}/refresh-priority").json()
    assert out["priority"] in ("Low", "Medium", "High") and out["priority_probabilities"] is not None
    assert client.post("/reminders/9999/refresh-priority").status_code == 404


# ------------------------------------------------------------------ generate-draft (Fase 4) & DB tidak tersedia
def test_generate_draft_unknown_reminder_404(client):
    # Menggantikan tes placeholder 501 Fase 3; perilaku lengkap dites di tests/test_drafts.py
    r = client.post("/generate-draft", json={"reminder_id": 1})
    assert r.status_code == 404 and r.json() == {"detail": "Reminder dengan id 1 tidak ditemukan.", "code": "not_found"}


def test_database_unavailable_returns_503(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from src.api.config import Settings

    app = create_app(settings=Settings(database_url=None), engine=None, model=None)
    with TestClient(app) as c:
        assert c.get("/health").json()["status"] == "degraded"
        r = c.get("/customers")
        assert r.status_code == 503 and r.json()["code"] == "database_unavailable"


def test_root_redirects_to_docs(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "/docs"
    assert client.get("/docs").status_code == 200
