import csv
from datetime import UTC, date, datetime
from io import StringIO
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Activity,
    AuditLog,
    AthleteMeasurement,
    AthleteProfile,
    AthleteStateSnapshot,
    CoachActionPreview,
    CoachConversation,
    CoachLlmAttempt,
    CoachMemory,
    CoachMessage,
    CoachingEvent,
    DailyReadinessActionPreview,
    DailyReadinessCheckIn,
    DailyTrainingLoad,
    DerivedActivityMetric,
    ImportBatch,
    LactateThresholdMeasurement,
    LlmProviderSetting,
    PerformanceResult,
    PlanRecalculationRequest,
    PlanRollbackPreview,
    RunningGoal,
    ScreenshotSource,
    TrainingPlan,
    TrainingPlanRecommendationAudit,
    TrainingPlanVersion,
    TrainingPlanWorkout,
    TrainingPlanWorkoutBlock,
    TrainingPlanWorkoutFeedback,
    TrainingZone,
    User,
    WeeklyReview,
    WeeklyStrategyPreview,
)


def value_to_json(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def model_to_dict(instance: Any, exclude: set[str] | None = None) -> dict[str, Any]:
    excluded = exclude or set()
    return {
        column.key: value_to_json(getattr(instance, column.key))
        for column in instance.__mapper__.columns
        if column.key not in excluded
    }


def csv_safe_value(value: Any) -> Any:
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return f"'{value}"
    return value


def llm_provider_export(provider: LlmProviderSetting) -> dict[str, Any]:
    data = model_to_dict(provider, exclude={"encrypted_api_key"})
    data["has_api_key"] = bool(provider.encrypted_api_key)
    return data


def activity_export(activity: Activity) -> dict[str, Any]:
    data = model_to_dict(activity)
    data["segments"] = [model_to_dict(segment) for segment in activity.segments]
    data["split_blocks"] = [model_to_dict(block) for block in activity.split_blocks]
    data["workout_blocks"] = [model_to_dict(block) for block in activity.workout_blocks]
    data["derived_metrics"] = [model_to_dict(metric) for metric in activity.derived_metrics]
    return data


ACTIVITY_CSV_FIELDS = [
    "id",
    "activity_type",
    "title",
    "started_at",
    "distance_km",
    "duration_seconds",
    "average_pace_seconds_per_km",
    "average_speed_kmh",
    "average_heart_rate_bpm",
    "calories_kcal",
    "aerobic_training_stress",
    "source_note",
]


def activities_csv_content(activities: list[Activity]) -> str:
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=ACTIVITY_CSV_FIELDS)
    writer.writeheader()
    for activity in activities:
        exported = model_to_dict(activity)
        writer.writerow({field: csv_safe_value(exported.get(field)) for field in ACTIVITY_CSV_FIELDS})
    return buffer.getvalue()


def training_plan_export(plan: TrainingPlan) -> dict[str, Any]:
    data = model_to_dict(plan)
    data["workouts"] = []
    for workout in plan.workouts:
        workout_data = model_to_dict(workout)
        workout_data["blocks"] = [model_to_dict(block) for block in workout.blocks]
        workout_data["feedback"] = model_to_dict(workout.feedback) if workout.feedback else None
        data["workouts"].append(workout_data)
    return data


def screenshot_source_export(source: ScreenshotSource) -> dict[str, Any]:
    # Local filesystem paths are not useful in a portable export and can expose host details.
    return model_to_dict(source, exclude={"file_path"})


def coach_message_export(message: CoachMessage) -> dict[str, Any]:
    data = model_to_dict(message)
    if message.content_redacted:
        data["content"] = None
        data["response_json"] = None
    return data


