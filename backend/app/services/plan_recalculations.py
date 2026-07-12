import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Activity, PlanRecalculationRequest, TrainingPlan, TrainingPlanWorkout, User
from app.services.coaching_events import record_coaching_event
from app.services.constraint_engine import CONSTRAINT_RULE_VERSION
from app.services.plan_versions import json_safe, plan_snapshot


RECALCULATION_RULE_VERSION = "plan-recalculation-v1"


def assessment_fingerprint(value: dict[str, object]) -> str:
    encoded = json.dumps(json_safe(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def user_recalculation_lock_query(user_id: int):
    # SQLAlchemy's key_share=True compiles to PostgreSQL FOR NO KEY UPDATE
    # unless read=True is also set. This remains compatible with FK KEY SHARE
    # locks held by newly inserted activities while serializing same-user work.
    return select(User.id).where(User.id == user_id).with_for_update(key_share=True)


def active_plan_for_recalculation(db: Session, user: User) -> TrainingPlan | None:
    return db.scalar(
        select(TrainingPlan)
        .where(TrainingPlan.user_id == user.id, TrainingPlan.status == "active")
        .options(
            selectinload(TrainingPlan.workouts).selectinload(TrainingPlanWorkout.completed_activity),
            selectinload(TrainingPlan.workouts).selectinload(TrainingPlanWorkout.feedback),
            selectinload(TrainingPlan.workouts).selectinload(TrainingPlanWorkout.blocks),
        )
        .order_by(TrainingPlan.id.desc())
        .limit(1)
    )


def request_plan_recalculation(
    db: Session,
    user: User,
    *,
    trigger_type: str,
    source_key: str,
    source_event_id: int | None = None,
    plan: TrainingPlan | None = None,
) -> PlanRecalculationRequest:
    db.scalar(user_recalculation_lock_query(user.id))
    existing = db.scalar(
        select(PlanRecalculationRequest).where(
            PlanRecalculationRequest.user_id == user.id,
            PlanRecalculationRequest.source_key == source_key,
        )
    )
    if existing is not None:
        return existing

    plan = plan or active_plan_for_recalculation(db, user)
    if plan is None:
        assessment = {
            "rule_version": RECALCULATION_RULE_VERSION,
            "constraint_rule_version": CONSTRAINT_RULE_VERSION,
            "status": "no_current_plan",
            "summary": "No active plan is available for recalculation.",
            "recommendations": [],
            "preview_required": True,
            "mutation_applied": False,
        }
        input_value = {"user_id": user.id, "plan": None, "trigger_type": trigger_type, "source_key": source_key}
    else:
        from app.services.planning import plan_adjustment_recommendations

        recommendation = plan_adjustment_recommendations(db, user, plan)
        assessment = {
            "rule_version": RECALCULATION_RULE_VERSION,
            "constraint_rule_version": CONSTRAINT_RULE_VERSION,
            "status": recommendation["status"],
            "summary": recommendation["summary"],
            "adaptation_summary": recommendation.get("adaptation_summary"),
            "risk_before": recommendation.get("risk_before"),
            "risk_after": recommendation.get("risk_after"),
            "recommendations": recommendation.get("recommendations") or [],
            "preview_required": True,
            "mutation_applied": False,
        }
        input_value = {
            "user_id": user.id,
            "plan": plan_snapshot(plan),
            "trigger_type": trigger_type,
            "source_key": source_key,
            "assessment": assessment,
        }
    request = PlanRecalculationRequest(
        user_id=user.id,
        plan_id=plan.id if plan else None,
        trigger_type=trigger_type,
        source_key=source_key,
        source_event_id=source_event_id,
        input_fingerprint=assessment_fingerprint(input_value),
        status="completed",
        assessment_json=json_safe(assessment),
        completed_at=datetime.now(UTC),
    )
    db.add(request)
    return request


def latest_plan_recalculation(db: Session, user: User) -> PlanRecalculationRequest | None:
    return db.scalar(
        select(PlanRecalculationRequest)
        .where(PlanRecalculationRequest.user_id == user.id)
        .order_by(PlanRecalculationRequest.requested_at.desc(), PlanRecalculationRequest.id.desc())
        .limit(1)
    )


def record_activity_import_recalculation(
    db: Session,
    user: User,
    activity: Activity,
    *,
    source_key: str,
    matched_workout: TrainingPlanWorkout | None = None,
) -> PlanRecalculationRequest:
    db.scalar(user_recalculation_lock_query(user.id))
    existing = db.scalar(
        select(PlanRecalculationRequest).where(
            PlanRecalculationRequest.user_id == user.id,
            PlanRecalculationRequest.source_key == source_key,
        )
    )
    if existing is not None:
        return existing
    event = record_coaching_event(
        db,
        user_id=user.id,
        event_type="activity_imported",
        category="fact",
        source="activity_import",
        occurred_at=getattr(activity, "started_at", None) or datetime.now(UTC),
        plan_id=matched_workout.plan_id if matched_workout else None,
        workout_id=matched_workout.id if matched_workout else None,
        activity_id=activity.id,
        correlation_id=source_key,
        payload={
            "distance_km": getattr(activity, "distance_km", None),
            "duration_seconds": getattr(activity, "duration_seconds", None),
            "matched_workout_id": matched_workout.id if matched_workout else None,
        },
    )
    db.flush()
    return request_plan_recalculation(
        db,
        user,
        trigger_type="activity_imported",
        source_key=source_key,
        source_event_id=event.id,
        plan=matched_workout.plan if matched_workout and matched_workout.plan else None,
    )
