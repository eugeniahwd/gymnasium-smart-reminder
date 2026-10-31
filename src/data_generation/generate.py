"""Generator dataset synthetic Gymnasium Smart Reminder & Follow-up.

Jalankan:  python -m src.data_generation.generate [--n-customers 400] [--seed 42]

Output:
  data/raw/*.csv                      tabel mentah (sesuai skema database)
  data/processed/training_dataset.csv fitur + label + customer_id + reference_date

Catatan desain (lihat docs/SYNTHETIC_DATA.md):
- Perilaku customer dipengaruhi faktor tersembunyi (motivasi, kesibukan) yang TIDAK menjadi fitur model.
- Label dibuat dari skor laten (fitur + faktor tersembunyi + noise), lalu di-threshold per kuantil
  dan sebagian kecil di-flip. Tidak ada satu aturan sederhana yang menghasilkan label sempurna.
- Semua nomor WhatsApp adalah nomor DUMMY (628990xxxxxx), bukan nomor sungguhan.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from src.ml.feature_engineering import (
    CLASSES,
    FEATURE_COLUMNS,
    LABEL_COLUMN,
    NO_RESPONSE_WINDOW_HOURS,
    PERSONAS,
    build_feature_frame,
    join_attendance_schedules,
)

SEED = 42
N_CUSTOMERS = 400
SIM_START = date(2026, 1, 5)       # Senin
SIM_END = date(2026, 9, 30)
JOIN_MIN, JOIN_MAX = date(2025, 9, 1), date(2026, 8, 25)
REF_MIN, REF_MAX = date(2026, 5, 4), date(2026, 9, 14)
REF_MIN_GAP_DAYS = 21
TARGET_DIST = {"Low": 0.50, "Medium": 0.30, "High": 0.20}
FLIP_RATE = 0.06
LABEL_NOISE_STD = 0.55
MCAR_RATE = 0.015  # missing acak pada beberapa fitur (gangguan pencatatan)

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"

PERSONA_MIX = [0.45, 0.25, 0.30]  # ibu-ibu, lansia, menengah_atas
# (alpha, beta) peluang dasar hadir dan peluang dasar merespons reminder
ATTEND_BETA = {"ibu-ibu": (6, 3), "lansia": (5, 2.5), "menengah_atas": (4, 3)}
RESPOND_BETA = {"ibu-ibu": (5, 2), "lansia": (3, 3), "menengah_atas": (4, 3)}
PRIVATE_PROB = {"ibu-ibu": 0.08, "lansia": 0.10, "menengah_atas": 0.35}

# (nama_kelas, weekday 0=Senin, jam, menit, pelatih, kapasitas, persona yang cocok)
GROUP_TEMPLATES = [
    ("Zumba Fun", 0, 9, 0, "Coach Dina", 20, ["ibu-ibu"]),
    ("Senam Ringan Lansia", 1, 8, 0, "Coach Budi", 20, ["lansia"]),
    ("Pilates Mat", 1, 10, 0, "Coach Rani", 15, ["ibu-ibu", "menengah_atas"]),
    ("Body Strength", 1, 18, 30, "Coach Andra", 12, ["menengah_atas"]),
    ("Senam Sehat Lansia", 2, 8, 0, "Coach Budi", 20, ["lansia"]),
    ("Aerobic Low Impact", 3, 9, 0, "Coach Dina", 20, ["ibu-ibu", "lansia"]),
    ("Yoga Lembut", 4, 8, 30, "Coach Sari", 15, ["lansia", "ibu-ibu", "menengah_atas"]),
    ("Core & Balance", 5, 9, 0, "Coach Sari", 15, ["menengah_atas", "ibu-ibu"]),
]
PRIVATE_TRAINERS = ["Coach Andra", "Coach Rani", "Coach Sari", "Coach Dina"]
RESCHEDULE_REASONS = ["Ada keperluan keluarga", "Jadwal bentrok", "Sedang bepergian", "Kurang fit hari ini"]

FIRST_NAMES = [
    "Sri", "Dewi", "Ratna", "Wati", "Lestari", "Rina", "Yuni", "Siti", "Aminah", "Fitri", "Nur", "Endang",
    "Maria", "Agnes", "Linda", "Susan", "Hendra", "Budi", "Agus", "Rudi", "Tono", "Dian", "Ayu", "Mega",
    "Indah", "Retno", "Tuti", "Sari", "Lina", "Wulan", "Anita", "Bambang", "Eko", "Joko", "Andri", "Vera",
]
LAST_NAMES = [
    "Hartono", "Wijaya", "Susanto", "Pratama", "Kusuma", "Santoso", "Halim", "Gunawan", "Lestari", "Putri",
    "Rahayu", "Setiawan", "Handayani", "Saputra", "Tanujaya", "Salim", "Wibowo", "Permata", "Utami", "Budiman",
]
NOTES = [None] * 8 + ["Lebih suka kelas pagi", "Pernah cedera lutut ringan (sudah sembuh)", "Dikenalkan teman member"]


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + np.exp(-x))


def _logit(p: float) -> float:
    p = min(max(p, 1e-3), 1 - 1e-3)
    return float(np.log(p / (1 - p)))


# --------------------------------------------------------------------------- customers
def make_customers(rng: np.random.Generator, n: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Customer + faktor laten. Faktor laten TIDAK disimpan ke CSV (tersembunyi)."""
    personas = rng.choice(PERSONAS, size=n, p=PERSONA_MIX)
    span = (JOIN_MAX - JOIN_MIN).days + 1
    join_dates = [JOIN_MIN + timedelta(days=int(d)) for d in rng.integers(0, span, n)]

    rows, latent = [], []
    for i in range(n):
        persona = str(personas[i])
        a, b = ATTEND_BETA[persona]
        ra, rb = RESPOND_BETA[persona]
        busy_shift = 0.5 if persona == "menengah_atas" else 0.0
        latent.append(
            {
                "motivation": float(rng.normal(0, 1)),
                "busyness": float(rng.normal(busy_shift, 1)),
                "base_attend": float(rng.beta(a, b)),
                "base_respond": float(rng.beta(ra, rb)),
                "trend": float(rng.normal(0, 0.8)),
                "resched_tendency": float(rng.beta(1.5, 8)),
                "has_lapse": bool(rng.random() < 0.18),
                "lapse_start": int(rng.integers(8, 34)),
                "lapse_len": int(rng.integers(3, 9)),
            }
        )
        rows.append(
            {
                "id": i + 1,
                "nama": f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}",
                "no_whatsapp": f"628990{i + 1:06d}",
                "persona": persona,
                "catatan": NOTES[int(rng.integers(0, len(NOTES)))],
                "join_date": join_dates[i],
                "created_at": datetime.combine(join_dates[i], datetime.min.time()),
            }
        )
    return pd.DataFrame(rows), pd.DataFrame(latent)


