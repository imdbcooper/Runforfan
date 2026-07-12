from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import User
from app.schemas.common import DailyReadinessActionApplyOut, DailyReadinessActionPreviewOut, DailyReadinessCheckInUpsert, DailyReadinessOut, EmptyRequest
from app.services.auth import get_current_user
from app.services.readiness import ReadinessActionConflict, apply_daily_readiness_action_preview, create_daily_readiness_action_preview, daily_readiness_for_today, save_daily_readiness_checkin


router = APIRouter(prefix="/readiness", tags=["readiness"])


@router.get("/today", response_model=DailyReadinessOut)
def get_today_readiness(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return daily_readiness_for_today(db, user)


@router.put("/today", response_model=DailyReadinessOut)
def update_today_readiness(payload: DailyReadinessCheckInUpsert, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return save_daily_readiness_checkin(db, user, payload)


def action_conflict(error: ReadinessActionConflict) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "conflict",
            "message": str(error),
            "details": {"reason": error.reason},
        },
    )


@router.post("/today/action-preview", response_model=DailyReadinessActionPreviewOut)
def preview_today_readiness_action(_payload: EmptyRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        return create_daily_readiness_action_preview(db, user)
    except ReadinessActionConflict as error:
        db.rollback()
        raise action_conflict(error) from error


@router.post("/today/actions/{preview_id}/apply", response_model=DailyReadinessActionApplyOut)
def apply_today_readiness_action(preview_id: str, _payload: EmptyRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        return apply_daily_readiness_action_preview(db, user, preview_id)
    except ReadinessActionConflict as error:
        db.rollback()
        raise action_conflict(error) from error
