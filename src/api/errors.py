"""Error terpusat. Semua error berformat {"detail": "...", "code": "..."}."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("gymnasium.api")

_HTTP_CODES = {404: "not_found", 405: "method_not_allowed", 401: "unauthorized", 403: "forbidden"}


class APIError(Exception):
    def __init__(self, status_code: int, code: str, detail: str):
        self.status_code, self.code, self.detail = status_code, code, detail
        super().__init__(detail)


def _json(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail, "code": code})


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def _api_error(_: Request, exc: APIError):
        return _json(exc.status_code, exc.code, exc.detail)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        parts = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"] if p not in ("body", "query", "path"))
            msg = str(err.get("msg", "tidak valid")).replace("Value error, ", "")
            parts.append(f"{loc}: {msg}" if loc else msg)
        return _json(422, "validation_error", "Validasi gagal. " + "; ".join(parts))

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        code = _HTTP_CODES.get(exc.status_code, f"http_{exc.status_code}")
        detail = "Endpoint tidak ditemukan." if exc.status_code == 404 else str(exc.detail)
        return _json(exc.status_code, code, detail)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        logger.exception("Error tak terduga: %s", type(exc).__name__)
        return _json(500, "internal_error", "Terjadi kesalahan pada server. Coba lagi beberapa saat.")
