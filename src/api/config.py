"""Konfigurasi aplikasi dari environment variable (.env dibaca otomatis bila ada)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    database_url: str | None = None
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:8501"])
    gemini_api_key: str | None = None  # dipakai di Fase 4
    gemini_model: str | None = None  # dipakai di Fase 4
    timezone: str = "Asia/Jakarta"
    log_level: str = "INFO"


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
        gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
        gemini_model=os.getenv("GEMINI_MODEL") or None,
        timezone=os.getenv("APP_TIMEZONE", "Asia/Jakarta"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )
