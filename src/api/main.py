"""Aplikasi FastAPI Gymnasium Smart Reminder & Follow-up.

Jalankan lokal:  uvicorn src.api.main:app --reload
Dokumentasi interaktif: http://localhost:8000/docs
"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from src.api.config import Settings, get_settings
from src.api.db.session import make_engine, make_session_factory
from src.api.errors import register_error_handlers
from src.api.routers import customers, drafts, health, predict, reminders, schedules
from src.ml import predict as ml_predict

logger = logging.getLogger("gymnasium.api")
_AUTO = object()

TAGS = [
    {"name": "Sistem", "description": "Status layanan."},
    {"name": "Customer", "description": "CRUD customer."},
    {"name": "Jadwal / Kelas", "description": "CRUD jadwal kelas group dan private."},
    {"name": "Reminder", "description": "Reminder, alur status, dan riwayat."},
    {"name": "Prediksi AI", "description": "Prioritas follow-up dari model machine learning."},
    {"name": "Generative AI", "description": "Draft pesan (Fase 4)."},
]
DESCRIPTION = (
    "Backend admin Gymnasium Smart Reminder & Follow-up.\n\n"
    "**PROTOTYPE** - model dilatih pada data synthetic; bukan klaim akurasi di kondisi nyata. "
    "Pesan tidak dikirim otomatis: admin mengirim lewat WhatsApp lalu memperbarui status."
)


def _load_model_safely():
    try:
        model = ml_predict.load_model()
        logger.info("Model dimuat: %s", model.version)
        return model
    except ml_predict.ModelNotFoundError as exc:
        logger.warning("%s - /predict akan membalas 503.", exc)
    except Exception:  # noqa: BLE001 (mis. versi scikit-learn tidak cocok)
        logger.exception("Gagal memuat model - /predict akan membalas 503.")
    return None


def create_app(settings: Settings | None = None, engine=None, model=_AUTO) -> FastAPI:
    """Factory aplikasi. `engine` dan `model` bisa disuntik (dipakai tes)."""
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if engine is None and settings.database_url:
        try:
            engine = make_engine(settings.database_url)
        except Exception:  # noqa: BLE001
            logger.exception("Gagal membuat engine database.")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if model is _AUTO:
            app.state.model = _load_model_safely()  # dimuat SEKALI saat startup
        yield
        if engine is not None:
            engine.dispose()

    app = FastAPI(title="Gymnasium Smart Reminder & Follow-up API", version="0.3.0",
                  description=DESCRIPTION, openapi_tags=TAGS, lifespan=lifespan)
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine) if engine is not None else None
    app.state.model = None if model is _AUTO else model

    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])
    register_error_handlers(app)

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        logger.info("%s %s -> %s (%.0f ms)", request.method, request.url.path, response.status_code,
                    (time.perf_counter() - start) * 1000)
        return response

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/docs")

    for r in (health.router, customers.router, schedules.router, reminders.router, predict.router, drafts.router):
        app.include_router(r)
    return app


app = create_app()
