"""Seed data synthetic (CSV di data/raw) ke database.

Contoh:
  python -m src.data_generation.seed_db --dry-run          # validasi CSV saja, tanpa koneksi DB
  python -m src.data_generation.seed_db                    # isi DB dari DATABASE_URL (.env); DB harus kosong
  python -m src.data_generation.seed_db --reset            # kosongkan tabel dulu, lalu isi

Prasyarat: migrasi sql/migrations/001_init.sql sudah dijalankan. DATABASE_URL dibaca dari env / .env,
TIDAK PERNAH ditulis di kode.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"

# urutan insert (parent dulu) dan kolom datetime tiap tabel
TABLES: list[tuple[str, list[str]]] = [
    ("customers", ["join_date", "created_at"]),
    ("schedules", ["waktu_mulai", "created_at"]),
    ("attendance", ["created_at"]),
    ("reschedules", ["created_at"]),
    ("reminders", ["created_at", "sent_at", "responded_at", "updated_at"]),
    ("reminder_status_history", ["changed_at"]),
]
# (tabel, kolom_fk, tabel_parent)
FOREIGN_KEYS = [
    ("attendance", "customer_id", "customers"),
    ("attendance", "schedule_id", "schedules"),
    ("reschedules", "customer_id", "customers"),
    ("reschedules", "schedule_id_asal", "schedules"),
    ("reschedules", "schedule_id_baru", "schedules"),
    ("reminders", "customer_id", "customers"),
    ("reminders", "schedule_id", "schedules"),
    ("reminder_status_history", "reminder_id", "reminders"),
]
# Batas jumlah parameter per INSERT: SQLite lama = 999, PostgreSQL (protokol) = 65535.
# Ukuran chunk dihitung dari jumlah kolom agar selalu di bawah batas.
PARAM_BUDGET = {"sqlite": 900, "postgresql": 20000}


def _chunksize(dialect: str, n_cols: int) -> int:
    return max(1, PARAM_BUDGET.get(dialect, 900) // n_cols)


def load_csvs(raw_dir: Path = RAW_DIR) -> dict[str, pd.DataFrame]:
    frames = {}
    for name, dt_cols in TABLES:
        path = raw_dir / f"{name}.csv"
        if not path.exists():
            raise FileNotFoundError(f"{path} tidak ditemukan. Jalankan: python -m src.data_generation.generate")
        frames[name] = pd.read_csv(path, parse_dates=dt_cols)
    return frames


def validate(frames: dict[str, pd.DataFrame]) -> list[str]:
    """Kembalikan daftar masalah integritas referensial (kosong = valid)."""
    problems = []
    for table, col, parent in FOREIGN_KEYS:
        vals = frames[table][col].dropna().astype(int)
        missing = set(vals) - set(frames[parent]["id"].astype(int))
        if missing:
            problems.append(f"{table}.{col}: {len(missing)} nilai tidak ada di {parent}.id")
    for name, df in frames.items():
        if df["id"].duplicated().any():
            problems.append(f"{name}.id duplikat")
    return problems


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    """NaN/NaT -> None agar masuk sebagai NULL."""
    return df.astype(object).where(df.notna(), None)


def seed(engine: Engine, frames: dict[str, pd.DataFrame], reset: bool = False) -> dict[str, int]:
    is_pg = engine.dialect.name == "postgresql"
    with engine.begin() as conn:
        if reset:
            if is_pg:
                names = ", ".join(n for n, _ in reversed(TABLES))
                conn.execute(text(f"TRUNCATE {names}, predictions RESTART IDENTITY CASCADE"))
            else:
                for n, _ in reversed(TABLES):
                    conn.execute(text(f"DELETE FROM {n}"))
        elif is_pg:
            n_existing = conn.execute(text("SELECT count(*) FROM customers")).scalar()
            if n_existing:
                raise RuntimeError("Tabel customers sudah berisi data. Gunakan --reset jika ingin menimpa.")

        counts = {}
        for name, _ in TABLES:
            df = _clean(frames[name])
            df.to_sql(
                name, conn, if_exists="append", index=False, method="multi",
                chunksize=_chunksize(engine.dialect.name, df.shape[1]),
            )
            counts[name] = len(df)

        if is_pg:  # sinkronkan sequence identity setelah insert dengan id eksplisit
            for name, _ in TABLES:
                conn.execute(
                    text(
                        f"SELECT setval(pg_get_serial_sequence('{name}', 'id'), "
                        f"COALESCE((SELECT MAX(id) FROM {name}), 1))"
                    )
                )
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed data synthetic ke database.")
    parser.add_argument("--dry-run", action="store_true", help="validasi CSV tanpa koneksi database")
    parser.add_argument("--reset", action="store_true", help="kosongkan tabel sebelum insert")
    args = parser.parse_args()

    frames = load_csvs()
    problems = validate(frames)
    for name, df in frames.items():
        print(f"{name:<26}{len(df):>8} baris")
    if problems:
        raise SystemExit("Validasi gagal:\n- " + "\n- ".join(problems))
    print("Validasi referensial: OK")
    if args.dry_run:
        return

    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL belum diset. Isi di file .env (lihat .env.example).")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    engine = create_engine(url)
    counts = seed(engine, frames, reset=args.reset)
    print("Seed selesai:", counts)


if __name__ == "__main__":
    main()