# --------------------------------------------------------------------------- schedules
def make_schedules(rng: np.random.Generator, customers: pd.DataFrame):
    """Jadwal group class mingguan + sesi private per customer. Return df + peta key->id + enrolment."""
    n_weeks = (SIM_END - SIM_START).days // 7 + 1
    recs = []
    for t, (nama, wd, hh, mm, pelatih, kap, _) in enumerate(GROUP_TEMPLATES):
        for w in range(n_weeks):
            start = datetime.combine(SIM_START + timedelta(days=w * 7 + wd), datetime.min.time()) + timedelta(
                hours=hh, minutes=mm
            )
            if start.date() <= SIM_END:
                recs.append(("g", t, w, nama, "group_class", start, pelatih, kap))

    enrol_group: dict[int, list[int]] = {}
    enrol_private: dict[int, tuple[int, int, str]] = {}
    for i, c in customers.iterrows():
        persona = c["persona"]
        pool = [t for t, tpl in enumerate(GROUP_TEMPLATES) if persona in tpl[6]]
        k = int(rng.choice([1, 2, 3], p=[0.35, 0.45, 0.20]))
        enrol_group[i] = [int(t) for t in rng.choice(pool, size=min(k, len(pool)), replace=False)]
        if rng.random() < PRIVATE_PROB[persona]:
            enrol_private[i] = (int(rng.integers(0, 6)), int(rng.integers(7, 20)), str(rng.choice(PRIVATE_TRAINERS)))

    for i, (wd, hh, trainer) in enrol_private.items():
        join = customers.loc[i, "join_date"]
        for w in range(n_weeks):
            start = datetime.combine(SIM_START + timedelta(days=w * 7 + wd), datetime.min.time()) + timedelta(hours=hh)
            if start.date() > SIM_END or start.date() < join or rng.random() < 0.08:
                continue
            recs.append(("p", i, w, "Private Coaching", "private", start, trainer, 1))

    recs.sort(key=lambda r: (r[5], r[0], r[1]))
    rows, key_to_id = [], {}
    for idx, (kind, ref, w, nama, tipe, start, pelatih, kap) in enumerate(recs, start=1):
        key_to_id[(kind, ref, w)] = idx
        rows.append(
            {
                "id": idx,
                "nama_kelas": nama,
                "tipe": tipe,
                "waktu_mulai": start,
                "pelatih": pelatih,
                "kapasitas": kap,
                "created_at": start - timedelta(days=14),
            }
        )
    return pd.DataFrame(rows), key_to_id, enrol_group, enrol_private, n_weeks


