"""Lanjutkan timeline data synthetic sampai HARI INI agar demo dan prediksi bermakna.

Masalah: dataset synthetic berakhir 30 Sep 2026. Jika "hari ini" lebih akhir, (a) tidak ada jadwal/reminder
untuk hari ini sehingga "Reminder Hari Ini" kosong, dan (b) jendela kehadiran 30/90 hari kosong sehingga fitur
terisi nilai median dan sinyal customer berisiko hilang (terukur: porsi prediksi High turun dari ~24% menjadi
~12%, kelas Medium membengkak). Dengan lanjutan timeline, sebaran prediksi kembali mirip kondisi akhir data.

Skrip ini (idempotent - aman dijalankan berulang, mis. sebelum demo):
 1. MENGHAPUS data demo lama (semua data setelah 30 Sep 2026: jadwal, kehadiran, reminder, prediksi),
 2. membuat jadwal kelas sampai hari ini + 7 hari, kehadiran dan reminder historis (perilaku customer
    mengikuti pola 60 hari terakhir mereka) sampai kemarin,
 3. membuat reminder berstatus Scheduled untuk kelas hari ini sampai --days-ahead hari ke depan,
 4. menghitung prioritas tiap customer dengan model ML (jika artefak model tersedia).

Jalankan:  python -m src.data_generation.seed_demo [--days-ahead 2] [--no-predict]
Butuh DATABASE_URL di .env. Data setelah 30 Sep (termasuk reminder uji coba buatan Anda) akan dihapus.
"""
from __future__ import annotations

import argparse
import os
import time as _time
from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import InterfaceError, OperationalError

from src.api.db.session import make_engine
from src.data_generation.generate import GROUP_TEMPLATES, PRIVATE_TRAINERS, RESCHEDULE_REASONS, SIM_END
from src.data_generation.seed_db import ROOT, _chunksize, _clean
from src.api.timeutil import now_wib
from src.ml.feature_engineering import NO_RESPONSE_WINDOW_HOURS

DEMO_SEED = 2026
CUTOFF = datetime.combine(SIM_END, time(23, 59, 59))
INSERT_ORDER = ["schedules", "attendance", "reschedules", "reminders", "reminder_status_history"]


# ----------------------------------------------------------------------------- purge
def _purge(conn) -> None:
    """Hapus semua data setelah CUTOFF (dipanggil di dalam transaksi)."""
    post_sched = "SELECT id FROM schedules WHERE waktu_mulai > :c"
    post_rem = f"SELECT id FROM reminders WHERE created_at > :c OR schedule_id IN ({post_sched})"
    stmts = [
        f"DELETE FROM reminder_status_history WHERE reminder_id IN ({post_rem})",
        f"DELETE FROM reminders WHERE id IN ({post_rem})",
        "DELETE FROM predictions WHERE created_at > :c",
        f"DELETE FROM reschedules WHERE schedule_id_asal IN ({post_sched})",
        f"UPDATE reschedules SET schedule_id_baru = NULL WHERE schedule_id_baru IN ({post_sched})",
        f"DELETE FROM attendance WHERE schedule_id IN ({post_sched})",
        "DELETE FROM schedules WHERE waktu_mulai > :c",
    ]
    for stmt in stmts:
        conn.execute(text(stmt), {"c": CUTOFF})


def purge_demo_data(engine: Engine) -> None:
    """Hapus data demo saja (tanpa membuat ulang)."""
    with engine.begin() as conn:
        _purge(conn)


