from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import RunningGoal, TrainingPlan, TrainingPlanWorkout, User
from app.schemas.common import GoalCompleteIn, GoalCreate, GoalUpdate
from app.services.analytics import user_analytics
from app.services.performance import performance_predictions, performance_vdot
from app.services.planning import plan_to_dict, today_for_user


GOAL_STATUSES = {"active", "paused", "completed", "missed", "archived"}
GOAL_FIELDS = {
    "title",
    "goal_type",
    "target_value",
    "unit",
    "period_start",
    "period_end",
    "race_distance_km",
    "target_date",
    "target_time_seconds",
    "priority",
    "course_notes",
    "training_plan_id",
    "reason",
    "status",
}


def normalize_goal_type(goal_type: str | None) -> str:
    legacy = {
        "custom": "custom_habit",
        "workout_count": "weekly_consistency",
        "longest_run": "long_run",
    }
    normalized = legacy.get(goal_type or "", goal_type or "custom_habit")
    if normalized not in {"race", "weekly_consistency", "monthly_distance", "long_run", "custom_habit", "health"}:
        return "custom_habit"
    return normalized


def validate_goal_data(data: dict[str, Any]) -> None:
    goal_type = normalize_goal_type(str(data.get("goal_type") or "custom_habit"))
    if goal_type == "race" and (data.get("race_distance_km") is None or data.get("target_date") is None):
        raise ValueError("Race goals require race_distance_km and target_date")
    status = data.get("status")
    if status is not None and status not in GOAL_STATUSES:
        raise ValueError("Invalid goal status")
    if data.get("period_start") and data.get("period_end") and data["period_start"] > data["period_end"]:
        raise ValueError("period_start must be before period_end")


def goal_query(user: User):
    return (
        select(RunningGoal)
        .where(RunningGoal.user_id == user.id)
        .options(selectinload(RunningGoal.training_plan).selectinload(TrainingPlan.workouts).selectinload(TrainingPlanWorkout.completed_activity))
    )


def get_goal(db: Session, user: User, goal_id: int) -> RunningGoal:
    goal = db.scalar(goal_query(user).where(RunningGoal.id == goal_id))
    if goal is None:
        raise ValueError("Goal not found")
    return goal


def ensure_plan_owner(db: Session, user: User, training_plan_id: int | None) -> None:
    if training_plan_id is None:
        return
    exists = db.scalar(select(TrainingPlan.id).where(TrainingPlan.id == training_plan_id, TrainingPlan.user_id == user.id))
    if exists is None:
        raise ValueError("Training plan not found")


def apply_goal_fields(goal: RunningGoal, data: dict[str, Any]) -> None:
    for field in GOAL_FIELDS:
        if field in data:
            value = data[field]
            if field == "goal_type":
                value = normalize_goal_type(value)
            setattr(goal, field, value)


def create_goal(db: Session, user: User, payload: GoalCreate) -> RunningGoal:
    data = payload.model_dump()
    data["goal_type"] = normalize_goal_type(data.get("goal_type"))
    validate_goal_data(data)
    ensure_plan_owner(db, user, data.get("training_plan_id"))
    goal = RunningGoal(user_id=user.id, **data)
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return get_goal(db, user, goal.id)


def update_goal(db: Session, user: User, goal: RunningGoal, payload: GoalUpdate) -> RunningGoal:
    data = payload.model_dump(exclude_unset=True)
    merged = {field: getattr(goal, field) for field in GOAL_FIELDS if hasattr(goal, field)}
    merged.update(data)
    merged["goal_type"] = normalize_goal_type(merged.get("goal_type"))
    validate_goal_data(merged)
    ensure_plan_owner(db, user, merged.get("training_plan_id"))
    apply_goal_fields(goal, data)
    db.commit()
    db.refresh(goal)
    return get_goal(db, user, goal.id)


def complete_goal(db: Session, user: User, goal: RunningGoal, payload: GoalCompleteIn) -> RunningGoal:
    goal.status = payload.status
    if payload.reason:
        goal.reason = payload.reason
    db.commit()
    db.refresh(goal)
    return get_goal(db, user, goal.id)


def delete_goal(db: Session, goal: RunningGoal) -> int:
    goal_id = goal.id
    db.delete(goal)
    db.commit()
    return goal_id