# --------------------------------------------------------------------------- simulasi perilaku
def simulate_behavior(rng, customers, latent, schedules, key_to_id, enrol_group, enrol_private, n_weeks):
    sch_start = dict(zip(schedules["id"], schedules["waktu_mulai"]))
    sch_name = dict(zip(schedules["id"], schedules["nama_kelas"]))
    group_ids_by_start = schedules[schedules["tipe"] == "group_class"].sort_values("waktu_mulai")

    att: dict[tuple[int, int], str] = {}
    resched_rows = []

    # fase 1: attendance utama
    for i, c in customers.iterrows():
        cid, lat = int(c["id"]), latent.loc[i]
        join_dt = datetime.combine(c["join_date"], datetime.min.time())
        keys = [("g", t, w) for t in enrol_group[i] for w in range(n_weeks)]
        if i in enrol_private:
            keys += [("p", i, w) for w in range(n_weeks)]
        for key in keys:
            sid = key_to_id.get(key)
            if sid is None or sch_start[sid] < join_dt:
                continue
            w = key[2]
            logit = (
                _logit(lat["base_attend"])
                + 0.6 * lat["motivation"]
                - 0.5 * lat["busyness"]
                + lat["trend"] * (w / n_weeks - 0.5)
            )
            if lat["has_lapse"] and lat["lapse_start"] <= w < lat["lapse_start"] + lat["lapse_len"]:
                logit -= 2.8
            if rng.random() < _sigmoid(logit):
                status = "hadir"
            else:
                p_res = min(0.9, lat["resched_tendency"] + 0.08 * max(lat["busyness"], 0))
                status = "reschedule" if rng.random() < p_res else "tidak_hadir"
            att[(cid, sid)] = status

    # fase 2: reschedule -> kelas pengganti
    main_items = list(att.items())
    for (cid, sid), status in main_items:
        if status != "reschedule":
            continue
        start = sch_start[sid]
        persona = customers.loc[cid - 1, "persona"]
        cand = group_ids_by_start[
            (group_ids_by_start["waktu_mulai"] > start + timedelta(hours=12))
            & (group_ids_by_start["waktu_mulai"] <= start + timedelta(days=7))
        ]
        cand = cand[cand["nama_kelas"].map(lambda n: persona in _persona_of(n))]
        baru = None
        if len(cand):
            baru = int(cand.iloc[int(rng.integers(0, len(cand)))]["id"])
            if (cid, baru) not in att:
                att[(cid, baru)] = "hadir" if rng.random() < 0.75 else "tidak_hadir"
        resched_rows.append(
            {
                "customer_id": cid,
                "schedule_id_asal": sid,
                "schedule_id_baru": baru,
                "alasan": str(rng.choice(RESCHEDULE_REASONS)),
                "created_at": start - timedelta(hours=int(rng.integers(3, 30))),
            }
        )

    attendance = pd.DataFrame(
        [
            {"customer_id": cid, "schedule_id": sid, "status": st, "created_at": sch_start[sid] + timedelta(hours=1)}
            for (cid, sid), st in att.items()
        ]
    )
    attendance = attendance.sort_values(["schedule_id", "customer_id"]).reset_index(drop=True)
    attendance.insert(0, "id", np.arange(1, len(attendance) + 1))

    reschedules = pd.DataFrame(resched_rows).sort_values("created_at").reset_index(drop=True)
    reschedules.insert(0, "id", np.arange(1, len(reschedules) + 1))

    # fase 3: reminder (hanya untuk attendance utama, bukan kelas pengganti)
    rem_rows = []
    sim_end_dt = datetime.combine(SIM_END, datetime.min.time()) + timedelta(days=1)

    def make_reminder(cid, sid, mtype, sent_at, p_resp, lat):
        responded = rng.random() < p_resp
        if responded:
            hours = float(np.exp(rng.normal(1.6 + 0.3 * lat["busyness"], 0.8)))
            hours = min(max(hours, 0.1), NO_RESPONSE_WINDOW_HOURS - 1.0)
            responded_at = sent_at + timedelta(hours=hours)
            status, updated = "Responded", responded_at
        else:
            responded_at = None
            status, updated = "No Response", sent_at + timedelta(hours=NO_RESPONSE_WINDOW_HOURS)
        rem_rows.append(
            {
                "customer_id": cid,
                "schedule_id": sid,
                "status": status,
                "priority": None,
                "priority_probabilities": None,
                "message_type": mtype,
                "draft_message": None,
                "draft_source": None,
                "final_message": None,
                "created_at": sent_at - timedelta(minutes=30),
                "sent_at": sent_at,
                "responded_at": responded_at,
                "updated_at": updated,
            }
        )
        return status

    for (cid, sid), status in main_items:
        lat = latent.loc[cid - 1]
        join_dt = datetime.combine(customers.loc[cid - 1, "join_date"], datetime.min.time())
        start = sch_start[sid]
        p_resp = _sigmoid(_logit(lat["base_respond"]) + 0.5 * lat["motivation"] - 0.3 * lat["busyness"])
        if rng.random() < 0.85:
            sent = datetime.combine(start.date() - timedelta(days=1), datetime.min.time()) + timedelta(
                hours=16, minutes=int(rng.integers(0, 90))
            )
            if sent >= join_dt and sent < sim_end_dt:
                st = make_reminder(cid, sid, "reminder_kelas", sent, p_resp, lat)
                if st == "No Response" and rng.random() < 0.30:
                    make_reminder(cid, sid, "follow_up_tidak_merespons", start - timedelta(hours=3), p_resp * 0.9, lat)
        if status == "tidak_hadir" and rng.random() < 0.60:
            sent = datetime.combine(start.date() + timedelta(days=1), datetime.min.time()) + timedelta(
                hours=10, minutes=int(rng.integers(0, 60))
            )
            if sent < sim_end_dt:
                make_reminder(cid, sid, "follow_up_absen", sent, p_resp * 0.9, lat)

    reminders = pd.DataFrame(rem_rows).sort_values("sent_at").reset_index(drop=True)
    reminders.insert(0, "id", np.arange(1, len(reminders) + 1))

    # riwayat status
    hist = []
    for r in reminders.itertuples():
        hist.append((r.id, None, "Scheduled", r.created_at))
        hist.append((r.id, "Scheduled", "Sent", r.sent_at))
        hist.append((r.id, "Sent", r.status, r.updated_at))
    history = pd.DataFrame(hist, columns=["reminder_id", "from_status", "to_status", "changed_at"])
    history.insert(0, "id", np.arange(1, len(history) + 1))

    return attendance, reschedules, reminders, history


