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


class DerivedActivityMetricOut(BaseModel):
    activity_id: int
    metric_key: str
    metric_value: float
    unit: str
    method: str
    source_reference: str | None = None
    input_hash: str
    computed_at: datetime

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
    derived_metrics: list[DerivedActivityMetricOut] = []

    model_config = {"from_attributes": True}


class GoalCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    goal_type: str = Field(default="custom_habit", pattern="^(race|weekly_consistency|monthly_distance|long_run|custom_habit|health|custom)$")
    target_value: float | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=64)
    period_start: date | None = None
    period_end: date | None = None
    race_distance_km: float | None = Field(default=None, ge=0.1, le=250)
    target_date: date | None = None
    target_time_seconds: StrictInt | None = Field(default=None, ge=60, le=172800)
    priority: str | None = Field(default=None, pattern="^(a|b|c|high|medium|low)$")
    course_notes: str | None = Field(default=None, max_length=2000)
    training_plan_id: StrictInt | None = Field(default=None, ge=1)
    reason: str | None = Field(default=None, max_length=2000)

class GoalUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    goal_type: str | None = Field(default=None, pattern="^(race|weekly_consistency|monthly_distance|long_run|custom_habit|health|custom)$")
    target_value: float | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=64)
    period_start: date | None = None
    period_end: date | None = None
    race_distance_km: float | None = Field(default=None, ge=0.1, le=250)
    target_date: date | None = None
    target_time_seconds: StrictInt | None = Field(default=None, ge=60, le=172800)
    priority: str | None = Field(default=None, pattern="^(a|b|c|high|medium|low)$")
    course_notes: str | None = Field(default=None, max_length=2000)
    training_plan_id: StrictInt | None = Field(default=None, ge=1)
    reason: str | None = Field(default=None, max_length=2000)
    status: str | None = Field(default=None, pattern="^(active|paused|completed|missed|archived)$")


class GoalCompleteIn(BaseModel):
    status: str = Field(default="completed", pattern="^(completed|missed|archived)$")
    reason: str | None = Field(default=None, max_length=2000)


class GoalOut(GoalCreate):
    id: int
    status: str
    created_at: datetime
    updated_at: datetime
    progress: dict[str, object] = Field(default_factory=dict)
    milestones: list[dict[str, object]] = Field(default_factory=list)
    plan: dict[str, object] | None = None
    current_fitness: dict[str, object] | None = None
    predicted_time_range: dict[str, object] | None = None

    model_config = {"from_attributes": True}


class AthleteProfileUpdate(BaseModel):
    date_of_birth: date | None = None
    sex: str | None = Field(default=None, pattern="^(male|female|other|unspecified)$")
    height_cm: float | None = Field(default=None, ge=80, le=260)
    weight_kg: float | None = Field(default=None, ge=25, le=250)
    timezone: str | None = None
    locale: str | None = None
    unit_system: str | None = Field(default=None, pattern="^(metric|imperial)$")
    preferred_weekdays: list[StrictInt] | None = Field(default=None, max_length=7)
    long_run_weekday: StrictInt | None = Field(default=None, ge=1, le=7)
    max_run_duration_minutes: StrictInt | None = Field(default=None, ge=15, le=600)
    resting_heart_rate_bpm: int | None = Field(default=None, ge=25, le=120)
    max_heart_rate_bpm: int | None = Field(default=None, ge=80, le=240)
    max_hr_source: str | None = Field(default=None, pattern="^(measured|manual|tanaka_estimated)$")
    lactate_threshold_hr_bpm: int | None = Field(default=None, ge=60, le=230)
    lactate_threshold_pace_seconds_per_km: int | None = Field(default=None, ge=120, le=1200)
    vo2max: float | None = Field(default=None, ge=10, le=100)
    conservative_mode: bool | None = None
    injury_notes: str | None = None
    health_conditions: str | None = None
    recovery_status: str | None = Field(default=None, pattern="^(fresh|normal|tired|strained|injured|unknown)$")

    @model_validator(mode="after")
    def validate_profile_weekdays(self):
        if self.preferred_weekdays:
            values = list(self.preferred_weekdays)
            if any(value < 1 or value > 7 for value in values):
                raise ValueError("preferred_weekdays must use ISO weekdays 1-7")
            if len(set(values)) != len(values):
                raise ValueError("preferred_weekdays must be unique")
        if self.long_run_weekday and self.preferred_weekdays and self.long_run_weekday not in self.preferred_weekdays:
            raise ValueError("long_run_weekday must be one of preferred_weekdays")
        return self


