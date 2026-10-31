"""Cek konfigurasi DATABASE_URL dan koneksi ke database (password disamarkan).

Jalankan:  python -m src.data_generation.check_db
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from sqlalchemy import create_engine, text

from src.data_generation.seed_db import normalize_db_url

ROOT = Path(__file__).resolve().parents[2]


def mask_url(url: str) -> str:
    """Samarkan password (aman walau password mengandung karakter spesial)."""
    return re.sub(r"(://[^:/@]+:).*(@[^@]+)$", r"\1****\2", url)


def diagnose(url: str) -> list[str]:
    tips = []
    if "[" in url or "]" in url:
        tips.append("URL masih mengandung tanda [ ]: hapus kurung siku di sekitar password.")
    if "YOUR-PASSWORD" in url.upper() or "PASSWORDMU" in url.upper():
        tips.append("Password masih placeholder: ganti dengan password database yang asli.")
    m = re.match(r"^\w[\w+]*://([^:/@]+):", url)
    user = m.group(1) if m else ""
    if "pooler.supabase.com" in url and "." not in user:
        tips.append(
            f"Username '{user}' tidak memuat project ref. Untuk pooler Supabase, "
            "username harus berbentuk postgres.<project-ref> (contoh: postgres.abcdefgh)."
        )
    return tips


def main() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL KOSONG. Pastikan file .env ada di root proyek dan sudah disimpan.")
    print("DATABASE_URL terbaca:", mask_url(url))
    for tip in diagnose(url):
        print("PERHATIAN:", tip)
    try:
        engine = create_engine(normalize_db_url(url), connect_args={"connect_timeout": 15})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            tables = conn.execute(
                text("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
            ).scalar()
        print(f"KONEKSI BERHASIL. Jumlah tabel di schema public: {tables} (harus 7 setelah migrasi).")
    except Exception as exc:  # noqa: BLE001
        msg = str(getattr(exc, "orig", exc)).strip().splitlines()[0]
        print("KONEKSI GAGAL:", msg)


if __name__ == "__main__":
    main()