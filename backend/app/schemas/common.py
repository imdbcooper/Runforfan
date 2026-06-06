from datetime import date, datetime

from pydantic import BaseModel, Field


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


class PlanWorkoutOut(BaseModel):
    week_index: int
    day_index: int
    workout_type: str
    title: str
    distance_km: float | None = None
    duration_seconds: int | None = None
    intensity: str | None = None
    description: str | None = None

    model_config = {"from_attributes": True}


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

    model_config = {"from_attributes": True}
