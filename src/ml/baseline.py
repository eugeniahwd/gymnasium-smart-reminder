"""Baseline rule-based sederhana (pembanding model ML).

Sengaja memakai HANYA dua fitur (attendance_rate_30d, consecutive_absences) dengan ambang tetap.
Aturan ini BERBEDA dari rumus pembuat label di generator (yang memakai skor laten + faktor tersembunyi),
sehingga perbandingan model vs baseline tetap bermakna.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin

# Aturan (dievaluasi berurutan):
#   High   : kehadiran 30 hari < 40%  ATAU  absen berturut-turut >= 3
#   Medium : kehadiran 30 hari < 65%  ATAU  absen berturut-turut >= 1
#   Low    : selain itu (termasuk customer tanpa riwayat kehadiran)
HIGH_RATE, MEDIUM_RATE = 0.40, 0.65
HIGH_STREAK, MEDIUM_STREAK = 3, 1

RULE_DESCRIPTION = (
    f"High jika attendance_rate_30d < {HIGH_RATE} atau consecutive_absences >= {HIGH_STREAK}; "
    f"Medium jika attendance_rate_30d < {MEDIUM_RATE} atau consecutive_absences >= {MEDIUM_STREAK}; "
    "selain itu Low."
)


class RuleBaseline(ClassifierMixin, BaseEstimator):
    """Classifier berbasis aturan, kompatibel dengan API scikit-learn (fit tidak belajar apa pun)."""

    def fit(self, X, y=None):
        self.classes_ = np.array(["High", "Low", "Medium"])
        return self

    def predict(self, X) -> np.ndarray:
        df = pd.DataFrame(X)
        rate = df["attendance_rate_30d"].to_numpy(dtype=float)
        streak = df["consecutive_absences"].fillna(0).to_numpy(dtype=float)
        has_rate = ~np.isnan(rate)
        high = (has_rate & (rate < HIGH_RATE)) | (streak >= HIGH_STREAK)
        medium = (has_rate & (rate < MEDIUM_RATE)) | (streak >= MEDIUM_STREAK)
        return np.where(high, "High", np.where(medium, "Medium", "Low")).astype(object)