def _is_connection_error(exc: BaseException) -> bool:
    """True jika error (atau penyebabnya) adalah masalah koneksi. pandas membungkus error SQLAlchemy
    menjadi DatabaseError, jadi rantai __cause__/__context__ harus ditelusuri."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        if isinstance(exc, (OperationalError, InterfaceError)):
            return True
        seen.add(id(exc))
        exc = exc.__cause__ or exc.__context__
    return False


def _retry(fn, engine: Engine, label: str, attempts: int = 4, delay: float = 2.0, log=print):
    """Ulangi operasi jika koneksi database terputus (mis. 'SSL error: unexpected eof')."""
    for i in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            if i == attempts or not _is_connection_error(exc):
                raise
            root = exc
            while root.__cause__ is not None:
                root = root.__cause__
            reason = str(getattr(root, "orig", root)).strip().splitlines()[0][:90]
            log(f"  [{label}] koneksi bermasalah ({reason}); mencoba ulang {i}/{attempts - 1} ...")
            engine.dispose()
            _time.sleep(delay * i)


# ----------------------------------------------------------------------------- generasi
def _read(engine: Engine) -> dict[str, pd.DataFrame]:
    """Baca tabel secara bertahap (5.000 baris per fetch) agar tahan koneksi yang kurang stabil."""
    out = {}
    with engine.connect().execution_options(stream_results=True) as conn:
        for t in ["customers", "schedules", "attendance", "reminders"]:
            chunks = list(pd.read_sql(text(f"SELECT * FROM {t}"), conn, chunksize=5000))
            out[t] = pd.concat(chunks, ignore_index=True) if chunks else pd.read_sql(
                text(f"SELECT * FROM {t} WHERE 1 = 0"), conn)
    out["schedules"]["waktu_mulai"] = pd.to_datetime(out["schedules"]["waktu_mulai"])
    for col in ["sent_at", "responded_at", "created_at"]:
        out["reminders"][col] = pd.to_datetime(out["reminders"][col])
    return out


def _only_original(data: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Buang sisa data demo lama dari hasil baca (penghapusannya terjadi di transaksi insert)."""
    sched = data["schedules"][data["schedules"]["waktu_mulai"] <= CUTOFF]
    keep_ids = set(sched["id"])
    att = data["attendance"][data["attendance"]["schedule_id"].isin(keep_ids)]
    rem = data["reminders"]
    rem = rem[(rem["created_at"] <= CUTOFF) & (rem["schedule_id"].isna() | rem["schedule_id"].isin(keep_ids))]
    return {"customers": data["customers"], "schedules": sched, "attendance": att, "reminders": rem}


