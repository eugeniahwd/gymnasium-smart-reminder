from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, contains_eager, joinedload

from src.api.db.models import Customer, Reminder, ReminderStatusHistory, Schedule
from src.api.deps import get_db, get_model
from src.api.errors import APIError
from src.api.schemas.common import MessageType, Page, Priority, ReminderStatus
from src.api.schemas.reminder import MessageUpdate, ReminderCreate, ReminderOut, StatusHistoryOut, StatusUpdate
from src.api.services import status_flow
from src.api.services.prediction_service import run_prediction
from src.api.timeutil import now_wib, today_wib
from src.ml.predict import LoadedModel

logger = logging.getLogger("gymnasium.api")
router = APIRouter(tags=["Reminder"])

_PRIORITY_ORDER = case((Reminder.priority == "High", 0), (Reminder.priority == "Medium", 1),
                       (Reminder.priority == "Low", 2), else_=3)


def _load(db: Session, reminder_id: int) -> Reminder:
    obj = db.execute(
        select(Reminder).where(Reminder.id == reminder_id)
        .options(joinedload(Reminder.customer), joinedload(Reminder.schedule))
    ).scalars().first()
    if obj is None:
        raise APIError(404, "not_found", f"Reminder dengan id {reminder_id} tidak ditemukan.")
    return obj


def _parse_date(value: str) -> date:
    if value.lower() == "today":
        return today_wib()
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise APIError(422, "invalid_date", "Parameter date harus 'today' atau format YYYY-MM-DD.") from None


def _query_reminders(db: Session, conds: list, order: list, limit: int, offset: int):
    total = db.execute(select(func.count()).select_from(Reminder)
                       .outerjoin(Schedule, Reminder.schedule_id == Schedule.id).where(*conds)).scalar_one()
    stmt = (select(Reminder).outerjoin(Schedule, Reminder.schedule_id == Schedule.id).where(*conds)
            .options(contains_eager(Reminder.schedule), joinedload(Reminder.customer))
            .order_by(*order).limit(limit).offset(offset))
    items = db.execute(stmt).scalars().unique().all()  # satu query (tanpa N+1)
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/reminders", response_model=Page[ReminderOut], summary="Daftar reminder",
            description="Filter `date` memakai TANGGAL KELAS (waktu_mulai jadwal). Urutan: prioritas High dulu, "
                        "lalu kelas terdekat. Reminder tanpa prioritas diurutkan paling akhir.")
