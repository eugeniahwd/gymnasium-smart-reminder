"""Konfigurasi aplikasi dari environment variable (.env dibaca otomatis bila ada)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Dipakai HANYA jika env GEMINI_MODEL kosong. Model stabil Flash-Lite (paling hemat kuota) menurut
# https://ai.google.dev/gemini-api/docs/models (dicek 8 Nov 2026). Ganti lewat GEMINI_MODEL, bukan di kode.
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"


@dataclass(frozen=True)
class Settings:
    database_url: str | None = None
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:8501"])
    gemini_api_key: str | None = None
    gemini_model: str | None = None  # None -> DEFAULT_GEMINI_MODEL
    gemini_temperature: float = 0.7
    gemini_timeout_seconds: float = 20.0
    gemini_max_retries: int = 2  # retry tambahan untuk 429/5xx/timeout (total percobaan = 1 + nilai ini)
    timezone: str = "Asia/Jakarta"
    log_level: str = "INFO"

    @property
    def effective_gemini_model(self) -> str:
        return self.gemini_model or DEFAULT_GEMINI_MODEL


def _env_number(name: str, default: float, cast: type, lo: float, hi: float):
    """Baca angka dari env; nilai kosong/tidak valid/di luar rentang -> default (tidak membuat server gagal start)."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = cast(raw.strip())
    except ValueError:
        return default
    return value if lo <= value <= hi else default


def get_settings() -> Settings:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:  # python-dotenv opsional
        pass
    origins = os.getenv("CORS_ORIGINS", "http://localhost:8501")
    return Settings(
        database_url=os.getenv("DATABASE_URL") or None,
        cors_origins=[o.strip() for o in origins.split(",") if o.strip()],
        gemini_api_key=(os.getenv("GEMINI_API_KEY") or "").strip() or None,
        gemini_model=(os.getenv("GEMINI_MODEL") or "").strip() or None,
        gemini_temperature=_env_number("GEMINI_TEMPERATURE", 0.7, float, 0.0, 2.0),
        gemini_timeout_seconds=_env_number("GEMINI_TIMEOUT_SECONDS", 20.0, float, 1.0, 120.0),
        gemini_max_retries=_env_number("GEMINI_MAX_RETRIES", 2, int, 0, 5),
        timezone=os.getenv("APP_TIMEZONE", "Asia/Jakarta"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )
