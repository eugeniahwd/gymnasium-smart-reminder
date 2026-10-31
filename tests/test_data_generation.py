"""Test Fase 1: generator dataset synthetic, fitur tanpa kebocoran, dan seed DB."""
import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from src.data_generation import generate as gen
from src.data_generation import seed_db
from src.ml.feature_engineering import (
    CATEGORICAL_FEATURES,
    CLASSES,
    FEATURE_COLUMNS,
    ID_COLUMNS,
    build_feature_frame,
    compute_customer_features,
    has_enough_history,
    join_attendance_schedules,
)

N = 120


@pytest.fixture(scope="module")
def data():
    return gen.generate_all(n_customers=N, seed=7)


def test_reproducible_same_seed(data):
    again = gen.generate_all(n_customers=N, seed=7)
    for name in data:
        pd.testing.assert_frame_equal(data[name], again[name])


def test_different_seed_differs(data):
    other = gen.generate_all(n_customers=N, seed=8)
    assert not data["training_dataset"]["attendance_rate_30d"].equals(other["training_dataset"]["attendance_rate_30d"])


def test_labels_valid_and_distribution_near_target(data):
    tr = data["training_dataset"]
    assert set(tr["priority"].unique()) <= set(CLASSES)
    dist = tr["priority"].value_counts(normalize=True)
    for cls, target in gen.TARGET_DIST.items():
        assert abs(dist.get(cls, 0) - target) < 0.07, f"{cls}: {dist.get(cls, 0):.3f} vs {target}"


def test_training_columns(data):
    tr = data["training_dataset"]
    for col in ID_COLUMNS + FEATURE_COLUMNS + ["priority"]:
        assert col in tr.columns
    assert not set(ID_COLUMNS) & set(FEATURE_COLUMNS)  # id/tanggal bukan fitur
    assert set(tr["persona"].unique()) <= set(gen.PERSONAS)


def test_hidden_factors_not_in_dataset(data):
    for col in ["motivation", "busyness", "base_attend", "trend"]:
        assert col not in data["training_dataset"].columns


def test_has_missing_values(data):
    assert data["training_dataset"][FEATURE_COLUMNS].isna().any().any()


def test_3_to_4_snapshots_per_customer(data):
    per = data["training_dataset"].groupby("customer_id").size()
    assert per.max() <= 4 and per.min() >= 1


def test_no_future_leakage(data):
    """Fitur tidak berubah jika SEMUA data pada/setelah reference_date dibuang."""
    customers = data["customers"]
    att = join_attendance_schedules(data["attendance"], data["schedules"])
    rem = data["reminders"]
    tr = data["training_dataset"].sample(60, random_state=1)
    for r in tr.itertuples():
        ref = pd.Timestamp(r.reference_date)
        c = customers[customers["id"] == r.customer_id].iloc[0]
        a_all = att[att["customer_id"] == r.customer_id]
        m_all = rem[rem["customer_id"] == r.customer_id]
        full = compute_customer_features(c["persona"], c["join_date"], a_all, m_all, ref)
        trimmed = compute_customer_features(
            c["persona"],
            c["join_date"],
            a_all[a_all["waktu_mulai"] < ref],
            m_all[m_all["sent_at"] < ref],
            ref,
        )
        for k in FEATURE_COLUMNS:
            a, b = full[k], trimmed[k]
            assert (pd.isna(a) and pd.isna(b)) or a == b, f"{k} berubah: {a} vs {b}"


def test_features_match_training_rows(data):
    """Fitur yang dihitung ulang = fitur di dataset (sebelum injeksi missing acak)."""
    tr = data["training_dataset"]
    att = join_attendance_schedules(data["attendance"], data["schedules"])
    snaps = tr[ID_COLUMNS].head(15)
    re = build_feature_frame(data["customers"], att, data["reminders"], snaps)
    for col in ["attendance_rate_30d", "consecutive_absences", "tenure_days", "persona"]:
        left, right = tr.head(15)[col].reset_index(drop=True), re[col].reset_index(drop=True)
        pd.testing.assert_series_equal(left, right, check_names=False)


def test_cold_start_customer():
    f = compute_customer_features("lansia", "2026-09-01", None, None, "2026-09-05")
    assert not has_enough_history(f)
    assert f["favorite_class_type"] == "unknown"
    assert np.isnan(f["attendance_rate_30d"])


def test_referential_integrity(data):
    assert seed_db.validate({k: v for k, v in data.items() if k != "training_dataset"}) == []


def test_enum_values_match_schema(data):
    assert set(data["attendance"]["status"]) <= {"hadir", "tidak_hadir", "reschedule"}
    assert set(data["reminders"]["status"]) <= {"Responded", "No Response"}
    assert set(data["reminders"]["message_type"]) <= {"reminder_kelas", "follow_up_absen", "follow_up_tidak_merespons"}
    assert set(data["schedules"]["tipe"]) <= {"group_class", "private"}
    assert data["customers"]["no_whatsapp"].is_unique


def test_response_after_sent(data):
    r = data["reminders"].dropna(subset=["responded_at"])
    assert (r["responded_at"] > r["sent_at"]).all()


def test_seed_roundtrip_sqlite(data, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    frames = {n: df for n, df in data.items() if n != "training_dataset"}
    counts = seed_db.seed(engine, frames)
    with engine.connect() as conn:
        for name, n_rows in counts.items():
            assert conn.execute(text(f"SELECT count(*) FROM {name}")).scalar() == n_rows
