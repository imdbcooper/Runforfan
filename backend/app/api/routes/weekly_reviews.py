from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import User
from app.schemas.common import EmptyRequest, WeeklyReviewOut, WeeklyStrategyApplyOut, WeeklyStrategyPreviewOut, WeeklyStrategyPreviewRequest
from app.services.auth import get_current_user
from app.services.historical_state import HistoricalStateConflict
from app.services.weekly_review import WeeklyReviewConflict, apply_weekly_strategy_preview, create_weekly_strategy_preview, materialize_weekly_review


router = APIRouter(prefix="/weekly-reviews", tags=["weekly-reviews"])


def weekly_conflict(error: WeeklyReviewConflict) -> HTTPException:
    return HTTPException(status_code=409, detail={"code": "conflict", "message": str(error), "details": {"reason": error.reason}})


@router.get("/current", response_model=WeeklyReviewOut)
def current_weekly_review(
    week_start: date | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return materialize_weekly_review(db, user, week_start=week_start)
    except HistoricalStateConflict as error:
        db.rollback()
        raise HTTPException(status_code=409, detail={"code": "conflict", "message": str(error), "details": {"reason": error.reason}}) from error
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/{review_id}/strategy-preview", response_model=WeeklyStrategyPreviewOut)
def preview_weekly_strategy(
    review_id: int,
    payload: WeeklyStrategyPreviewRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return create_weekly_strategy_preview(db, user, review_id, payload.strategy)
    except WeeklyReviewConflict as error:
        db.rollback()
        raise weekly_conflict(error) from error


@router.post("/strategy-previews/{preview_id}/apply", response_model=WeeklyStrategyApplyOut)
def apply_weekly_strategy(
    preview_id: str,
    _payload: EmptyRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return apply_weekly_strategy_preview(db, user, preview_id)
    except WeeklyReviewConflict as error:
        db.rollback()
        raise weekly_conflict(error) from error
