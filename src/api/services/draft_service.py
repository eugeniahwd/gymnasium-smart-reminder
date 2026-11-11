"""Layanan draft pesan: cache -> Gemini -> post-check (1x regenerasi) -> template cadangan.

Admin SELALU mendapat draft (HTTP 200). `final_message` tidak pernah disentuh di sini.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from src.api.db.models import Prediction, Reminder
from src.api.errors import APIError
from src.api.services.gemini_client import DraftGenerator, GeminiError, classify_error
from src.api.services.post_check import check_draft, clean_output
from src.api.services.prompt_builder import SYSTEM_INSTRUCTION, DraftContext, build_prompt
from src.api.services.templates import render_template
from src.api.timeutil import now_wib

logger = logging.getLogger("gymnasium.api")

VALID_SOURCES = ("gemini", "template_fallback")
_SUFFIX = "Draft dibuat dari template cadangan; periksa dan sesuaikan sebelum dikirim."
GEMINI_ERROR_WARNINGS = {
    "not_configured": "Gemini belum dikonfigurasi (GEMINI_API_KEY kosong).",
    "rate_limit": "Kuota Gemini habis atau terlalu banyak permintaan (HTTP 429). Coba regenerate beberapa saat lagi.",
    "timeout": "Gemini tidak merespons tepat waktu (timeout). Coba regenerate beberapa saat lagi.",
    "connection": "Server tidak dapat terhubung ke Gemini. Coba regenerate beberapa saat lagi.",
    "server": "Layanan Gemini sedang bermasalah (HTTP 5xx). Coba regenerate beberapa saat lagi.",
    "auth": "API key Gemini ditolak (HTTP 401/403). Periksa GEMINI_API_KEY.",
    "bad_request": "Permintaan ke Gemini ditolak (HTTP 400). Periksa GEMINI_API_KEY dan GEMINI_MODEL.",
    "not_found": "Model Gemini tidak ditemukan (HTTP 404). Periksa GEMINI_MODEL.",
    "unknown": "Terjadi kesalahan tak terduga saat memanggil Gemini.",
}
WARNING_CACHED_FALLBACK = ("Draft tersimpan berasal dari template cadangan. Gunakan regenerate untuk mencoba "
                           "Gemini lagi.")
WARNING_NO_PRIORITY = "Prioritas reminder belum tersedia; draft memakai gaya pengingat ringan."


@dataclass
class ComposeResult:
    text: str
    source: str  # gemini | template_fallback
    warning: str | None = None
    attempts: int = 0  # jumlah panggilan generator (0 = tidak memanggil)
    rejected_reasons: list[list[str]] = field(default_factory=list)  # alasan post-check per percobaan gagal


@dataclass
class DraftResult:
    reminder_id: int
    draft_message: str
    draft_source: str
    cached: bool
    message_type: str
    warning: str | None = None


def _fallback(ctx: DraftContext, warning: str, attempts: int, rejected: list[list[str]]) -> ComposeResult:
    return ComposeResult(render_template(ctx), "template_fallback", f"{warning} {_SUFFIX}", attempts, rejected)


def compose_draft(ctx: DraftContext, generator: DraftGenerator | None) -> ComposeResult:
    """Buat teks draft tanpa menyentuh DB (dipakai endpoint dan skrip evaluasi).

    Gemini dipanggil maksimal 2x: percobaan awal + 1 regenerasi bila post-check gagal (termasuk respons kosong
    atau terlalu panjang). Retry jaringan (429/5xx/timeout) ditangani di dalam GeminiClient.
    """
    if generator is None:
        return _fallback(ctx, GEMINI_ERROR_WARNINGS["not_configured"], 0, [])
    rejected: list[list[str]] = []
    for attempt in (1, 2):
        prompt = build_prompt(ctx, rejected[-1] if rejected else None)
        try:
            text = clean_output(generator.generate(SYSTEM_INSTRUCTION, prompt))
        except Exception as exc:  # noqa: BLE001 - admin harus tetap mendapat draft
            err = exc if isinstance(exc, GeminiError) else classify_error(exc)
            if not isinstance(exc, GeminiError):
                logger.exception("Error tak terduga dari generator draft: %s", type(exc).__name__)
            return _fallback(ctx, GEMINI_ERROR_WARNINGS.get(err.kind, GEMINI_ERROR_WARNINGS["unknown"]),
                             attempt, rejected)
        reasons = check_draft(text, ctx)
        if not reasons:
            return ComposeResult(text, "gemini", None, attempt, rejected)
        logger.warning("Draft Gemini ditolak post-check (percobaan %d): %s", attempt, "; ".join(reasons))
        rejected.append(reasons)
    summary = "; ".join(rejected[-1])
    return _fallback(ctx, f"Draft dari Gemini tidak lolos pemeriksaan otomatis setelah 1 kali regenerasi "
                          f"({summary}).", 2, rejected)


# ------------------------------------------------------------------ data dari DB
def _load_reminder(db: Session, reminder_id: int) -> Reminder:
    obj = db.execute(select(Reminder).where(Reminder.id == reminder_id)
                     .options(joinedload(Reminder.customer), joinedload(Reminder.schedule))).scalars().first()
    if obj is None:
        raise APIError(404, "not_found", f"Reminder dengan id {reminder_id} tidak ditemukan.")
    return obj


def _last_message_at(db: Session, reminder: Reminder) -> datetime | None:
    return db.execute(select(Reminder.sent_at).where(
        Reminder.customer_id == reminder.customer_id, Reminder.id != reminder.id, Reminder.sent_at.is_not(None))
        .order_by(Reminder.sent_at.desc()).limit(1)).scalar()


def _latest_top_factors(db: Session, customer_id: int) -> list[str]:
    factors = db.execute(select(Prediction.top_factors).where(Prediction.customer_id == customer_id)
                         .order_by(Prediction.created_at.desc(), Prediction.id.desc()).limit(1)).scalar()
    return [str(f) for f in factors] if isinstance(factors, list) else []


def build_context(db: Session, reminder: Reminder, now: datetime | None = None) -> DraftContext:
    customer, schedule = reminder.customer, reminder.schedule
    return DraftContext(
        nama_customer=customer.nama, persona=customer.persona, message_type=reminder.message_type,
        now=now or now_wib(), priority=reminder.priority,
        nama_kelas=schedule.nama_kelas if schedule else None, class_type=schedule.tipe if schedule else None,
        waktu_kelas=schedule.waktu_mulai if schedule else None, pelatih=schedule.pelatih if schedule else None,
        tanggal_pesan_terakhir=_last_message_at(db, reminder),
        top_factors=_latest_top_factors(db, customer.id),
    )


def generate_draft(db: Session, reminder_id: int, regenerate: bool, generator: DraftGenerator | None) -> DraftResult:
    """Alur endpoint POST /generate-draft. Caller tidak perlu commit."""
    reminder = _load_reminder(db, reminder_id)
    if reminder.status != "Scheduled":
        raise APIError(409, "draft_not_allowed",
                       f"Draft hanya dapat dibuat untuk reminder berstatus 'Scheduled'. "
                       f"Status saat ini: '{reminder.status}'.")
    if not regenerate and reminder.draft_message and reminder.draft_source in VALID_SOURCES:
        warning = WARNING_CACHED_FALLBACK if reminder.draft_source == "template_fallback" else None
        return DraftResult(reminder.id, reminder.draft_message, reminder.draft_source, True,
                           reminder.message_type, warning)

    ctx = build_context(db, reminder)
    result = compose_draft(ctx, generator)
    warnings = [w for w in (result.warning, None if reminder.priority else WARNING_NO_PRIORITY) if w]
    reminder.draft_message = result.text
    reminder.draft_source = result.source
    reminder.updated_at = now_wib()
    db.commit()
    logger.info("Draft reminder %s: source=%s persona=%s priority=%s attempts=%d", reminder.id, result.source,
                ctx.persona, ctx.effective_priority, result.attempts)
    return DraftResult(reminder.id, result.text, result.source, False, reminder.message_type,
                       " ".join(warnings) or None)
