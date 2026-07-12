from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import User
from app.schemas.common import DailyReadinessCheckInUpsert, DailyReadinessOut
from app.services.auth import get_current_user
from app.services.readiness import daily_readiness_for_today, save_daily_readiness_checkin


router = APIRouter(prefix="/readiness", tags=["readiness"])


@router.get("/today", response_model=DailyReadinessOut)
def get_today_readiness(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return daily_readiness_for_today(db, user)


@router.put("/today", response_model=DailyReadinessOut)
def update_today_readiness(payload: DailyReadinessCheckInUpsert, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return save_daily_readiness_checkin(db, user, payload)
