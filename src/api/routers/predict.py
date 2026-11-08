from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.api.db.models import Customer
from src.api.deps import get_db, get_model
from src.api.errors import APIError
from src.api.schemas.predict import PredictRequest, PredictResponse
from src.api.services.prediction_service import run_prediction
from src.ml.predict import LoadedModel

router = APIRouter(tags=["Prediksi AI"])


@router.post("/predict", response_model=PredictResponse, summary="Prediksi prioritas follow-up customer",
             description="Fitur dihitung dari data database dengan modul yang sama seperti saat training. "
                         "Customer dengan riwayat < 3 kejadian ditandai `cold_start` (prioritas dibatasi Low/Medium).")
def predict(body: PredictRequest, db: Session = Depends(get_db), model: LoadedModel | None = Depends(get_model)):
    customer = db.get(Customer, body.customer_id)
    if customer is None:
        raise APIError(404, "not_found", f"Customer dengan id {body.customer_id} tidak ditemukan.")
    result = run_prediction(db, customer, model, body.reference_date)
    db.commit()
    return result
