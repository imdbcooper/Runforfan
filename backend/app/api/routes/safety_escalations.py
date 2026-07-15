from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import User
from app.schemas.common import SafetyEscalationAcknowledgeIn, SafetyEscalationCurrentOut
from app.services.auth import get_current_user
from app.services.safety_escalations import SafetyEscalationConflict, acknowledge_escalation, materialize_current_escalation


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