def _persona_of(nama_kelas: str) -> list[str]:
    for tpl in GROUP_TEMPLATES:
        if tpl[0] == nama_kelas:
            return tpl[6]
    return []


# --------------------------------------------------------------------------- snapshot & label
def make_snapshots(rng: np.random.Generator, customers: pd.DataFrame) -> pd.DataFrame:
    days = [REF_MIN + timedelta(days=d) for d in range((REF_MAX - REF_MIN).days + 1)]
    rows = []
    for c in customers.itertuples():
        n_snap = int(rng.choice([3, 4]))
        chosen: list[date] = []
        for idx in rng.permutation(len(days)):
            d = days[int(idx)]
            if d < c.join_date + timedelta(days=3):
                continue
            if all(abs((d - o).days) >= REF_MIN_GAP_DAYS for o in chosen):
                chosen.append(d)
            if len(chosen) == n_snap:
                break
        rows += [{"customer_id": c.id, "reference_date": pd.Timestamp(d)} for d in sorted(chosen)]
    return pd.DataFrame(rows)


def latent_risk_score(feats: pd.DataFrame, latent: pd.DataFrame, rng: np.random.Generator) -> np.ndarray:
    """Skor risiko laten: sebagian fitur + faktor tersembunyi + noise Gaussian."""
    f = feats
    att30 = f["attendance_rate_30d"].fillna(0.65)
    att90 = f["attendance_rate_90d"].fillna(0.65)
    resp = f["reminder_response_rate"].fillna(0.60)
    dsla = f["days_since_last_attendance"].fillna(15.0).clip(upper=45) / 45
    streak = f["consecutive_absences"].clip(upper=4) / 4
    nrs = f["no_response_streak"].clip(upper=4) / 4

    lat = latent.loc[(f["customer_id"] - 1).to_numpy()].reset_index(drop=True)
    n = len(f)
    motivation = lat["motivation"].to_numpy() + rng.normal(0, 0.3, n)  # fluktuasi per snapshot
    busyness = lat["busyness"].to_numpy() + rng.normal(0, 0.3, n)

    score = (
        1.5 * (1 - att30).to_numpy()
        + 0.8 * (1 - att90).to_numpy()
        + 0.9 * streak.to_numpy()
        + 0.7 * nrs.to_numpy()
        + 0.6 * dsla.to_numpy()
        + 0.6 * (1 - resp).to_numpy()
        - 0.9 * motivation  # faktor tersembunyi (bukan fitur model)
        + 0.7 * busyness  # faktor tersembunyi (bukan fitur model)
        + rng.normal(0, LABEL_NOISE_STD, n)
    )
    return score


