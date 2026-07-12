from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import CoachingEvent
from app.services.plan_versions import json_safe


EVENT_TYPES = {
    "coach_action_applied",
    "illness_reported",
    "pain_reported",
    "readiness_checkin_saved",
    "workout_completed",
    "workout_completion_removed",
    "workout_feedback_saved",
    "workout_missed",
}
CATEGORIES = {"fact", "outcome", "user_input"}
SOURCES = {"activity_import", "coach_action_preview", "daily_readiness", "manual_activity_link", "manual_completion", "post_workout_feedback", "user"}


def record_coaching_event(
    db: Session,
    *,
    user_id: int,
    event_type: str,
    category: str,
    source: str,
    occurred_at: datetime | None = None,
    plan_id: int | None = None,
    workout_id: int | None = None,
    activity_id: int | None = None,
    checkin_id: int | None = None,
    feedback_id: int | None = None,
    correlation_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> CoachingEvent:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Unsupported coaching event type: {event_type}")
    if category not in CATEGORIES:
        raise ValueError(f"Unsupported coaching event category: {category}")
    if source not in SOURCES:
        raise ValueError(f"Unsupported coaching event source: {source}")
    event = CoachingEvent(
        user_id=user_id,
        event_type=event_type,
        event_version="v1",
        category=category,
        source=source,
        occurred_at=occurred_at or datetime.now(UTC),
        plan_id=plan_id,
        workout_id=workout_id,
        activity_id=activity_id,
        checkin_id=checkin_id,
        feedback_id=feedback_id,
        correlation_id=correlation_id,
        payload_json=json_safe(payload or {}),
    )
    db.add(event)
    return event
