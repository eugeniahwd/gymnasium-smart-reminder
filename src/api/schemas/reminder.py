from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from src.api.schemas.common import ClassType, MessageType, Persona, Priority, ReminderStatus


class ReminderCreate(BaseModel):
    customer_id: int
    schedule_id: int | None = Field(default=None, description="Kelas terkait (opsional)")
    message_type: MessageType = "reminder_kelas"

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "customer_id": 1, "schedule_id": 120, "message_type": "reminder_kelas"}]})


class StatusUpdate(BaseModel):
    status: ReminderStatus

    model_config = ConfigDict(json_schema_extra={"examples": [{"status": "Sent"}]})


class MessageUpdate(BaseModel):
    final_message: str = Field(min_length=1, max_length=2000, description="Pesan akhir yang dikirim admin")

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "final_message": "Selamat pagi Bu Sari, kami mengingatkan kelas Yoga Lembut besok pukul 08.30. Sampai jumpa ya!"}]})


class CustomerBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nama: str
    no_whatsapp: str
    persona: Persona


class ScheduleBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nama_kelas: str
    tipe: ClassType
    waktu_mulai: datetime
    pelatih: str


class ReminderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    customer_id: int
    schedule_id: int | None
    status: ReminderStatus
    priority: Priority | None
    priority_probabilities: dict[str, float] | None
    message_type: MessageType
    draft_message: str | None
    draft_source: str | None
    final_message: str | None
    created_at: datetime
    sent_at: datetime | None
    responded_at: datetime | None
    updated_at: datetime
    customer: CustomerBrief | None = None
    schedule: ScheduleBrief | None = None


class StatusHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    reminder_id: int
    from_status: ReminderStatus | None
    to_status: ReminderStatus
    changed_at: datetime
