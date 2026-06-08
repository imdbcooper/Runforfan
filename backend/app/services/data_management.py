from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Activity,
    AuditLog,
    AthleteMeasurement,
    AthleteProfile,
    ImportBatch,
    LactateThresholdMeasurement,
    LlmProviderSetting,
    PerformanceResult,
    RunningGoal,
    ScreenshotSource,
    TrainingPlan,
    TrainingPlanRecommendationAudit,
    TrainingPlanVersion,
    TrainingPlanWorkout,
    TrainingPlanWorkoutFeedback,
    TrainingZone,
    User,
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


def llm_provider_export(provider: LlmProviderSetting) -> dict[str, Any]:
    data = model_to_dict(provider, exclude={"encrypted_api_key"})
    data["has_api_key"] = bool(provider.encrypted_api_key)
    return data


def activity_export(activity: Activity) -> dict[str, Any]:
    data = model_to_dict(activity)
    data["segments"] = [model_to_dict(segment) for segment in activity.segments]
    data["split_blocks"] = [model_to_dict(block) for block in activity.split_blocks]
    data["workout_blocks"] = [model_to_dict(block) for block in activity.workout_blocks]
    return data


def training_plan_export(plan: TrainingPlan) -> dict[str, Any]:
    data = model_to_dict(plan)
    data["workouts"] = []
    for workout in plan.workouts:
        workout_data = model_to_dict(workout)
        workout_data["feedback"] = model_to_dict(workout.feedback) if workout.feedback else None
        data["workouts"].append(workout_data)
    return data


def screenshot_source_export(source: ScreenshotSource) -> dict[str, Any]:
    # Local filesystem paths are not useful in a portable export and can expose host details.
    return model_to_dict(source, exclude={"file_path"})


def export_user_data(db: Session, user: User) -> dict[str, Any]:
    activities = list(db.scalars(
        select(Activity)
        .where(Activity.user_id == user.id)
        .options(selectinload(Activity.segments), selectinload(Activity.split_blocks), selectinload(Activity.workout_blocks))
        .order_by(Activity.started_at.desc().nullslast(), Activity.id.desc())
    ))
    plans = list(db.scalars(
        select(TrainingPlan)
        .where(TrainingPlan.user_id == user.id)
        .options(selectinload(TrainingPlan.workouts).selectinload(TrainingPlanWorkout.feedback))
        .order_by(TrainingPlan.created_at.desc(), TrainingPlan.id.desc())
    ))
    providers = list(db.scalars(select(LlmProviderSetting).where(LlmProviderSetting.user_id == user.id).order_by(LlmProviderSetting.created_at.desc())))
    audit_logs = list(db.scalars(select(AuditLog).where(AuditLog.user_id == user.id).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(500)))

    return {
        "exported_at": datetime.now(UTC).isoformat(),
        "version": "2026-06-08.0018",
        "user": model_to_dict(user, exclude={"is_active"}),
        "profile": model_to_dict(user.athlete_profile) if user.athlete_profile else None,
        "measurements": [model_to_dict(item) for item in db.scalars(select(AthleteMeasurement).where(AthleteMeasurement.user_id == user.id).order_by(AthleteMeasurement.measured_at.desc().nullslast()))],
        "training_zones": [model_to_dict(item) for item in db.scalars(select(TrainingZone).where(TrainingZone.user_id == user.id).order_by(TrainingZone.zone_type, TrainingZone.method, TrainingZone.zone_key))],
        "activities": [activity_export(activity) for activity in activities],
        "goals": [model_to_dict(item) for item in db.scalars(select(RunningGoal).where(RunningGoal.user_id == user.id).order_by(RunningGoal.created_at.desc()))],
        "training_plans": [training_plan_export(plan) for plan in plans],
        "plan_versions": [model_to_dict(item) for item in db.scalars(select(TrainingPlanVersion).where(TrainingPlanVersion.user_id == user.id).order_by(TrainingPlanVersion.plan_id.asc(), TrainingPlanVersion.version_number.asc()))],
        "performance_results": [model_to_dict(item) for item in db.scalars(select(PerformanceResult).where(PerformanceResult.user_id == user.id).order_by(PerformanceResult.result_date.desc()))],
        "imports": [model_to_dict(item) for item in db.scalars(select(ImportBatch).where(ImportBatch.user_id == user.id).order_by(ImportBatch.created_at.desc()))],
        "screenshot_sources": [screenshot_source_export(item) for item in db.scalars(select(ScreenshotSource).where(ScreenshotSource.user_id == user.id).order_by(ScreenshotSource.created_at.desc()))],
        "lactate_threshold_measurements": [model_to_dict(item) for item in db.scalars(select(LactateThresholdMeasurement).where(LactateThresholdMeasurement.user_id == user.id).order_by(LactateThresholdMeasurement.measured_at.desc().nullslast()))],
        "llm_providers": [llm_provider_export(provider) for provider in providers],
        "audit_log": [model_to_dict(item) for item in audit_logs],
    }


def count_rows_for_user(db: Session, model: Any, user_id: int) -> int:
    return int(db.scalar(select(func.count()).select_from(model).where(model.user_id == user_id)) or 0)


DELETE_MODELS: tuple[tuple[str, Any], ...] = (
    ("audit_log", AuditLog),
    ("training_plan_recommendation_audits", TrainingPlanRecommendationAudit),
    ("plan_versions", TrainingPlanVersion),
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
    counts = {name: count_rows_for_user(db, model, user_id) for name, model in DELETE_MODELS}
    for _, model in DELETE_MODELS:
        db.execute(delete(model).where(model.user_id == user_id))
    return counts
