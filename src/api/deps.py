"""Dependency FastAPI."""
from __future__ import annotations

from typing import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from src.api.errors import APIError
from src.api.services.gemini_client import DraftGenerator
from src.ml.predict import LoadedModel


def get_db(request: Request) -> Iterator[Session]:
    factory = request.app.state.session_factory
    if factory is None:
        raise APIError(503, "database_unavailable", "Database belum dikonfigurasi (DATABASE_URL kosong).")
    db = factory()
    try:
        yield db
    finally:
        db.close()


def get_model(request: Request) -> LoadedModel | None:
    return request.app.state.model


def get_draft_generator(request: Request) -> DraftGenerator | None:
    """Generator draft (GeminiClient asli, klien palsu di tes, atau None bila GEMINI_API_KEY kosong)."""
    return request.app.state.draft_generator
