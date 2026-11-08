"""Test seed_demo: kelanjutan timeline sampai hari ini (SQLite sementara)."""
from datetime import datetime

import pytest
from sklearn.linear_model import LogisticRegression
from sqlalchemy import text

from src.api.db.models import Base
from src.api.db.session import make_engine
from src.data_generation import generate as gen
from src.data_generation import seed_db, seed_demo
from src.ml.feature_engineering import FEATURE_COLUMNS
from src.ml.predict import LoadedModel
from src.ml.train import load_dataset, make_pipeline

NOW = datetime(2026, 11, 2, 9, 0)  # Senin


@pytest.fixture(scope="module")
def synthetic():
    return {k: v for k, v in gen.generate_all(n_customers=60, seed=7).items() if k != "training_dataset"}


def fresh_engine(tmp_path, synthetic):
    engine = make_engine(f"sqlite:///{tmp_path / 'demo.db'}")
    Base.metadata.create_all(engine)
    seed_db.seed(engine, synthetic)
    with engine.begin() as cn:  # SQLite menyimpan DATE dari pandas sebagai teks bertanggal-jam
        cn.execute(text("UPDATE customers SET join_date = substr(join_date, 1, 10)"))
    return engine


def scalar(engine, sql, **p):
    with engine.connect() as cn:
        return cn.execute(text(sql), p).scalar()


def test_extends_timeline_and_is_idempotent(tmp_path, synthetic):
    engine = fresh_engine(tmp_path, synthetic)
    n_old = scalar(engine, "SELECT count(*) FROM schedules")
    s1 = seed_demo.run(engine, now=NOW, predict=False, verbose=False)
    after1 = {t: scalar(engine, f"SELECT count(*) FROM {t}") for t in ["schedules", "attendance", "reminders"]}
    s2 = seed_demo.run(engine, now=NOW, predict=False, verbose=False)
    after2 = {t: scalar(engine, f"SELECT count(*) FROM {t}") for t in ["schedules", "attendance", "reminders"]}
    assert s1["inserted"] == s2["inserted"] and after1 == after2  # aman dijalankan berulang
    assert after1["schedules"] > n_old and s1["scheduled_reminders"] > 0
    # data synthetic asli tidak tersentuh
    assert scalar(engine, "SELECT count(*) FROM schedules WHERE waktu_mulai <= :c", c=seed_demo.CUTOFF) == n_old


def test_scheduled_reminders_target_today_and_future_classes(tmp_path, synthetic):
    engine = fresh_engine(tmp_path, synthetic)
    seed_demo.run(engine, now=NOW, days_ahead=2, predict=False, verbose=False)
    bad = scalar(engine, """SELECT count(*) FROM reminders r JOIN schedules s ON s.id = r.schedule_id
                            WHERE r.status = 'Scheduled' AND (s.waktu_mulai < '2026-11-02 00:00:00'
                                                              OR s.waktu_mulai >= '2026-11-05 00:00:00')""")
    assert bad == 0
    assert scalar(engine, "SELECT count(*) FROM reminders WHERE status = 'Scheduled' AND sent_at IS NOT NULL") == 0
    assert scalar(engine, "SELECT count(*) FROM reminders WHERE status = 'Scheduled' AND created_at > '2026-09-30 23:59:59'") > 0


def test_no_event_in_the_future_of_now(tmp_path, synthetic):
    engine = fresh_engine(tmp_path, synthetic)
    seed_demo.run(engine, now=NOW, predict=False, verbose=False)
    assert scalar(engine, "SELECT count(*) FROM reminders WHERE responded_at > :n", n=NOW) == 0
    assert scalar(engine, "SELECT count(*) FROM reminders WHERE sent_at > :n", n=NOW) == 0
    assert scalar(engine, """SELECT count(*) FROM attendance a JOIN schedules s ON s.id = a.schedule_id
                             WHERE s.waktu_mulai >= '2026-11-02 00:00:00'""") == 0  # kehadiran hanya sampai kemarin


def test_foreign_keys_valid_after_extension(tmp_path, synthetic):
    engine = fresh_engine(tmp_path, synthetic)
    seed_demo.run(engine, now=NOW, predict=False, verbose=False)
    checks = [
        "SELECT count(*) FROM attendance WHERE schedule_id NOT IN (SELECT id FROM schedules)",
        "SELECT count(*) FROM attendance WHERE customer_id NOT IN (SELECT id FROM customers)",
        "SELECT count(*) FROM reminders WHERE schedule_id IS NOT NULL AND schedule_id NOT IN (SELECT id FROM schedules)",
        "SELECT count(*) FROM reminder_status_history WHERE reminder_id NOT IN (SELECT id FROM reminders)",
        "SELECT count(*) FROM reschedules WHERE schedule_id_asal NOT IN (SELECT id FROM schedules)",
    ]
    assert [scalar(engine, c) for c in checks] == [0] * len(checks)


def test_priorities_assigned_and_distribution_is_sane(tmp_path, synthetic):
    engine = fresh_engine(tmp_path, synthetic)
    summary = seed_demo.run(engine, now=NOW, predict=False, verbose=False)
    df = load_dataset()
    pipe = make_pipeline(LogisticRegression(max_iter=2000, class_weight="balanced")).fit(df[FEATURE_COLUMNS], df["priority"])
    model = LoadedModel(pipeline=pipe, metadata={"model_version": "test-model"})
    with engine.connect() as cn:
        ids = [r[0] for r in cn.execute(text("SELECT id FROM reminders WHERE status = 'Scheduled' AND created_at > '2026-09-30 23:59:59'"))]
    n = seed_demo.assign_priorities(engine, ids, NOW.date(), model, verbose=False)
    assert n == len(ids) == summary["scheduled_reminders"]
    assert scalar(engine, "SELECT count(*) FROM reminders WHERE status = 'Scheduled' AND priority IS NULL "
                          "AND created_at > '2026-09-30 23:59:59'") == 0
    high = scalar(engine, "SELECT count(*) FROM reminders WHERE priority = 'High'")
    total = scalar(engine, "SELECT count(*) FROM reminders WHERE priority IS NOT NULL")
    assert 0.10 < high / total < 0.50  # sebaran wajar (kondisi akhir data synthetic: sekitar 24% High)
    assert scalar(engine, "SELECT count(*) FROM predictions") > 0


# ------------------------------------------------------------------ ketahanan koneksi & atomisitas
from sqlalchemy import event  # noqa: E402
from pandas.errors import DatabaseError  # noqa: E402
from sqlalchemy.exc import IntegrityError, OperationalError  # noqa: E402


class _FakeEngine:
    def __init__(self):
        self.disposed = 0

    def dispose(self):
        self.disposed += 1


def _drop():
    return OperationalError("SELECT 1", {}, Exception("SSL error: unexpected eof while reading"))


def test_retry_recovers_after_dropped_connections(monkeypatch):
    monkeypatch.setattr(seed_demo._time, "sleep", lambda s: None)
    calls, eng = {"n": 0}, _FakeEngine()

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _drop()
        return "ok"

    assert seed_demo._retry(flaky, eng, "uji", log=lambda *a: None) == "ok"
    assert calls["n"] == 3 and eng.disposed == 2  # koneksi dibuang dan dibuat ulang tiap gagal


def test_retry_gives_up_and_ignores_non_connection_errors(monkeypatch):
    monkeypatch.setattr(seed_demo._time, "sleep", lambda s: None)
    eng = _FakeEngine()
    with pytest.raises(OperationalError):
        seed_demo._retry(lambda: (_ for _ in ()).throw(_drop()), eng, "uji", attempts=3, log=lambda *a: None)
    assert eng.disposed == 2
    calls = {"n": 0}

    def bug():
        calls["n"] += 1
        raise ValueError("bug logika")

    with pytest.raises(ValueError):
        seed_demo._retry(bug, eng, "uji", log=lambda *a: None)
    assert calls["n"] == 1  # error non-koneksi tidak diulang


def test_full_run_survives_connection_drops_while_reading(tmp_path, synthetic, monkeypatch):
    """Simulasi persis kasus nyata: koneksi putus saat membaca tabel attendance."""
    monkeypatch.setattr(seed_demo._time, "sleep", lambda s: None)
    engine = fresh_engine(tmp_path, synthetic)
    baseline = seed_demo.run(engine, now=NOW, predict=False, verbose=False)

    state = {"fails": 2}

    @event.listens_for(engine, "before_cursor_execute")
    def _flaky(conn, cursor, statement, params, context, executemany):
        if "FROM attendance" in statement and state["fails"] > 0:
            state["fails"] -= 1
            raise _drop()

    result = seed_demo.run(engine, now=NOW, predict=False, verbose=False)
    assert state["fails"] == 0  # gangguan benar-benar terjadi dua kali
    assert result["inserted"] == baseline["inserted"]  # tetap menghasilkan data yang sama


def test_failed_insert_rolls_back_purge(tmp_path, synthetic):
    """Jika penyisipan gagal di tengah, data demo lama TIDAK ikut hilang (satu transaksi)."""
    engine = fresh_engine(tmp_path, synthetic)
    seed_demo.run(engine, now=NOW, predict=False, verbose=False)
    before = scalar(engine, "SELECT count(*) FROM schedules WHERE waktu_mulai > :c", c=seed_demo.CUTOFF)
    assert before > 0
    data = seed_demo._only_original(seed_demo._read(engine))
    frames = seed_demo.build_continuation(data, NOW)
    frames["attendance"].loc[frames["attendance"].index[0], "id"] = 1  # bentrok dengan PK data lama
    with pytest.raises((IntegrityError, DatabaseError)) as exc_info:  # pandas membungkus error SQLAlchemy
        seed_demo.insert_frames(engine, frames)
    assert not seed_demo._is_connection_error(exc_info.value)  # bukan gangguan koneksi -> tidak diulang
    assert scalar(engine, "SELECT count(*) FROM schedules WHERE waktu_mulai > :c", c=seed_demo.CUTOFF) == before


def test_run_removes_manual_test_reminders_after_cutoff(tmp_path, synthetic):
    """Perilaku yang didokumentasikan: reminder buatan admin setelah 30 Sep ikut dihapus saat demo disegarkan."""
    engine = fresh_engine(tmp_path, synthetic)
    seed_demo.run(engine, now=NOW, predict=False, verbose=False)
    with engine.begin() as cn:
        cn.execute(text("INSERT INTO reminders (customer_id, status, message_type, created_at, updated_at) "
                        "VALUES (1, 'Scheduled', 'reminder_kelas', '2026-11-02 10:00:00.000000', '2026-11-02 10:00:00.000000')"))
    n = scalar(engine, "SELECT count(*) FROM reminders WHERE schedule_id IS NULL AND created_at > :c", c=seed_demo.CUTOFF)
    assert n == 1
    seed_demo.run(engine, now=NOW, predict=False, verbose=False)
    assert scalar(engine, "SELECT count(*) FROM reminders WHERE schedule_id IS NULL AND created_at > :c", c=seed_demo.CUTOFF) == 0
