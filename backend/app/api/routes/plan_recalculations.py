from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import User
from app.schemas.common import PlanRecalculationOut
from app.services.auth import get_current_user
from app.services.plan_recalculations import latest_plan_recalculation


router = APIRouter(prefix="/plan-recalculations", tags=["plan-recalculations"])


@router.get("/latest", response_model=PlanRecalculationOut | None)
def get_latest_plan_recalculation(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return latest_plan_recalculation(db, user)
