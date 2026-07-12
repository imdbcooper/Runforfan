from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import CoachingEvent, User
from app.schemas.common import CoachingEventOut
from app.services.auth import get_current_user
from app.services.coaching_events import EVENT_TYPES


router = APIRouter(prefix="/coaching-events", tags=["coaching-events"])


@router.get("", response_model=list[CoachingEventOut])
def list_coaching_events(
    event_type: str | None = Query(default=None, max_length=64),
    workout_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=10000),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if event_type is not None and event_type not in EVENT_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported coaching event type")
    query = select(CoachingEvent).where(CoachingEvent.user_id == user.id)
    if event_type is not None:
        query = query.where(CoachingEvent.event_type == event_type)
    if workout_id is not None:
        query = query.where(CoachingEvent.workout_id == workout_id)
    return list(db.scalars(
        query.order_by(CoachingEvent.occurred_at.desc(), CoachingEvent.id.desc())
        .limit(limit)
        .offset(offset)
    ))