class CalculationOut(BaseModel):
    value: float | int | None = None
    unit: str
    method: str
    confidence: str
    source_reference: str


class AnalyticsPeriodOut(BaseModel):
    from_date: date | None = None
    to_date: date | None = None
    label: str


class AnalyticsActivityHighlightOut(BaseModel):
    id: int
    title: str
    started_at: datetime | None = None
    distance_km: float | None = None
    duration_seconds: int | None = None
    average_pace_seconds_per_km: int | None = None
    average_heart_rate_bpm: int | None = None


class AnalyticsMonthOut(BaseModel):
    month: str
    distance_km: float
    duration_seconds: int
    count: int


class AnalyticsConsistencyOut(BaseModel):
    training_days: int
    training_days_per_week: float
    missed_planned_sessions: int


class AnalyticsAdherenceOut(BaseModel):
    total_workouts: int
    done_workouts: int
    missed_workouts: int
    skipped_workouts: int
    linked_workouts: int
    unlinked_done_workouts: int
    planned_distance_km: float
    completed_distance_km: float
    planned_duration_seconds: int = 0
    completed_duration_seconds: int = 0
    completion_rate: float
    distance_completion_rate: float
    duration_completion_rate: float = 0
    support_workouts: int = 0
    warnings: list[str] = Field(default_factory=list)


class AnalyticsBestEffortOut(BaseModel):
    target_distance_km: float
    activity_id: int
    title: str
    started_at: datetime | None = None
    source: str
    confidence: str
    distance_km: float
    duration_seconds: int
    pace_seconds_per_km: int
    estimated_vdot: CalculationOut | None = None


class AnalyticsSummaryOut(BaseModel):
    period: AnalyticsPeriodOut
    activity_count: int
    total_distance_km: float
    total_duration_seconds: int
    weighted_average_pace_seconds_per_km: int | None = None
    average_heart_rate_bpm: int | None = None
    training_load: float | None = None
    load_method: str
    longest_activity_id: int | None = None
    longest_distance_km: float | None = None
    fastest_activity_id: int | None = None
    fastest_average_pace_seconds_per_km: int | None = None
    longest_activity: AnalyticsActivityHighlightOut | None = None
    fastest_activity: AnalyticsActivityHighlightOut | None = None
    adherence: AnalyticsAdherenceOut | None = None
    consistency: AnalyticsConsistencyOut
    best_efforts: list[AnalyticsBestEffortOut] = Field(default_factory=list)
    estimated_vdot: CalculationOut | None = None
    estimated_vdot_activity_id: int | None = None
    manual_vo2max: CalculationOut | None = None
    months: list[AnalyticsMonthOut] = Field(default_factory=list)


class AnalyticsTimeseriesPointOut(BaseModel):
    period_start: date
    period_label: str
    value: float | int | None = None
    distance_km: float
    duration_seconds: int
    count: int
    weighted_average_pace_seconds_per_km: int | None = None
    average_heart_rate_bpm: int | None = None
    training_load: float | None = None


class AnalyticsTimeseriesOut(BaseModel):
    metric: str
    granularity: str
    points: list[AnalyticsTimeseriesPointOut] = Field(default_factory=list)


class AnalyticsInsightOut(BaseModel):
    severity: str
    title: str
    message: str
    reasons: list[str] = Field(default_factory=list)


