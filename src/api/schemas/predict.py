from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from src.api.schemas.common import Priority


class PredictRequest(BaseModel):
    customer_id: int
    reference_date: date | None = Field(default=None, description="Tanggal acuan fitur. Default: hari ini (WIB)")

    model_config = ConfigDict(json_schema_extra={"examples": [{"customer_id": 1}]})


class PredictResponse(BaseModel):
    customer_id: int
    reference_date: date
    priority: Priority
    probabilities: dict[str, float]
    top_factors: list[str] = Field(description="Alasan prioritas untuk ADMIN (bahasa Indonesia, maks. 3)")
    model_version: str
    cold_start: bool
    note: str | None = None
    prediction_id: int | None = None


class DraftRequest(BaseModel):
    reminder_id: int
    regenerate: bool = False
