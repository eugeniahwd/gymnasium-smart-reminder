from __future__ import annotations

from fastapi import APIRouter

from src.api.errors import APIError
from src.api.schemas.predict import DraftRequest

router = APIRouter(tags=["Generative AI"])


@router.post("/generate-draft", summary="Buat draft pesan (Fase 4)", status_code=501,
             description="PLACEHOLDER. Integrasi Gemini diimplementasikan di Fase 4.")
def generate_draft(body: DraftRequest):
    raise APIError(501, "not_implemented", "Akan diimplementasikan di Fase 4.")
