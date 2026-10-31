"""Test Fase 2: pipeline, split, inference, cold start, top_factors."""
import json
import math

import numpy as np
import pandas as pd
import pytest

from src.ml import predict as pr
from src.ml.baseline import RuleBaseline
from src.ml.feature_engineering import (
    CATEGORICAL_FEATURES,
    CLASSES,
    FEATURE_COLUMNS,
    ID_COLUMNS,
    NUMERIC_FEATURES,
    compute_customer_features,
    join_attendance_schedules,
)
from src.ml.train import load_dataset, run_training


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    out = tmp_path_factory.mktemp("artifacts")
    res = run_training(output_dir=out, fig_dir=out / "figs", fast=True, write=True, update_docs=False, verbose=False)
    return res, out


@pytest.fixture(scope="module")
def loaded(trained):
    _, out = trained
    return pr.load_model(out / "priority_model.joblib", out / "model_metadata.json")


def test_features_exclude_ids():
    assert not set(ID_COLUMNS) & set(FEATURE_COLUMNS)
    assert "n_history_events" not in FEATURE_COLUMNS
    assert set(NUMERIC_FEATURES + CATEGORICAL_FEATURES) == set(FEATURE_COLUMNS)


def test_no_customer_overlap(trained):
    res, _ = trained
    assert not res["train_customers"] & res["test_customers"]
    assert abs(len(res["test_idx"]) / res["df_shape"][0] - 0.2) < 0.05  # sekitar 20%


def test_artifacts_and_metadata(trained):
    _, out = trained
    assert (out / "priority_model.joblib").exists()
    meta = json.loads((out / "model_metadata.json").read_text(encoding="utf-8"))
    for key in ["model_version", "classes", "features", "test_metrics", "seed", "sklearn_version", "disclaimer"]:
        assert key in meta
    assert set(meta["classes"]) == set(CLASSES)


def test_model_beats_dummy_and_no_leakage_flag(trained):
    res, _ = trained
    tm = res["test_metrics"]
    assert tm[res["chosen"]]["macro_f1"] > tm["Dummy (kelas terbanyak)"]["macro_f1"] + 0.2
    assert not res["leakage_suspected"]
    assert tm[res["chosen"]]["accuracy"] < 0.97


def test_baseline_rule_is_simple_and_valid():
    df = load_dataset().head(200)
    pred = RuleBaseline().fit(df[FEATURE_COLUMNS]).predict(df[FEATURE_COLUMNS])
    assert set(pred) <= set(CLASSES)
    assert (pred == df["priority"].to_numpy()).mean() < 0.97  # baseline bukan rumus label


def test_model_predicts_valid_classes_and_probabilities(loaded):
    df = load_dataset().sample(30, random_state=0)
    for row in df.to_dict("records"):
        out = pr.predict_priority(row, loaded)
        assert out["priority"] in CLASSES
        assert math.isclose(sum(out["probabilities"].values()), 1.0, abs_tol=0.01)
        assert set(out["probabilities"]) == set(CLASSES)
        assert out["model_version"] == loaded.version


def test_cold_start_does_not_error_and_caps_priority(loaded):
    f = compute_customer_features("lansia", "2026-09-01", None, None, "2026-09-05")
    out = pr.predict_priority(f, loaded)
    assert out["cold_start"] is True
    assert out["priority"] in ("Low", "Medium")
    assert out["note"] == "riwayat belum cukup"
    assert out["top_factors"] == []


def test_top_factors_indonesian_max3_and_empty():
    bad = {"consecutive_absences": 4, "attendance_rate_30d": 0.2, "no_response_streak": 3,
           "days_since_last_attendance": 30, "reminder_response_rate": 0.1, "reschedule_count_90d": 5}
    tf = pr.build_top_factors(bad)
    assert 1 <= len(tf) <= 3
    assert any("absen" in t or "kehadiran" in t or "reminder" in t for t in tf)
    good = {"consecutive_absences": 0, "attendance_rate_30d": 0.9, "no_response_streak": 0,
            "days_since_last_attendance": 3, "reminder_response_rate": 0.9, "reschedule_count_90d": 0}
    assert pr.build_top_factors(good) == []
    nan_case = {k: float("nan") for k in good}
    assert pr.build_top_factors(nan_case) == []  # NaN tidak memicu alasan palsu


def test_inference_from_raw_tables_matches_training_row(loaded):
    """Fitur dihitung dari tabel mentah (jalur inference) = fitur di training_dataset (tanpa train-serve skew)."""
    from src.data_generation.seed_db import load_csvs

    frames = load_csvs()
    tr = load_dataset()
    row = tr[tr["n_history_events"] >= 10].iloc[0]
    c = frames["customers"][frames["customers"]["id"] == row["customer_id"]].iloc[0]
    att = join_attendance_schedules(frames["attendance"], frames["schedules"])
    att = att[att["customer_id"] == row["customer_id"]]
    rem = frames["reminders"][frames["reminders"]["customer_id"] == row["customer_id"]]
    feats = compute_customer_features(c["persona"], c["join_date"], att, rem, row["reference_date"])
    for col in ["attendance_rate_30d", "attendance_rate_90d", "consecutive_absences", "no_response_streak", "tenure_days"]:
        assert np.isclose(feats[col], row[col], equal_nan=True, atol=1e-9)
    out = pr.predict_priority(feats, loaded)
    assert out["priority"] in CLASSES


def test_load_model_missing_file_raises(tmp_path):
    with pytest.raises(pr.ModelNotFoundError):
        pr.load_model(tmp_path / "nope.joblib", tmp_path / "nope.json")
