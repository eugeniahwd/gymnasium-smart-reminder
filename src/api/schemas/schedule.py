from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.api.schemas.common import ClassType
from src.api.timeutil import to_naive_wib


class ScheduleCreate(BaseModel):
    nama_kelas: str = Field(min_length=1, max_length=100)
    tipe: ClassType
    waktu_mulai: datetime
    pelatih: str = Field(min_length=1, max_length=100)
    kapasitas: int = Field(gt=0, le=500)

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "nama_kelas": "Yoga Lembut", "tipe": "group_class", "waktu_mulai": "2026-11-06T08:30:00",
        "pelatih": "Coach Sari", "kapasitas": 15}]})

    @field_validator("waktu_mulai")
    @classmethod
    def _tz(cls, v: datetime) -> datetime:
        return to_naive_wib(v)


class ScheduleUpdate(BaseModel):
    nama_kelas: str | None = Field(default=None, min_length=1, max_length=100)
    tipe: ClassType | None = None
    waktu_mulai: datetime | None = None
    pelatih: str | None = Field(default=None, min_length=1, max_length=100)
    kapasitas: int | None = Field(default=None, gt=0, le=500)

    @field_validator("waktu_mulai")
    @classmethod
    def _tz(cls, v: datetime | None) -> datetime | None:
        return to_naive_wib(v) if v is not None else None


class ScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nama_kelas: str
    tipe: ClassType
    waktu_mulai: datetime
    pelatih: str
    kapasitas: int
    created_at: datetime
