from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import text

router = APIRouter(tags=["Sistem"])


@router.get("/health", summary="Status layanan")
def health(request: Request) -> dict:
    """Selalu membalas 200. `status` = `ok` jika database terhubung, selain itu `degraded`."""
    db_ok = False
    factory = request.app.state.session_factory
    if factory is not None:
        try:
            with factory() as db:
                db.execute(text("SELECT 1"))
            db_ok = True
        except Exception:  # noqa: BLE001
            db_ok = False
    model = request.app.state.model
    return {
        "status": "ok" if db_ok else "degraded",
        "db_connected": db_ok,
        "model_loaded": model is not None,
        "model_version": model.version if model is not None else None,
    }
