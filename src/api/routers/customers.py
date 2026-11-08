from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from src.api.db.models import Attendance, Customer, Prediction, Reminder, ReminderStatusHistory, Reschedule
from src.api.deps import get_db
from src.api.errors import APIError
from src.api.schemas.common import Page, Persona
from src.api.schemas.customer import CustomerCreate, CustomerOut, CustomerUpdate
from src.api.timeutil import mask_phone, now_wib, today_wib
import logging

logger = logging.getLogger("gymnasium.api")
router = APIRouter(prefix="/customers", tags=["Customer"])


def _get_or_404(db: Session, customer_id: int) -> Customer:
    obj = db.get(Customer, customer_id)
    if obj is None:
        raise APIError(404, "not_found", f"Customer dengan id {customer_id} tidak ditemukan.")
    return obj


def _ensure_unique_wa(db: Session, number: str, exclude_id: int | None = None) -> None:
    q = select(Customer.id).where(Customer.no_whatsapp == number)
    if exclude_id is not None:
        q = q.where(Customer.id != exclude_id)
    if db.execute(q).first():
        raise APIError(409, "duplicate_whatsapp", "Nomor WhatsApp sudah terdaftar pada customer lain.")


@router.get("", response_model=Page[CustomerOut], summary="Daftar customer")
def list_customers(
    q: str | None = Query(None, description="Cari berdasarkan nama (mengandung teks)"),
    persona: Persona | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    conds = []
    if q:
        conds.append(func.lower(Customer.nama).contains(q.strip().lower()))
    if persona:
        conds.append(Customer.persona == persona)
    total = db.execute(select(func.count()).select_from(Customer).where(*conds)).scalar_one()
    items = db.execute(select(Customer).where(*conds).order_by(Customer.id).limit(limit).offset(offset)).scalars().all()
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.post("", response_model=CustomerOut, status_code=201, summary="Tambah customer")
def create_customer(body: CustomerCreate, db: Session = Depends(get_db)):
    _ensure_unique_wa(db, body.no_whatsapp)
    obj = Customer(nama=body.nama, no_whatsapp=body.no_whatsapp, persona=body.persona, catatan=body.catatan,
                   join_date=body.join_date or today_wib(), created_at=now_wib())
    db.add(obj)
    db.commit()
    logger.info("Customer dibuat id=%s wa=%s", obj.id, mask_phone(obj.no_whatsapp))
    return obj


@router.get("/{customer_id}", response_model=CustomerOut, summary="Detail customer")
def get_customer(customer_id: int, db: Session = Depends(get_db)):
    return _get_or_404(db, customer_id)


@router.patch("/{customer_id}", response_model=CustomerOut, summary="Ubah customer")
def update_customer(customer_id: int, body: CustomerUpdate, db: Session = Depends(get_db)):
    obj = _get_or_404(db, customer_id)
    data = body.model_dump(exclude_unset=True)
    for required in ("nama", "no_whatsapp", "persona"):
        if required in data and data[required] is None:
            raise APIError(422, "validation_error", f"Validasi gagal. {required}: tidak boleh null")
    if "no_whatsapp" in data:
        _ensure_unique_wa(db, data["no_whatsapp"], exclude_id=customer_id)
    for key, value in data.items():
        setattr(obj, key, value)
    db.commit()
    return obj


@router.delete("/{customer_id}", status_code=204, summary="Hapus customer beserta riwayatnya")
def delete_customer(customer_id: int, db: Session = Depends(get_db)):
    _get_or_404(db, customer_id)
    rem_ids = select(Reminder.id).where(Reminder.customer_id == customer_id)
    db.execute(delete(ReminderStatusHistory).where(ReminderStatusHistory.reminder_id.in_(rem_ids)))
    db.execute(delete(Reminder).where(Reminder.customer_id == customer_id))
    db.execute(delete(Prediction).where(Prediction.customer_id == customer_id))
    db.execute(delete(Reschedule).where(Reschedule.customer_id == customer_id))
    db.execute(delete(Attendance).where(Attendance.customer_id == customer_id))
    db.execute(delete(Customer).where(Customer.id == customer_id))
    db.commit()