def export_user_data(db: Session, user: User) -> dict[str, Any]:
    activities = list(db.scalars(
        select(Activity)
        .where(Activity.user_id == user.id)
        .options(selectinload(Activity.segments), selectinload(Activity.split_blocks), selectinload(Activity.workout_blocks), selectinload(Activity.derived_metrics))
        .order_by(Activity.started_at.desc().nullslast(), Activity.id.desc())
    ))
    plans = list(db.scalars(
        select(TrainingPlan)
        .where(TrainingPlan.user_id == user.id)
        .options(selectinload(TrainingPlan.workouts).selectinload(TrainingPlanWorkout.feedback), selectinload(TrainingPlan.workouts).selectinload(TrainingPlanWorkout.blocks))
        .order_by(TrainingPlan.created_at.desc(), TrainingPlan.id.desc())
    ))
    providers = list(db.scalars(select(LlmProviderSetting).where(LlmProviderSetting.user_id == user.id).order_by(LlmProviderSetting.created_at.desc())))
    audit_logs = list(db.scalars(select(AuditLog).where(AuditLog.user_id == user.id).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(500)))
    coaching_events = list(db.scalars(select(CoachingEvent).where(CoachingEvent.user_id == user.id).order_by(CoachingEvent.occurred_at.desc(), CoachingEvent.id.desc())))
    daily_training_loads = list(db.scalars(select(DailyTrainingLoad).where(DailyTrainingLoad.user_id == user.id).order_by(DailyTrainingLoad.date.asc())))

    return {
        "exported_at": datetime.now(UTC).isoformat(),
        "version": "2026-07-13.0027",
        "user": model_to_dict(user, exclude={"is_active"}),
        "profile": model_to_dict(user.athlete_profile) if user.athlete_profile else None,
        "measurements": [model_to_dict(item) for item in db.scalars(select(AthleteMeasurement).where(AthleteMeasurement.user_id == user.id).order_by(AthleteMeasurement.measured_at.desc().nullslast()))],
        "training_zones": [model_to_dict(item) for item in db.scalars(select(TrainingZone).where(TrainingZone.user_id == user.id).order_by(TrainingZone.zone_type, TrainingZone.method, TrainingZone.zone_key))],
        "activities": [activity_export(activity) for activity in activities],
        "goals": [model_to_dict(item) for item in db.scalars(select(RunningGoal).where(RunningGoal.user_id == user.id).order_by(RunningGoal.created_at.desc()))],
        "training_plans": [training_plan_export(plan) for plan in plans],
        "plan_versions": [model_to_dict(item) for item in db.scalars(select(TrainingPlanVersion).where(TrainingPlanVersion.user_id == user.id).order_by(TrainingPlanVersion.plan_id.asc(), TrainingPlanVersion.version_number.asc()))],
        "performance_results": [model_to_dict(item) for item in db.scalars(select(PerformanceResult).where(PerformanceResult.user_id == user.id).order_by(PerformanceResult.result_date.desc()))],
        "daily_training_loads": [model_to_dict(item) for item in daily_training_loads],
        "daily_readiness_checkins": [model_to_dict(item) for item in db.scalars(select(DailyReadinessCheckIn).where(DailyReadinessCheckIn.user_id == user.id).order_by(DailyReadinessCheckIn.checkin_date.asc()))],
        "daily_readiness_action_previews": [model_to_dict(item) for item in db.scalars(select(DailyReadinessActionPreview).where(DailyReadinessActionPreview.user_id == user.id).order_by(DailyReadinessActionPreview.created_at.asc()))],
        "coach_action_previews": [model_to_dict(item) for item in db.scalars(select(CoachActionPreview).where(CoachActionPreview.user_id == user.id).order_by(CoachActionPreview.created_at.asc()))],
        "plan_rollback_previews": [model_to_dict(item) for item in db.scalars(select(PlanRollbackPreview).where(PlanRollbackPreview.user_id == user.id).order_by(PlanRollbackPreview.created_at.asc()))],
        "plan_recalculation_requests": [model_to_dict(item) for item in db.scalars(select(PlanRecalculationRequest).where(PlanRecalculationRequest.user_id == user.id).order_by(PlanRecalculationRequest.requested_at.asc()))],
        "athlete_state_snapshots": [model_to_dict(item) for item in db.scalars(select(AthleteStateSnapshot).where(AthleteStateSnapshot.user_id == user.id).order_by(AthleteStateSnapshot.computed_at.asc()))],
        "weekly_reviews": [model_to_dict(item) for item in db.scalars(select(WeeklyReview).where(WeeklyReview.user_id == user.id).order_by(WeeklyReview.week_start.asc(), WeeklyReview.id.asc()))],
        "weekly_strategy_previews": [model_to_dict(item) for item in db.scalars(select(WeeklyStrategyPreview).where(WeeklyStrategyPreview.user_id == user.id).order_by(WeeklyStrategyPreview.created_at.asc()))],
        "coach_conversations": [model_to_dict(item) for item in db.scalars(select(CoachConversation).where(CoachConversation.user_id == user.id).order_by(CoachConversation.created_at.asc(), CoachConversation.id.asc()))],
        "coach_messages": [coach_message_export(item) for item in db.scalars(select(CoachMessage).where(CoachMessage.user_id == user.id).order_by(CoachMessage.created_at.asc(), CoachMessage.id.asc()))],
        "coach_memory": [model_to_dict(item) for item in db.scalars(select(CoachMemory).where(CoachMemory.user_id == user.id).order_by(CoachMemory.memory_key.asc()))],
        "coach_llm_attempts": [model_to_dict(item) for item in db.scalars(select(CoachLlmAttempt).where(CoachLlmAttempt.user_id == user.id).order_by(CoachLlmAttempt.created_at.asc(), CoachLlmAttempt.id.asc()))],
        "coaching_events": [model_to_dict(item) for item in coaching_events],
        "imports": [model_to_dict(item) for item in db.scalars(select(ImportBatch).where(ImportBatch.user_id == user.id).order_by(ImportBatch.created_at.desc()))],
        "screenshot_sources": [screenshot_source_export(item) for item in db.scalars(select(ScreenshotSource).where(ScreenshotSource.user_id == user.id).order_by(ScreenshotSource.created_at.desc()))],
        "lactate_threshold_measurements": [model_to_dict(item) for item in db.scalars(select(LactateThresholdMeasurement).where(LactateThresholdMeasurement.user_id == user.id).order_by(LactateThresholdMeasurement.measured_at.desc().nullslast()))],
        "llm_providers": [llm_provider_export(provider) for provider in providers],
        "audit_log": [model_to_dict(item) for item in audit_logs],
    }