class TrainingLoadDailyPointOut(BaseModel):
    date: Date
    load: float
    load_method: str
    load_methods: list[str] = Field(default_factory=list)
    distance_km: float
    duration_seconds: int
    activity_count: int
    srpe_count: int = 0
    hard_session: bool = False
    hard_reasons: list[str] = Field(default_factory=list)
    recovery_day: bool = False


class TrainingLoadDailyOut(BaseModel):
    period: AnalyticsPeriodOut
    method: str
    points: list[TrainingLoadDailyPointOut] = Field(default_factory=list)


class TrainingLoadWeeklyPointOut(BaseModel):
    week_start: Date
    week_label: str
    load: float
    load_method: str
    distance_km: float
    duration_seconds: int
    activity_count: int
    hard_sessions: int
    recovery_days: int
    long_run_share: float | None = None
    monotony: float | None = None
    strain: float | None = None


class TrainingLoadWeeklyOut(BaseModel):
    period: AnalyticsPeriodOut
    method: str
    points: list[TrainingLoadWeeklyPointOut] = Field(default_factory=list)


class TrainingLoadFitnessFatiguePointOut(BaseModel):
    date: Date
    load: float
    ctl: float
    atl: float
    tsb: float


class TrainingLoadFitnessFatigueOut(BaseModel):
    period: AnalyticsPeriodOut
    method: str
    explanation: str
    current: dict[str, CalculationOut]
    points: list[TrainingLoadFitnessFatiguePointOut] = Field(default_factory=list)


class TrainingLoadWarningOut(BaseModel):
    severity: str
    title: str
    message: str
    reasons: list[str] = Field(default_factory=list)
    metric: str | None = None
    value: float | None = None
    threshold: float | None = None


class PerformanceResultCreate(BaseModel):
    result_type: str = Field(default="race", pattern="^(race|time_trial)$")
    name: str = Field(default="Race result", min_length=1, max_length=255)
    result_date: datetime | None = None
    distance_km: float = Field(gt=0, le=500)
    duration_seconds: StrictInt = Field(gt=0, le=172800)
    activity_id: int | None = None
    source: str = Field(default="manual", pattern="^(manual|activity|device|import)$")
    terrain: str = Field(default="road", pattern="^(road|track|trail|mixed|treadmill|unknown)$")
    weather: str | None = Field(default=None, max_length=255)
    elevation_gain_m: float | None = Field(default=None, ge=0, le=10000)
    temperature_c: float | None = Field(default=None, ge=-50, le=60)
    is_noisy: bool = False
    notes: str | None = Field(default=None, max_length=1000)


class PerformanceResultOut(BaseModel):
    id: int
    user_id: int
    activity_id: int | None = None
    result_type: str
    name: str
    result_date: datetime
    distance_km: float
    duration_seconds: int
    pace_seconds_per_km: int
    source: str
    terrain: str
    weather: str | None = None
    elevation_gain_m: float | None = None
    temperature_c: float | None = None
    is_noisy: bool
    noisy_reasons: list[str] = Field(default_factory=list)
    age_days: int | None = None
    estimated_vdot: CalculationOut | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


class PerformanceThresholdTrendPointOut(BaseModel):
    result_id: int
    result_date: datetime
    distance_km: float
    duration_seconds: int
    threshold_pace_seconds_per_km: int
    source: str
    confidence: str


class PerformancePaceZoneOut(BaseModel):
    zone_key: str
    label: str | None = None
    lower_value: float | None = None
    upper_value: float | None = None
    unit: str
    method: str
    confidence: str
    source_reference: str | None = None


class PerformanceVdotOut(BaseModel):
    estimate: CalculationOut | None = None
    source: PerformanceResultOut | None = None
    confidence: str
    warnings: list[str] = Field(default_factory=list)
    threshold_trend: list[PerformanceThresholdTrendPointOut] = Field(default_factory=list)
    pace_zones: list[PerformancePaceZoneOut] = Field(default_factory=list)