def assign_labels(score: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    q_low = np.quantile(score, TARGET_DIST["Low"])
    q_med = np.quantile(score, TARGET_DIST["Low"] + TARGET_DIST["Medium"])
    labels = np.where(score <= q_low, "Low", np.where(score <= q_med, "Medium", "High")).astype(object)
    flip = rng.random(len(labels)) < FLIP_RATE
    for i in np.where(flip)[0]:
        labels[i] = str(rng.choice([c for c in CLASSES if c != labels[i]]))
    return labels


# --------------------------------------------------------------------------- orkestrasi
def generate_all(n_customers: int = N_CUSTOMERS, seed: int = SEED) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    customers, latent = make_customers(rng, n_customers)
    schedules, key_to_id, enrol_group, enrol_private, n_weeks = make_schedules(rng, customers)
    attendance, reschedules, reminders, history = simulate_behavior(
        rng, customers, latent, schedules, key_to_id, enrol_group, enrol_private, n_weeks
    )
    snapshots = make_snapshots(rng, customers)

    att_joined = join_attendance_schedules(attendance, schedules)
    feats = build_feature_frame(customers, att_joined, reminders, snapshots)

    score = latent_risk_score(feats, latent, rng)
    feats[LABEL_COLUMN] = assign_labels(score, rng)

    # missing value acak (gangguan pencatatan) SETELAH label dibuat
    for col in ["avg_response_time_hours", "days_since_last_reminder", "reminder_response_rate"]:
        mask = rng.random(len(feats)) < MCAR_RATE
        feats.loc[mask, col] = np.nan

    return {
        "customers": customers,
        "schedules": schedules,
        "attendance": attendance,
        "reschedules": reschedules,
        "reminders": reminders,
        "reminder_status_history": history,
        "training_dataset": feats,
    }


def write_outputs(data: dict[str, pd.DataFrame], raw_dir: Path = RAW_DIR, processed_dir: Path = PROCESSED_DIR) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)
    for name, df in data.items():
        target = processed_dir / "training_dataset.csv" if name == "training_dataset" else raw_dir / f"{name}.csv"
        df.to_csv(target, index=False)


def summarize(data: dict[str, pd.DataFrame]) -> None:
    print("\n=== Jumlah baris per tabel ===")
    for name, df in data.items():
        print(f"{name:<26}{len(df):>8}")
    tr = data["training_dataset"]
    print("\n=== Distribusi kelas (training_dataset) ===")
    print(tr[LABEL_COLUMN].value_counts(normalize=True).reindex(CLASSES).round(3).to_string())
    print("\n=== Missing value per fitur (%) ===")
    print((tr[FEATURE_COLUMNS].isna().mean() * 100).round(1).to_string())


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate dataset synthetic Gymnasium.")
    parser.add_argument("--n-customers", type=int, default=N_CUSTOMERS)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    data = generate_all(args.n_customers, args.seed)
    write_outputs(data)
    summarize(data)
    print(f"\nTersimpan di {RAW_DIR} dan {PROCESSED_DIR}")


if __name__ == "__main__":
    main()
