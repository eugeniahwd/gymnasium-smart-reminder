"""Feature engineering bersama untuk training DAN inference.

Satu-satunya tempat logika fitur didefinisikan, supaya tidak ada train-serve skew.
Aturan emas: semua fitur dihitung HANYA dari data sebelum `reference_date` (00:00).

Input (DataFrame):
- attendance : kolom `status` (hadir | tidak_hadir | reschedule), `waktu_mulai` (datetime),
               `tipe` (group_class | private)  -> hasil join attendance + schedules
- reminders  : kolom `status`, `sent_at`, `responded_at`
- reschedules: tidak dipakai langsung; reschedule dihitung dari attendance.status == 'reschedule'

Definisi hasil reminder yang "sudah diketahui" pada reference_date:
- Responded   : diketahui jika responded_at < reference_date
- No Response : diketahui jika sent_at + 48 jam < reference_date
Reminder yang masih menggantung pada reference_date tidak dihitung (mencegah kebocoran).
"""
from __future__ import annotations

from typing import Iterable, Mapping

import numpy as np
import pandas as pd

CLASSES: list[str] = ["Low", "Medium", "High"]
PERSONAS: list[str] = ["ibu-ibu", "lansia", "menengah_atas"]
CLASS_TYPES: list[str] = ["group_class", "private", "unknown"]

NUMERIC_FEATURES: list[str] = [
    "attendance_rate_30d",
    "attendance_rate_90d",
    "absent_count_30d",
    "consecutive_absences",
    "reschedule_count_90d",
    "reminder_response_rate",
    "no_response_streak",
    "avg_response_time_hours",
    "days_since_last_attendance",
    "days_since_last_reminder",
    "tenure_days",
]
CATEGORICAL_FEATURES: list[str] = ["persona", "favorite_class_type"]
FEATURE_COLUMNS: list[str] = NUMERIC_FEATURES + CATEGORICAL_FEATURES
LABEL_COLUMN: str = "priority"
ID_COLUMNS: list[str] = ["customer_id", "reference_date"]  # BUKAN fitur model

NO_RESPONSE_WINDOW_HOURS: int = 48
MIN_HISTORY_EVENTS: int = 3  # di bawah ini = cold start ("riwayat belum cukup")

_ATT_COLS = ["status", "waktu_mulai", "tipe"]
_REM_COLS = ["status", "sent_at", "responded_at"]


def _empty(cols: list[str]) -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="object") for c in cols})


def _prep_attendance(att: pd.DataFrame | None) -> pd.DataFrame:
    if att is None or len(att) == 0:
        out = _empty(_ATT_COLS)
        out["waktu_mulai"] = pd.to_datetime(out["waktu_mulai"])
        return out
    out = att[_ATT_COLS].copy()
    out["waktu_mulai"] = pd.to_datetime(out["waktu_mulai"])
    return out.sort_values("waktu_mulai").reset_index(drop=True)


def _prep_reminders(rem: pd.DataFrame | None) -> pd.DataFrame:
    if rem is None or len(rem) == 0:
        out = _empty(_REM_COLS)
        out["sent_at"] = pd.to_datetime(out["sent_at"])
        out["responded_at"] = pd.to_datetime(out["responded_at"])
        return out
    out = rem[_REM_COLS].copy()
    out["sent_at"] = pd.to_datetime(out["sent_at"])
    out["responded_at"] = pd.to_datetime(out["responded_at"])
    return out[out["sent_at"].notna()].reset_index(drop=True)


