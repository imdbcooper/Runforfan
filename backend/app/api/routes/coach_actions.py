from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import User
from app.schemas.common import CoachActionApplyOut, CoachActionPreviewOut, CoachActionPreviewRequest, EmptyRequest
from app.services.auth import get_current_user
from app.services.coach_actions import CoachActionConflict, apply_coach_action_preview, create_coach_action_preview


router = APIRouter(prefix="/coach-actions", tags=["coach-actions"])


def action_conflict(error: CoachActionConflict) -> HTTPException:
    return HTTPException(status_code=409, detail={"code": "conflict", "message": str(error), "details": {"reason": error.reason}})


@router.post("/workouts/{workout_id}/preview", response_model=CoachActionPreviewOut)
def preview_coach_action(workout_id: int, payload: CoachActionPreviewRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        return create_coach_action_preview(db, user, workout_id, payload)
    except CoachActionConflict as error:
        db.rollback()
        raise action_conflict(error) from error


@router.post("/{preview_id}/apply", response_model=CoachActionApplyOut)
def apply_coach_action(preview_id: str, _payload: EmptyRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        return apply_coach_action_preview(db, user, preview_id)
    except CoachActionConflict as error:
        db.rollback()
        raise action_conflict(error) from error
