from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import TrainingPlan, TrainingPlanVersion, TrainingPlanWorkout, User


def json_safe(value: Any) -> Any:
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


def workout_snapshot(workout: TrainingPlanWorkout) -> dict[str, Any]:
    return json_safe({
        "id": workout.id,
        "week_index": workout.week_index,
        "day_index": workout.day_index,
        "scheduled_date": workout.scheduled_date,
        "status": workout.status,
        "completed_activity_id": workout.completed_activity_id,
        "workout_type": workout.workout_type,
        "title": workout.title,
        "distance_km": workout.distance_km,
        "duration_seconds": workout.duration_seconds,
        "intensity": workout.intensity,
        "description": workout.description,
    })


def plan_snapshot(plan: TrainingPlan) -> dict[str, Any]:
    workouts = sorted(plan.workouts, key=lambda workout: (workout.week_index, workout.day_index, workout.id or 0))
    return json_safe({
        "id": plan.id,
        "user_id": plan.user_id,
        "title": plan.title,
        "goal_type": plan.goal_type,
        "race_distance_km": plan.race_distance_km,
        "target_date": plan.target_date,
        "target_time_seconds": plan.target_time_seconds,
        "available_days_per_week": plan.available_days_per_week,
        "status": plan.status,
        "explanation": plan.explanation,
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
        "workouts": [workout_snapshot(workout) for workout in workouts],
    })


def next_plan_version_number(db: Session, plan_id: int) -> int:
    db.scalar(select(TrainingPlan.id).where(TrainingPlan.id == plan_id).with_for_update())
    current = db.scalar(select(func.max(TrainingPlanVersion.version_number)).where(TrainingPlanVersion.plan_id == plan_id))
    return int(current or 0) + 1


def create_plan_version(db: Session, user: User, plan: TrainingPlan, reason: str, summary: str | None = None) -> TrainingPlanVersion:
    db.flush()
    version = TrainingPlanVersion(
        user_id=user.id,
        plan_id=plan.id,
        version_number=next_plan_version_number(db, plan.id),
        reason=reason,
        summary=summary,
        snapshot_json=plan_snapshot(plan),
    )
    db.add(version)
    return version
