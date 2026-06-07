from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import User
from app.schemas.common import CalendarOut
from app.services.auth import get_current_user
from app.services.calendar import MAX_CALENDAR_RANGE_DAYS, calendar_range


router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("", response_model=CalendarOut)
def get_calendar(
    from_date: date = Query(alias="from"),
    to_date: date = Query(alias="to"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if from_date > to_date:
        raise HTTPException(status_code=400, detail="from must be before or equal to to")
    if (to_date - from_date).days + 1 > MAX_CALENDAR_RANGE_DAYS:
        raise HTTPException(status_code=400, detail=f"calendar range cannot exceed {MAX_CALENDAR_RANGE_DAYS} days")
    return calendar_range(db, user, from_date, to_date)