class PerformancePredictionOut(BaseModel):
    target_distance_km: float
    label: str
    predicted_duration_seconds: int | None = None
    predicted_pace_seconds_per_km: int | None = None
    source_result_id: int | None = None
    source_result_name: str | None = None
    source_distance_km: float | None = None
    source_duration_seconds: int | None = None
    method: str
    confidence: str
    extrapolation_ratio: float | None = None
    extrapolation_limited: bool = False
    noisy: bool = False
    warnings: list[str] = Field(default_factory=list)
    source_reference: str


class PerformancePbOut(BaseModel):
    target_distance_km: float
    label: str
    result_id: int
    name: str
    result_type: str
    result_date: datetime
    distance_km: float
    duration_seconds: int
    normalized_duration_seconds: int
    pace_seconds_per_km: int
    estimated_vdot: CalculationOut | None = None
    is_noisy: bool = False
    noisy_reasons: list[str] = Field(default_factory=list)


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
    source: str = Field(default="manual", pattern="^(manual|screenshot|device|calculated|lab)$")
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


class ZoneDistributionItemOut(BaseModel):
    zone_key: str
    label: str
    duration_seconds: int
    percentage: float
    source_count: int


class ZoneDistributionBucketOut(BaseModel):
    period_start: Date
    period_label: str
    total_duration_seconds: int
    items: list[ZoneDistributionItemOut] = Field(default_factory=list)


class ZonePlannedActualOut(BaseModel):
    zone_key: str
    label: str
    planned_duration_seconds: int
    planned_percentage: float
    actual_duration_seconds: int
    actual_percentage: float
    diff_percentage: float


class ZoneDistributionOut(BaseModel):
    period: AnalyticsPeriodOut
    granularity: str
    zones: ZonesOut
    actual_hr: list[ZoneDistributionItemOut] = Field(default_factory=list)
    actual_pace: list[ZoneDistributionItemOut] = Field(default_factory=list)
    actual_rpe: list[ZoneDistributionItemOut] = Field(default_factory=list)
    actual_five_zone: list[ZoneDistributionItemOut] = Field(default_factory=list)
    seiler_three_zone: list[ZoneDistributionItemOut] = Field(default_factory=list)
    planned_five_zone: list[ZoneDistributionItemOut] = Field(default_factory=list)
    planned_vs_actual: list[ZonePlannedActualOut] = Field(default_factory=list)
    time_buckets: list[ZoneDistributionBucketOut] = Field(default_factory=list)
    metadata: dict


class LlmProviderCreate(BaseModel):
    provider: str = Field(pattern="^(openai|anthropic)$")
    display_name: str = Field(min_length=1, max_length=255)
    base_url: str | None = None
    model: str = Field(min_length=1, max_length=255)
    api_key: str | None = None
    is_default: bool = False


class LlmProviderUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    base_url: str | None = None
    model: str | None = Field(default=None, min_length=1, max_length=255)
    api_key: str | None = None
    is_default: bool | None = None


class LlmProviderOut(BaseModel):
    id: int
    provider: str
    display_name: str
    base_url: str | None = None
    model: str
    is_default: bool
    is_active: bool
    has_api_key: bool
    supports_vision: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class LlmProviderTestOut(BaseModel):
    ok: bool
    status: str
    provider: str
    model: str
    response_ms: int | None = None
    supports_vision: bool
    message: str


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
    include_strength: bool = False
    strength_sessions_per_week: StrictInt | None = Field(default=None, ge=0, le=3)
    include_mobility: bool = False
    mobility_sessions_per_week: StrictInt | None = Field(default=None, ge=0, le=4)
    strength_equipment: str | None = Field(default=None, max_length=64)
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
    support_sessions: int = 0
    support_duration_seconds: int = 0


class PlanBuilderRiskFlagOut(BaseModel):
    code: str
    severity: str
    message: str
    reasons: list[str] = Field(default_factory=list)


