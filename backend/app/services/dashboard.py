from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import Activity, ActivityScreenshot, ImportBatch, LlmProviderSetting, TrainingPlan, TrainingPlanWorkout, User
from app.services.analytics import user_analytics
from app.services.planning import adherence_summary, plan_adjustment_recommendations, today_for_user, workout_to_dict
from app.services.profile import get_or_create_profile, profile_completeness, safety_check


PENDING_IMPORT_STATUSES = (
    "uploaded",
    "recognizing",
    "recognized_candidate",
    "pending_confirmation",
    "validation_failed",
    "recognition_failed",
    "rejected_no_llm_template",
)


def plan_load_options():
    return (
        selectinload(TrainingPlan.workouts).selectinload(TrainingPlanWorkout.completed_activity),
        selectinload(TrainingPlan.workouts).selectinload(TrainingPlanWorkout.feedback),
        selectinload(TrainingPlan.workouts).selectinload(TrainingPlanWorkout.blocks),
    )


def active_training_plan(db: Session, user: User) -> TrainingPlan | None:
    return db.scalar(
        select(TrainingPlan)
        .where(TrainingPlan.user_id == user.id, TrainingPlan.status == "active")
        .options(*plan_load_options())
        .order_by(TrainingPlan.created_at.desc(), TrainingPlan.id.desc())
        .limit(1)
    )


def week_bounds(day: date) -> tuple[date, date]:
    week_start = day - timedelta(days=day.weekday())
    return week_start, week_start + timedelta(days=6)


def next_pending_workout(workouts: list[TrainingPlanWorkout], today: date) -> TrainingPlanWorkout | None:
    pending = [
        workout
        for workout in workouts
        if workout.scheduled_date and workout.scheduled_date >= today and workout.status in {"planned", "rescheduled"}
    ]
    if pending:
        return pending[0]
    upcoming = [workout for workout in workouts if workout.scheduled_date and workout.scheduled_date >= today]
    return upcoming[0] if upcoming else None


def current_week_for_plan(db: Session, user: User, plan: TrainingPlan | None) -> dict[str, object]:
    today = today_for_user(db, user)
    week_start, week_end = week_bounds(today)
    base = {
        "week_start": week_start,
        "week_end": week_end,
        "today": today,
    }
    if plan is None:
        return {
            **base,
            "plan_id": None,
            "plan_title": None,
            "plan_status": None,
            "week_index": None,
            "status": "no_plan",
            "message": "Create an active plan to see today's workout and weekly adherence.",
            "workouts": [],
            "adherence": None,
            "today_workout": None,
            "next_workout": None,
        }

    workouts = sorted(plan.workouts, key=lambda workout: (workout.scheduled_date or date.max, workout.week_index, workout.day_index, workout.id))
    current_workouts = [workout for workout in workouts if workout.scheduled_date and week_start <= workout.scheduled_date <= week_end]
    today_workouts = [workout for workout in current_workouts if workout.scheduled_date == today]
    next_workout = next_pending_workout(workouts, today)
    week_index = current_workouts[0].week_index if current_workouts else None
    status = "active"
    message = "Follow the current week plan and keep feedback updated after each workout."
    if not current_workouts and next_workout:
        status = "waiting"
        message = f"No workouts in this calendar week. Next planned workout is scheduled for {next_workout.scheduled_date}."
    elif not current_workouts:
        status = "complete"
        message = "No remaining scheduled workouts found for the active plan."

    return {
        **base,
        "plan_id": plan.id,
        "plan_title": plan.title,
        "plan_status": plan.status,
        "week_index": week_index,
        "status": status,
        "message": message,
        "workouts": [workout_to_dict(workout) for workout in current_workouts],
        "adherence": adherence_summary(current_workouts) if current_workouts else None,
        "today_workout": workout_to_dict(today_workouts[0]) if today_workouts else None,
        "next_workout": workout_to_dict(next_workout) if next_workout else None,
    }


def current_week_for_user(db: Session, user: User) -> dict[str, object]:
    return current_week_for_plan(db, user, active_training_plan(db, user))


def pending_import_count(db: Session, user: User) -> int:
    return int(db.scalar(
        select(func.count())
        .select_from(ImportBatch)
        .where(ImportBatch.user_id == user.id, ImportBatch.status.in_(PENDING_IMPORT_STATUSES))
    ) or 0)


def active_provider_count(db: Session, user: User) -> int:
    return int(db.scalar(
        select(func.count())
        .select_from(LlmProviderSetting)
        .where(LlmProviderSetting.user_id == user.id, LlmProviderSetting.is_active.is_(True))
    ) or 0)


def recent_activities(db: Session, user: User, limit: int = 6) -> list[Activity]:
    return list(db.scalars(
        select(Activity)
        .where(Activity.user_id == user.id)
        .options(
            selectinload(Activity.segments),
            selectinload(Activity.split_blocks),
            selectinload(Activity.workout_blocks),
            selectinload(Activity.derived_metrics),
            selectinload(Activity.screenshots).selectinload(ActivityScreenshot.source),
        )
        .order_by(Activity.started_at.desc().nullslast(), Activity.id.desc())
        .limit(limit)
    ))


