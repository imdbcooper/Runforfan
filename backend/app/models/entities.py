from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, ForeignKeyConstraint, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, index=True)
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
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    daily_training_loads: Mapped[list["DailyTrainingLoad"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    daily_readiness_checkins: Mapped[list["DailyReadinessCheckIn"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    recovery_signal_observations: Mapped[list["RecoverySignalObservation"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    daily_readiness_action_previews: Mapped[list["DailyReadinessActionPreview"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    coach_action_previews: Mapped[list["CoachActionPreview"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    plan_rollback_previews: Mapped[list["PlanRollbackPreview"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    plan_recalculation_requests: Mapped[list["PlanRecalculationRequest"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    coaching_events: Mapped[list["CoachingEvent"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    athlete_state_snapshots: Mapped[list["AthleteStateSnapshot"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    weekly_reviews: Mapped[list["WeeklyReview"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    weekly_strategy_previews: Mapped[list["WeeklyStrategyPreview"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    coach_conversations: Mapped[list["CoachConversation"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    coach_messages: Mapped[list["CoachMessage"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    coach_memory: Mapped[list["CoachMemory"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    coach_llm_attempts: Mapped[list["CoachLlmAttempt"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    coach_delivery_preference: Mapped["CoachDeliveryPreference | None"] = relationship(back_populates="user", cascade="all, delete-orphan", uselist=False)
    coach_deliveries: Mapped[list["CoachDelivery"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship()


class TelegramLoginCode(Base):
    __tablename__ = "telegram_login_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    code_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship()


class CoachDeliveryPreference(Base, TimestampMixin):
    __tablename__ = "coach_delivery_preferences"
    __table_args__ = (
        CheckConstraint("NOT telegram_enabled OR (telegram_chat_id IS NOT NULL AND telegram_chat_verified_at IS NOT NULL)", name="ck_coach_delivery_preference_enabled_destination"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True)
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    telegram_chat_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    telegram_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    daily_brief_local_time: Mapped[time] = mapped_column(default=time(8, 0), server_default=text("'08:00:00'"))
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="coach_delivery_preference")


class CoachDelivery(Base, TimestampMixin):
    __tablename__ = "coach_deliveries"
    __table_args__ = (
        CheckConstraint("channel = 'telegram'", name="ck_coach_delivery_channel"),
        CheckConstraint("delivery_type = 'daily_brief'", name="ck_coach_delivery_type"),
        CheckConstraint("template_key IN ('checkin_required', 'proceed', 'conservative', 'rest', 'stop')", name="ck_coach_delivery_template"),
        CheckConstraint("status IN ('pending', 'sending', 'sent', 'retry_scheduled', 'permanent_failure', 'cancelled')", name="ck_coach_delivery_status"),
        CheckConstraint("attempt_count >= 0 AND max_attempts > 0 AND attempt_count <= max_attempts", name="ck_coach_delivery_attempt_counts"),
        CheckConstraint("retry_at IS NULL OR status = 'retry_scheduled'", name="ck_coach_delivery_retry_status"),
        CheckConstraint("status != 'retry_scheduled' OR retry_at IS NOT NULL", name="ck_coach_delivery_retry_scheduled_at"),
        CheckConstraint("status != 'sending' OR (locked_at IS NOT NULL AND locked_by IS NOT NULL)", name="ck_coach_delivery_sending_lock"),
        UniqueConstraint("user_id", "channel", "delivery_type", "local_date", "rule_version", name="uq_coach_delivery_daily"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(32), default="telegram")
    delivery_type: Mapped[str] = mapped_column(String(32), default="daily_brief")
    local_date: Mapped[date] = mapped_column(Date, index=True)
    timezone: Mapped[str] = mapped_column(String(100))
    rule_version: Mapped[str] = mapped_column(String(64))
    athlete_state_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("athlete_state_snapshots.id", ondelete="SET NULL"))
    readiness_checkin_id: Mapped[int | None] = mapped_column(ForeignKey("daily_readiness_checkins.id", ondelete="SET NULL"))
    workout_id: Mapped[int | None] = mapped_column(ForeignKey("training_plan_workouts.id", ondelete="SET NULL"))
    template_key: Mapped[str] = mapped_column(String(32))
    content_fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(128))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="coach_deliveries")
    attempts: Mapped[list["CoachDeliveryAttempt"]] = relationship(back_populates="delivery", cascade="all, delete-orphan")


class CoachDeliveryAttempt(Base):
    __tablename__ = "coach_delivery_attempts"
    __table_args__ = (
        CheckConstraint("attempt_number > 0", name="ck_coach_delivery_attempt_number"),
        CheckConstraint("status IN ('success', 'retryable_failure', 'permanent_failure')", name="ck_coach_delivery_attempt_status"),
        CheckConstraint("failure_class IS NULL OR failure_class IN ('timeout', 'network', 'rate_limited', 'upstream', 'forbidden', 'bad_request', 'configuration', 'internal')", name="ck_coach_delivery_attempt_failure_class"),
        UniqueConstraint("delivery_id", "attempt_number", name="uq_coach_delivery_attempt"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    delivery_id: Mapped[str] = mapped_column(ForeignKey("coach_deliveries.id", ondelete="CASCADE"), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32))
    failure_class: Mapped[str | None] = mapped_column(String(32))
    http_status: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    delivery: Mapped[CoachDelivery] = relationship(back_populates="attempts")


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
    unit_system: Mapped[str] = mapped_column(String(16), default="metric")
    preferred_weekdays: Mapped[list[int] | None] = mapped_column(JSONB)
    long_run_weekday: Mapped[int | None] = mapped_column(Integer)
    max_run_duration_minutes: Mapped[int | None] = mapped_column(Integer)
    resting_heart_rate_bpm: Mapped[int | None] = mapped_column(Integer)
    max_heart_rate_bpm: Mapped[int | None] = mapped_column(Integer)
    max_hr_source: Mapped[str | None] = mapped_column(String(64))
    lactate_threshold_hr_bpm: Mapped[int | None] = mapped_column(Integer)
    lactate_threshold_pace_seconds_per_km: Mapped[int | None] = mapped_column(Integer)
    vo2max: Mapped[float | None] = mapped_column(Float)
    conservative_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    injury_notes: Mapped[str | None] = mapped_column(Text)
    health_conditions: Mapped[str | None] = mapped_column(Text)
    recovery_status: Mapped[str] = mapped_column(String(32), default="normal")

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


class RecoverySignalObservation(Base):
    __tablename__ = "recovery_signal_observations"
    __table_args__ = (
        CheckConstraint("metric_key IN ('sleep_duration_seconds', 'sleep_efficiency_pct', 'hrv_rmssd_ms', 'resting_heart_rate_bpm')", name="ck_recovery_signal_metric_key"),
        CheckConstraint("unit IN ('seconds', 'percent', 'ms', 'bpm')", name="ck_recovery_signal_unit"),
        CheckConstraint("source_kind IN ('manual', 'device_import', 'partner_sync')", name="ck_recovery_signal_source_kind"),
        CheckConstraint("quality IN ('high', 'medium', 'low')", name="ck_recovery_signal_quality"),
        CheckConstraint("quality_score IS NULL OR (quality_score >= 0 AND quality_score <= 1)", name="ck_recovery_signal_quality_score"),
        CheckConstraint("observed_at <= received_at", name="ck_recovery_signal_observed_received"),
        UniqueConstraint("user_id", "source_system", "metric_key", "source_record_id", name="uq_recovery_signal_source_record"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    metric_key: Mapped[str] = mapped_column(String(64), index=True)
    value_numeric: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(32))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    source_kind: Mapped[str] = mapped_column(String(32))
    source_system: Mapped[str] = mapped_column(String(64))
    source_label: Mapped[str] = mapped_column(String(100))
    source_record_id: Mapped[str] = mapped_column(String(255))
    quality: Mapped[str] = mapped_column(String(16))
    quality_score: Mapped[float | None] = mapped_column(Float)
    normalization_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="recovery_signal_observations")


class UploadDeletionJob(Base):
    __tablename__ = "upload_deletion_jobs"
    __table_args__ = (
        CheckConstraint("file_count >= 0", name="ck_upload_deletion_job_file_count"),
        UniqueConstraint("staged_name", name="uq_upload_deletion_job_staged_name"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    staged_name: Mapped[str] = mapped_column(String(100))
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


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
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
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
    derived_metrics: Mapped[list["DerivedActivityMetric"]] = relationship(back_populates="activity", cascade="all, delete-orphan")
    screenshots: Mapped[list["ActivityScreenshot"]] = relationship(back_populates="activity", cascade="all, delete-orphan")

    @property
    def sources(self) -> list["ActivityScreenshot"]:
        return self.screenshots


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

    @property
    def file_name(self) -> str | None:
        return Path(self.source.file_path).name if self.source and self.source.file_path else None

    @property
    def screen_type(self) -> str | None:
        return self.source.screen_type if self.source else None

    @property
    def source_app(self) -> str | None:
        return self.source.source_app if self.source else None

    @property
    def captured_at(self) -> datetime | None:
        return self.source.captured_at if self.source else None

    @property
    def notes(self) -> str | None:
        return self.source.notes if self.source else None

    @property
    def uploaded_at(self) -> datetime | None:
        return self.source.created_at if self.source else None


class DerivedActivityMetric(Base):
    __tablename__ = "derived_activity_metrics"
    __table_args__ = (UniqueConstraint("activity_id", "metric_key", name="uq_derived_activity_metric"),)

    activity_id: Mapped[int] = mapped_column(ForeignKey("activities.id", ondelete="CASCADE"), primary_key=True)
    metric_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    metric_value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(64))
    method: Mapped[str] = mapped_column(String(64))
    source_reference: Mapped[str | None] = mapped_column(String(255))
    input_hash: Mapped[str] = mapped_column(String(64))
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    activity: Mapped[Activity] = relationship(back_populates="derived_metrics")


class DailyTrainingLoad(Base):
    __tablename__ = "daily_training_loads"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True, index=True)
    load_value: Mapped[float] = mapped_column(Float, default=0.0)
    method: Mapped[str] = mapped_column(String(64), default="unavailable")
    duration_minutes: Mapped[float] = mapped_column(Float, default=0.0)
    activity_ids: Mapped[list[int] | None] = mapped_column(JSON)
    ctl: Mapped[float | None] = mapped_column(Float)
    atl: Mapped[float | None] = mapped_column(Float)
    tsb: Mapped[float | None] = mapped_column(Float)
    monotony_window_value: Mapped[float | None] = mapped_column(Float)
    strain_window_value: Mapped[float | None] = mapped_column(Float)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    user: Mapped[User] = relationship(back_populates="daily_training_loads")


class DailyReadinessCheckIn(Base, TimestampMixin):
    __tablename__ = "daily_readiness_checkins"
    __table_args__ = (
        CheckConstraint("weather_condition IS NULL OR weather_condition IN ('normal', 'heat', 'cold', 'storm', 'poor_air')", name="ck_daily_readiness_weather_condition"),
        CheckConstraint("surface_condition IS NULL OR surface_condition IN ('dry', 'wet', 'icy', 'uneven')", name="ck_daily_readiness_surface_condition"),
        CheckConstraint("available_time_minutes IS NULL OR (available_time_minutes >= 0 AND available_time_minutes <= 600)", name="ck_daily_readiness_available_time"),
        UniqueConstraint("user_id", "checkin_date", name="uq_daily_readiness_checkins_user_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    checkin_date: Mapped[date] = mapped_column(Date, index=True)
    sleep_quality_0_10: Mapped[int | None] = mapped_column(Integer)
    fatigue_0_10: Mapped[int | None] = mapped_column(Integer)
    soreness_0_10: Mapped[int | None] = mapped_column(Integer)
    stress_0_10: Mapped[int | None] = mapped_column(Integer)
    pain: Mapped[bool] = mapped_column(Boolean, default=False)
    pain_level_0_10: Mapped[int | None] = mapped_column(Integer)
    pain_notes: Mapped[str | None] = mapped_column(Text)
    illness_symptoms: Mapped[bool] = mapped_column(Boolean, default=False)
    illness_notes: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    weather_condition: Mapped[str | None] = mapped_column(String(32))
    surface_condition: Mapped[str | None] = mapped_column(String(32))
    available_time_minutes: Mapped[int | None] = mapped_column(Integer)
    recommendation_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    user: Mapped[User] = relationship(back_populates="daily_readiness_checkins")


class DailyReadinessActionPreview(Base):
    __tablename__ = "daily_readiness_action_previews"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("training_plans.id", ondelete="CASCADE"), index=True)
    workout_id: Mapped[int] = mapped_column(ForeignKey("training_plan_workouts.id", ondelete="CASCADE"), index=True)
    checkin_id: Mapped[int] = mapped_column(ForeignKey("daily_readiness_checkins.id", ondelete="CASCADE"), index=True)
    checkin_date: Mapped[date] = mapped_column(Date, index=True)
    action: Mapped[str] = mapped_column(String(64))
    rule_version: Mapped[str] = mapped_column(String(64))
    recommendation_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    preview_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    state_fingerprint: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recommendation_audit_id: Mapped[int | None] = mapped_column(ForeignKey("training_plan_recommendation_audits.id", ondelete="SET NULL"))
    plan_version_id: Mapped[int | None] = mapped_column(ForeignKey("plan_versions.id", ondelete="SET NULL"))
    audit_log_id: Mapped[int | None] = mapped_column(ForeignKey("audit_log.id", ondelete="SET NULL"))
    applied_response_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="daily_readiness_action_previews")


class CoachActionPreview(Base):
    __tablename__ = "coach_action_previews"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("training_plans.id", ondelete="CASCADE"), index=True)
    workout_id: Mapped[int] = mapped_column(ForeignKey("training_plan_workouts.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(64))
    rule_version: Mapped[str] = mapped_column(String(64))
    request_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    preview_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    state_fingerprint: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recommendation_audit_id: Mapped[int | None] = mapped_column(ForeignKey("training_plan_recommendation_audits.id", ondelete="SET NULL"))
    plan_version_id: Mapped[int | None] = mapped_column(ForeignKey("plan_versions.id", ondelete="SET NULL"))
    audit_log_id: Mapped[int | None] = mapped_column(ForeignKey("audit_log.id", ondelete="SET NULL"))
    coaching_event_id: Mapped[int | None] = mapped_column(ForeignKey("coaching_events.id", ondelete="SET NULL"))
    applied_response_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="coach_action_previews")


class PlanRollbackPreview(Base):
    __tablename__ = "plan_rollback_previews"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("training_plans.id", ondelete="CASCADE"), index=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("plan_versions.id", ondelete="CASCADE"), index=True)
    preview_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    state_fingerprint: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rollback_version_id: Mapped[int | None] = mapped_column(ForeignKey("plan_versions.id", ondelete="SET NULL"))
    recommendation_audit_id: Mapped[int | None] = mapped_column(ForeignKey("training_plan_recommendation_audits.id", ondelete="SET NULL"))
    audit_log_id: Mapped[int | None] = mapped_column(ForeignKey("audit_log.id", ondelete="SET NULL"))
    coaching_event_id: Mapped[int | None] = mapped_column(ForeignKey("coaching_events.id", ondelete="SET NULL"))
    applied_response_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="plan_rollback_previews")


class PlanRecalculationRequest(Base):
    __tablename__ = "plan_recalculation_requests"
    __table_args__ = (UniqueConstraint("user_id", "source_key", name="uq_plan_recalculation_user_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("training_plans.id", ondelete="SET NULL"), index=True)
    trigger_type: Mapped[str] = mapped_column(String(64), index=True)
    source_key: Mapped[str] = mapped_column(String(160))
    source_event_id: Mapped[int | None] = mapped_column(ForeignKey("coaching_events.id", ondelete="SET NULL"), index=True)
    input_fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="completed", index=True)
    assessment_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="plan_recalculation_requests")


class CoachingEvent(Base):
    __tablename__ = "coaching_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    event_version: Mapped[str] = mapped_column(String(32), default="v1")
    category: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("training_plans.id", ondelete="SET NULL"), index=True)
    workout_id: Mapped[int | None] = mapped_column(ForeignKey("training_plan_workouts.id", ondelete="SET NULL"), index=True)
    activity_id: Mapped[int | None] = mapped_column(ForeignKey("activities.id", ondelete="SET NULL"), index=True)
    checkin_id: Mapped[int | None] = mapped_column(ForeignKey("daily_readiness_checkins.id", ondelete="SET NULL"), index=True)
    feedback_id: Mapped[int | None] = mapped_column(ForeignKey("training_plan_workout_feedback.id", ondelete="SET NULL"), index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(128), index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="coaching_events")


class AthleteStateSnapshot(Base):
    __tablename__ = "athlete_state_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "local_date",
            "state_version",
            "input_fingerprint",
            name="uq_athlete_state_snapshot_input",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    local_date: Mapped[date] = mapped_column(Date, index=True)
    timezone: Mapped[str] = mapped_column(String(100))
    state_version: Mapped[str] = mapped_column(String(64))
    rule_version: Mapped[str] = mapped_column(String(64))
    input_fingerprint: Mapped[str] = mapped_column(String(64))
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    as_of_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    trigger_type: Mapped[str] = mapped_column(String(64), default="on_read")

    user: Mapped[User] = relationship(back_populates="athlete_state_snapshots")


class WeeklyReview(Base):
    __tablename__ = "weekly_reviews"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "week_start",
            "review_version",
            "input_fingerprint",
            name="uq_weekly_review_input",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("training_plans.id", ondelete="SET NULL"), index=True)
    week_start: Mapped[date] = mapped_column(Date, index=True)
    week_end: Mapped[date] = mapped_column(Date)
    timezone: Mapped[str] = mapped_column(String(100))
    review_version: Mapped[str] = mapped_column(String(64))
    rule_version: Mapped[str] = mapped_column(String(64))
    input_fingerprint: Mapped[str] = mapped_column(String(64))
    resolution_status: Mapped[str] = mapped_column(String(32), index=True)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    as_of_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    trigger_type: Mapped[str] = mapped_column(String(64), default="on_read")

    user: Mapped[User] = relationship(back_populates="weekly_reviews")


class WeeklyStrategyPreview(Base):
    __tablename__ = "weekly_strategy_previews"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("weekly_reviews.id", ondelete="CASCADE"), index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("training_plans.id", ondelete="CASCADE"), index=True)
    strategy: Mapped[str] = mapped_column(String(64), index=True)
    rule_version: Mapped[str] = mapped_column(String(64))
    request_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    preview_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    state_fingerprint: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recommendation_audit_id: Mapped[int | None] = mapped_column(ForeignKey("training_plan_recommendation_audits.id", ondelete="SET NULL"))
    plan_version_id: Mapped[int | None] = mapped_column(ForeignKey("plan_versions.id", ondelete="SET NULL"))
    audit_log_id: Mapped[int | None] = mapped_column(ForeignKey("audit_log.id", ondelete="SET NULL"))
    coaching_event_id: Mapped[int | None] = mapped_column(ForeignKey("coaching_events.id", ondelete="SET NULL"))
    applied_response_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="weekly_strategy_previews")


class CoachConversation(Base, TimestampMixin):
    __tablename__ = "coach_conversations"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'archived')", name="ck_coach_conversations_status"),
        CheckConstraint("surface IN ('overview')", name="ck_coach_conversations_surface"),
        UniqueConstraint("id", "user_id", name="uq_coach_conversations_id_user"),
    )

    # These IDs are generated by the service and intentionally carry no database sequence semantics.
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    surface: Mapped[str] = mapped_column(String(64))
    title: Mapped[str | None] = mapped_column(String(255))
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    user: Mapped[User] = relationship(back_populates="coach_conversations")
    messages: Mapped[list["CoachMessage"]] = relationship(back_populates="conversation", cascade="all, delete-orphan", overlaps="coach_messages,user")
    llm_attempts: Mapped[list["CoachLlmAttempt"]] = relationship(back_populates="conversation", cascade="all, delete-orphan", overlaps="coach_llm_attempts,llm_attempts,message,user")


class CoachMessage(Base):
    __tablename__ = "coach_messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="ck_coach_messages_role"),
        CheckConstraint("turn_status IN ('pending', 'completed')", name="ck_coach_messages_turn_status"),
        CheckConstraint("role = 'user' OR turn_status = 'completed'", name="ck_coach_messages_assistant_completed"),
        ForeignKeyConstraint(["conversation_id", "user_id"], ["coach_conversations.id", "coach_conversations.user_id"], ondelete="CASCADE", name="fk_coach_messages_conversation_owner"),
        UniqueConstraint("id", "user_id", name="uq_coach_messages_id_user"),
        UniqueConstraint("id", "user_id", "conversation_id", name="uq_coach_messages_id_user_conversation"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(32))
    turn_status: Mapped[str] = mapped_column(String(32), default="completed", index=True)
    content: Mapped[str | None] = mapped_column(Text)
    content_redacted: Mapped[bool] = mapped_column(Boolean, default=False)
    response_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    user: Mapped[User] = relationship(back_populates="coach_messages", overlaps="conversation,messages")
    conversation: Mapped[CoachConversation] = relationship(back_populates="messages", overlaps="coach_messages,user")
    source_for_memory: Mapped[list["CoachMemory"]] = relationship(back_populates="source_message", overlaps="coach_memory,user")
    llm_attempts: Mapped[list["CoachLlmAttempt"]] = relationship(back_populates="message", overlaps="coach_llm_attempts,conversation,llm_attempts,user")


class CoachMemory(Base, TimestampMixin):
    __tablename__ = "coach_memory"
    __table_args__ = (
        CheckConstraint("memory_key IN ('communication_style', 'coaching_focus', 'confirmed_available_days')", name="ck_coach_memory_key"),
        CheckConstraint("status IN ('confirmed')", name="ck_coach_memory_status"),
        ForeignKeyConstraint(["source_message_id", "user_id"], ["coach_messages.id", "coach_messages.user_id"], ondelete="CASCADE", name="fk_coach_memory_source_owner"),
        UniqueConstraint("user_id", "memory_key", name="uq_coach_memory_user_key"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    memory_key: Mapped[str] = mapped_column(String(128))
    value_json: Mapped[Any] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="confirmed")
    source_message_id: Mapped[int | None] = mapped_column(BigInteger, index=True)

    user: Mapped[User] = relationship(back_populates="coach_memory", overlaps="source_for_memory")
    source_message: Mapped[CoachMessage | None] = relationship(back_populates="source_for_memory", overlaps="coach_memory,user")


class CoachLlmAttempt(Base):
    __tablename__ = "coach_llm_attempts"
    __table_args__ = (
        CheckConstraint("attempt_number > 0", name="ck_coach_llm_attempt_number"),
        CheckConstraint("status IN ('success', 'failed')", name="ck_coach_llm_attempt_status"),
        CheckConstraint("request_phase IN ('initial', 'repair')", name="ck_coach_llm_attempt_phase"),
        CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="ck_coach_llm_attempt_duration"),
        ForeignKeyConstraint(["conversation_id", "user_id"], ["coach_conversations.id", "coach_conversations.user_id"], ondelete="CASCADE", name="fk_coach_llm_attempt_conversation_owner"),
        ForeignKeyConstraint(["message_id", "user_id", "conversation_id"], ["coach_messages.id", "coach_messages.user_id", "coach_messages.conversation_id"], ondelete="CASCADE", name="fk_coach_llm_attempt_message_owner"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[str] = mapped_column(String(64), index=True)
    message_id: Mapped[int] = mapped_column(BigInteger, index=True)
    provider: Mapped[str] = mapped_column(String(64))
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("llm_provider_settings.id", ondelete="SET NULL"))
    model: Mapped[str | None] = mapped_column(String(255))
    attempt_number: Mapped[int] = mapped_column(Integer)
    request_phase: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), index=True)
    failure_class: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    request_fingerprint: Mapped[str | None] = mapped_column(String(128))
    output_fingerprint: Mapped[str | None] = mapped_column(String(128))
    validation_errors: Mapped[list[Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    user: Mapped[User] = relationship(back_populates="coach_llm_attempts", overlaps="conversation,llm_attempts,message")
    conversation: Mapped[CoachConversation] = relationship(back_populates="llm_attempts", overlaps="coach_llm_attempts,llm_attempts,message,user")
    message: Mapped[CoachMessage] = relationship(back_populates="llm_attempts", overlaps="coach_llm_attempts,conversation,llm_attempts,user")


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
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    recognition_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recognition_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recognition_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    recognition_attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    recognition_max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    recognition_locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    recognition_locked_by: Mapped[str | None] = mapped_column(String(100))
    recognition_last_error: Mapped[str | None] = mapped_column(Text)

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
    provider_id: Mapped[int | None] = mapped_column(Integer, index=True)
    model: Mapped[str | None] = mapped_column(String(255))
    attempt_number: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    failure_class: Mapped[str | None] = mapped_column(String(64))
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
    race_distance_km: Mapped[float | None] = mapped_column(Float)
    target_date: Mapped[date | None] = mapped_column(Date, index=True)
    target_time_seconds: Mapped[int | None] = mapped_column(Integer)
    priority: Mapped[str | None] = mapped_column(String(16))
    course_notes: Mapped[str | None] = mapped_column(Text)
    training_plan_id: Mapped[int | None] = mapped_column(ForeignKey("training_plans.id", ondelete="SET NULL"), index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(64), default="active")

    user: Mapped[User] = relationship(back_populates="goals")
    training_plan: Mapped["TrainingPlan | None"] = relationship(back_populates="goals")


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
    goals: Mapped[list[RunningGoal]] = relationship(back_populates="training_plan")
    versions: Mapped[list["TrainingPlanVersion"]] = relationship(back_populates="plan", cascade="all, delete-orphan")


class TrainingPlanVersion(Base):
    __tablename__ = "plan_versions"
    __table_args__ = (UniqueConstraint("plan_id", "version_number", name="uq_plan_versions_plan_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("training_plans.id", ondelete="CASCADE"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(64))
    summary: Mapped[str | None] = mapped_column(Text)
    snapshot_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    pre_snapshot_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    post_snapshot_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    rollback_of_version_id: Mapped[int | None] = mapped_column(ForeignKey("plan_versions.id", ondelete="SET NULL"), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    plan: Mapped[TrainingPlan] = relationship(back_populates="versions")


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
    blocks: Mapped[list["TrainingPlanWorkoutBlock"]] = relationship(back_populates="workout", cascade="all, delete-orphan")


class TrainingPlanWorkoutBlock(Base):
    __tablename__ = "planned_workout_blocks"
    __table_args__ = (UniqueConstraint("workout_id", "block_index", name="uq_planned_workout_block"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workout_id: Mapped[int] = mapped_column(ForeignKey("training_plan_workouts.id", ondelete="CASCADE"), index=True)
    block_index: Mapped[int] = mapped_column(Integer)
    block_type: Mapped[str] = mapped_column(String(64))
    repeat_count: Mapped[int] = mapped_column(Integer, default=1)
    target_distance_km: Mapped[float | None] = mapped_column(Float)
    target_duration_seconds: Mapped[int | None] = mapped_column(Integer)
    target_pace_min_seconds_per_km: Mapped[int | None] = mapped_column(Integer)
    target_pace_max_seconds_per_km: Mapped[int | None] = mapped_column(Integer)
    target_hr_min_bpm: Mapped[int | None] = mapped_column(Integer)
    target_hr_max_bpm: Mapped[int | None] = mapped_column(Integer)
    target_rpe_min: Mapped[int | None] = mapped_column(Integer)
    target_rpe_max: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)

    workout: Mapped[TrainingPlanWorkout] = relationship(back_populates="blocks")


class TrainingPlanWorkoutFeedback(Base, TimestampMixin):
    __tablename__ = "training_plan_workout_feedback"
    __table_args__ = (UniqueConstraint("workout_id", name="uq_training_plan_workout_feedback_workout"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workout_id: Mapped[int] = mapped_column(ForeignKey("training_plan_workouts.id", ondelete="CASCADE"), index=True)
    activity_id: Mapped[int | None] = mapped_column(ForeignKey("activities.id", ondelete="SET NULL"), index=True)
    completion_status: Mapped[str | None] = mapped_column(String(32))
    rpe: Mapped[int | None] = mapped_column(Integer)
    soreness_0_10: Mapped[int | None] = mapped_column(Integer)
    fatigue: Mapped[int | None] = mapped_column(Integer)
    pain: Mapped[bool] = mapped_column(Boolean, default=False)
    pain_level: Mapped[int | None] = mapped_column(Integer)
    sleep_quality_0_10: Mapped[int | None] = mapped_column(Integer)
    sleep_quality: Mapped[int | None] = mapped_column(Integer)
    pain_notes: Mapped[str | None] = mapped_column(Text)
    user_notes: Mapped[str | None] = mapped_column(Text)
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


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    user: Mapped[User] = relationship(back_populates="audit_logs")