class PlannedWorkoutBlockOut(BaseModel):
    id: int | None = None
    workout_id: int | None = None
    block_index: int
    block_type: str
    repeat_count: int = 1
    target_distance_km: float | None = None
    target_duration_seconds: int | None = None
    target_pace_min_seconds_per_km: int | None = None
    target_pace_max_seconds_per_km: int | None = None
    target_hr_min_bpm: int | None = None
    target_hr_max_bpm: int | None = None
    target_rpe_min: int | None = None
    target_rpe_max: int | None = None
    description: str | None = None

    model_config = {"from_attributes": True}


class PlanBuilderPreviewWorkoutOut(BaseModel):
    week_index: int
    day_index: int
    scheduled_date: Date
    workout_type: str
    title: str
    distance_km: float | None = None
    duration_seconds: int | None = None
    intensity: str | None = None
    description: str | None = None
    blocks: list[PlannedWorkoutBlockOut] = Field(default_factory=list)


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
    weather_notes: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=1000)


class PlanWorkoutFeedbackPatchIn(BaseModel):
    rpe: StrictInt | None = Field(default=None, ge=0, le=10)
    fatigue: StrictInt | None = Field(default=None, ge=0, le=10)
    pain: bool | None = None
    pain_level: StrictInt | None = Field(default=None, ge=0, le=10)
    sleep_quality: StrictInt | None = Field(default=None, ge=0, le=10)
    weather_notes: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=1000)


class PlanWorkoutCompleteIn(BaseModel):
    actual_distance_km: float | None = Field(default=None, ge=0, le=250)
    actual_duration_seconds: StrictInt = Field(ge=1, le=172800)
    completed_at: datetime | None = None
    average_heart_rate_bpm: StrictInt | None = Field(default=None, ge=30, le=240)
    rpe: StrictInt | None = Field(default=None, ge=0, le=10)
    fatigue: StrictInt | None = Field(default=None, ge=0, le=10)
    pain: bool = False
    pain_level: StrictInt | None = Field(default=None, ge=0, le=10)
    sleep_quality: StrictInt | None = Field(default=None, ge=0, le=10)
    weather_notes: str | None = Field(default=None, max_length=1000)
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
    intensity_score: float | None = None
    adherence_status: str = "unknown"
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
    planned_duration_seconds: int = 0
    completed_duration_seconds: int = 0
    completion_rate: float
    distance_completion_rate: float
    duration_completion_rate: float = 0
    support_workouts: int = 0
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
    blocks: list[PlannedWorkoutBlockOut] = Field(default_factory=list)
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
    support_workouts: int = 0
    support_duration_seconds: int = 0
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
    duration_delta_seconds: int | None = None


class PlanWorkoutMatchCandidateOut(BaseModel):
    workout: PlanWorkoutOut
    score: float
    confidence: str
    reasons: list[str]
    date_delta_days: int | None = None
    distance_delta_km: float | None = None
    duration_delta_seconds: int | None = None


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


class PlanVersionOut(BaseModel):
    id: int
    plan_id: int
    version_number: int
    reason: str
    summary: str | None = None
    snapshot_json: dict | None = None
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
    analytics: AnalyticsSummaryOut
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


class IntegrationOut(BaseModel):
    id: str
    name: str
    category: str
    status: str
    configured: bool
    description: str
    details: dict[str, object] = Field(default_factory=dict)


class CsvImportOut(BaseModel):
    id: int
    status: str
    source_app: str = "csv"
    created_activities: int
    skipped_duplicates: int
    failed_rows: int
    matched_workouts: int
    created_activity_ids: list[int] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    recognition_message: str | None = None


class AccountDataDeleteIn(BaseModel):
    confirmation: str = Field(pattern="^DELETE$")


class AccountDataDeleteOut(BaseModel):
    deleted: bool
    counts: dict[str, int]
    audit_id: int | None = None


class AuditLogOut(BaseModel):
    id: int
    action: str
    entity_type: str
    entity_id: int | None = None
    metadata_json: dict[str, object] | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
