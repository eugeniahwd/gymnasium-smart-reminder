"""Hitung fitur dari database (modul feature_engineering YANG SAMA dengan training) lalu prediksi."""
from __future__ import annotations

from datetime import date

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.db.models import Attendance, Customer, Prediction, Reminder, Schedule
from src.api.errors import APIError
from src.api.timeutil import now_wib, today_wib
from src.ml.feature_engineering import compute_customer_features
from src.ml.predict import LoadedModel, predict_priority


def load_history(db: Session, customer_id: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    att_rows = db.execute(
        select(Attendance.status, Schedule.waktu_mulai, Schedule.tipe)
        .join(Schedule, Schedule.id == Attendance.schedule_id)
        .where(Attendance.customer_id == customer_id)
    ).all()
    rem_rows = db.execute(
        select(Reminder.status, Reminder.sent_at, Reminder.responded_at).where(Reminder.customer_id == customer_id)
    ).all()
    att = pd.DataFrame(att_rows, columns=["status", "waktu_mulai", "tipe"])
    rem = pd.DataFrame(rem_rows, columns=["status", "sent_at", "responded_at"])
    return att, rem


def compute_features(db: Session, customer: Customer, reference_date: date) -> dict:
    att, rem = load_history(db, customer.id)
    return compute_customer_features(customer.persona, customer.join_date, att, rem, reference_date)


def require_model(model: LoadedModel | None) -> LoadedModel:
    if model is None:
        raise APIError(503, "model_unavailable",
                       "Model prediksi belum tersedia di server. Jalankan `python -m src.ml.train` lalu deploy ulang.")
    return model


def run_prediction(db: Session, customer: Customer, model: LoadedModel | None,
                   reference_date: date | None = None, persist: bool = True) -> dict:
    """Prediksi prioritas satu customer; hasil disimpan ke tabel predictions (caller yang commit)."""
    model = require_model(model)
    ref = reference_date or today_wib()
    features = compute_features(db, customer, ref)
    result = predict_priority(features, model)
    result.update({"customer_id": customer.id, "reference_date": ref, "prediction_id": None})
    if persist:
        row = Prediction(customer_id=customer.id, priority=result["priority"], probabilities=result["probabilities"],
                         top_factors=result["top_factors"], model_version=result["model_version"], created_at=now_wib())
        db.add(row)
        db.flush()
        result["prediction_id"] = row.id
    return result
