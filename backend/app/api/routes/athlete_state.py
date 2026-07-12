from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import User
from app.schemas.common import AthleteStateOut
from app.services.athlete_state import materialize_athlete_state
from app.services.auth import get_current_user


router = APIRouter(prefix="/athlete-state", tags=["athlete-state"])


@router.get("/today", response_model=AthleteStateOut)
def get_today_athlete_state(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return materialize_athlete_state(db, user)