def build_continuation(data: dict[str, pd.DataFrame], now: datetime, days_ahead: int = 2, seed: int = DEMO_SEED) -> dict:
    rng = np.random.default_rng(seed)
    customers, schedules, attendance, reminders = (data[k] for k in ["customers", "schedules", "attendance", "reminders"])
    today, day0 = now.date(), datetime.combine(now.date(), time.min)
    start_day, end_day = SIM_END + timedelta(days=1), now.date() + timedelta(days=7)
    if end_day < start_day:
        return {}

    next_sched = int(schedules["id"].max()) + 1
    next_att = int(attendance["id"].max()) + 1 if len(attendance) else 1
    next_rem = int(reminders["id"].max()) + 1 if len(reminders) else 1

    # --- jadwal baru
    new_sched, group_by_name, private_by_cust = [], {}, {}
    days = [start_day + timedelta(days=i) for i in range((end_day - start_day).days + 1)]
    for d in days:
        for nama, wd, hh, mm, pelatih, kap, _ in GROUP_TEMPLATES:
            if d.weekday() == wd:
                st = datetime.combine(d, time(hh, mm))
                row = {"id": next_sched, "nama_kelas": nama, "tipe": "group_class", "waktu_mulai": st,
                       "pelatih": pelatih, "kapasitas": kap, "created_at": st - timedelta(days=14)}
                new_sched.append(row)
                group_by_name.setdefault(nama, []).append(row)
                next_sched += 1

    att_s = attendance.merge(schedules[["id", "waktu_mulai", "tipe", "nama_kelas", "pelatih"]]
                             .rename(columns={"id": "schedule_id"}), on="schedule_id")
    priv_last = att_s[att_s["tipe"] == "private"].sort_values("waktu_mulai").groupby("customer_id").tail(1)
    for r in priv_last.itertuples():
        for d in days:
            if d.weekday() == r.waktu_mulai.weekday() and rng.random() > 0.08:
                st = datetime.combine(d, time(r.waktu_mulai.hour, 0))
                row = {"id": next_sched, "nama_kelas": "Private Coaching", "tipe": "private", "waktu_mulai": st,
                       "pelatih": r.pelatih, "kapasitas": 1, "created_at": st - timedelta(days=14)}
                new_sched.append(row)
                private_by_cust.setdefault(int(r.customer_id), []).append(row)
                next_sched += 1

    # --- perilaku customer dari 60 hari terakhir sebelum CUTOFF
    win = att_s[att_s["waktu_mulai"] >= CUTOFF - timedelta(days=60)]
    rem_known = reminders[(reminders["created_at"] >= CUTOFF - timedelta(days=90)) &
                          reminders["status"].isin(["Responded", "No Response"])]
    resp_rate = rem_known.groupby("customer_id")["status"].apply(lambda s: (s == "Responded").mean()).to_dict()

    att_rows, res_rows, rem_rows, hist_rows = [], [], [], []

    def add_reminder(cid, sid, mtype, sent_at, p_resp, status=None):
        nonlocal next_rem
        rid, created = next_rem, sent_at - timedelta(minutes=30)
        next_rem += 1
        if status == "Scheduled":
            row = {"status": "Scheduled", "sent_at": None, "responded_at": None, "updated_at": now, "created_at": now}
            hist = [(None, "Scheduled", now)]
        else:
            responded = rng.random() < p_resp
            resp_at = sent_at + timedelta(hours=float(min(max(np.exp(rng.normal(1.6, 0.8)), 0.1), 47)))
            hist = [(None, "Scheduled", created), ("Scheduled", "Sent", sent_at)]
            if responded and resp_at <= now:
                st, upd, rat = "Responded", resp_at, resp_at
                hist.append(("Sent", "Responded", resp_at))
            elif not responded and sent_at + timedelta(hours=NO_RESPONSE_WINDOW_HOURS) <= now:
                st, upd, rat = "No Response", sent_at + timedelta(hours=NO_RESPONSE_WINDOW_HOURS), None
                hist.append(("Sent", "No Response", upd))
            else:  # masih menunggu respons
                st, upd, rat = "Sent", sent_at, None
            row = {"status": st, "sent_at": sent_at, "responded_at": rat, "updated_at": upd, "created_at": created}
        rem_rows.append({"id": rid, "customer_id": cid, "schedule_id": sid, "priority": None,
                         "priority_probabilities": None, "message_type": mtype, "draft_message": None,
                         "draft_source": None, "final_message": None, **row})
        for f, t, at in hist:
            hist_rows.append({"reminder_id": rid, "from_status": f, "to_status": t, "changed_at": at})

    enrolled_future: dict[int, list[dict]] = {}
    for c in customers.itertuples():
        cid = int(c.id)
        mine = att_s[att_s["customer_id"] == cid]
        if mine.empty:
            continue
        w = win[win["customer_id"] == cid]
        base = w if len(w) >= 4 else mine
        p = float(np.clip((base["status"] == "hadir").mean() * rng.uniform(0.9, 1.08), 0.05, 0.97))
        nonhadir = base[base["status"] != "hadir"]
        resched_share = float((nonhadir["status"] == "reschedule").mean()) if len(nonhadir) else 0.15
        p_resp = resp_rate.get(cid, 0.6)
        names = mine[(mine["tipe"] == "group_class")]
        recent = names[names["waktu_mulai"] >= CUTOFF - timedelta(days=56)]["nama_kelas"].value_counts()
        enrolled = [n for n, k in recent.items() if k >= 2] or (
            [names["nama_kelas"].value_counts().index[0]] if len(names) else [])
        occ = [r for n in enrolled for r in group_by_name.get(n, [])] + private_by_cust.get(cid, [])
        for s in sorted(occ, key=lambda r: r["waktu_mulai"]):
            start = s["waktu_mulai"]
            if start < day0:  # masa lalu: kehadiran + reminder historis
                if rng.random() < p:
                    status = "hadir"
                else:
                    status = "reschedule" if rng.random() < resched_share else "tidak_hadir"
                att_rows.append({"id": next_att, "customer_id": cid, "schedule_id": s["id"], "status": status,
                                 "created_at": start + timedelta(hours=1)})
                next_att += 1
                if status == "reschedule":
                    res_rows.append({"customer_id": cid, "schedule_id_asal": s["id"], "schedule_id_baru": None,
                                     "alasan": str(rng.choice(RESCHEDULE_REASONS)),
                                     "created_at": start - timedelta(hours=int(rng.integers(3, 30)))})
                if rng.random() < 0.85:
                    sent = datetime.combine(start.date() - timedelta(days=1), time(16, int(rng.integers(0, 60))))
                    if sent <= now:
                        add_reminder(cid, s["id"], "reminder_kelas", sent, p_resp)
                if status == "tidak_hadir" and rng.random() < 0.6:
                    sent = datetime.combine(start.date() + timedelta(days=1), time(10, int(rng.integers(0, 60))))
                    if sent <= now:
                        add_reminder(cid, s["id"], "follow_up_absen", sent, p_resp * 0.9)
            elif start < day0 + timedelta(days=days_ahead + 1):
                enrolled_future.setdefault(cid, []).append(s)

    # --- reminder Scheduled untuk kelas hari ini .. +days_ahead (jenis pesan mengikuti kondisi terakhir customer)
    all_att = pd.concat([att_s[["customer_id", "status", "waktu_mulai"]],
                         pd.DataFrame([{"customer_id": a["customer_id"], "status": a["status"],
                                        "waktu_mulai": next(s["waktu_mulai"] for s in new_sched if s["id"] == a["schedule_id"])}
                                       for a in att_rows])]) if att_rows else att_s
    last_att = all_att[all_att["waktu_mulai"] < day0].sort_values("waktu_mulai").groupby("customer_id")["status"].last()
    known_rem = pd.concat([rem_known[["customer_id", "status", "sent_at"]],
                           pd.DataFrame([r for r in rem_rows if r["status"] in ("Responded", "No Response")])
                           [["customer_id", "status", "sent_at"]] if rem_rows else None])
    last_rem = known_rem.sort_values("sent_at").groupby("customer_id")["status"].last() if len(known_rem) else {}
    scheduled_ids = []
    for cid, slist in enrolled_future.items():
        if last_att.get(cid) == "tidak_hadir":
            mtype = "follow_up_absen"
        elif last_rem.get(cid) == "No Response":
            mtype = "follow_up_tidak_merespons"
        else:
            mtype = "reminder_kelas"
        for s in slist:
            if rng.random() < 0.9:
                scheduled_ids.append(next_rem)
                add_reminder(cid, s["id"], mtype, now, 0, status="Scheduled")

    return {
        "schedules": pd.DataFrame(new_sched),
        "attendance": pd.DataFrame(att_rows),
        "reschedules": pd.DataFrame(res_rows),
        "reminders": pd.DataFrame(rem_rows),
        "reminder_status_history": pd.DataFrame(hist_rows),
        "scheduled_ids": scheduled_ids,
    }


