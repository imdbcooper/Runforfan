from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.models import Activity, User
from app.schemas.common import ActivityOut
from app.services.analytics import activity_local_date, profile_timezone
from app.services.auth import get_current_user
from app.services.training_load import sync_daily_training_loads_for_dates


router = APIRouter(prefix="/activities", tags=["activities"])


@router.get("", response_model=list[ActivityOut])
def list_activities(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list(db.scalars(
        select(Activity)
        .where(Activity.user_id == user.id)
        .options(selectinload(Activity.segments), selectinload(Activity.split_blocks), selectinload(Activity.workout_blocks), selectinload(Activity.derived_metrics))
        .order_by(Activity.started_at.desc().nullslast(), Activity.id.desc())
    ))


@router.get("/{activity_id}", response_model=ActivityOut)
def get_activity(activity_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    activity = db.scalar(
        select(Activity)
        .where(Activity.id == activity_id, Activity.user_id == user.id)
        .options(selectinload(Activity.segments), selectinload(Activity.split_blocks), selectinload(Activity.workout_blocks), selectinload(Activity.derived_metrics))
    )
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")
    return activity


@router.delete("/{activity_id}")
def delete_activity(activity_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    activity = db.scalar(select(Activity).where(Activity.id == activity_id, Activity.user_id == user.id))
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")
    timezone = profile_timezone(db, user)
    changed_date = activity_local_date(activity, timezone)
    db.delete(activity)
    db.flush()
    if changed_date is not None:
        sync_daily_training_loads_for_dates(db, user, [changed_date])
    db.commit()
    return {"deleted": True, "id": activity_id}
