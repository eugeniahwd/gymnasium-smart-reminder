from __future__ import annotations

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")

Persona = Literal["ibu-ibu", "lansia", "menengah_atas"]
ClassType = Literal["group_class", "private"]
ReminderStatus = Literal["Scheduled", "Sent", "Responded", "No Response"]
Priority = Literal["Low", "Medium", "High"]
MessageType = Literal["reminder_kelas", "follow_up_absen", "follow_up_tidak_merespons"]


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int = Field(description="Total data yang cocok dengan filter")
    limit: int
    offset: int


class ErrorResponse(BaseModel):
    detail: str
    code: str
