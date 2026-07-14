from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import CoachDeliveryPreference, User
from app.schemas.common import CoachDeliveryPreferenceOut, CoachDeliveryPreferenceUpdate
from app.services.auth import get_current_user
from app.services.coach_delivery import preference_response, update_preference

router = APIRouter(prefix="/coach-delivery", tags=["coach-delivery"])

@router.get("/preferences", response_model=CoachDeliveryPreferenceOut)
def get_preferences(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return preference_response(user, db.scalar(select(CoachDeliveryPreference).where(CoachDeliveryPreference.user_id == user.id)))

@router.put("/preferences", response_model=CoachDeliveryPreferenceOut)
def put_preferences(payload: CoachDeliveryPreferenceUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    preference = update_preference(db, user, telegram_enabled=payload.telegram_enabled, daily_brief_local_time=payload.daily_brief_local_time)
    return preference_response(user, preference)
