from __future__ import annotations

import re
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.api.schemas.common import Persona

_WA = re.compile(r"^(?:\+?62|0)8\d{7,12}$")


def normalize_whatsapp(value: str) -> str:
    """Terima 08xx / +628xx / 628xx dan simpan sebagai 628xx."""
    cleaned = re.sub(r"[\s\-().]", "", value or "")
    if not _WA.match(cleaned):
        raise ValueError("format nomor WhatsApp tidak valid (contoh: 081234567890 atau 6281234567890)")
    digits = cleaned.lstrip("+")
    if digits.startswith("0"):
        digits = "62" + digits[1:]
    return digits


class CustomerCreate(BaseModel):
    nama: str = Field(min_length=1, max_length=100)
    no_whatsapp: str
    persona: Persona
    catatan: str | None = Field(default=None, max_length=500)
    join_date: date | None = Field(default=None, description="Default: hari ini")

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "nama": "Ibu Sari Wijaya", "no_whatsapp": "081234567890", "persona": "ibu-ibu",
        "catatan": "Lebih suka kelas pagi"}]})

    @field_validator("nama")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("nama tidak boleh kosong")
        return v

    @field_validator("no_whatsapp")
    @classmethod
    def _wa(cls, v: str) -> str:
        return normalize_whatsapp(v)


class CustomerUpdate(BaseModel):
    nama: str | None = Field(default=None, min_length=1, max_length=100)
    no_whatsapp: str | None = None
    persona: Persona | None = None
    catatan: str | None = Field(default=None, max_length=500)

    @field_validator("no_whatsapp")
    @classmethod
    def _wa(cls, v: str | None) -> str | None:
        return normalize_whatsapp(v) if v is not None else None


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nama: str
    no_whatsapp: str
    persona: Persona
    catatan: str | None
    join_date: date
    created_at: datetime