# ----------------------------------------------------------------------------- insert & prioritas
def insert_frames(engine: Engine, frames: dict) -> dict[str, int]:
    """Hapus data demo lama DAN sisipkan yang baru dalam SATU transaksi (atomik, aman diulang)."""
    counts = {}
    with engine.begin() as conn:
        _purge(conn)
        for name in INSERT_ORDER:
            df = frames[name]
            if len(df) == 0:
                counts[name] = 0
                continue
            if name in ("reschedules", "reminder_status_history"):
                nxt = conn.execute(text(f"SELECT COALESCE(MAX(id), 0) + 1 FROM {name}")).scalar()
                df = df.copy()
                df.insert(0, "id", np.arange(nxt, nxt + len(df)))
            _clean(df).to_sql(name, conn, if_exists="append", index=False, method="multi",
                              chunksize=_chunksize(engine.dialect.name, df.shape[1]))
            counts[name] = len(df)
        if engine.dialect.name == "postgresql":
            for name in INSERT_ORDER:
                conn.execute(text(f"SELECT setval(pg_get_serial_sequence('{name}', 'id'), "
                                  f"COALESCE((SELECT MAX(id) FROM {name}), 1))"))
    return counts


def assign_priorities(engine: Engine, reminder_ids: list[int], reference: date, model, verbose: bool = True) -> int:
    from sqlalchemy import update
    from sqlalchemy.orm import Session

    from src.api.db.models import Customer, Reminder
    from src.api.services.prediction_service import run_prediction

    updated = 0
    with Session(engine) as db:
        rems = db.query(Reminder).filter(Reminder.id.in_(reminder_ids)).all()
        by_customer: dict[int, list[Reminder]] = {}
        for r in rems:
            by_customer.setdefault(r.customer_id, []).append(r)
        for i, (cid, rlist) in enumerate(by_customer.items(), 1):
            res = run_prediction(db, db.get(Customer, cid), model, reference)
            for r in rlist:
                r.priority, r.priority_probabilities = res["priority"], res["probabilities"]
                updated += 1
            if verbose and i % 50 == 0:
                print(f"  prediksi {i}/{len(by_customer)} customer ...")
        db.commit()
    return updated


