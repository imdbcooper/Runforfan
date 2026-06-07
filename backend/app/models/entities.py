from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int | None] = mapped_column(Integer, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255))
    first_name: Mapped[str | None] = mapped_column(String(255))
    last_name: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(255), default="Runner")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    activities: Mapped[list["Activity"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    goals: Mapped[list["RunningGoal"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    llm_providers: Mapped[list["LlmProviderSetting"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    athlete_profile: Mapped["AthleteProfile | None"] = relationship(back_populates="user", cascade="all, delete-orphan", uselist=False)
    measurements: Mapped[list["AthleteMeasurement"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    training_zones: Mapped[list["TrainingZone"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    performance_results: Mapped[list["PerformanceResult"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship()


class AthleteProfile(Base, TimestampMixin):
    __tablename__ = "athlete_profiles"
    __table_args__ = (UniqueConstraint("user_id", name="uq_athlete_profile_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    sex: Mapped[str] = mapped_column(String(32), default="unspecified")
    height_cm: Mapped[float | None] = mapped_column(Float)
    weight_kg: Mapped[float | None] = mapped_column(Float)
    timezone: Mapped[str | None] = mapped_column(String(100), default="Europe/Moscow")
    locale: Mapped[str | None] = mapped_column(String(32), default="ru-RU")
    resting_heart_rate_bpm: Mapped[int | None] = mapped_column(Integer)
    max_heart_rate_bpm: Mapped[int | None] = mapped_column(Integer)
    max_hr_source: Mapped[str | None] = mapped_column(String(64))
    lactate_threshold_hr_bpm: Mapped[int | None] = mapped_column(Integer)
    lactate_threshold_pace_seconds_per_km: Mapped[int | None] = mapped_column(Integer)
    conservative_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    injury_notes: Mapped[str | None] = mapped_column(Text)

    user: Mapped[User] = relationship(back_populates="athlete_profile")


class AthleteMeasurement(Base, TimestampMixin):
    __tablename__ = "athlete_measurements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    measurement_type: Mapped[str] = mapped_column(String(64))
    measured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    value_numeric: Mapped[float | None] = mapped_column(Float)
    value_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    source: Mapped[str] = mapped_column(String(64), default="manual")
    confidence: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)

    user: Mapped[User] = relationship(back_populates="measurements")


class TrainingZone(Base, TimestampMixin):
    __tablename__ = "training_zones"
    __table_args__ = (UniqueConstraint("user_id", "zone_type", "method", "zone_key", name="uq_user_zone_method_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    zone_type: Mapped[str] = mapped_column(String(32))
    method: Mapped[str] = mapped_column(String(64))
    zone_key: Mapped[str] = mapped_column(String(64))
    label: Mapped[str | None] = mapped_column(String(255))
    lower_value: Mapped[float | None] = mapped_column(Float)
    upper_value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(64))
    confidence: Mapped[str] = mapped_column(String(32), default="low")
    source_reference: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    user: Mapped[User] = relationship(back_populates="training_zones")


class ScreenshotSource(Base, TimestampMixin):
    __tablename__ = "screenshot_sources"
    __table_args__ = (UniqueConstraint("user_id", "file_path", name="uq_user_screenshot_path"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    file_path: Mapped[str] = mapped_column(String(1000))
    screen_type: Mapped[str] = mapped_column(String(100), default="uploaded_screenshot")
    source_app: Mapped[str | None] = mapped_column(String(100))
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)


class Activity(Base, TimestampMixin):
    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    activity_type: Mapped[str] = mapped_column(String(64), default="outdoor_run")
    title: Mapped[str] = mapped_column(String(255), default="Бег на улице")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    distance_km: Mapped[float | None] = mapped_column(Float)
    duration_seconds: Mapped[int] = mapped_column(Integer)
    calories_kcal: Mapped[int | None] = mapped_column(Integer)
    average_pace_seconds_per_km: Mapped[int | None] = mapped_column(Integer)
    fastest_pace_seconds_per_km: Mapped[int | None] = mapped_column(Integer)
    average_speed_kmh: Mapped[float | None] = mapped_column(Float)
    average_cadence_spm: Mapped[int | None] = mapped_column(Integer)
    average_stride_cm: Mapped[int | None] = mapped_column(Integer)
    steps_count: Mapped[int | None] = mapped_column(Integer)
    average_heart_rate_bpm: Mapped[int | None] = mapped_column(Integer)
    elevation_gain_m: Mapped[float | None] = mapped_column(Float)
    elevation_loss_m: Mapped[float | None] = mapped_column(Float)
    aerobic_training_stress: Mapped[float | None] = mapped_column(Float)
    aerobic_training_effect: Mapped[str | None] = mapped_column(String(255))
    source_note: Mapped[str | None] = mapped_column(Text)

    user: Mapped[User] = relationship(back_populates="activities")
    segments: Mapped[list["ActivitySegment"]] = relationship(back_populates="activity", cascade="all, delete-orphan")
    split_blocks: Mapped[list["ActivitySplitBlock"]] = relationship(back_populates="activity", cascade="all, delete-orphan")
    workout_blocks: Mapped[list["ActivityWorkoutBlock"]] = relationship(back_populates="activity", cascade="all, delete-orphan")
    screenshots: Mapped[list["ActivityScreenshot"]] = relationship(back_populates="activity", cascade="all, delete-orphan")


class ActivitySegment(Base):
    __tablename__ = "activity_segments"
    __table_args__ = (UniqueConstraint("activity_id", "segment_index", name="uq_activity_segment"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    activity_id: Mapped[int] = mapped_column(ForeignKey("activities.id", ondelete="CASCADE"), index=True)
    segment_index: Mapped[int] = mapped_column(Integer)
    distance_km: Mapped[float] = mapped_column(Float)
    duration_seconds: Mapped[int] = mapped_column(Integer)
    pace_seconds_per_km: Mapped[int] = mapped_column(Integer)
    average_heart_rate_bpm: Mapped[int | None] = mapped_column(Integer)
    average_cadence_spm: Mapped[int | None] = mapped_column(Integer)

    activity: Mapped[Activity] = relationship(back_populates="segments")


class ActivitySplitBlock(Base):
    __tablename__ = "activity_split_blocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    activity_id: Mapped[int] = mapped_column(ForeignKey("activities.id", ondelete="CASCADE"), index=True)
    block_index: Mapped[int] = mapped_column(Integer)
    start_km: Mapped[float] = mapped_column(Float)
    end_km: Mapped[float] = mapped_column(Float)
    distance_km: Mapped[float] = mapped_column(Float)
    duration_seconds: Mapped[int] = mapped_column(Integer)
    cumulative_duration_seconds: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)

    activity: Mapped[Activity] = relationship(back_populates="split_blocks")


class ActivityWorkoutBlock(Base):
    __tablename__ = "activity_workout_blocks"
    __table_args__ = (UniqueConstraint("activity_id", "block_index", name="uq_activity_workout_block"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    activity_id: Mapped[int] = mapped_column(ForeignKey("activities.id", ondelete="CASCADE"), index=True)
    block_index: Mapped[int] = mapped_column(Integer)
    block_type: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(255))
    distance_km: Mapped[float | None] = mapped_column(Float)
    duration_seconds: Mapped[int] = mapped_column(Integer)
    pace_seconds_per_km: Mapped[int | None] = mapped_column(Integer)
    average_heart_rate_bpm: Mapped[int | None] = mapped_column(Integer)
    average_cadence_spm: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)

    activity: Mapped[Activity] = relationship(back_populates="workout_blocks")


class ActivityScreenshot(Base):
    __tablename__ = "activity_screenshots"
    __table_args__ = (UniqueConstraint("activity_id", "source_id", name="uq_activity_screenshot"),)

    activity_id: Mapped[int] = mapped_column(ForeignKey("activities.id", ondelete="CASCADE"), primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("screenshot_sources.id", ondelete="CASCADE"), primary_key=True)

    activity: Mapped[Activity] = relationship(back_populates="screenshots")
    source: Mapped[ScreenshotSource] = relationship()


class LactateThresholdMeasurement(Base, TimestampMixin):
    __tablename__ = "lactate_threshold_measurements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("screenshot_sources.id", ondelete="SET NULL"))
    measured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    calories_kcal: Mapped[int | None] = mapped_column(Integer)
    average_pace_seconds_per_km: Mapped[int | None] = mapped_column(Integer)
    average_speed_kmh: Mapped[float | None] = mapped_column(Float)
    average_cadence_spm: Mapped[int | None] = mapped_column(Integer)
    average_stride_cm: Mapped[int | None] = mapped_column(Integer)
    steps_count: Mapped[int | None] = mapped_column(Integer)
    average_heart_rate_bpm: Mapped[int | None] = mapped_column(Integer)
    elevation_gain_m: Mapped[float | None] = mapped_column(Float)
    elevation_loss_m: Mapped[float | None] = mapped_column(Float)
    threshold_heart_rate_bpm: Mapped[int] = mapped_column(Integer)
    threshold_pace_seconds_per_km: Mapped[int] = mapped_column(Integer)
    distance_km: Mapped[float | None] = mapped_column(Float)
    distance_is_estimated: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)


class PerformanceResult(Base, TimestampMixin):
    __tablename__ = "performance_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    activity_id: Mapped[int | None] = mapped_column(ForeignKey("activities.id", ondelete="SET NULL"), index=True)
    result_type: Mapped[str] = mapped_column(String(32), default="race")
    name: Mapped[str] = mapped_column(String(255))
    result_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    distance_km: Mapped[float] = mapped_column(Float)
    duration_seconds: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(64), default="manual")
    terrain: Mapped[str] = mapped_column(String(64), default="road")
    weather: Mapped[str | None] = mapped_column(String(255))
    elevation_gain_m: Mapped[float | None] = mapped_column(Float)
    temperature_c: Mapped[float | None] = mapped_column(Float)
    is_noisy: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)

    user: Mapped[User] = relationship(back_populates="performance_results")
    activity: Mapped[Activity | None] = relationship()


class ImportBatch(Base, TimestampMixin):
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(64), default="uploaded")
    source_app: Mapped[str | None] = mapped_column(String(100))
    recognition_engine: Mapped[str | None] = mapped_column(String(100))
    recognition_message: Mapped[str | None] = mapped_column(Text)
    created_activity_id: Mapped[int | None] = mapped_column(ForeignKey("activities.id", ondelete="SET NULL"))

    sources: Mapped[list["ImportBatchSource"]] = relationship(back_populates="batch", cascade="all, delete-orphan")


class ImportBatchSource(Base):
    __tablename__ = "import_batch_sources"

    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id", ondelete="CASCADE"), primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("screenshot_sources.id", ondelete="CASCADE"), primary_key=True)

    batch: Mapped[ImportBatch] = relationship(back_populates="sources")
    source: Mapped[ScreenshotSource] = relationship()


class ImportRecognitionAttempt(Base, TimestampMixin):
    __tablename__ = "import_recognition_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id", ondelete="CASCADE"), index=True)
    engine: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(64))
    raw_response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    parsed_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    validation_errors: Mapped[list[Any] | None] = mapped_column(JSONB)


class RunningGoal(Base, TimestampMixin):
    __tablename__ = "running_goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    goal_type: Mapped[str] = mapped_column(String(64))
    target_value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(64))
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(64), default="active")

    user: Mapped[User] = relationship(back_populates="goals")


class LlmProviderSetting(Base, TimestampMixin):
    __tablename__ = "llm_provider_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(64))
    display_name: Mapped[str] = mapped_column(String(255))
    base_url: Mapped[str | None] = mapped_column(String(1000))
    model: Mapped[str] = mapped_column(String(255))
    encrypted_api_key: Mapped[str | None] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    user: Mapped[User] = relationship(back_populates="llm_providers")


class TrainingPlan(Base, TimestampMixin):
    __tablename__ = "training_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    goal_type: Mapped[str] = mapped_column(String(64))
    race_distance_km: Mapped[float | None] = mapped_column(Float)
    target_date: Mapped[date | None] = mapped_column(Date)
    target_time_seconds: Mapped[int | None] = mapped_column(Integer)
    available_days_per_week: Mapped[int] = mapped_column(Integer, default=4)
    status: Mapped[str] = mapped_column(String(64), default="draft")
    explanation: Mapped[str | None] = mapped_column(Text)

    workouts: Mapped[list["TrainingPlanWorkout"]] = relationship(back_populates="plan", cascade="all, delete-orphan")


class TrainingPlanWorkout(Base):
    __tablename__ = "training_plan_workouts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("training_plans.id", ondelete="CASCADE"), index=True)
    scheduled_date: Mapped[date | None] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(64), default="planned")
    completed_activity_id: Mapped[int | None] = mapped_column(ForeignKey("activities.id", ondelete="SET NULL"), index=True)
    week_index: Mapped[int] = mapped_column(Integer)
    day_index: Mapped[int] = mapped_column(Integer)
    workout_type: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(255))
    distance_km: Mapped[float | None] = mapped_column(Float)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    intensity: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)

    plan: Mapped[TrainingPlan] = relationship(back_populates="workouts")
    completed_activity: Mapped[Activity | None] = relationship()
    feedback: Mapped["TrainingPlanWorkoutFeedback | None"] = relationship(back_populates="workout", cascade="all, delete-orphan", uselist=False)


class TrainingPlanWorkoutFeedback(Base, TimestampMixin):
    __tablename__ = "training_plan_workout_feedback"
    __table_args__ = (UniqueConstraint("workout_id", name="uq_training_plan_workout_feedback_workout"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workout_id: Mapped[int] = mapped_column(ForeignKey("training_plan_workouts.id", ondelete="CASCADE"), index=True)
    rpe: Mapped[int | None] = mapped_column(Integer)
    fatigue: Mapped[int | None] = mapped_column(Integer)
    pain: Mapped[bool] = mapped_column(Boolean, default=False)
    pain_level: Mapped[int | None] = mapped_column(Integer)
    sleep_quality: Mapped[int | None] = mapped_column(Integer)
    weather_notes: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    workout: Mapped[TrainingPlanWorkout] = relationship(back_populates="feedback")


class TrainingPlanRecommendationAudit(Base):
    __tablename__ = "training_plan_recommendation_audits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("training_plans.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(64), default="applied")
    recommendations_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    preview_changes: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    applied_changes: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
