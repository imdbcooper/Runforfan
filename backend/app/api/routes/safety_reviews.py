from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import User
from app.schemas.common import SafetyReviewCompleteIn, SafetyReviewContextOut, SafetyReviewerCapabilityOut, SafetyReviewerQueueItemOut, SafetyReviewResultOut
from app.services.auth import get_current_user
from app.services.safety_reviews import SafetyReviewConflict, claim_request, complete_request, release_request, require_active_reviewer, reviewer_context, reviewer_queue


router = APIRouter(prefix="/safety-reviewer", tags=["safety-reviewer"])


def _conflict(error: SafetyReviewConflict) -> HTTPException:
    return HTTPException(status_code=409, detail={"code": "conflict", "message": str(error)})


def _database_conflict(error: DBAPIError) -> HTTPException | None:
    sqlstate = getattr(error.orig, "sqlstate", None)
    if sqlstate in {"40001", "40P01"}:
        return HTTPException(status_code=409, detail={"code": "conflict", "message": "Concurrent review state change; retry with current state"})
    return None


@router.get("/capability", response_model=SafetyReviewerCapabilityOut)
def capability(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_active_reviewer(db, user)
    return {"available": True}


@router.get("/requests", response_model=list[SafetyReviewerQueueItemOut])
def list_requests(limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return reviewer_queue(db, user, limit, offset)


@router.post("/requests/{request_id}/claim", response_model=SafetyReviewContextOut)
def claim(request_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        return claim_request(db, user, request_id)
    except SafetyReviewConflict as error:
        db.rollback()
        raise _conflict(error) from error
    except DBAPIError as error:
        db.rollback()
        conflict = _database_conflict(error)
        if conflict is None:
            raise
        raise conflict from error


@router.get("/requests/{request_id}/context", response_model=SafetyReviewContextOut)
def context(request_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        return reviewer_context(db, user, request_id)
    except SafetyReviewConflict as error:
        db.rollback()
        raise _conflict(error) from error
    except DBAPIError as error:
        db.rollback()
        conflict = _database_conflict(error)
        if conflict is None:
            raise
        raise conflict from error


@router.post("/requests/{request_id}/release", response_model=SafetyReviewerQueueItemOut)
def release(request_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        return release_request(db, user, request_id)
    except SafetyReviewConflict as error:
        db.rollback()
        raise _conflict(error) from error
    except DBAPIError as error:
        db.rollback()
        conflict = _database_conflict(error)
        if conflict is None:
            raise
        raise conflict from error


@router.post("/requests/{request_id}/complete", response_model=SafetyReviewResultOut)
def complete(request_id: int, payload: SafetyReviewCompleteIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        return complete_request(db, user, request_id, payload.disposition_code)
    except SafetyReviewConflict as error:
        db.rollback()
        raise _conflict(error) from error
    except DBAPIError as error:
        db.rollback()
        conflict = _database_conflict(error)
        if conflict is None:
            raise
        raise conflict from error
