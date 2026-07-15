import csv
import secrets
import shutil
from datetime import UTC, date, datetime
from io import StringIO
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Activity,
    AuditLog,
    AthleteMeasurement,
    AthleteProfile,
    AthleteStateSnapshot,
    CoachActionPreview,
    CoachConversation,
    CoachDelivery,
    CoachDeliveryAttempt,
    CoachDeliveryPreference,
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
    RecoverySignalObservation,
    RunningGoal,
    SafetyEscalation,
    SafetyEscalationEvent,
    SafetyReviewAudienceEnrollment,
    SafetyReviewConsent,
    SafetyReviewEvent,
    SafetyReviewerGrant,
    SafetyReviewRequest,
    ScreenshotSource,
    TrainingPlan,
    TrainingPlanRecommendationAudit,
    TrainingPlanVersion,
    TrainingPlanWorkout,
    TrainingPlanWorkoutBlock,
    TrainingPlanWorkoutFeedback,
    TrainingZone,
    UploadDeletionJob,
    User,
    WeeklyReview,
    WeeklyStrategyPreview,
)
from app.services.safety_reviews import release_reviewer_claims


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
    coach_delivery_preference = db.scalar(select(CoachDeliveryPreference).where(CoachDeliveryPreference.user_id == user.id))
    audience_enrollment = db.scalar(select(SafetyReviewAudienceEnrollment).where(SafetyReviewAudienceEnrollment.user_id == user.id))

    return {
        "exported_at": datetime.now(UTC).isoformat(),
        "version": "2026-07-15.0034",
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
        "recovery_signal_observations": [model_to_dict(item) for item in db.scalars(select(RecoverySignalObservation).where(RecoverySignalObservation.user_id == user.id).order_by(RecoverySignalObservation.observed_at.asc(), RecoverySignalObservation.id.asc()))],
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
        "coach_delivery_preference": model_to_dict(coach_delivery_preference, exclude={"telegram_chat_id"}) if coach_delivery_preference else None,
        "coach_deliveries": [model_to_dict(item) for item in db.scalars(select(CoachDelivery).where(CoachDelivery.user_id == user.id).order_by(CoachDelivery.created_at.asc()))],
        "coach_delivery_attempts": [model_to_dict(item) for item in db.scalars(select(CoachDeliveryAttempt).join(CoachDelivery).where(CoachDelivery.user_id == user.id).order_by(CoachDeliveryAttempt.created_at.asc(), CoachDeliveryAttempt.id.asc()))],
        "safety_escalations": [model_to_dict(item, exclude={"source_key", "source_fingerprint"}) for item in db.scalars(select(SafetyEscalation).where(SafetyEscalation.user_id == user.id).order_by(SafetyEscalation.created_at.asc(), SafetyEscalation.id.asc()))],
        "safety_escalation_events": [model_to_dict(item) for item in db.scalars(select(SafetyEscalationEvent).where(SafetyEscalationEvent.user_id == user.id).order_by(SafetyEscalationEvent.occurred_at.asc(), SafetyEscalationEvent.id.asc()))],
        "safety_review_audience_enrollment": model_to_dict(audience_enrollment) if audience_enrollment else None,
        "safety_review_consents": [model_to_dict(item) for item in db.scalars(select(SafetyReviewConsent).where(SafetyReviewConsent.user_id == user.id).order_by(SafetyReviewConsent.created_at.asc(), SafetyReviewConsent.id.asc()))],
        "safety_review_requests": [model_to_dict(item, exclude={"reviewer_user_id"}) for item in db.scalars(select(SafetyReviewRequest).where(SafetyReviewRequest.user_id == user.id).order_by(SafetyReviewRequest.requested_at.asc(), SafetyReviewRequest.id.asc()))],
        "safety_review_events": [model_to_dict(item, exclude={"actor_user_id"}) for item in db.scalars(select(SafetyReviewEvent).where(SafetyReviewEvent.user_id == user.id).order_by(SafetyReviewEvent.occurred_at.asc(), SafetyReviewEvent.id.asc()))],
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
    ("safety_escalation_events", SafetyEscalationEvent),
    ("safety_escalations", SafetyEscalation),
    ("coach_delivery_attempts", CoachDeliveryAttempt),
    ("coach_deliveries", CoachDelivery),
    ("coach_delivery_preferences", CoachDeliveryPreference),
    ("coach_llm_attempts", CoachLlmAttempt),
    ("coach_memory", CoachMemory),
    ("coach_messages", CoachMessage),
    ("coach_conversations", CoachConversation),
    ("weekly_strategy_previews", WeeklyStrategyPreview),
    ("weekly_reviews", WeeklyReview),
    ("athlete_state_snapshots", AthleteStateSnapshot),
    ("recovery_signal_observations", RecoverySignalObservation),
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


def stage_user_upload_deletion(upload_dir: Path, user_id: int) -> tuple[Path | None, int]:
    root = upload_dir.resolve()
    user_dir = upload_dir / str(user_id)
    if user_dir.parent.resolve() != root:
        raise RuntimeError("User upload directory escaped the configured upload root")
    if not user_dir.exists() and not user_dir.is_symlink():
        return None, 0
    file_count = sum(1 for item in user_dir.rglob("*") if item.is_file() or item.is_symlink())
    if user_dir.is_symlink():
        file_count = max(file_count, 1)
    staged = root / f".delete-{secrets.token_hex(16)}"
    user_dir.rename(staged)
    return staged, file_count


def finish_user_upload_deletion(staged: Path | None) -> None:
    if staged is None:
        return
    if staged.is_symlink():
        staged.unlink(missing_ok=True)
    elif staged.exists():
        shutil.rmtree(staged)


def restore_user_upload_deletion(staged: Path | None, upload_dir: Path, user_id: int) -> None:
    if staged is None or (not staged.exists() and not staged.is_symlink()):
        return
    target = upload_dir / str(user_id)
    if target.exists() or target.is_symlink():
        raise RuntimeError("Cannot restore staged user uploads because the target exists")
    staged.rename(target)


def create_upload_deletion_job(db: Session, staged: Path, file_count: int) -> UploadDeletionJob:
    if staged.name != str(staged.name) or not staged.name.startswith(".delete-") or Path(staged.name).name != staged.name:
        raise RuntimeError("Invalid staged upload deletion name")
    job = UploadDeletionJob(staged_name=staged.name, file_count=file_count)
    db.add(job)
    db.flush()
    return job


def finish_upload_deletion_job(db: Session, upload_dir: Path, job_id: int) -> None:
    job = db.get(UploadDeletionJob, job_id)
    if job is None:
        return
    if not job.staged_name.startswith(".delete-") or Path(job.staged_name).name != job.staged_name:
        raise RuntimeError("Invalid persisted upload deletion name")
    staged = upload_dir / job.staged_name
    if staged.parent.resolve() != upload_dir.resolve():
        raise RuntimeError("Staged upload deletion escaped the configured upload root")
    finish_user_upload_deletion(staged)
    db.delete(job)
    db.commit()


def process_pending_upload_deletions(db: Session, upload_dir: Path) -> int:
    job_ids = list(db.scalars(select(UploadDeletionJob.id).order_by(UploadDeletionJob.created_at.asc(), UploadDeletionJob.id.asc())))
    completed = 0
    for job_id in job_ids:
        try:
            finish_upload_deletion_job(db, upload_dir, int(job_id))
            completed += 1
        except (OSError, SQLAlchemyError):
            db.rollback()
    return completed


def delete_user_data(db: Session, user_id: int) -> dict[str, int]:
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT set_config('runforfan.safety_review_erasure_user_id', :user_id, true)"), {"user_id": str(user_id)})
    counts = {
        "derived_activity_metrics": int(db.scalar(select(func.count()).select_from(DerivedActivityMetric).join(Activity, DerivedActivityMetric.activity_id == Activity.id).where(Activity.user_id == user_id)) or 0),
        "planned_workout_blocks": int(db.scalar(select(func.count()).select_from(TrainingPlanWorkoutBlock).join(TrainingPlanWorkout, TrainingPlanWorkoutBlock.workout_id == TrainingPlanWorkout.id).join(TrainingPlan).where(TrainingPlan.user_id == user_id)) or 0),
        "coach_delivery_attempts": int(db.scalar(select(func.count()).select_from(CoachDeliveryAttempt).join(CoachDelivery).where(CoachDelivery.user_id == user_id)) or 0),
    }
    counts.update({name: count_rows_for_user(db, model, user_id) for name, model in DELETE_MODELS if hasattr(model, "user_id")})
    counts["safety_review_events"] = count_rows_for_user(db, SafetyReviewEvent, user_id)
    counts["safety_review_requests"] = count_rows_for_user(db, SafetyReviewRequest, user_id)
    counts["safety_review_consents"] = count_rows_for_user(db, SafetyReviewConsent, user_id)
    counts["safety_review_audience_enrollments"] = count_rows_for_user(db, SafetyReviewAudienceEnrollment, user_id)
    reviewer_grant = db.scalar(select(SafetyReviewerGrant).where(SafetyReviewerGrant.user_id == user_id).with_for_update())
    claimed_review_count = int(db.scalar(select(func.count()).select_from(SafetyReviewRequest).where(SafetyReviewRequest.reviewer_user_id == user_id, SafetyReviewRequest.status == "claimed")) or 0)
    counts["safety_reviewer_grants_revoked"] = 1 if reviewer_grant is not None and reviewer_grant.status == "active" else 0
    counts["safety_review_claims_released"] = claimed_review_count
    if claimed_review_count:
        release_reviewer_claims(db, user_id)
    if reviewer_grant is not None and reviewer_grant.status == "active":
        reviewer_grant.status = "revoked"
        reviewer_grant.revoked_at = datetime.now(UTC)
    db.flush()
    db.execute(delete(SafetyReviewAudienceEnrollment).where(SafetyReviewAudienceEnrollment.user_id == user_id))
    db.execute(delete(DerivedActivityMetric).where(DerivedActivityMetric.activity_id.in_(select(Activity.id).where(Activity.user_id == user_id))))
    db.execute(delete(TrainingPlanWorkoutBlock).where(TrainingPlanWorkoutBlock.workout_id.in_(select(TrainingPlanWorkout.id).join(TrainingPlan).where(TrainingPlan.user_id == user_id))))
    for _, model in DELETE_MODELS:
        if hasattr(model, "user_id"):
            db.execute(delete(model).where(model.user_id == user_id))
    return counts