def run(engine: Engine, now: datetime | None = None, days_ahead: int = 2, predict: bool = True, seed: int = DEMO_SEED,
        verbose: bool = True) -> dict:
    log = print if verbose else (lambda *a, **k: None)
    now = now or now_wib()
    log("Membaca data ...")
    data = _only_original(_retry(lambda: _read(engine), engine, "baca", log=log))
    if data["customers"].empty:
        raise RuntimeError("Tabel customers kosong. Jalankan seed_db terlebih dahulu.")
    frames = build_continuation(data, now, days_ahead, seed)
    if not frames:
        log("Tanggal hari ini masih dalam rentang data synthetic; tidak ada yang perlu dilanjutkan.")
        _retry(lambda: purge_demo_data(engine), engine, "hapus", log=log)
        return {}
    log("Menyimpan data demo (hapus lama + tambah baru dalam satu transaksi) ...")
    counts = _retry(lambda: insert_frames(engine, frames), engine, "simpan", log=log)
    log("Data demo ditambahkan:", counts)
    summary = {"inserted": counts, "scheduled_reminders": len(frames["scheduled_ids"]), "priorities_assigned": 0}
    if predict and frames["scheduled_ids"]:
        from src.ml.predict import ModelNotFoundError, load_model

        try:
            model = load_model()
            log("Menghitung prioritas dengan model", model.version)
            summary["priorities_assigned"] = _retry(
                lambda: assign_priorities(engine, frames["scheduled_ids"], now.date(), model, verbose),
                engine, "prioritas", log=log)
        except ModelNotFoundError:
            log("PERINGATAN: artefak model tidak ditemukan; prioritas tidak diisi. Jalankan `python -m src.ml.train`.")
    log(f"Selesai: {summary['scheduled_reminders']} reminder Scheduled, prioritas terisi: {summary['priorities_assigned']}")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Lanjutkan data synthetic sampai hari ini untuk demo.")
    parser.add_argument("--days-ahead", type=int, default=2, help="reminder Scheduled untuk kelas hari ini s/d N hari ke depan")
    parser.add_argument("--no-predict", action="store_true", help="lewati perhitungan prioritas")
    args = parser.parse_args()
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL belum diset. Isi di file .env.")
    run(make_engine(url), days_ahead=args.days_ahead, predict=not args.no_predict)


if __name__ == "__main__":
    main()