def export_activities_csv(db: Session, user: User) -> str:
    activities = list(db.scalars(
        select(Activity)
        .where(Activity.user_id == user.id)
        .order_by(Activity.started_at.desc().nullslast(), Activity.id.desc())
    ))
    return activities_csv_content(activities)


def count_rows_for_user(db: Session, model: Any, user_id: int) -> int:
    return int(db.scalar(select(func.count()).select_from(model).where(model.user_id == user_id)) or 0)


DELETE_MODELS: tuple[tuple[str, Any], ...] = (
    ("coach_llm_attempts", CoachLlmAttempt),
    ("coach_memory", CoachMemory),
    ("coach_messages", CoachMessage),
    ("coach_conversations", CoachConversation),
    ("weekly_strategy_previews", WeeklyStrategyPreview),
    ("weekly_reviews", WeeklyReview),
    ("athlete_state_snapshots", AthleteStateSnapshot),
    ("plan_rollback_previews", PlanRollbackPreview),
    ("plan_recalculation_requests", PlanRecalculationRequest),
    ("coach_action_previews", CoachActionPreview),
    ("coaching_events", CoachingEvent),
    ("daily_readiness_action_previews", DailyReadinessActionPreview),
    ("daily_readiness_checkins", DailyReadinessCheckIn),
    ("audit_log", AuditLog),
    ("training_plan_recommendation_audits", TrainingPlanRecommendationAudit),
    ("plan_versions", TrainingPlanVersion),
    ("daily_training_loads", DailyTrainingLoad),
    ("planned_workout_blocks", TrainingPlanWorkoutBlock),
    ("training_plan_workout_feedback", TrainingPlanWorkoutFeedback),
    ("running_goals", RunningGoal),
    ("performance_results", PerformanceResult),
    ("import_batches", ImportBatch),
    ("training_plans", TrainingPlan),
    ("activities", Activity),
    ("lactate_threshold_measurements", LactateThresholdMeasurement),
    ("screenshot_sources", ScreenshotSource),
    ("athlete_measurements", AthleteMeasurement),
    ("athlete_profiles", AthleteProfile),
    ("training_zones", TrainingZone),
    ("llm_provider_settings", LlmProviderSetting),
)


def delete_user_data(db: Session, user_id: int) -> dict[str, int]:
    counts = {
        "derived_activity_metrics": int(db.scalar(select(func.count()).select_from(DerivedActivityMetric).join(Activity, DerivedActivityMetric.activity_id == Activity.id).where(Activity.user_id == user_id)) or 0),
        "planned_workout_blocks": int(db.scalar(select(func.count()).select_from(TrainingPlanWorkoutBlock).join(TrainingPlanWorkout, TrainingPlanWorkoutBlock.workout_id == TrainingPlanWorkout.id).join(TrainingPlan).where(TrainingPlan.user_id == user_id)) or 0),
    }
    counts.update({name: count_rows_for_user(db, model, user_id) for name, model in DELETE_MODELS if hasattr(model, "user_id")})
    db.execute(delete(DerivedActivityMetric).where(DerivedActivityMetric.activity_id.in_(select(Activity.id).where(Activity.user_id == user_id))))
    db.execute(delete(TrainingPlanWorkoutBlock).where(TrainingPlanWorkoutBlock.workout_id.in_(select(TrainingPlanWorkout.id).join(TrainingPlan).where(TrainingPlan.user_id == user_id))))
    for _, model in DELETE_MODELS:
        if hasattr(model, "user_id"):
            db.execute(delete(model).where(model.user_id == user_id))
    return counts