def active_matching_plan(db: Session, user: User, goal: RunningGoal) -> TrainingPlan | None:
    if goal.training_plan:
        return goal.training_plan
    if goal.goal_type != "race" or goal.race_distance_km is None:
        return None
    query = (
        select(TrainingPlan)
        .where(TrainingPlan.user_id == user.id, TrainingPlan.status.in_(("active", "draft")))
        .options(selectinload(TrainingPlan.workouts).selectinload(TrainingPlanWorkout.completed_activity))
        .order_by(TrainingPlan.status.asc(), TrainingPlan.created_at.desc(), TrainingPlan.id.desc())
    )
    candidates = list(db.scalars(query))
    for plan in candidates:
        same_distance = plan.race_distance_km is not None and abs(plan.race_distance_km - goal.race_distance_km) <= max(0.2, goal.race_distance_km * 0.02)
        same_date = goal.target_date is None or plan.target_date is None or abs((plan.target_date - goal.target_date).days) <= 14
        if same_distance and same_date:
            return plan
    return None


def predicted_range_for_goal(goal: RunningGoal, predictions: list[dict[str, Any]]) -> dict[str, Any] | None:
    if goal.goal_type != "race" or goal.race_distance_km is None:
        return None
    prediction = min(predictions, key=lambda item: abs(float(item["target_distance_km"]) - float(goal.race_distance_km)), default=None)
    if prediction is None:
        return None
    if abs(float(prediction["target_distance_km"]) - float(goal.race_distance_km)) > max(0.2, goal.race_distance_km * 0.02):
        return None
    predicted = prediction.get("predicted_duration_seconds")
    if predicted is None:
        return None
    margin = {"high": 0.03, "medium": 0.06}.get(str(prediction.get("confidence")), 0.1)
    lower = round(int(predicted) * (1 - margin))
    upper = round(int(predicted) * (1 + margin))
    return {
        "target_distance_km": prediction["target_distance_km"],
        "predicted_duration_seconds": int(predicted),
        "lower_seconds": lower,
        "upper_seconds": upper,
        "confidence": prediction.get("confidence"),
        "source": prediction.get("source_result_name"),
        "target_delta_seconds": int(predicted) - goal.target_time_seconds if goal.target_time_seconds else None,
        "warnings": prediction.get("warnings") or [],
    }


def progress_percentage(done: float, target: float | None) -> float:
    if not target or target <= 0:
        return 0.0
    return round(max(0.0, min(1.0, done / target)), 2)


def race_readiness(goal: RunningGoal, plan_summary: dict[str, Any] | None, predicted_range: dict[str, Any] | None) -> str:
    if goal.status in {"completed", "missed", "archived", "paused"}:
        return goal.status
    adherence = ((plan_summary or {}).get("adherence") or {}) if plan_summary else {}
    if adherence and float(adherence.get("completion_rate") or 0) < 0.7:
        return "at_risk"
    if predicted_range and goal.target_time_seconds:
        if int(predicted_range["upper_seconds"]) <= goal.target_time_seconds:
            return "on_track"
        if int(predicted_range["lower_seconds"]) > goal.target_time_seconds:
            return "at_risk"
        return "watch"
    if plan_summary:
        return "watch"
    return "unknown"


def goal_progress(goal: RunningGoal, analytics: dict[str, Any], plan_summary: dict[str, Any] | None, predicted_range: dict[str, Any] | None) -> dict[str, Any]:
    goal_type = normalize_goal_type(goal.goal_type)
    if goal.status in {"completed", "missed", "archived", "paused"}:
        percentage = 1.0 if goal.status == "completed" else 0.0
        return {"metric": goal_type, "value": percentage, "target": 1.0, "percentage": percentage, "readiness": goal.status}
    if goal_type == "race":
        adherence = ((plan_summary or {}).get("adherence") or {}) if plan_summary else {}
        return {
            "metric": "race_readiness",
            "value": round(float(adherence.get("completion_rate") or 0), 2) if adherence else None,
            "target": 1.0,
            "percentage": round(float(adherence.get("completion_rate") or 0), 2) if adherence else 0,
            "readiness": race_readiness(goal, plan_summary, predicted_range),
        }
    if goal_type == "monthly_distance":
        value = float(analytics.get("total_distance_km") or 0)
        target = goal.target_value
        return {"metric": "distance_km", "value": round(value, 2), "target": target, "percentage": progress_percentage(value, target), "readiness": "on_track" if progress_percentage(value, target) >= 0.8 else "watch"}
    if goal_type == "weekly_consistency":
        value = float(((analytics.get("consistency") or {}).get("training_days_per_week")) or 0)
        target = goal.target_value
        return {"metric": "training_days_per_week", "value": round(value, 2), "target": target, "percentage": progress_percentage(value, target), "readiness": "on_track" if progress_percentage(value, target) >= 0.8 else "watch"}
    if goal_type == "long_run":
        value = float(analytics.get("longest_distance_km") or 0)
        target = goal.target_value or goal.race_distance_km
        return {"metric": "longest_run_km", "value": round(value, 2), "target": target, "percentage": progress_percentage(value, target), "readiness": "on_track" if progress_percentage(value, target) >= 0.8 else "watch"}
    percentage = 1.0 if goal.status == "completed" else 0.0
    return {"metric": goal_type, "value": percentage, "target": 1.0, "percentage": percentage, "readiness": goal.status}


