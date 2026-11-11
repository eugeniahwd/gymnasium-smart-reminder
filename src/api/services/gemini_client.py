"""Klien Gemini (SDK `google-genai`) dengan timeout dan retry terbatas.

Dipanggil HANYA dari backend. Klien bisa disuntik (protokol `DraftGenerator`) sehingga tes memakai klien palsu
dan tidak pernah menyentuh jaringan.

Cara pakai SDK diverifikasi dari dokumentasi resmi dan source `google-genai` 2.34.0:
- `genai.Client(api_key=..., http_options=types.HttpOptions(timeout=<milidetik>))`
- `client.models.generate_content(model=..., contents=..., config=types.GenerateContentConfig(
  system_instruction=..., temperature=...))` lalu `response.text`
- error HTTP -> `google.genai.errors.ClientError` (4xx) / `ServerError` (5xx), atribut `.code`
- retry bawaan SDK MATI jika `HttpOptions.retry_options` tidak diisi, jadi retry diatur di modul ini.
"""
from __future__ import annotations

import logging
import random
import time
from typing import Any, Callable, Protocol

from src.api.config import DEFAULT_GEMINI_MODEL, Settings

logger = logging.getLogger("gymnasium.api")

RETRYABLE_HTTP_CODES = {408, 429, 500, 502, 503, 504}
MAX_BACKOFF_SECONDS = 8.0


class DraftGenerator(Protocol):
    """Kontrak minimal generator teks yang dipakai draft_service (klien asli maupun palsu)."""

    def generate(self, system_instruction: str, prompt: str) -> str:
        """Kembalikan teks hasil generasi (boleh string kosong)."""
        ...


class GeminiError(Exception):
    """Kegagalan pemanggilan Gemini yang sudah diklasifikasikan.

    kind: rate_limit | timeout | connection | server | auth | bad_request | not_found | unknown
    """

    def __init__(self, kind: str, detail: str, retryable: bool = False, http_code: int | None = None):
        self.kind, self.detail, self.retryable, self.http_code = kind, detail, retryable, http_code
        super().__init__(f"{kind}: {detail}")


def classify_error(exc: BaseException) -> GeminiError:
    """Petakan exception SDK/httpx ke GeminiError. Pesan asli tidak disalin (hindari data sensitif di log)."""
    if isinstance(exc, GeminiError):
        return exc
    try:
        from google.genai import errors as genai_errors
    except ImportError:  # pragma: no cover - SDK ada di requirements
        genai_errors = None
    if genai_errors is not None and isinstance(exc, genai_errors.APIError):
        code = int(getattr(exc, "code", 0) or 0)
        status = getattr(exc, "status", None) or ""
        detail = f"HTTP {code} {status}".strip()
        if code == 429:
            return GeminiError("rate_limit", detail, True, code)
        if code == 408:
            return GeminiError("timeout", detail, True, code)
        if code >= 500:
            return GeminiError("server", detail, code in RETRYABLE_HTTP_CODES, code)
        if code in (401, 403):
            return GeminiError("auth", detail, False, code)
        if code == 404:
            return GeminiError("not_found", detail, False, code)
        return GeminiError("bad_request", detail, False, code)
    try:
        import httpx

        if isinstance(exc, httpx.TimeoutException):
            return GeminiError("timeout", type(exc).__name__, True)
        if isinstance(exc, (httpx.ConnectError, httpx.RemoteProtocolError)):
            return GeminiError("connection", type(exc).__name__, True)
    except ImportError:  # pragma: no cover
        pass
    if isinstance(exc, TimeoutError):
        return GeminiError("timeout", type(exc).__name__, True)
    if isinstance(exc, ConnectionError):
        return GeminiError("connection", type(exc).__name__, True)
    return GeminiError("unknown", type(exc).__name__, False)


class GeminiClient:
    """Implementasi DraftGenerator berbasis google-genai.

    `sdk_client` dan `sleep` bisa disuntik untuk tes (tanpa jaringan, tanpa menunggu).
    """

    def __init__(self, api_key: str, model: str, temperature: float = 0.7, timeout_seconds: float = 20.0,
                 max_retries: int = 2, base_delay: float = 1.0, sdk_client: Any = None,
                 sleep: Callable[[float], None] = time.sleep):
        if not api_key:
            raise ValueError("api_key Gemini kosong")
        self._api_key = api_key
        self.model = model
        self.temperature = temperature
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(0, int(max_retries))
        self.base_delay = base_delay
        self._sdk = sdk_client
        self._sleep = sleep

    def __repr__(self) -> str:  # jangan pernah menampilkan api key
        return f"GeminiClient(model={self.model!r}, temperature={self.temperature}, timeout={self.timeout_seconds}s)"

    def _client(self) -> Any:
        if self._sdk is None:  # dibuat malas: startup API tidak bergantung pada SDK/jaringan
            from google import genai
            from google.genai import types

            self._sdk = genai.Client(api_key=self._api_key,
                                     http_options=types.HttpOptions(timeout=int(self.timeout_seconds * 1000)))
        return self._sdk

    def _config(self, system_instruction: str) -> Any:
        from google.genai import types

        # max_output_tokens sengaja TIDAK diisi: menurut dokumentasi resmi batas itu ikut menghitung token
        # "thinking" sehingga batas rendah bisa memotong/mengosongkan jawaban. Panjang dijaga oleh post-check.
        return types.GenerateContentConfig(system_instruction=system_instruction, temperature=self.temperature)

    def _backoff(self, attempt: int) -> float:
        delay = min(self.base_delay * (2 ** attempt), MAX_BACKOFF_SECONDS)
        return delay + random.uniform(0, delay * 0.1) if delay > 0 else 0.0

    def generate(self, system_instruction: str, prompt: str) -> str:
        """Panggil Gemini; retry dengan exponential backoff hanya untuk error sementara (429/5xx/timeout)."""
        attempts = self.max_retries + 1
        for attempt in range(attempts):
            try:
                response = self._client().models.generate_content(
                    model=self.model, contents=prompt, config=self._config(system_instruction))
                return (getattr(response, "text", None) or "").strip()
            except Exception as exc:  # noqa: BLE001 - diklasifikasikan di bawah
                err = classify_error(exc)
                last = attempt == attempts - 1
                logger.warning("Gemini gagal (percobaan %d/%d): %s%s", attempt + 1, attempts, err.kind,
                               "" if (last or not err.retryable) else " - mencoba lagi")
                if last or not err.retryable:
                    raise err from exc
                self._sleep(self._backoff(attempt))
        raise GeminiError("unknown", "loop retry berakhir tanpa hasil")  # pragma: no cover


def build_draft_generator(settings: Settings) -> GeminiClient | None:
    """Buat klien dari Settings. `None` jika GEMINI_API_KEY kosong (draft_service lalu memakai template)."""
    if not settings.gemini_api_key:
        logger.warning("GEMINI_API_KEY kosong - /generate-draft akan memakai template cadangan.")
        return None
    if not settings.gemini_model:
        logger.warning("GEMINI_MODEL kosong - memakai default %s.", DEFAULT_GEMINI_MODEL)
    return GeminiClient(api_key=settings.gemini_api_key, model=settings.effective_gemini_model,
                        temperature=settings.gemini_temperature, timeout_seconds=settings.gemini_timeout_seconds,
                        max_retries=settings.gemini_max_retries)
