from __future__ import annotations

from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from src.api.db.models import Attendance, Reminder, Reschedule, Schedule
from src.api.deps import get_db
from src.api.errors import APIError
from src.api.schemas.common import ClassType, Page
from src.api.schemas.schedule import ScheduleCreate, ScheduleOut, ScheduleUpdate
from src.api.timeutil import now_wib

router = APIRouter(prefix="/schedules", tags=["Jadwal / Kelas"])


def _get_or_404(db: Session, schedule_id: int) -> Schedule:
    obj = db.get(Schedule, schedule_id)
    if obj is None:
        raise APIError(404, "not_found", f"Jadwal dengan id {schedule_id} tidak ditemukan.")
    return obj


@router.get("", response_model=Page[ScheduleOut], summary="Daftar jadwal (terbaru dulu)")
def list_schedules(
    date_from: date | None = Query(None, description="Mulai tanggal (inklusif)"),
    date_to: date | None = Query(None, description="Sampai tanggal (inklusif)"),
    tipe: ClassType | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    conds = []
    if date_from:
        conds.append(Schedule.waktu_mulai >= datetime.combine(date_from, time.min))
    if date_to:
        conds.append(Schedule.waktu_mulai < datetime.combine(date_to + timedelta(days=1), time.min))
    if tipe:
        conds.append(Schedule.tipe == tipe)
    total = db.execute(select(func.count()).select_from(Schedule).where(*conds)).scalar_one()
    items = db.execute(select(Schedule).where(*conds).order_by(Schedule.waktu_mulai.desc(), Schedule.id.desc())
                       .limit(limit).offset(offset)).scalars().all()
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.post("", response_model=ScheduleOut, status_code=201, summary="Tambah jadwal")
def create_schedule(body: ScheduleCreate, db: Session = Depends(get_db)):
    obj = Schedule(**body.model_dump(), created_at=now_wib())
    db.add(obj)
    db.commit()
    return obj


@router.get("/{schedule_id}", response_model=ScheduleOut, summary="Detail jadwal")
def get_schedule(schedule_id: int, db: Session = Depends(get_db)):
    return _get_or_404(db, schedule_id)


@router.patch("/{schedule_id}", response_model=ScheduleOut, summary="Ubah jadwal")
def update_schedule(schedule_id: int, body: ScheduleUpdate, db: Session = Depends(get_db)):
    obj = _get_or_404(db, schedule_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        if value is None:
            raise APIError(422, "validation_error", f"Validasi gagal. {key}: tidak boleh null")
        setattr(obj, key, value)
    db.commit()
    return obj


@router.delete("/{schedule_id}", status_code=204, summary="Hapus jadwal")
def delete_schedule(schedule_id: int, db: Session = Depends(get_db)):
    _get_or_404(db, schedule_id)
    db.execute(update(Reminder).where(Reminder.schedule_id == schedule_id).values(schedule_id=None))
    db.execute(update(Reschedule).where(Reschedule.schedule_id_baru == schedule_id).values(schedule_id_baru=None))
    db.execute(delete(Reschedule).where(Reschedule.schedule_id_asal == schedule_id))
    db.execute(delete(Attendance).where(Attendance.schedule_id == schedule_id))
    db.execute(delete(Schedule).where(Schedule.id == schedule_id))
    db.commit()