def goal_milestones(goal: RunningGoal, analytics: dict[str, Any], today: date) -> list[dict[str, Any]]:
    if goal.goal_type == "race" and goal.target_date:
        distance = goal.race_distance_km or 0
        longest_target = round(max(5.0, distance * (0.75 if distance >= 21 else 0.6)), 1) if distance else None
        longest_done = float(analytics.get("longest_distance_km") or 0)
        return [
            {"title": "Tune-up race", "due_date": goal.target_date - timedelta(days=28), "status": "due" if today <= goal.target_date - timedelta(days=28) else "check", "target": "5K/10K controlled race"},
            {"title": "Threshold test", "due_date": goal.target_date - timedelta(days=21), "status": "due" if today <= goal.target_date - timedelta(days=21) else "check", "target": "20-30 min controlled test"},
            {"title": "Longest run", "due_date": goal.target_date - timedelta(days=14), "status": "completed" if longest_target and longest_done >= longest_target else "pending", "target": longest_target, "value": round(longest_done, 1)},
        ]
    return [{"title": "Progress check-in", "due_date": goal.period_end or goal.target_date, "status": goal.status, "target": goal.target_value}]


def goal_plan_summary(plan: TrainingPlan | None) -> dict[str, Any] | None:
    if plan is None:
        return None
    data = plan_to_dict(plan)
    return {
        "id": data["id"],
        "title": data["title"],
        "status": data["status"],
        "goal_type": data["goal_type"],
        "race_distance_km": data["race_distance_km"],
        "target_date": data["target_date"],
        "adherence": data["adherence"],
    }


def goal_to_dict(db: Session, user: User, goal: RunningGoal, predictions: list[dict[str, Any]] | None = None, fitness: dict[str, Any] | None = None, today: date | None = None) -> dict[str, Any]:
    current_day = today or today_for_user(db, user)
    analytics = user_analytics(db, user, goal.period_start, goal.period_end)
    plan_summary = goal_plan_summary(active_matching_plan(db, user, goal))
    predictions = performance_predictions(db, user) if predictions is None else predictions
    fitness = performance_vdot(db, user) if fitness is None else fitness
    predicted_range = predicted_range_for_goal(goal, predictions)
    return {
        "id": goal.id,
        "title": goal.title,
        "goal_type": normalize_goal_type(goal.goal_type),
        "target_value": goal.target_value,
        "unit": goal.unit,
        "period_start": goal.period_start,
        "period_end": goal.period_end,
        "race_distance_km": goal.race_distance_km,
        "target_date": goal.target_date,
        "target_time_seconds": goal.target_time_seconds,
        "priority": goal.priority,
        "course_notes": goal.course_notes,
        "training_plan_id": goal.training_plan_id,
        "reason": goal.reason,
        "status": goal.status,
        "created_at": goal.created_at,
        "updated_at": goal.updated_at,
        "progress": goal_progress(goal, analytics, plan_summary, predicted_range),
        "milestones": goal_milestones(goal, analytics, current_day),
        "plan": plan_summary,
        "current_fitness": fitness,
        "predicted_time_range": predicted_range,
    }


def list_goals(db: Session, user: User) -> list[dict[str, Any]]:
    goals = list(db.scalars(goal_query(user).order_by(RunningGoal.status.asc(), RunningGoal.target_date.asc().nullslast(), RunningGoal.created_at.desc())))
    predictions = performance_predictions(db, user)
    fitness = performance_vdot(db, user)
    current_day = today_for_user(db, user)
    return [goal_to_dict(db, user, goal, predictions, fitness, current_day) for goal in goals]