def list_reminders(
    date_: str | None = Query(None, alias="date", description="'today' atau YYYY-MM-DD (tanggal kelas)"),
    status: ReminderStatus | None = None,
    priority: Priority | None = None,
    customer_id: int | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    conds = []
    if date_:
        d = _parse_date(date_)
        conds += [Schedule.waktu_mulai >= datetime.combine(d, time.min),
                  Schedule.waktu_mulai < datetime.combine(d + timedelta(days=1), time.min)]
    if status:
        conds.append(Reminder.status == status)
    if priority:
        conds.append(Reminder.priority == priority)
    if customer_id is not None:
        conds.append(Reminder.customer_id == customer_id)
    return _query_reminders(db, conds, [_PRIORITY_ORDER, Schedule.waktu_mulai.asc(), Reminder.id.asc()], limit, offset)


@router.post("/reminders", response_model=ReminderOut, status_code=201, summary="Buat reminder (status Scheduled)")
def create_reminder(body: ReminderCreate, db: Session = Depends(get_db),
                    model: LoadedModel | None = Depends(get_model)):
    customer = db.get(Customer, body.customer_id)
    if customer is None:
        raise APIError(404, "not_found", f"Customer dengan id {body.customer_id} tidak ditemukan.")
    if body.schedule_id is not None:
        if db.get(Schedule, body.schedule_id) is None:
            raise APIError(404, "not_found", f"Jadwal dengan id {body.schedule_id} tidak ditemukan.")
        dup = db.execute(select(Reminder.id).where(
            Reminder.customer_id == body.customer_id, Reminder.schedule_id == body.schedule_id,
            Reminder.message_type == body.message_type, Reminder.status.in_(["Scheduled", "Sent"]))).first()
        if dup:
            raise APIError(409, "duplicate_reminder",
                           "Reminder yang sama (customer, kelas, dan jenis pesan) masih aktif. Selesaikan dulu reminder tersebut.")
    now = now_wib()
    reminder = Reminder(customer_id=body.customer_id, schedule_id=body.schedule_id, status="Scheduled",
                        message_type=body.message_type, created_at=now, updated_at=now)
    db.add(reminder)
    db.flush()
    db.add(ReminderStatusHistory(reminder_id=reminder.id, from_status=None, to_status="Scheduled", changed_at=now))
    if model is not None:  # prioritas otomatis; kegagalan prediksi tidak boleh menggagalkan pembuatan reminder
        try:
            res = run_prediction(db, customer, model)
            reminder.priority, reminder.priority_probabilities = res["priority"], res["probabilities"]
        except Exception:  # noqa: BLE001
            logger.exception("Prediksi otomatis gagal untuk reminder baru (customer_id=%s)", customer.id)
    db.commit()
    return _load(db, reminder.id)


@router.get("/reminders/{reminder_id}", response_model=ReminderOut, summary="Detail reminder")
def get_reminder(reminder_id: int, db: Session = Depends(get_db)):
    return _load(db, reminder_id)


@router.get("/reminders/{reminder_id}/history", response_model=list[StatusHistoryOut],
            summary="Riwayat perubahan status reminder")
def reminder_history(reminder_id: int, db: Session = Depends(get_db)):
    _load(db, reminder_id)
    return db.execute(select(ReminderStatusHistory).where(ReminderStatusHistory.reminder_id == reminder_id)
                      .order_by(ReminderStatusHistory.changed_at, ReminderStatusHistory.id)).scalars().all()


@router.get("/customers/{customer_id}/reminders", response_model=Page[ReminderOut],
            summary="Riwayat reminder satu customer (terbaru dulu)")
def customer_reminders(customer_id: int, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                       db: Session = Depends(get_db)):
    if db.get(Customer, customer_id) is None:
        raise APIError(404, "not_found", f"Customer dengan id {customer_id} tidak ditemukan.")
    return _query_reminders(db, [Reminder.customer_id == customer_id],
                            [Reminder.created_at.desc(), Reminder.id.desc()], limit, offset)


@router.patch("/reminders/{reminder_id}/status", response_model=ReminderOut, summary="Ubah status reminder",
              description="Alur valid: Scheduled → Sent → Responded / No Response. Transisi lain ditolak (409). "
                          "`sent_at` dan `responded_at` terisi otomatis; setiap perubahan dicatat di riwayat.")
def update_status(reminder_id: int, body: StatusUpdate, db: Session = Depends(get_db)):
    reminder = _load(db, reminder_id)
    status_flow.change_status(db, reminder, body.status)
    db.commit()
    return _load(db, reminder_id)


@router.patch("/reminders/{reminder_id}/message", response_model=ReminderOut,
              summary="Simpan pesan akhir (final_message)",
              description="Hanya boleh saat status masih Scheduled; setelah Sent pesan terkunci (409).")
def update_message(reminder_id: int, body: MessageUpdate, db: Session = Depends(get_db)):
    reminder = _load(db, reminder_id)
    if reminder.status != "Scheduled":
        raise APIError(409, "message_locked",
                       f"Pesan tidak dapat diubah karena reminder sudah berstatus '{reminder.status}'.")
    reminder.final_message = body.final_message.strip()
    reminder.updated_at = now_wib()
    db.commit()
    return _load(db, reminder_id)


@router.post("/reminders/{reminder_id}/refresh-priority", response_model=ReminderOut,
             summary="Hitung ulang prioritas reminder dengan model ML")
def refresh_priority(reminder_id: int, db: Session = Depends(get_db),
                     model: LoadedModel | None = Depends(get_model)):
    reminder = _load(db, reminder_id)
    result = run_prediction(db, reminder.customer, model)
    reminder.priority, reminder.priority_probabilities = result["priority"], result["probabilities"]
    reminder.updated_at = now_wib()
    db.commit()
    return _load(db, reminder_id)
