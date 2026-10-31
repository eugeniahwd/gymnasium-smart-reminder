"""Inference prioritas follow-up.

Kontrak (docs/AI_SPEC.md bagian A4):
    predict_priority(features) -> {
        "priority": "High", "probabilities": {"Low":..,"Medium":..,"High":..},
        "top_factors": [...], "model_version": "...", "cold_start": False, "note": None
    }
`features` = dict dari src.ml.feature_engineering.compute_customer_features (modul yang sama dengan training).
"""
from __future__ import annotations

import json
import warnings
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Mapping

import joblib
import numpy as np
import pandas as pd

from src.ml.feature_engineering import CLASSES, features_to_frame, has_enough_history

ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"
MODEL_PATH = ARTIFACT_DIR / "priority_model.joblib"
METADATA_PATH = ARTIFACT_DIR / "model_metadata.json"
COLD_START_NOTE = "riwayat belum cukup"


class ModelNotFoundError(FileNotFoundError):
    """Artefak model tidak ditemukan (API harus membalas 503, bukan crash)."""


@dataclass
class LoadedModel:
    pipeline: object
    metadata: dict

    @property
    def version(self) -> str:
        return self.metadata.get("model_version", "unknown")


def load_model(model_path: Path | str | None = None, metadata_path: Path | str | None = None) -> LoadedModel:
    """Muat pipeline + metadata. Panggil SEKALI saat startup; hasil default di-cache."""
    if model_path is None and metadata_path is None:
        return _load_default()
    return _load(Path(model_path or MODEL_PATH), Path(metadata_path or METADATA_PATH))


@lru_cache(maxsize=1)
def _load_default() -> LoadedModel:
    return _load(MODEL_PATH, METADATA_PATH)


def _load(model_path: Path, metadata_path: Path) -> LoadedModel:
    if not model_path.exists():
        raise ModelNotFoundError(f"File model tidak ditemukan: {model_path}")
    pipeline = joblib.load(model_path)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    import sklearn

    trained_with = metadata.get("sklearn_version")
    if trained_with and trained_with != sklearn.__version__:
        warnings.warn(
            f"Model dilatih dengan scikit-learn {trained_with}, saat ini {sklearn.__version__}. "
            "Jalankan ulang `python -m src.ml.train` agar artefak sesuai.",
            stacklevel=2,
        )
    return LoadedModel(pipeline=pipeline, metadata=metadata)


def _num(features: Mapping, key: str) -> float:
    v = features.get(key)
    return float("nan") if v is None else float(v)


def build_top_factors(features: Mapping, max_items: int = 3) -> list[str]:
    """Alasan prioritas untuk ADMIN (bahasa Indonesia, maksimal 3), berbasis nilai fitur."""
    out: list[str] = []
    streak = _num(features, "consecutive_absences")
    rate30 = _num(features, "attendance_rate_30d")
    nores = _num(features, "no_response_streak")
    dsla = _num(features, "days_since_last_attendance")
    resp = _num(features, "reminder_response_rate")
    resched = _num(features, "reschedule_count_90d")

    if streak >= 2:
        out.append(f"{int(streak)} absen berturut-turut")
    if rate30 < 0.5:
        out.append(f"tingkat kehadiran 30 hari: {rate30:.0%}")
    if nores >= 2:
        out.append(f"{int(nores)} reminder terakhir tidak direspons")
    if dsla > 14:
        out.append(f"belum hadir selama {int(dsla)} hari")
    if resp < 0.4:
        out.append(f"jarang merespons reminder ({resp:.0%} direspons)")
    if resched >= 3:
        out.append(f"{int(resched)}x reschedule dalam 90 hari")
    return out[:max_items]


def predict_priority(features: Mapping, model: LoadedModel | None = None) -> dict:
    """Prediksi prioritas follow-up untuk satu customer."""
    model = model or load_model()
    X = features_to_frame(features)
    proba = model.pipeline.predict_proba(X)[0]
    by_class = {c: float(proba[list(model.pipeline.classes_).index(c)]) for c in CLASSES}
    priority = max(by_class, key=by_class.get)

    cold = not has_enough_history(features)
    note = None
    if cold:
        # riwayat terlalu sedikit: jangan klaim High; batasi Low/Medium
        if priority == "High":
            priority = "Medium"
        note = COLD_START_NOTE

    total = sum(by_class.values()) or 1.0
    return {
        "priority": priority,
        "probabilities": {c: round(v / total, 4) for c, v in by_class.items()},
        "top_factors": [] if cold else build_top_factors(features),
        "model_version": model.version,
        "cold_start": cold,
        "note": note,
    }
