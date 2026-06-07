from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import User
from app.schemas.common import (
    PerformancePbOut,
    PerformancePredictionOut,
    PerformanceResultCreate,
    PerformanceResultOut,
    PerformanceVdotOut,
)
from app.services.auth import get_current_user
from app.services.performance import (
    create_performance_result,
    list_performance_results,
    performance_pbs,
    performance_predictions,
    performance_vdot,
)


router = APIRouter(prefix="/performance", tags=["performance"])


@router.get("/results", response_model=list[PerformanceResultOut])
def list_results(from_date: date | None = Query(default=None, alias="from"), to_date: date | None = Query(default=None, alias="to"), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list_performance_results(db, user, from_date, to_date)


@router.post("/results", response_model=PerformanceResultOut)
def create_result(payload: PerformanceResultCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        return create_performance_result(db, user, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/vdot", response_model=PerformanceVdotOut)
def get_vdot(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return performance_vdot(db, user)


@router.get("/predictions", response_model=list[PerformancePredictionOut])
def get_predictions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return performance_predictions(db, user)


@router.get("/pbs", response_model=list[PerformancePbOut])
def get_pbs(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return performance_pbs(db, user)