def readiness_from_signals(current_week: dict[str, object], safety: dict[str, object], recommendations: dict[str, object] | None) -> dict[str, object]:
    status = "ok"
    factors: list[str] = []
    adherence = current_week.get("adherence") if isinstance(current_week.get("adherence"), dict) else None
    if safety.get("conservative_mode"):
        status = "watch"
        factors.append("conservative mode or safety limits are active")
    for warning in safety.get("warnings") or []:
        status = "watch"
        factors.append(str(warning))
    if adherence:
        missed = int(adherence.get("missed_workouts") or 0) + int(adherence.get("skipped_workouts") or 0)
        if missed:
            status = "risk" if missed >= 2 else "watch"
            factors.append(f"{missed} missed or skipped workouts this week")
    for workout in current_week.get("workouts") or []:
        score = workout.get("execution_score") if isinstance(workout, dict) else None
        if isinstance(score, dict) and score.get("subjective_risk") == "high":
            status = "risk"
            factors.append(f"high subjective risk on workout #{workout.get('id')}")
    if recommendations:
        recommendation_status = recommendations.get("status")
        if recommendation_status == "adjust":
            status = "risk"
            factors.append(str(recommendations.get("summary") or "coach recommends adjustment"))
        elif recommendation_status == "watch" and status == "ok":
            status = "watch"
            factors.append(str(recommendations.get("summary") or "coach recommends watching load"))
    message = {
        "ok": "No major readiness risks detected from plan, profile and recent feedback.",
        "watch": "Keep the next workouts controlled and review the listed factors before adding load.",
        "risk": "Reduce intensity or review the plan before the next hard session.",
    }[status]
    return {"status": status, "message": message, "factors": factors[:6]}


def dashboard_alerts(
    current_week: dict[str, object],
    completeness: dict[str, object],
    safety: dict[str, object],
    pending_imports: int,
    provider_count: int,
    recommendations: dict[str, object] | None,
) -> list[dict[str, object]]:
    alerts: list[dict[str, object]] = []
    if current_week.get("status") == "no_plan":
        alerts.append({
            "severity": "warning",
            "title": "No active plan",
            "message": "Create or activate a plan to show today's workout and adherence.",
            "action": "planning",
        })
    if float(completeness.get("score") or 0) < 0.8:
        missing = ", ".join(str(item) for item in (completeness.get("missing") or [])[:3])
        alerts.append({
            "severity": "info",
            "title": "Profile data is incomplete",
            "message": f"Missing data lowers zone and plan confidence: {missing or 'profile fields'}.",
            "action": "profile",
        })
    for warning in safety.get("warnings") or []:
        alerts.append({
            "severity": "warning",
            "title": "Safety signal",
            "message": str(warning),
            "action": "profile",
        })
    if pending_imports:
        alerts.append({
            "severity": "warning",
            "title": "Imports need attention",
            "message": f"{pending_imports} import batches require review or retry.",
            "action": "imports",
        })
    if provider_count == 0:
        alerts.append({
            "severity": "info",
            "title": "No LLM provider",
            "message": "Unknown screenshots will use only deterministic templates until a provider is configured.",
            "action": "settings",
        })
    if recommendations and recommendations.get("status") in {"watch", "adjust"}:
        alerts.append({
            "severity": "warning" if recommendations.get("status") == "watch" else "critical",
            "title": "Coach recommendation",
            "message": str(recommendations.get("summary") or "Review coach recommendations before increasing load."),
            "action": "planning",
        })
    return alerts[:8]


def dashboard_summary(db: Session, user: User) -> dict[str, object]:
    today = today_for_user(db, user)
    plan = active_training_plan(db, user)
    current_week = current_week_for_plan(db, user, plan)
    profile = get_or_create_profile(db, user, commit=True)
    completeness = profile_completeness(profile)
    safety = safety_check(profile)
    recommendations = plan_adjustment_recommendations(db, user, plan) if plan else None
    pending_imports = pending_import_count(db, user)
    providers = active_provider_count(db, user)
    readiness = readiness_from_signals(current_week, safety, recommendations)
    plan_summary = None
    if plan:
        all_workouts = sorted(plan.workouts, key=lambda workout: (workout.week_index, workout.day_index, workout.id))
        plan_summary = {
            "id": plan.id,
            "title": plan.title,
            "status": plan.status,
            "goal_type": plan.goal_type,
            "race_distance_km": plan.race_distance_km,
            "target_date": plan.target_date,
            "adherence": adherence_summary(all_workouts),
        }
    return {
        "generated_at": datetime.now(UTC),
        "today": today,
        "analytics": user_analytics(db, user),
        "active_plan": plan_summary,
        "current_week": current_week,
        "weekly_snapshot": current_week.get("adherence"),
        "today_workout": current_week.get("today_workout"),
        "next_workout": current_week.get("next_workout"),
        "profile_completeness": completeness,
        "safety": safety,
        "readiness": readiness,
        "alerts": dashboard_alerts(current_week, completeness, safety, pending_imports, providers, recommendations),
        "recommendations": {
            "status": recommendations["status"],
            "summary": recommendations["summary"],
            "recommendations": recommendations["recommendations"][:3],
        } if recommendations else None,
        "pending_imports_count": pending_imports,
        "provider_count": providers,
        "recent_activities": recent_activities(db, user),
    }
