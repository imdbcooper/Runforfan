from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.db.session import get_db
from app.models import CoachMessage, User
from app.schemas.coach import CoachAssistantResponse, CoachTurnCreate, ConversationCreate, ConversationOut, MemoryUpdate, PreviewCreate
from app.schemas.common import CoachActionPreviewRequest as ExistingCoachActionPreviewRequest
from app.services.audit import log_audit_event
from app.services.auth import get_current_user
from app.services.coach_actions import CoachActionConflict, create_coach_action_preview
from app.services.conversational_coach import CoachConflict, authorize_preview_request, create_conversation, delete_memory, get_conversation, list_conversations, memory_out, submit_turn, update_memory
from app.services.coach_tools import authoritative_safety, build_coach_context
from app.services.readiness import ReadinessActionConflict, create_daily_readiness_action_preview
from app.services.weekly_review import WeeklyReviewConflict, create_weekly_strategy_preview


router = APIRouter(prefix="/coach", tags=["coach"])


def enabled() -> None:
    if not get_settings().coach_enabled:
        raise HTTPException(status_code=503, detail={"code": "coach_disabled", "message": "Conversational coach is disabled", "details": None})


def conflict(error: Exception) -> HTTPException:
    reason = getattr(error, "reason", "conflict")
    return HTTPException(status_code=409, detail={"code": "conflict", "message": str(error), "details": {"reason": reason}})


@router.post("/conversations", response_model=ConversationOut)
def post_conversation(payload: ConversationCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    enabled()
    return create_conversation(db, user, payload.surface)


@router.get("/conversations", response_model=list[ConversationOut])
def conversations(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    enabled()
    return list_conversations(db, user, limit, offset)


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
def conversation(conversation_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    enabled()
    result = get_conversation(db, user, conversation_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Conversation was not found")
    return result


@router.post("/conversations/{conversation_id}/turns")
def post_turn(conversation_id: str, payload: CoachTurnCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    enabled()
    try:
        return submit_turn(db, user, conversation_id, payload)
    except CoachConflict as error:
        db.rollback()
        if error.reason == "not_found":
            raise HTTPException(status_code=404, detail="Conversation was not found") from error
        if error.reason == "rate_limited":
            raise HTTPException(status_code=429, detail={"code": "rate_limited", "message": str(error), "details": None}) from error
        raise conflict(error) from error


@router.get("/memory")
def get_memory(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    enabled()
    return memory_out(db, user)


@router.put("/memory")
def put_memory(payload: MemoryUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    enabled()
    try:
        return update_memory(db, user, payload)
    except CoachConflict as error:
        db.rollback()
        raise conflict(error) from error


@router.delete("/memory", status_code=204)
def remove_memory(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    enabled()
    delete_memory(db, user)


@router.post("/conversations/{conversation_id}/previews")
def post_preview(conversation_id: str, payload: PreviewCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    enabled()
    message = db.scalar(select(CoachMessage).where(CoachMessage.id == payload.assistant_message_id, CoachMessage.user_id == user.id, CoachMessage.conversation_id == conversation_id, CoachMessage.role == "assistant"))
    if message is None:
        raise HTTPException(status_code=404, detail="Assistant message was not found")
    try:
        response = CoachAssistantResponse.model_validate(message.response_json or {})
        output = response.output
        if output.preview_request is None:
            raise CoachConflict("Assistant message has no preview handoff", "preview_missing")
        context = build_coach_context(db, user, conversation_id)
        ranks = {"normal": 0, "caution": 1, "medical_boundary": 2}
        current = authoritative_safety(context, "")
        safety = max((current, response.authoritative_safety_status), key=lambda item: ranks[item])
        authorize_preview_request(db, user, output.preview_request, safety, context)
        handoff = output.preview_request
        if handoff.kind == "readiness_action":
            result = create_daily_readiness_action_preview(db, user)
        elif handoff.kind == "weekly_strategy":
            result = create_weekly_strategy_preview(db, user, handoff.review_id, handoff.strategy)
        else:
            result = create_coach_action_preview(db, user, handoff.workout_id, ExistingCoachActionPreviewRequest(action=handoff.action, reason=handoff.reason, target_date=handoff.target_date))
        log_audit_event(db, user.id, "coach.preview_requested", "coach_message", message.id, {"conversation_id": conversation_id, "message_id": message.id, "kind": handoff.kind})
        db.commit()
        return {"kind": handoff.kind, "payload": result}
    except (CoachConflict, CoachActionConflict, ReadinessActionConflict, WeeklyReviewConflict) as error:
        db.rollback()
        raise conflict(error) from error
