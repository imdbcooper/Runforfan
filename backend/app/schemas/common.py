from datetime import date, datetime

from pydantic import BaseModel, Field, model_validator


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
    race_distance_km: float | None = 42.2
    target_date: date | None = None
    available_days_per_week: int = Field(default=4, ge=2, le=7)
    current_weekly_distance_km: float | None = None


class PlanWorkoutUpdate(BaseModel):
    scheduled_date: date | None = None
    status: str | None = Field(default=None, pattern="^(planned|done|missed|skipped|rescheduled)$")
    completed_activity_id: int | None = None


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

    model_config = {"from_attributes": True}


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


class PlanWorkoutLinkActivityRequest(BaseModel):
    activity_id: int


class PlanOut(BaseModel):
    id: int
    title: str
    goal_type: str
    race_distance_km: float | None = None
    target_date: date | None = None
    available_days_per_week: int
    status: str
    explanation: str | None = None
    workouts: list[PlanWorkoutOut]
    adherence: PlanAdherenceOut | None = None
    weekly_adherence: list[PlanWeeklyAdherenceOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}
