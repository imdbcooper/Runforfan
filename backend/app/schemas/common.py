from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, StrictInt, model_validator


Date = date


class UserOut(BaseModel):
    id: int
    telegram_id: int | None = None
    username: str | None = None
    display_name: str
    is_demo: bool

    model_config = {"from_attributes": True}


class AuthToken(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class SegmentOut(BaseModel):
    id: int
    segment_index: int
    distance_km: float
    duration_seconds: int
    pace_seconds_per_km: int
    average_heart_rate_bpm: int | None = None
    average_cadence_spm: int | None = None

    model_config = {"from_attributes": True}


class SplitBlockOut(BaseModel):
    id: int
    block_index: int
    start_km: float
    end_km: float
    distance_km: float
    duration_seconds: int
    cumulative_duration_seconds: int | None = None
    notes: str | None = None

    model_config = {"from_attributes": True}


class WorkoutBlockOut(BaseModel):
    id: int
    block_index: int
    block_type: str
    title: str
    distance_km: float | None = None
    duration_seconds: int
    pace_seconds_per_km: int | None = None
    average_heart_rate_bpm: int | None = None
    average_cadence_spm: int | None = None
    notes: str | None = None

    model_config = {"from_attributes": True}


class ActivityOut(BaseModel):
    id: int
    activity_type: str
    title: str
    started_at: datetime | None = None
    distance_km: float | None = None
    duration_seconds: int
    calories_kcal: int | None = None
    average_pace_seconds_per_km: int | None = None
    fastest_pace_seconds_per_km: int | None = None
    average_speed_kmh: float | None = None
    average_cadence_spm: int | None = None
    average_stride_cm: int | None = None
    steps_count: int | None = None
    average_heart_rate_bpm: int | None = None
    elevation_gain_m: float | None = None
    elevation_loss_m: float | None = None
    aerobic_training_stress: float | None = None
    aerobic_training_effect: str | None = None
    segments: list[SegmentOut] = []
    split_blocks: list[SplitBlockOut] = []
    workout_blocks: list[WorkoutBlockOut] = []

    model_config = {"from_attributes": True}


class GoalCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    goal_type: str = "custom"
    target_value: float | None = None
    unit: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    reason: str | None = None


class GoalOut(GoalCreate):
    id: int
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AthleteProfileUpdate(BaseModel):
    date_of_birth: date | None = None
    sex: str | None = Field(default=None, pattern="^(male|female|other|unspecified)$")
    height_cm: float | None = Field(default=None, ge=80, le=260)
    weight_kg: float | None = Field(default=None, ge=25, le=250)
    timezone: str | None = None
    locale: str | None = None
    resting_heart_rate_bpm: int | None = Field(default=None, ge=25, le=120)
    max_heart_rate_bpm: int | None = Field(default=None, ge=80, le=240)
    max_hr_source: str | None = Field(default=None, pattern="^(measured|manual|tanaka_estimated)$")
    lactate_threshold_hr_bpm: int | None = Field(default=None, ge=60, le=230)
    lactate_threshold_pace_seconds_per_km: int | None = Field(default=None, ge=120, le=1200)
    conservative_mode: bool | None = None
    injury_notes: str | None = None


class CalculationOut(BaseModel):
    value: float | int | None = None
    unit: str
    method: str
    confidence: str
    source_reference: str


class AthleteProfileOut(AthleteProfileUpdate):
    id: int
    user_id: int
    sex: str
    timezone: str | None = None
    locale: str | None = None
    conservative_mode: bool
    estimated_max_heart_rate: CalculationOut | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProfileCompletenessOut(BaseModel):
    score: float
    missing: list[str]
    can_calculate_hr_zones: bool
    can_calculate_hrr_zones: bool
    can_calculate_pace_zones: bool
    confidence: str


class SafetyCheckOut(BaseModel):
    conservative_mode: bool
    warnings: list[str]
    message: str


class AthleteMeasurementCreate(BaseModel):
    measurement_type: str = Field(pattern="^(weight|resting_hr|max_hr|lactate_threshold|vo2max|note)$")
    measured_at: datetime | None = None
    value_numeric: float | None = None
    value_json: dict | None = None
    source: str = Field(default="manual", pattern="^(manual|screenshot|device|calculated)$")
    confidence: float | None = Field(default=None, ge=0, le=1)
    notes: str | None = None


class AthleteMeasurementTimelineOut(BaseModel):
    id: int
    user_id: int
    source_model: str
    measurement_type: str
    measured_at: datetime | None = None
    value_numeric: float | None = None
    value_json: dict | None = None
    source: str
    confidence: float | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


class ZoneOut(BaseModel):
    id: int | None = None
    zone_type: str
    method: str
    zone_key: str
    label: str | None = None
    lower_value: float | None = None
    upper_value: float | None = None
    unit: str
    confidence: str
    source_reference: str | None = None
    is_active: bool = True

    model_config = {"from_attributes": True}


class ZoneWrite(BaseModel):
    zone_key: str = Field(min_length=1, max_length=64)
    lower_value: float | None = None
    upper_value: float | None = None
    unit: str = Field(min_length=1, max_length=64)
    label: str | None = None

    @model_validator(mode="after")
    def validate_range(self):
        if self.lower_value is None and self.upper_value is None:
            raise ValueError("zone must define lower_value or upper_value")
        if self.lower_value is not None and self.upper_value is not None and self.lower_value > self.upper_value:
            raise ValueError("lower_value must be less than or equal to upper_value")
        return self


class ZonesOut(BaseModel):
    hr: list[ZoneOut]
    pace: list[ZoneOut]
    rpe: list[ZoneOut]
    metadata: dict


class LlmProviderCreate(BaseModel):
    provider: str = Field(pattern="^(openai|anthropic)$")
    display_name: str = Field(min_length=1, max_length=255)
    base_url: str | None = None
    model: str = Field(min_length=1, max_length=255)
    api_key: str | None = None
    is_default: bool = False


class LlmProviderOut(BaseModel):
    id: int
    provider: str
    display_name: str
    base_url: str | None = None
    model: str
    is_default: bool
    is_active: bool
    has_api_key: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class PlanGenerateRequest(BaseModel):
    title: str = "Тренировочная программа"
    goal_type: str = "marathon"
    race_distance_km: float | None = Field(default=42.2, ge=1, le=100)
    target_date: date | None = None
    target_time_seconds: StrictInt | None = Field(default=None, ge=60, le=172800)
    priority: str = Field(default="b", pattern="^(a|b|c|low|medium|high)$")
    available_days_per_week: int = Field(default=4, ge=2, le=7)
    current_weekly_distance_km: float | None = Field(default=None, ge=0, le=250)
    longest_recent_run_km: float | None = Field(default=None, ge=0, le=100)
    recent_race_distance_km: float | None = Field(default=None, ge=1, le=100)
    recent_race_time_seconds: StrictInt | None = Field(default=None, ge=60, le=172800)
    preferred_weekdays: list[StrictInt] | None = Field(default=None, max_length=7)
    time_budget_minutes_per_week: StrictInt | None = Field(default=None, ge=30, le=5000)
    intensity_mode: str = Field(default="mixed", pattern="^(hr|pace|rpe|mixed)$")
    injury: bool = False
    no_hard_workouts: bool = False
    max_long_run_km: float | None = Field(default=None, ge=1, le=100)
    max_long_run_duration_minutes: StrictInt | None = Field(default=None, ge=15, le=600)
    terrain: str | None = Field(default=None, max_length=100)
    activate: bool = False

    @model_validator(mode="after")
    def validate_preferred_weekdays(self):
        if self.preferred_weekdays:
            values = list(self.preferred_weekdays)
            if any(value < 1 or value > 7 for value in values):
                raise ValueError("preferred_weekdays must use ISO weekdays 1-7")
            if len(set(values)) != len(values):
                raise ValueError("preferred_weekdays must be unique")
        return self


class PlanBuilderBaselineOut(BaseModel):
    observed_weekly_volume_km: list[float]
    current_weekly_volume_km: float
    current_weekly_volume_source: str
    recent_long_run_km: float | None = None
    history_span_days: int
    activity_count: int
    training_age_level: str
    confidence: str


class PlanBuilderWeeklyVolumeOut(BaseModel):
    week_index: int
    planned_distance_km: float
    long_run_km: float
    hard_sessions: int


class PlanBuilderRiskFlagOut(BaseModel):
    code: str
    severity: str
    message: str
    reasons: list[str] = Field(default_factory=list)


class PlanBuilderPreviewWorkoutOut(BaseModel):
    week_index: int
    day_index: int
    scheduled_date: Date
    workout_type: str
    title: str
    distance_km: float | None = None
    intensity: str | None = None
    description: str | None = None


class PlanBuilderPreviewOut(BaseModel):
    title: str
    goal_type: str
    race_distance_km: float | None = None
    target_date: date | None = None
    target_time_seconds: int | None = None
    priority: str
    weeks: int
    available_days_per_week: int
    preferred_weekdays: list[int] = Field(default_factory=list)
    intensity_mode: str
    start_date: date
    current_weekly_distance_km: float
    peak_weekly_distance_km: float
    constraints: dict = Field(default_factory=dict)
    baseline: PlanBuilderBaselineOut
    weekly_volume_curve: list[PlanBuilderWeeklyVolumeOut]
    intensity_split: dict[str, float]
    risk_flags: list[PlanBuilderRiskFlagOut] = Field(default_factory=list)
    workouts: list[PlanBuilderPreviewWorkoutOut]
    explanation: str


class PlanUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    status: str | None = Field(default=None, pattern="^(draft|active|completed|archived)$")


class PlanWorkoutUpdate(BaseModel):
    scheduled_date: date | None = None
    status: str | None = Field(default=None, pattern="^(planned|done|missed|skipped|rescheduled)$")
    completed_activity_id: int | None = None


class PlanWorkoutFeedbackIn(BaseModel):
    rpe: StrictInt | None = Field(default=None, ge=0, le=10)
    fatigue: StrictInt | None = Field(default=None, ge=0, le=10)
    pain: bool = False
    pain_level: StrictInt | None = Field(default=None, ge=0, le=10)
    sleep_quality: StrictInt | None = Field(default=None, ge=0, le=10)
    notes: str | None = Field(default=None, max_length=1000)


class PlanWorkoutFeedbackOut(PlanWorkoutFeedbackIn):
    id: int
    workout_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PlanWorkoutExecutionScoreOut(BaseModel):
    score: float | None = None
    status: str
    volume_score: float | None = None
    subjective_risk: str = "unknown"
    flags: list[str] = Field(default_factory=list)


class PlanAdherenceOut(BaseModel):
    total_workouts: int
    done_workouts: int
    missed_workouts: int
    skipped_workouts: int
    linked_workouts: int = 0
    unlinked_done_workouts: int = 0
    planned_distance_km: float
    completed_distance_km: float
    completion_rate: float
    distance_completion_rate: float
    warnings: list[str] = Field(default_factory=list)


class PlanWeeklyAdherenceOut(PlanAdherenceOut):
    week_index: int
    planned_workouts: int
    total_workouts: int | None = None


class PlanWorkoutOut(BaseModel):
    id: int
    plan_id: int
    week_index: int
    day_index: int
    scheduled_date: date | None = None
    status: str = "planned"
    completed_activity_id: int | None = None
    actual_distance_km: float | None = None
    actual_duration_seconds: int | None = None
    workout_type: str
    title: str
    distance_km: float | None = None
    duration_seconds: int | None = None
    intensity: str | None = None
    description: str | None = None
    feedback: PlanWorkoutFeedbackOut | None = None
    execution_score: PlanWorkoutExecutionScoreOut | None = None

    model_config = {"from_attributes": True}


class PlanWeekSummaryOut(BaseModel):
    week_index: int
    planned_distance_km: float
    planned_duration_seconds: int | None = None
    completed_distance_km: float
    completed_duration_seconds: int
    completion_rate: float
    distance_completion_rate: float
    planned_time_label: str
    hard_sessions: int
    long_run_km: float | None = None
    deload: bool = False
    workouts: list[PlanWorkoutOut] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PlanActivityMatchCandidateOut(BaseModel):
    activity: ActivityOut
    score: float
    confidence: str
    reasons: list[str]
    date_delta_days: int | None = None
    distance_delta_km: float | None = None


class PlanWorkoutMatchCandidateOut(BaseModel):
    workout: PlanWorkoutOut
    score: float
    confidence: str
    reasons: list[str]
    date_delta_days: int | None = None
    distance_delta_km: float | None = None


class PlanRecommendationOut(BaseModel):
    type: str
    severity: str
    title: str
    message: str
    workout_id: int | None = None
    week_index: int | None = None
    reasons: list[str]
    suggested_payload: dict | None = None


class PlanRecommendationsMetricsOut(BaseModel):
    completion_rate: float
    distance_completion_rate: float
    missed_recent_workouts: int
    unlinked_done_workouts: int
    planned_distance_km: float
    completed_distance_km: float
    recent_completed_distance_km: float
    upcoming_planned_distance_km: float


class PlanRecommendationsOut(BaseModel):
    plan_id: int
    status: str
    generated_at: datetime
    summary: str
    metrics: PlanRecommendationsMetricsOut
    recommendations: list[PlanRecommendationOut]


class PlanRecommendationChangeOut(BaseModel):
    workout_id: int | None = None
    field: str
    before: object | None = None
    after: object | None = None
    reason: str | None = None


class PlanRecommendationPreviewOut(BaseModel):
    plan_id: int
    generated_at: datetime
    changes: list[PlanRecommendationChangeOut]
    skipped: list[dict] = Field(default_factory=list)
    recommendations: list[PlanRecommendationOut]


class PlanRecommendationApplyRequest(BaseModel):
    changes: list[PlanRecommendationChangeOut] | None = None


class PlanRecommendationAuditOut(BaseModel):
    id: int
    plan_id: int
    action: str
    status: str
    recommendations_snapshot: dict | None = None
    preview_changes: dict | None = None
    applied_changes: dict | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PlanWorkoutLinkActivityRequest(BaseModel):
    activity_id: int


class PlanOut(BaseModel):
    id: int
    title: str
    goal_type: str
    race_distance_km: float | None = None
    target_date: date | None = None
    target_time_seconds: int | None = None
    available_days_per_week: int
    status: str
    explanation: str | None = None
    workouts: list[PlanWorkoutOut]
    adherence: PlanAdherenceOut | None = None
    weekly_adherence: list[PlanWeeklyAdherenceOut] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class CurrentWeekOut(BaseModel):
    plan_id: int | None = None
    plan_title: str | None = None
    plan_status: str | None = None
    week_index: int | None = None
    week_start: date
    week_end: date
    today: date
    status: str
    message: str
    workouts: list[PlanWorkoutOut] = Field(default_factory=list)
    adherence: PlanAdherenceOut | None = None
    today_workout: PlanWorkoutOut | None = None
    next_workout: PlanWorkoutOut | None = None


class DashboardPlanSummaryOut(BaseModel):
    id: int
    title: str
    status: str
    goal_type: str
    race_distance_km: float | None = None
    target_date: date | None = None
    adherence: PlanAdherenceOut | None = None


class DashboardReadinessOut(BaseModel):
    status: str
    message: str
    factors: list[str] = Field(default_factory=list)


class DashboardAlertOut(BaseModel):
    severity: str
    title: str
    message: str
    action: str | None = None


class DashboardRecommendationSummaryOut(BaseModel):
    status: str
    summary: str
    recommendations: list[PlanRecommendationOut] = Field(default_factory=list)


class DashboardSummaryOut(BaseModel):
    generated_at: datetime
    today: date
    analytics: dict
    active_plan: DashboardPlanSummaryOut | None = None
    current_week: CurrentWeekOut
    weekly_snapshot: PlanAdherenceOut | None = None
    today_workout: PlanWorkoutOut | None = None
    next_workout: PlanWorkoutOut | None = None
    profile_completeness: ProfileCompletenessOut
    safety: SafetyCheckOut
    readiness: DashboardReadinessOut
    alerts: list[DashboardAlertOut] = Field(default_factory=list)
    recommendations: DashboardRecommendationSummaryOut | None = None
    pending_imports_count: int = 0
    provider_count: int = 0
    recent_activities: list[ActivityOut] = Field(default_factory=list)


class CalendarEventOut(BaseModel):
    id: str
    kind: str
    date: Date
    title: str
    status: str | None = None
    planned_workout_id: int | None = None
    linked_activity_id: int | None = None
    plan_id: int | None = None
    plan_title: str | None = None
    workout_type: str | None = None
    distance_km: float | None = None
    duration_seconds: int | None = None
    execution_score: PlanWorkoutExecutionScoreOut | None = None
    workout: PlanWorkoutOut | None = None
    activity: ActivityOut | None = None


class CalendarWarningOut(BaseModel):
    severity: str
    title: str
    message: str
    date: Date | None = None
    planned_workout_ids: list[int] = Field(default_factory=list)


class CalendarSummaryOut(BaseModel):
    planned_workouts: int
    done_workouts: int
    missed_workouts: int
    skipped_workouts: int
    activities: int
    linked_activities: int
    unlinked_activities: int
    planned_distance_km: float
    activity_distance_km: float


class CalendarOut(BaseModel):
    from_date: date
    to_date: date
    events: list[CalendarEventOut] = Field(default_factory=list)
    warnings: list[CalendarWarningOut] = Field(default_factory=list)
    summary: CalendarSummaryOut


class PlanRecommendationApplyOut(BaseModel):
    plan_id: int
    audit_id: int
    changes: list[PlanRecommendationChangeOut]
    skipped: list[dict] = Field(default_factory=list)
    plan: PlanOut
