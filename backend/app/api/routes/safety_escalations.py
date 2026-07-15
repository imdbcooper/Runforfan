from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import User
from app.schemas.common import SafetyEscalationAcknowledgeIn, SafetyEscalationCurrentOut, SafetyReviewConsentIn, SafetyReviewRequestIn, SafetyReviewStateOut
from app.services.auth import get_current_user
from app.services.safety_escalations import SafetyEscalationConflict, acknowledge_escalation, materialize_current_escalation
from app.services.safety_reviews import SafetyReviewConflict, grant_consent, request_review, review_state, withdraw_consent


router = APIRouter(prefix="/safety-escalations", tags=["safety-escalations"])


@router.get("/current", response_model=SafetyEscalationCurrentOut)
def get_current_escalation(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return materialize_current_escalation(db, user)


@router.post("/{escalation_id}/acknowledge", response_model=SafetyEscalationCurrentOut)
def acknowledge_current_escalation(escalation_id: int, _payload: SafetyEscalationAcknowledgeIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        return acknowledge_escalation(db, user, escalation_id)
    except SafetyEscalationConflict as error:
        db.rollback()
        raise HTTPException(status_code=409, detail={"code": "conflict", "message": str(error)}) from error


@router.get("/{escalation_id}/review", response_model=SafetyReviewStateOut)
def get_review_state(escalation_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        return review_state(db, user.id, escalation_id)
    except SafetyReviewConflict as error:
        raise HTTPException(status_code=409, detail={"code": "conflict", "message": str(error)}) from error


@router.post("/{escalation_id}/review-consent", response_model=SafetyReviewStateOut)
def consent_to_review(escalation_id: int, _payload: SafetyReviewConsentIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        return grant_consent(db, user, escalation_id)
    except SafetyReviewConflict as error:
        db.rollback()
        raise HTTPException(status_code=409, detail={"code": "conflict", "message": str(error)}) from error


@router.post("/{escalation_id}/review-request", response_model=SafetyReviewStateOut)
def create_review_request(escalation_id: int, _payload: SafetyReviewRequestIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        return request_review(db, user, escalation_id)
    except SafetyReviewConflict as error:
        db.rollback()
        raise HTTPException(status_code=409, detail={"code": "conflict", "message": str(error)}) from error


@router.delete("/{escalation_id}/review-consent", response_model=SafetyReviewStateOut)
def revoke_review_consent(escalation_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        return withdraw_consent(db, user, escalation_id)
    except SafetyReviewConflict as error:
        db.rollback()
        raise HTTPException(status_code=409, detail={"code": "conflict", "message": str(error)}) from error
