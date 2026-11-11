from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.api.deps import get_db, get_draft_generator
from src.api.schemas.common import ErrorResponse
from src.api.schemas.predict import DraftRequest, DraftResponse
from src.api.services import draft_service
from src.api.services.gemini_client import DraftGenerator

router = APIRouter(tags=["Generative AI"])


@router.post(
    "/generate-draft", response_model=DraftResponse, summary="Buat draft pesan WhatsApp (Gemini + template cadangan)",
    description=(
        "Membuat draft pesan sesuai persona, prioritas, dan jenis pesan reminder. Draft TIDAK dikirim otomatis; "
        "admin mengedit (PATCH /reminders/{id}/message) lalu mengirim sendiri lewat WhatsApp.\n\n"
        "- Hanya untuk reminder berstatus `Scheduled` (selain itu 409 `draft_not_allowed`).\n"
        "- Jika draft sudah ada dan `regenerate=false`, draft tersimpan dikembalikan (`cached=true`) tanpa "
        "memanggil Gemini.\n"
        "- Jika Gemini gagal (kuota/timeout/respons kosong), API key kosong, atau draft tidak lolos post-check "
        "setelah 1 kali regenerasi, respons tetap 200 dengan `draft_source=template_fallback` dan `warning`.\n"
        "- Draft disimpan di `draft_message`; `final_message` tidak diubah."),
    responses={404: {"model": ErrorResponse, "description": "Reminder tidak ditemukan"},
               409: {"model": ErrorResponse, "description": "Status reminder bukan Scheduled (draft_not_allowed)"}},
)
def generate_draft(body: DraftRequest, db: Session = Depends(get_db),
                   generator: DraftGenerator | None = Depends(get_draft_generator)) -> DraftResponse:
    result = draft_service.generate_draft(db, body.reminder_id, body.regenerate, generator)
    return DraftResponse(**asdict(result))
