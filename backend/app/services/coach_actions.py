import hashlib
import json
import secrets
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.orm.attributes import set_committed_value

from app.models import CoachActionPreview, TrainingPlan, TrainingPlanRecommendationAudit, TrainingPlanWorkout, User
from app.schemas.common import CoachActionPreviewRequest
from app.services.audit import log_audit_event
from app.services.coaching_events import record_coaching_event
from app.services.constraint_engine import CONSTRAINT_RULE_VERSION, validate_coach_action_target
from app.services.plan_versions import action_plan_snapshot, create_plan_version, json_safe, workout_snapshot
from app.services.planning import today_for_user, workout_is_hard, workout_to_dict


ACTION_PREVIEW_TTL_MINUTES = 10


class CoachActionConflict(ValueError):
    def __init__(self, message: str, reason: str):
        super().__init__(message)
        self.reason = reason


def state_fingerprint(value: dict[str, object]) -> str:
    encoded = json.dumps(json_safe(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_plan_context(db: Session, user: User, workout_id: int, *, lock: bool) -> tuple[TrainingPlan, TrainingPlanWorkout]:
    plan_id = db.scalar(
        select(TrainingPlanWorkout.plan_id)
        .join(TrainingPlan, TrainingPlan.id == TrainingPlanWorkout.plan_id)
        .where(TrainingPlanWorkout.id == workout_id, TrainingPlan.user_id == user.id, TrainingPlan.status == "active")
    )
    if plan_id is None:
        raise CoachActionConflict("Workout is not part of the current plan", "workout_not_found")
    plan_query = select(TrainingPlan).where(TrainingPlan.id == plan_id, TrainingPlan.user_id == user.id, TrainingPlan.status == "active")
    if lock:
        plan_query = plan_query.with_for_update()
    plan = db.scalar(plan_query.execution_options(populate_existing=True))
    if plan is None:
        raise CoachActionConflict("Workout is not part of the current plan", "workout_not_found")
    workouts_query = (
        select(TrainingPlanWorkout)
        .where(TrainingPlanWorkout.plan_id == plan.id)
        .options(
            selectinload(TrainingPlanWorkout.completed_activity),
            selectinload(TrainingPlanWorkout.feedback),
            selectinload(TrainingPlanWorkout.blocks),
        )
        .order_by(TrainingPlanWorkout.id.asc())
        .execution_options(populate_existing=True)
    )
    if lock:
        workouts_query = workouts_query.with_for_update()
    workouts = list(db.scalars(workouts_query))
    set_committed_value(plan, "workouts", workouts)
    workout = next((item for item in workouts if item.id == workout_id), None)
    if workout is None:
        raise CoachActionConflict("Workout is not part of the current plan", "workout_not_found")
    return plan, workout


def action_state_snapshot(user: User, plan: TrainingPlan, request: dict[str, object]) -> dict[str, object]:
    return json_safe({
        "rule_version": CONSTRAINT_RULE_VERSION,
        "user_id": user.id,
        "plan": {"id": plan.id, "status": plan.status, "updated_at": plan.updated_at},
        "request": request,
        "workouts": [workout_snapshot(item) for item in sorted(plan.workouts, key=lambda value: (value.week_index, value.day_index, value.id or 0))],
    })


def action_target(db: Session, user: User, plan: TrainingPlan, workout: TrainingPlanWorkout, request: dict[str, object]) -> tuple[dict[str, object], list[str]]:
    action = str(request.get("action") or "")
    raw_target_date = request.get("target_date")
    target_date = date.fromisoformat(raw_target_date) if isinstance(raw_target_date, str) else raw_target_date
    other_hard_dates = [
        item.scheduled_date
        for item in plan.workouts
        if item.id != workout.id and item.scheduled_date and item.status in {"planned", "rescheduled"} and workout_is_hard(item)
    ]
    scheduled_dates = [item.scheduled_date for item in plan.workouts if item.scheduled_date]
    last_scheduled_date = max(scheduled_dates) if scheduled_dates else today_for_user(db, user)
    final_calendar_week_end = last_scheduled_date + timedelta(days=6 - last_scheduled_date.weekday())
    plan_end_date = plan.target_date or final_calendar_week_end
    evaluation = validate_coach_action_target(
        action=action,
        target_date=target_date if isinstance(target_date, date) else None,
        current_date=workout.scheduled_date,
        status=workout.status,
        completed_activity_id=workout.completed_activity_id,
        workout_is_hard=workout_is_hard(workout),
        other_hard_workout_dates=other_hard_dates,
        reason=str(request.get("reason") or ""),
        today=today_for_user(db, user),
        plan_end_date=plan_end_date,
    )
    if not evaluation.allowed:
        raise CoachActionConflict(evaluation.message or "Coach action is blocked", evaluation.reason or "action_blocked")
    if action == "skip":
        return {"status": "skipped", "scheduled_date": workout.scheduled_date}, ["No missed volume will be moved to another workout."]
    facts = ["Hard-session spacing was checked against the current active plan."] if workout_is_hard(workout) else ["This workout is not classified as a hard session by the planning policy."]
    return {"status": "rescheduled", "scheduled_date": target_date}, facts


def action_changes(workout: TrainingPlanWorkout, target: dict[str, object]) -> list[dict[str, object]]:
    before = workout_snapshot(workout)
    return [
        {"field": field, "before": before.get(field), "after": json_safe(target.get(field))}
        for field in ("scheduled_date", "status")
        if before.get(field) != json_safe(target.get(field))
    ]


def weekly_effect(plan: TrainingPlan, workout: TrainingPlanWorkout, action: str) -> dict[str, object]:
    active_statuses = {"planned", "rescheduled"}
    week = [item for item in plan.workouts if item.week_index == workout.week_index and item.status in active_statuses]
    distance_before = round(sum(item.distance_km or 0 for item in week), 2)
    duration_before = sum(item.duration_seconds or 0 for item in week)
    active_before = workout.status in active_statuses
    active_after = action == "reschedule"
    distance_delta = (workout.distance_km or 0) * (int(active_after) - int(active_before))
    duration_delta = (workout.duration_seconds or 0) * (int(active_after) - int(active_before))
    return {
        "planned_distance_km_before": distance_before,
        "planned_distance_km_after": round(distance_before + distance_delta, 2),
        "planned_duration_seconds_before": duration_before,
        "planned_duration_seconds_after": duration_before + duration_delta,
    }


def calendar_week_effects(plan: TrainingPlan, workout: TrainingPlanWorkout, target: dict[str, object]) -> list[dict[str, object]]:
    target_date = target.get("scheduled_date")
    impacted_dates = {item for item in (workout.scheduled_date, target_date) if isinstance(item, date)}
    week_starts = sorted({item - timedelta(days=item.weekday()) for item in impacted_dates})
    effects = []
    active_statuses = {"planned", "rescheduled"}
    for week_start in week_starts:
        week_end = week_start + timedelta(days=6)
        before_workouts = [
            item for item in plan.workouts
            if item.scheduled_date and week_start <= item.scheduled_date <= week_end and item.status in active_statuses
        ]
        after_workouts = []
        for item in plan.workouts:
            item_date = target_date if item.id == workout.id else item.scheduled_date
            item_status = target.get("status") if item.id == workout.id else item.status
            if isinstance(item_date, date) and week_start <= item_date <= week_end and item_status in active_statuses:
                after_workouts.append(item)
        effects.append({
            "week_start": week_start,
            "week_end": week_end,
            "planned_distance_km_before": round(sum(item.distance_km or 0 for item in before_workouts), 2),
            "planned_distance_km_after": round(sum(item.distance_km or 0 for item in after_workouts), 2),
            "planned_duration_seconds_before": sum(item.duration_seconds or 0 for item in before_workouts),
            "planned_duration_seconds_after": sum(item.duration_seconds or 0 for item in after_workouts),
        })
    return effects


def build_preview(preview_id: str, expires_at: datetime, plan: TrainingPlan, workout: TrainingPlanWorkout, request: dict[str, object], target: dict[str, object], facts: list[str]) -> dict[str, object]:
    action = str(request["action"])
    summary = "Тренировка будет отменена без переноса пропущенного объёма." if action == "skip" else "Тренировка будет перенесена после проверки интервалов между тяжёлыми сессиями."
    return json_safe({
        "preview_id": preview_id,
        "expires_at": expires_at,
        "action": action,
        "rule_version": CONSTRAINT_RULE_VERSION,
        "reason": request["reason"],
        "target_date": request.get("target_date"),
        "workout": workout_to_dict(workout),
        "changes": action_changes(workout, target),
        "weekly_effect": weekly_effect(plan, workout, action),
        "calendar_week_effects": calendar_week_effects(plan, workout, target),
        "constraint_facts": facts,
        "summary": summary,
        "target": target,
    })


def create_coach_action_preview(db: Session, user: User, workout_id: int, payload: CoachActionPreviewRequest) -> dict[str, object]:
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    plan, workout = load_plan_context(db, user, workout_id, lock=True)
    request = json_safe(payload.model_dump())
    target, facts = action_target(db, user, plan, workout, request)
    preview_id = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(minutes=ACTION_PREVIEW_TTL_MINUTES)
    preview_snapshot = build_preview(preview_id, expires_at, plan, workout, request, target, facts)
    preview = CoachActionPreview(
        id=preview_id,
        user_id=user.id,
        plan_id=plan.id,
        workout_id=workout.id,
        action=payload.action,
        rule_version=CONSTRAINT_RULE_VERSION,
        request_snapshot=request,
        preview_snapshot=preview_snapshot,
        state_fingerprint=state_fingerprint(action_state_snapshot(user, plan, request)),
        expires_at=expires_at,
    )
    db.add(preview)
    db.commit()
    return {key: value for key, value in preview_snapshot.items() if key != "target"}


def load_preview(db: Session, user: User, preview_id: str) -> CoachActionPreview | None:
    return db.scalar(
        select(CoachActionPreview)
        .where(CoachActionPreview.id == preview_id, CoachActionPreview.user_id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def find_preview(db: Session, user: User, preview_id: str) -> CoachActionPreview | None:
    return db.scalar(
        select(CoachActionPreview)
        .where(CoachActionPreview.id == preview_id, CoachActionPreview.user_id == user.id)
        .execution_options(populate_existing=True)
    )


def apply_coach_action_preview(db: Session, user: User, preview_id: str) -> dict[str, object]:
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    preview = find_preview(db, user, preview_id)
    now = datetime.now(UTC)
    if preview is None:
        raise CoachActionConflict("Action preview is invalid, expired, or no longer applicable", "preview_invalid_or_expired")
    if preview.applied_at is not None and preview.applied_response_json:
        return {**preview.applied_response_json, "status": "already_applied"}
    if preview.expires_at < now:
        raise CoachActionConflict("Action preview is invalid, expired, or no longer applicable", "preview_invalid_or_expired")
    plan, workout = load_plan_context(db, user, preview.workout_id, lock=True)
    preview = load_preview(db, user, preview_id)
    if preview is None:
        raise CoachActionConflict("Action preview is invalid, expired, or no longer applicable", "preview_invalid_or_expired")
    if preview.applied_at is not None and preview.applied_response_json:
        return {**preview.applied_response_json, "status": "already_applied"}
    if plan.id != preview.plan_id:
        raise CoachActionConflict("Action preview is stale; create a new preview", "preview_stale")
    target, _facts = action_target(db, user, plan, workout, preview.request_snapshot)
    if state_fingerprint(action_state_snapshot(user, plan, preview.request_snapshot)) != preview.state_fingerprint or json_safe(target) != preview.preview_snapshot.get("target"):
        raise CoachActionConflict("Action preview is stale; create a new preview", "preview_stale")

    changes = list(preview.preview_snapshot.get("changes") or [])
    pre_snapshot = action_plan_snapshot(plan)
    workout.scheduled_date = target.get("scheduled_date")
    workout.status = str(target["status"])
    db.flush()
    recommendation_audit = TrainingPlanRecommendationAudit(
        user_id=user.id,
        plan_id=plan.id,
        action="apply_coach_action",
        status="applied",
        recommendations_snapshot={"action": preview.action, "rule_version": preview.rule_version, "request": preview.request_snapshot},
        preview_changes={"preview_id": preview.id, "changes": changes},
        applied_changes={"preview_id": preview.id, "changes": changes},
    )
    db.add(recommendation_audit)
    db.flush()
    version = create_plan_version(
        db,
        user,
        plan,
        f"coach_action_{preview.action}",
        f"Applied {preview.action} to workout #{workout.id}",
        pre_snapshot=pre_snapshot,
    )
    db.flush()
    event = record_coaching_event(
        db,
        user_id=user.id,
        event_type="coach_action_applied",
        category="outcome",
        source="coach_action_preview",
        plan_id=plan.id,
        workout_id=workout.id,
        correlation_id=preview.id,
        payload={"action": preview.action, "reason": preview.request_snapshot.get("reason"), "notes": preview.request_snapshot.get("notes"), "rule_version": preview.rule_version, "changes": changes},
    )
    db.flush()
    audit_event = log_audit_event(
        db,
        user.id,
        "coach_action_applied",
        "training_plan_workout",
        workout.id,
        {"preview_id": preview.id, "plan_id": plan.id, "action": preview.action, "rule_version": preview.rule_version, "recommendation_audit_id": recommendation_audit.id, "plan_version_id": version.id, "coaching_event_id": event.id, "changes": changes},
    )
    db.flush()
    response = json_safe({
        "status": "applied",
        "preview_id": preview.id,
        "action": preview.action,
        "workout": workout_to_dict(workout),
        "plan_version_id": version.id,
        "plan_version_number": version.version_number,
        "recommendation_audit_id": recommendation_audit.id,
        "audit_log_id": audit_event.id,
        "coaching_event_id": event.id,
        "summary": preview.preview_snapshot["summary"],
    })
    preview.applied_at = now
    preview.recommendation_audit_id = recommendation_audit.id
    preview.plan_version_id = version.id
    preview.audit_log_id = audit_event.id
    preview.coaching_event_id = event.id
    preview.applied_response_json = response
    db.commit()
    return response
