"""Model ORM (cermin dari sql/migrations/001_init.sql). Constraint enum dijaga di DB dan skema Pydantic."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, BigInteger, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from src.api.timeutil import now_wib

JSONType = JSON().with_variant(JSONB(), "postgresql")
ID = BigInteger().with_variant(Integer(), "sqlite")  # agar autoincrement berjalan di SQLite (tes)


class Base(DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    nama: Mapped[str] = mapped_column(Text)
    no_whatsapp: Mapped[str] = mapped_column(String, unique=True)
    persona: Mapped[str] = mapped_column(String)
    catatan: Mapped[str | None] = mapped_column(Text, nullable=True)
    join_date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_wib)


class Schedule(Base):
    __tablename__ = "schedules"
    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    nama_kelas: Mapped[str] = mapped_column(Text)
    tipe: Mapped[str] = mapped_column(String)
    waktu_mulai: Mapped[datetime] = mapped_column(DateTime, index=True)
    pelatih: Mapped[str] = mapped_column(Text)
    kapasitas: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_wib)


class Attendance(Base):
    __tablename__ = "attendance"
    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(ID, ForeignKey("customers.id"), index=True)
    schedule_id: Mapped[int] = mapped_column(ID, ForeignKey("schedules.id"), index=True)
    status: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_wib)


class Reschedule(Base):
    __tablename__ = "reschedules"
    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(ID, ForeignKey("customers.id"), index=True)
    schedule_id_asal: Mapped[int] = mapped_column(ID, ForeignKey("schedules.id"))
    schedule_id_baru: Mapped[int | None] = mapped_column(ID, ForeignKey("schedules.id"), nullable=True)
    alasan: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_wib)


class Reminder(Base):
    __tablename__ = "reminders"
    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(ID, ForeignKey("customers.id"), index=True)
    schedule_id: Mapped[int | None] = mapped_column(ID, ForeignKey("schedules.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String, default="Scheduled", index=True)
    priority: Mapped[str | None] = mapped_column(String, nullable=True)
    priority_probabilities: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    message_type: Mapped[str] = mapped_column(String, default="reminder_kelas")
    draft_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    draft_source: Mapped[str | None] = mapped_column(String, nullable=True)
    final_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_wib)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_wib)

    customer: Mapped[Customer] = relationship(lazy="select")
    schedule: Mapped[Schedule | None] = relationship(lazy="select")


class ReminderStatusHistory(Base):
    __tablename__ = "reminder_status_history"
    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    reminder_id: Mapped[int] = mapped_column(ID, ForeignKey("reminders.id"), index=True)
    from_status: Mapped[str | None] = mapped_column(String, nullable=True)
    to_status: Mapped[str] = mapped_column(String)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=now_wib)


class Prediction(Base):
    __tablename__ = "predictions"
    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(ID, ForeignKey("customers.id"), index=True)
    priority: Mapped[str] = mapped_column(String)
    probabilities: Mapped[dict] = mapped_column(JSONType)
    top_factors: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    model_version: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_wib)
