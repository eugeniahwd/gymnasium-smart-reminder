"""Dependency FastAPI."""
from __future__ import annotations

from typing import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from src.api.errors import APIError
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