def compute_customer_features(
    persona: str,
    join_date,
    attendance: pd.DataFrame | None,
    reminders: pd.DataFrame | None,
    reference_date,
) -> dict:
    """Hitung semua fitur untuk SATU customer pada `reference_date`.

    Mengembalikan dict berisi FEATURE_COLUMNS + `n_history_events` (untuk deteksi cold start).
    NaN dipakai untuk nilai yang tidak bisa dihitung (ditangani imputer di pipeline).
    """
    ref = pd.Timestamp(reference_date).normalize()
    att = _prep_attendance(attendance)
    att = att[att["waktu_mulai"] < ref]
    rem = _prep_reminders(reminders)
    rem = rem[rem["sent_at"] < ref]

    # ---- attendance
    def window(days: int) -> pd.DataFrame:
        return att[att["waktu_mulai"] >= ref - pd.Timedelta(days=days)]

    def rate(w: pd.DataFrame) -> float:
        return float((w["status"] == "hadir").mean()) if len(w) else np.nan

    w30, w90 = window(30), window(90)
    tenure = max((ref - pd.Timestamp(join_date).normalize()).days, 0)

    consecutive = 0
    for s in reversed(att["status"].tolist()):
        if s == "hadir":
            break
        if s == "tidak_hadir":
            consecutive += 1  # 'reschedule' dilewati: tidak memutus dan tidak menambah

    hadir = att[att["status"] == "hadir"]
    if len(hadir):
        dsla = (ref - hadir["waktu_mulai"].iloc[-1]).total_seconds() / 86400.0
    elif len(att):
        dsla = float(tenure)  # pernah terjadwal tetapi belum pernah hadir
    else:
        dsla = np.nan

    source = hadir if len(hadir) else att
    if len(source):
        fav = source["tipe"].value_counts().idxmax()
    else:
        fav = "unknown"

    # ---- reminders (hanya hasil yang sudah diketahui pada ref)
    resp_mask = (rem["status"] == "Responded") & (rem["responded_at"] < ref)
    window_td = pd.Timedelta(hours=NO_RESPONSE_WINDOW_HOURS)
    nores_mask = (rem["status"] == "No Response") & ((rem["sent_at"] + window_td) < ref)
    known = rem[resp_mask | nores_mask].copy()
    known["outcome_time"] = np.where(
        known["status"] == "Responded", known["responded_at"], known["sent_at"] + window_td
    )
    known = known.sort_values("outcome_time")

    if len(known):
        response_rate = float((known["status"] == "Responded").mean())
    else:
        response_rate = np.nan

    streak = 0
    for s in reversed(known["status"].tolist()):
        if s == "No Response":
            streak += 1
        else:
            break

    responded = known[known["status"] == "Responded"]
    if len(responded):
        avg_resp = float(
            ((responded["responded_at"] - responded["sent_at"]).dt.total_seconds() / 3600.0).mean()
        )
    else:
        avg_resp = np.nan

    if len(rem):
        dslr = (ref - rem["sent_at"].max()).total_seconds() / 86400.0
    else:
        dslr = np.nan

    return {
        "attendance_rate_30d": rate(w30),
        "attendance_rate_90d": rate(w90),
        "absent_count_30d": float((w30["status"] == "tidak_hadir").sum()),
        "consecutive_absences": float(consecutive),
        "reschedule_count_90d": float((w90["status"] == "reschedule").sum()),
        "reminder_response_rate": response_rate,
        "no_response_streak": float(streak),
        "avg_response_time_hours": avg_resp,
        "days_since_last_attendance": dsla,
        "days_since_last_reminder": dslr,
        "tenure_days": float(tenure),
        "persona": persona,
        "favorite_class_type": fav,
        "n_history_events": int(len(att) + len(known)),
    }


def has_enough_history(features: Mapping) -> bool:
    """False jika customer belum punya riwayat cukup (cold start)."""
    return int(features.get("n_history_events", 0)) >= MIN_HISTORY_EVENTS


def join_attendance_schedules(attendance: pd.DataFrame, schedules: pd.DataFrame) -> pd.DataFrame:
    """Gabungkan attendance dengan schedules -> kolom waktu_mulai, tipe, nama_kelas."""
    sch = schedules[["id", "waktu_mulai", "tipe", "nama_kelas"]].rename(columns={"id": "schedule_id"})
    return attendance.merge(sch, on="schedule_id", how="left")


def build_feature_frame(
    customers: pd.DataFrame,
    attendance: pd.DataFrame,
    reminders: pd.DataFrame,
    snapshots: pd.DataFrame,
) -> pd.DataFrame:
    """Hitung fitur untuk banyak (customer_id, reference_date).

    customers : kolom id, persona, join_date
    attendance: sudah di-join dengan schedules (lihat join_attendance_schedules), ada customer_id
    reminders : ada customer_id
    snapshots : kolom customer_id, reference_date
    """
    cust = customers.set_index("id")
    att_by = {k: v for k, v in attendance.groupby("customer_id")}
    rem_by = {k: v for k, v in reminders.groupby("customer_id")}

    rows = []
    for cid, ref in zip(snapshots["customer_id"], snapshots["reference_date"]):
        c = cust.loc[cid]
        feats = compute_customer_features(
            persona=c["persona"],
            join_date=c["join_date"],
            attendance=att_by.get(cid),
            reminders=rem_by.get(cid),
            reference_date=ref,
        )
        feats["customer_id"] = cid
        feats["reference_date"] = pd.Timestamp(ref).normalize()
        rows.append(feats)

    out = pd.DataFrame(rows)
    return out[ID_COLUMNS + FEATURE_COLUMNS + ["n_history_events"]]


def features_to_frame(features: Mapping | Iterable[Mapping]) -> pd.DataFrame:
    """Dict fitur (satu atau banyak) -> DataFrame dengan urutan kolom FEATURE_COLUMNS (untuk model)."""
    if isinstance(features, Mapping):
        features = [features]
    return pd.DataFrame(list(features))[FEATURE_COLUMNS]
