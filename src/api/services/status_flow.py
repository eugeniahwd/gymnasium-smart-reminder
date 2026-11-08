"""Alur status reminder: Scheduled -> Sent -> Responded | No Response (divalidasi di backend)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from src.api.db.models import Reminder, ReminderStatusHistory
from src.api.errors import APIError
from src.api.timeutil import now_wib

ALLOWED: dict[str, set[str]] = {
    "Scheduled": {"Sent"},
    "Sent": {"Responded", "No Response"},
    "Responded": set(),
    "No Response": set(),
}
FLOW_TEXT = "Scheduled → Sent → Responded / No Response"


def validate_transition(current: str, new: str) -> None:
    if current == new:
        raise APIError(409, "invalid_status_transition", f"Reminder sudah berstatus '{current}'.")
    if not ALLOWED.get(current):
        raise APIError(409, "invalid_status_transition",
                       f"Reminder sudah berstatus final '{current}' dan tidak dapat diubah lagi.")
    if new not in ALLOWED[current]:
        allowed = " atau ".join(f"'{s}'" for s in sorted(ALLOWED[current]))
        raise APIError(409, "invalid_status_transition",
                       f"Transisi '{current}' → '{new}' tidak diizinkan. Dari '{current}' hanya boleh ke {allowed}. "
                       f"Alur yang valid: {FLOW_TEXT}.")


def change_status(db: Session, reminder: Reminder, new_status: str) -> Reminder:
    """Validasi, terapkan, dan catat riwayat. Caller yang commit."""
    validate_transition(reminder.status, new_status)
    now = now_wib()
    old = reminder.status
    reminder.status = new_status
    reminder.updated_at = now
    if new_status == "Sent":
        reminder.sent_at = now
        if not reminder.final_message and reminder.draft_message:
            reminder.final_message = reminder.draft_message  # draft dikirim apa adanya
    elif new_status == "Responded":
        reminder.responded_at = now
    db.add(ReminderStatusHistory(reminder_id=reminder.id, from_status=old, to_status=new_status, changed_at=now))
    return reminder
