from datetime import UTC, date, datetime, timedelta
from math import ceil
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models import Activity, AthleteProfile, CoachingEvent, TrainingPlan, TrainingPlanRecommendationAudit, TrainingPlanWorkout, TrainingPlanWorkoutBlock, TrainingPlanWorkoutFeedback, TrainingZone, User
from app.schemas.common import PlanGenerateRequest, PlanUpdate, PlanWorkoutCompleteIn, PlanWorkoutFeedbackIn, PlanWorkoutFeedbackPatchIn, PlanWorkoutMissIn, PlanWorkoutUpdate
from app.services.activity_metrics import is_running_activity_type, sync_derived_activity_metrics
from app.services.coaching_events import record_coaching_event
from app.services.plan_versions import create_plan_version
from app.services.profile import get_or_create_profile, profile_completeness, safety_check
from app.services.training_load import sync_daily_training_loads_for_activity
from app.services.zones import calculated_zones, zone_type_for_unit


MATCHABLE_WORKOUT_STATUSES = ("planned", "rescheduled")
CANDIDATE_MIN_SCORE = 0.25
CANDIDATE_DATE_WINDOW_DAYS = 7
AUTO_MATCH_MIN_SCORE = 0.78
AUTO_MATCH_DATE_WINDOW_DAYS = 3
DEFAULT_WEEKLY_VOLUME_KM = 15.0
RECENT_CONTEXT_WINDOW_DAYS = 28
RECENT_LONG_RUN_WINDOW_DAYS = 56
TRAINING_LEVEL_RANK = {"beginner": 0, "intermediate": 1, "advanced": 2}
TRAINING_LEVEL_MAX_WEEKLY_GROWTH = {"beginner": 0.05, "intermediate": 0.08, "advanced": 0.10}
TRAINING_LEVEL_LONG_RUN_SHARE = {"beginner": 0.30, "intermediate": 0.33, "advanced": 0.35}
MARATHON_LONG_RUN_DISTANCE_CAP_KM = {"beginner": 28.0, "intermediate": 30.0, "advanced": 32.0}
MARATHON_LONG_RUN_DURATION_CAP_MINUTES = {"beginner": 150, "intermediate": 165, "advanced": 180}
HALF_MARATHON_LONG_RUN_DISTANCE_CAP_KM = {"beginner": 16.0, "intermediate": 20.0, "advanced": 22.0}
TRAINING_LEVEL_MAX_RUNNING_DAYS = {"beginner": 5, "intermediate": 6, "advanced": 7}
INTERVAL_WORK_CAP_SECONDS = {"beginner": 15 * 60, "intermediate": 20 * 60, "advanced": 25 * 60}
TEMPO_WORK_CAP_SECONDS = {"beginner": 20 * 60, "intermediate": 30 * 60, "advanced": 40 * 60}
HILL_WORK_CAP_SECONDS = {"beginner": 12 * 60, "intermediate": 16 * 60, "advanced": 20 * 60}
HARD_PLAN_WORKOUT_TYPES = {"interval", "tempo", "threshold", "hill", "race_pace"}
HARD_PLAN_INTENSITIES = {"interval", "tempo", "threshold", "race_pace", "hard"}
LOW_PLAN_INTENSITIES = {"easy", "recovery", "strides"}
SKIP_MISSED_WORKOUT_NOTE = "Coach adjustment: skip this missed workout; do not stack it into the next training window."
SUPPORT_WORKOUT_TYPES = {"strength", "ofp", "mobility", "prehab", "core", "cross_training"}
STRENGTH_WORKOUT_TYPES = {"strength", "ofp", "core"}
MOBILITY_WORKOUT_TYPES = {"mobility", "prehab"}
APPLICABLE_RECOMMENDATION_ACTIONS = {
    "hold_next_week_volume",
    "reduce_next_week_volume",
    "reduce_intensity",
    "cap_next_week_growth",
    "review_or_move_key_workout",
    "skip_missed_key_workout",
    "skip_missed_easy_workout",
}


def weeks_until(target_date: date | None, today: date | None = None) -> int:
    if not target_date:
        return 8
    reference_date = today or date.today()
    return max(4, min(24, ceil((target_date - reference_date).days / 7)))


def plan_weeks_for_request(request: PlanGenerateRequest, today: date) -> int:
    if request.target_date:
        return weeks_until(request.target_date, today)
    if request.plan_length_weeks:
        return int(request.plan_length_weeks)
    return weeks_until(None, today)


def observed_consistent_weeks(observed_weekly_volume: list[float], history_span_days: int) -> int:
    active_recent_weeks = sum(1 for volume in observed_weekly_volume if float(volume or 0) > 0)
    history_weeks = max(0, history_span_days // 7)
    return min(active_recent_weeks, history_weeks) if history_weeks else 0


def consecutive_active_weeks(dates: list[date], today: date) -> int:
    active_week_starts = {item - timedelta(days=item.isoweekday() - 1) for item in dates}
    cursor = today - timedelta(days=today.isoweekday() - 1)
    if cursor not in active_week_starts:
        cursor -= timedelta(days=7)
    weeks = 0
    while cursor in active_week_starts:
        weeks += 1
        cursor -= timedelta(days=7)
    return weeks


def activity_is_quality_session(activity: Activity) -> bool:
    haystack = " ".join(str(part or "") for part in (activity.title, activity.activity_type, activity.aerobic_training_effect)).lower()
    quality_markers = ("interval", "интервал", "tempo", "темп", "threshold", "порог", "hill", "гор", "race pace", "race-pace", "fartlek", "vo2")
    if any(marker in haystack for marker in quality_markers):
        return True
    blocks = getattr(activity, "workout_blocks", []) or []
    for block in blocks:
        block_haystack = " ".join(str(part or "") for part in (getattr(block, "title", None), getattr(block, "notes", None))).lower()
        if any(marker in block_haystack for marker in quality_markers):
            return True
    work_blocks = [block for block in blocks if getattr(block, "block_type", None) == "work"]
    recovery_blocks = [block for block in blocks if getattr(block, "block_type", None) == "recovery"]
    return len(work_blocks) >= 2 and bool(recovery_blocks)


def classify_training_age_level(current_volume: float, recent_long_run: float | None, consistent_weeks: int, quality_sessions: int) -> str:
    if consistent_weeks < 3 or current_volume < 15 or recent_long_run is None or recent_long_run < 6:
        return "beginner"
    if consistent_weeks > 12 and current_volume > 45 and quality_sessions >= 2:
        return "advanced"
    if consistent_weeks >= 4 and current_volume >= 15 and recent_long_run >= 6:
        return "intermediate"
    return "beginner"


def apply_aggressiveness_override(detected_level: str, requested_aggressiveness: str) -> str:
    if requested_aggressiveness == "auto":
        return detected_level
    requested_rank = TRAINING_LEVEL_RANK.get(requested_aggressiveness, TRAINING_LEVEL_RANK["beginner"])
    detected_rank = TRAINING_LEVEL_RANK.get(detected_level, TRAINING_LEVEL_RANK["beginner"])
    if requested_rank <= detected_rank:
        return requested_aggressiveness
    return detected_level


def max_weekly_growth_for_level(training_age_level: str) -> float:
    return TRAINING_LEVEL_MAX_WEEKLY_GROWTH.get(training_age_level, TRAINING_LEVEL_MAX_WEEKLY_GROWTH["beginner"])


def long_run_share_for_level(training_age_level: str, conservative: bool) -> float:
    share = TRAINING_LEVEL_LONG_RUN_SHARE.get(training_age_level, TRAINING_LEVEL_LONG_RUN_SHARE["beginner"])
    return min(share, 0.32) if conservative else share


def long_run_share_for_goal_frequency(training_age_level: str, conservative: bool, goal_distance: float, running_days: int) -> float:
    share = long_run_share_for_level(training_age_level, conservative)
    if goal_distance >= 42 and running_days <= 2:
        return max(share, 0.55)
    if goal_distance >= 42 and running_days == 3:
        return max(share, 0.42)
    if goal_distance >= 21 and running_days <= 2:
        return max(share, 0.50)
    return share


def default_long_run_distance_cap_km(goal_distance: float, training_age_level: str) -> float | None:
    if goal_distance >= 42:
        return MARATHON_LONG_RUN_DISTANCE_CAP_KM.get(training_age_level, MARATHON_LONG_RUN_DISTANCE_CAP_KM["beginner"])
    if goal_distance >= 21:
        return HALF_MARATHON_LONG_RUN_DISTANCE_CAP_KM.get(training_age_level, HALF_MARATHON_LONG_RUN_DISTANCE_CAP_KM["beginner"])
    return None


def default_long_run_duration_cap_minutes(goal_distance: float, training_age_level: str) -> int | None:
    if goal_distance >= 42:
        return MARATHON_LONG_RUN_DURATION_CAP_MINUTES.get(training_age_level, MARATHON_LONG_RUN_DURATION_CAP_MINUTES["beginner"])
    return None


def smallest_cap(values: list[float | int | None]) -> float | None:
    caps = [float(value) for value in values if value is not None]
    return min(caps) if caps else None


def max_running_days_for_level(training_age_level: str) -> int:
    return TRAINING_LEVEL_MAX_RUNNING_DAYS.get(training_age_level, TRAINING_LEVEL_MAX_RUNNING_DAYS["beginner"])


def taper_weeks_for_goal(goal_distance_km: float | None, weeks: int) -> int:
    if weeks <= 1 or not goal_distance_km:
        return 0
    if goal_distance_km and goal_distance_km >= 42:
        desired = 3 if weeks >= 16 else 2
    elif goal_distance_km and goal_distance_km >= 21:
        desired = 2 if weeks >= 8 else 1
    else:
        desired = 1
    return max(1, min(desired, max(1, weeks // 3)))


def phase_for_week(week_index: int, weeks: int, goal_distance_km: float | None) -> str:
    if not goal_distance_km:
        base_end = max(1, round(weeks * 0.4))
        return "base" if week_index <= base_end else "build"
    taper_weeks = taper_weeks_for_goal(goal_distance_km, weeks)
    taper_start = weeks - taper_weeks + 1 if taper_weeks else weeks + 1
    if week_index >= taper_start:
        return "taper"
    pre_taper_weeks = max(1, taper_start - 1)
    base_end = max(1, round(pre_taper_weeks * 0.35))
    specific_start = max(base_end + 1, pre_taper_weeks - max(1, round(pre_taper_weeks * 0.25)) + 1)
    if week_index <= base_end:
        return "base"
    if week_index >= specific_start:
        return "specific"
    return "build"


def taper_week_index(week_index: int, weeks: int, goal_distance_km: float | None) -> int | None:
    taper_weeks = taper_weeks_for_goal(goal_distance_km, weeks)
    taper_start = weeks - taper_weeks + 1 if taper_weeks else weeks + 1
    if week_index < taper_start:
        return None
    return week_index - taper_start + 1


def taper_volume_multiplier(week_index: int, weeks: int, goal_distance_km: float | None) -> float:
    index = taper_week_index(week_index, weeks, goal_distance_km)
    if not index:
        return 1.0
    taper_weeks = taper_weeks_for_goal(goal_distance_km, weeks)
    if taper_weeks >= 3:
        multipliers = [0.85, 0.72, 0.60]
    elif taper_weeks == 2:
        multipliers = [0.80, 0.65]
    else:
        multipliers = [0.72]
    return multipliers[min(index - 1, len(multipliers) - 1)]


def hard_work_cap_seconds(workout_type: str, training_age_level: str) -> int:
    if workout_type == "interval":
        return INTERVAL_WORK_CAP_SECONDS.get(training_age_level, INTERVAL_WORK_CAP_SECONDS["beginner"])
    if workout_type == "hill":
        return HILL_WORK_CAP_SECONDS.get(training_age_level, HILL_WORK_CAP_SECONDS["beginner"])
    return TEMPO_WORK_CAP_SECONDS.get(training_age_level, TEMPO_WORK_CAP_SECONDS["beginner"])


def capped_work_seconds(duration: int | None, workout_type: str, training_age_level: str, ratio: float) -> int | None:
    if duration is None:
        return None
    return max(1, min(round(duration * ratio), hard_work_cap_seconds(workout_type, training_age_level)))


def capped_work_distance(distance: float | None, duration: int | None, work_seconds: int | None, distance_ratio: float, duration_ratio: float, repeat_count: int = 1) -> float | None:
    if distance is None:
        return None
    scaled_distance = float(distance) * distance_ratio
    if duration and work_seconds:
        planned_work_seconds = max(1, round(duration * duration_ratio))
        scaled_distance *= min(1.0, work_seconds / planned_work_seconds)
    return round(max(0.0, scaled_distance / max(1, repeat_count)), 2)


def race_name(distance_km: float | None) -> str:
    if not distance_km:
        return "цель"
    if distance_km <= 5.5:
        return "5K"
    if distance_km <= 11:
        return "10K"
    if distance_km <= 22:
        return "полумарафон"
    if distance_km <= 43:
        return "марафон"
    return f"{distance_km:g} км"


def format_pace(seconds: float | int | None) -> str:
    if seconds is None:
        return "--"
    rounded = round(seconds)
    return f"{rounded // 60}'{rounded % 60:02d}\"/км"


def format_zone_range(zone: dict[str, object] | None) -> str | None:
    if not zone:
        return None
    lower = zone.get("lower_value")
    upper = zone.get("upper_value")
    unit = str(zone.get("unit"))
    if unit == "seconds_per_km":
        return f"{format_pace(lower)} - {format_pace(upper)}"
    if unit == "bpm":
        lower_text = "--" if lower is None else str(round(float(lower)))
        upper_text = "--" if upper is None else str(round(float(upper)))
        return f"{lower_text}-{upper_text} bpm"
    return f"{lower or '--'}-{upper or '--'} {unit}"


def zone_map(zones: dict) -> dict[str, dict[str, object]]:
    mapped: dict[str, dict[str, object]] = {}
    for zone in zones.get("pace", []):
        mapped[f"pace:{zone['zone_key']}"] = zone
    for zone in zones.get("hr", []):
        mapped[f"hr:{zone['zone_key']}"] = zone
    return mapped


def target_text(zones: dict, pace_key: str | None = None, hr_key: str | None = None, fallback: str = "RPE 2-4") -> str:
    mapped = zone_map(zones)
    parts = []
    if pace_key:
        pace_range = format_zone_range(mapped.get(f"pace:{pace_key}"))
        if pace_range:
            parts.append(f"pace {pace_key}: {pace_range}")
    if hr_key:
        hr_range = format_zone_range(mapped.get(f"hr:{hr_key}"))
        if hr_range:
            parts.append(f"HR {hr_key}: {hr_range}")
    return "; ".join(parts) if parts else fallback


def schedule_offsets(days: int) -> list[int]:
    schedules = {
        2: [0, 3],
        3: [0, 2, 5],
        4: [0, 2, 4, 6],
        5: [0, 1, 3, 5, 6],
        6: [0, 1, 2, 4, 5, 6],
        7: [0, 1, 2, 3, 4, 5, 6],
    }
    return schedules.get(days, schedules[4])


def is_support_workout_type(workout_type: str | None) -> bool:
    return (workout_type or "") in SUPPORT_WORKOUT_TYPES


def activity_type_is_support(activity_type: str | None) -> bool:
    value = (activity_type or "").lower()
    return any(marker in value for marker in SUPPORT_WORKOUT_TYPES)


def support_match_markers(workout_type: str) -> set[str]:
    markers = {workout_type}
    if workout_type in STRENGTH_WORKOUT_TYPES:
        markers.update({"strength", "ofp", "сил", "офп", "core", "gym"})
    if workout_type in MOBILITY_WORKOUT_TYPES:
        markers.update({"mobility", "prehab", "моб", "stretch", "activation"})
    if workout_type == "cross_training":
        markers.update({"cross training", "cross-training"})
    return markers


def activity_matches_support_marker(activity: Activity, workout_type: str) -> bool:
    haystack = f"{activity.activity_type or ''} {activity.title or ''}".lower().replace("_", " ").replace("-", " ")
    markers = {marker.lower().replace("_", " ").replace("-", " ") for marker in support_match_markers(workout_type)}
    return any(marker in haystack for marker in markers)


def schedule_offsets_for_plan(start_date: date, days: int, preferred_weekdays: list[int] | None = None, long_run_weekday: int | None = None) -> list[int]:
    default_offsets = schedule_offsets(days)
    start_weekday = start_date.isoweekday()
    long_offset = (long_run_weekday - start_weekday) % 7 if long_run_weekday else None
    if not preferred_weekdays:
        if long_offset is None or days <= 1:
            return default_offsets
        offsets = [offset for offset in default_offsets if offset != long_offset]
        for offset in default_offsets:
            if len(offsets) >= days - 1:
                break
            if offset not in offsets:
                offsets.append(offset)
        return sorted(offsets[:max(0, days - 1)] + [long_offset])
    preferred_offsets = sorted({(weekday - start_weekday) % 7 for weekday in preferred_weekdays})
    offsets = preferred_offsets[:days]
    for offset in default_offsets:
        if len(offsets) >= days:
            break
        if offset not in offsets:
            offsets.append(offset)
    offsets = sorted(offsets[:days])
    if long_offset is not None:
        if long_offset not in offsets:
            offsets = offsets[:max(0, days - 1)] + [long_offset]
        offsets = sorted(offsets[:days])
    return offsets


def scheduled_workout_date(start_date: date, week_index: int, day_index: int, days: int, preferred_weekdays: list[int] | None = None, long_run_weekday: int | None = None) -> date:
    offsets = schedule_offsets_for_plan(start_date, days, preferred_weekdays, long_run_weekday)
    offset = offsets[min(day_index - 1, len(offsets) - 1)]
    return start_date + timedelta(days=(week_index - 1) * 7 + offset)


def recent_training_context(db: Session, user: User) -> dict[str, object]:
    activities = list(db.scalars(
        select(Activity)
        .where(Activity.user_id == user.id)
        .order_by(Activity.started_at.desc().nullslast(), Activity.id.desc())
        .limit(60)
    ))
    dated = [activity for activity in activities if activity.started_at]
    today = date.today()
    recent = [activity for activity in dated if 0 <= (today - activity.started_at.date()).days <= 14]
    if recent:
        oldest = min(activity.started_at.date() for activity in recent)
        newest = max(activity.started_at.date() for activity in recent)
        span_days = max(1, (newest - oldest).days + 1)
        weekly_distance = sum(activity.distance_km or 0 for activity in recent) * 7 / max(7, span_days)
    else:
        span_days = 0
        weekly_distance = 0.0
    history_span_days = 0
    if len(dated) >= 2:
        history_span_days = (max(activity.started_at.date() for activity in dated) - min(activity.started_at.date() for activity in dated)).days + 1
    elif dated:
        history_span_days = 1
    return {
        "activity_count": len(activities),
        "recent_activity_count": len(recent),
        "history_span_days": history_span_days,
        "recent_weekly_distance_km": round(weekly_distance, 1) if weekly_distance else None,
    }


def profile_for_plan_builder(db: Session, user: User, persist: bool = False) -> AthleteProfile:
    if persist:
        return get_or_create_profile(db, user)
    profile = db.scalar(select(AthleteProfile).where(AthleteProfile.user_id == user.id))
    if profile:
        return profile
    return AthleteProfile(user_id=user.id, sex="unspecified", timezone="Europe/Moscow", locale="ru-RU", unit_system="metric", conservative_mode=False, recovery_status="normal")


def zones_for_plan_builder(db: Session, user: User, profile: AthleteProfile) -> dict[str, object]:
    stored = list(db.scalars(select(TrainingZone).where(TrainingZone.user_id == user.id, TrainingZone.is_active.is_(True))))
    stored_dicts = [
        {
            "id": zone.id,
            "zone_type": zone.zone_type,
            "method": zone.method,
            "zone_key": zone.zone_key,
            "label": zone.label,
            "lower_value": zone.lower_value,
            "upper_value": zone.upper_value,
            "unit": zone.unit,
            "confidence": zone.confidence,
            "source_reference": zone.source_reference,
            "is_active": zone.is_active,
        }
        for zone in stored
    ]
    manual_types = {zone.zone_type for zone in stored if zone.method == "manual"}
    stored_signatures = {(zone.zone_type, zone.method, zone.zone_key) for zone in stored}
    calculated = [
        zone for zone in calculated_zones(profile)
        if zone_type_for_unit(str(zone["unit"])) not in manual_types
        and (zone_type_for_unit(str(zone["unit"])), str(zone["method"]), str(zone["zone_key"])) not in stored_signatures
    ]
    combined = stored_dicts + [
        {
            "id": None,
            "zone_type": zone_type_for_unit(str(zone["unit"])),
            "method": zone["method"],
            "zone_key": zone["zone_key"],
            "label": zone.get("label"),
            "lower_value": zone["lower_value"],
            "upper_value": zone["upper_value"],
            "unit": zone["unit"],
            "confidence": zone["confidence"],
            "source_reference": zone["source_reference"],
            "is_active": True,
        }
        for zone in calculated
    ]
    return {
        "hr": [zone for zone in combined if zone["zone_type"] == "hr"],
        "pace": [zone for zone in combined if zone["zone_type"] == "pace"],
        "rpe": [zone for zone in combined if zone["zone_type"] == "rpe"],
        "metadata": {
            "calculated_count": len(calculated),
            "stored_count": len(stored),
            "manual_zone_types": sorted(manual_types),
        },
    }


def plan_builder_timezone(profile: AthleteProfile) -> ZoneInfo:
    try:
        return ZoneInfo(profile.timezone or "Europe/Moscow")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def activity_started_date(activity: Activity, profile: AthleteProfile) -> date | None:
    if not activity.started_at:
        return None
    started_at = activity.started_at
    timezone = plan_builder_timezone(profile)
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone)
    return started_at.astimezone(timezone).date()


def estimated_volume_from_sparse_history(recent_run_distances: list[float], active_recent_weeks: list[float], requested_days: int | None = None) -> tuple[float, str]:
    if active_recent_weeks:
        return max(DEFAULT_WEEKLY_VOLUME_KM, float(median(active_recent_weeks))), "observed_active_week"
    if not recent_run_distances:
        return DEFAULT_WEEKLY_VOLUME_KM, "fallback"
    typical_run = float(median(recent_run_distances))
    recent_long = max(recent_run_distances)
    frequency_floor = min(requested_days or 2, 2)
    estimated_volume = max(DEFAULT_WEEKLY_VOLUME_KM, typical_run * frequency_floor, recent_long * 1.1)
    return estimated_volume, "estimated_from_recent_runs"


def plan_builder_training_context(db: Session, user: User, profile: AthleteProfile, today: date, requested_days: int | None = None) -> dict[str, object]:
    activities = list(db.scalars(
        select(Activity)
        .where(Activity.user_id == user.id, Activity.started_at.is_not(None))
        .options(selectinload(Activity.workout_blocks))
        .order_by(Activity.started_at.desc(), Activity.id.desc())
        .limit(240)
    ))
    dated = [
        (activity, started_date)
        for activity in activities
        if is_running_activity_type(activity.activity_type)
        and (started_date := activity_started_date(activity, profile)) is not None
        and started_date <= today
    ]
    history_span_days = (max(started_date for _, started_date in dated) - min(started_date for _, started_date in dated)).days + 1 if dated else 0
    observed_weekly_volume = [0.0 for _ in range(6)]
    observed_start = today - timedelta(days=41)
    recent_long_run = 0.0
    quality_sessions_8w = 0
    recent_long_start = today - timedelta(days=RECENT_LONG_RUN_WINDOW_DAYS - 1)
    recent_context_start = today - timedelta(days=RECENT_CONTEXT_WINDOW_DAYS - 1)
    recent_run_distances: list[float] = []
    for activity, started_date in dated:
        distance = float(activity.distance_km or 0)
        if observed_start <= started_date <= today:
            bucket = min(5, max(0, (started_date - observed_start).days // 7))
            observed_weekly_volume[bucket] += distance
        if distance > 0 and recent_context_start <= started_date <= today:
            recent_run_distances.append(distance)
        if recent_long_start <= started_date <= today:
            recent_long_run = max(recent_long_run, distance)
            if activity_is_quality_session(activity):
                quality_sessions_8w += 1

    active_recent_weeks = [volume for volume in observed_weekly_volume[-4:] if volume > 0]
    if len(active_recent_weeks) >= 2:
        current_volume = float(median(active_recent_weeks))
        source = "observed_median_4w"
    else:
        current_volume, source = estimated_volume_from_sparse_history(recent_run_distances, active_recent_weeks, requested_days)

    running_dates = [started_date for activity, started_date in dated if float(activity.distance_km or 0) > 0]
    consistent_weeks = consecutive_active_weeks(running_dates, today)
    training_age_level = classify_training_age_level(current_volume, recent_long_run or None, consistent_weeks, quality_sessions_8w)

    if source == "observed_median_4w" and history_span_days >= 42:
        confidence = "high"
    elif source in {"observed_median_4w", "observed_active_week"} or history_span_days >= 14:
        confidence = "medium"
    else:
        confidence = "low"
    recent_run_distance_median = float(median(recent_run_distances)) if recent_run_distances else None

    return {
        "activity_count": len(dated),
        "history_span_days": history_span_days,
        "observed_weekly_volume_km": [round(volume, 1) for volume in observed_weekly_volume],
        "current_weekly_volume_km": round(current_volume, 1),
        "current_weekly_volume_source": source,
        "recent_weekly_distance_km": round(current_volume, 1),
        "recent_long_run_km": round(recent_long_run, 1) if recent_long_run else None,
        "recent_run_distance_median_km": round(recent_run_distance_median, 1) if recent_run_distance_median else None,
        "recent_run_count_4w": len(recent_run_distances),
        "consistent_weeks": consistent_weeks,
        "quality_sessions_8w": quality_sessions_8w,
        "training_age_level": training_age_level,
        "confidence": confidence,
    }


def build_safety_context(profile, completeness: dict, context: dict[str, object], goal_distance: float, request: PlanGenerateRequest | None = None) -> dict[str, object]:
    reasons = []
    activity_count = int(context.get("activity_count") or 0)
    quality_sessions = int(context.get("quality_sessions_8w") or 0)
    current_weekly_volume = float(context.get("recent_weekly_distance_km") or context.get("current_weekly_volume_km") or 0)
    recent_long_run = float(context.get("recent_long_run_km") or 0)
    recent_median = float(context.get("recent_run_distance_median_km") or 0)
    rpe_quality_ready = activity_count >= 3 and current_weekly_volume >= 20 and (recent_long_run >= 8 or recent_median >= 8)
    if profile.conservative_mode:
        reasons.append("profile conservative mode")
    if profile.injury_notes:
        reasons.append("injury notes present")
    if profile.health_conditions:
        reasons.append("health conditions present")
    if profile.recovery_status in {"tired", "strained", "injured"}:
        reasons.append(f"profile recovery status: {profile.recovery_status}")
    if request and request.injury:
        reasons.append("wizard injury constraint")
    if request and request.no_hard_workouts:
        reasons.append("wizard no hard workouts constraint")
    if int(context["history_span_days"] or 0) < 14 and activity_count < 2:
        reasons.append("training history shorter than 14 days")
    intensity_mode = request.intensity_mode if request else "mixed"
    if intensity_mode == "pace" and not completeness["can_calculate_pace_zones"]:
        reasons.append("no threshold pace zones")
    if intensity_mode == "mixed" and not (completeness["can_calculate_pace_zones"] or completeness["can_calculate_hr_zones"] or completeness["can_calculate_hrr_zones"]) and quality_sessions == 0 and not rpe_quality_ready:
        reasons.append("no threshold pace zones")
    if intensity_mode == "hr" and not (completeness["can_calculate_hr_zones"] or completeness["can_calculate_hrr_zones"]):
        reasons.append("no HR zones")
    if goal_distance >= 21 and current_weekly_volume < 25 and not (quality_sessions > 0 and current_weekly_volume >= 15) and not rpe_quality_ready:
        reasons.append("low current volume for long-distance goal")
    return {
        "conservative": bool(reasons),
        "reasons": reasons,
    }


def ready_for_controlled_rpe_quality(context: dict[str, object], current_volume: float) -> bool:
    recent_median = float(context.get("recent_run_distance_median_km") or 0)
    recent_long = float(context.get("recent_long_run_km") or 0)
    recent_runs = int(context.get("recent_run_count_4w") or 0)
    activity_count = int(context.get("activity_count") or 0)
    return activity_count >= 3 and recent_runs >= 2 and current_volume >= 20 and (recent_median >= 8 or recent_long >= 8)


def effective_running_days_for_pattern(requested_days: int, max_days: int, current_volume: float, recent_run_median: float | None, goal_distance: float) -> tuple[int, bool]:
    days = min(requested_days, max_days)
    if not recent_run_median or recent_run_median < 8 or current_volume <= 0:
        return days, False
    primary_floor = float(recent_run_median) * 0.85
    if days <= 2 or current_volume / days >= primary_floor:
        return days, False
    feasible_days = max(2, int(current_volume // primary_floor))
    if goal_distance >= 21 and current_volume >= float(recent_run_median) * 2.2:
        feasible_days = max(3, feasible_days)
    effective_days = max(2, min(days, feasible_days))
    return effective_days, effective_days < days


def workout_template(days: int, conservative: bool, can_prescribe_hard: bool, training_age_level: str, has_pace_zones: bool, week_index: int = 1, weeks: int = 8, has_target_time: bool = False, phase: str = "build", has_race_goal: bool = True, recent_quality_sessions: int = 0, goal_distance: float | None = None) -> list[tuple[int, str, str, str]]:
    hard_allowed = (not conservative) and can_prescribe_hard
    quality_lite = (not conservative)
    specific_phase = phase in {"specific", "taper"} and has_race_goal and has_target_time

    def primary_quality() -> tuple[str, str, str]:
        if phase == "base":
            if hard_allowed and week_index == 1 and (recent_quality_sessions > 0 or training_age_level != "beginner"):
                return "interval", "Контролируемые интервалы", "interval"
            return "strides" if quality_lite else "easy", "Страйды" if quality_lite else "Легкий бег", "strides" if quality_lite else "easy"
        if not hard_allowed:
            return "steady", "Аэробная работа", "steady-rpe"
        if specific_phase:
            return "race_pace", "Работа в целевом темпе", "race_pace"
        if phase == "taper":
            return "tempo" if has_pace_zones else "hill", "Контролируемая интенсивность", "threshold" if has_pace_zones else "hill"
        if has_pace_zones:
            return "interval", "Длинные интервалы", "interval"
        return "interval", "Контролируемые интервалы по RPE", "interval-rpe"

    def secondary_quality() -> tuple[str, str, str]:
        if phase in {"base", "taper"}:
            return "easy", "Легкий бег", "easy"
        if not hard_allowed:
            return "strides" if quality_lite else "easy", "Страйды" if quality_lite else "Легкий бег", "strides" if quality_lite else "easy"
        if specific_phase:
            return "interval", "Контролируемые интервалы", "interval"
        return "tempo", "Темповая работа", "threshold"

    quality_type, quality_title, quality_intensity = primary_quality()
    if days <= 2:
        if hard_allowed:
            return [
                (1, quality_type, quality_title, quality_intensity),
                (days, "long", "Длинная тренировка", "easy-long"),
            ]
        if goal_distance and goal_distance >= 21 and not conservative:
            return [
                (1, "steady", "Аэробная работа", "steady-rpe"),
                (days, "long", "Длинная тренировка", "easy-long"),
            ]
        return [
            (1, "strides" if quality_lite else "easy", "Легкий бег со страйдами" if quality_lite else "Легкий бег", "strides" if quality_lite else "easy"),
            (days, "long", "Длинная тренировка", "easy-long"),
        ]
    template = [(1, "easy", "Легкий бег", "easy"), (2, quality_type, quality_title, quality_intensity)]
    if days >= 4:
        template.append((3, "recovery", "Восстановительный бег", "recovery"))
    if days >= 5:
        second_type, second_title, second_intensity = secondary_quality()
        if phase == "taper":
            template.append((4, "recovery", "Восстановительный бег", "recovery"))
        elif hard_allowed and training_age_level == "advanced" and days >= 6:
            template.append((4, second_type, second_title, second_intensity))
        elif not hard_allowed:
            template.append((4, second_type, second_title, second_intensity))
        else:
            template.append((4, "strides", "Страйды", "strides"))
    for day in range(5, days):
        if day == 5 and days >= 7:
            template.append((day, "easy", "Легкий бег", "easy"))
        else:
            template.append((day, "recovery" if day % 2 == 1 else "easy", "Восстановительный бег" if day % 2 == 1 else "Легкий бег", "recovery" if day % 2 == 1 else "easy"))
    template.append((days, "long", "Длинная тренировка", "easy-long"))
    return template[:days]


def workout_template_for_schedule(days: int, conservative: bool, can_prescribe_hard: bool, training_age_level: str, has_pace_zones: bool, long_run_day_index: int | None = None, week_index: int = 1, weeks: int = 8, has_target_time: bool = False, phase: str = "build", has_race_goal: bool = True, recent_quality_sessions: int = 0, goal_distance: float | None = None) -> list[tuple[int, str, str, str]]:
    template = workout_template(days, conservative, can_prescribe_hard, training_age_level, has_pace_zones, week_index, weeks, has_target_time, phase, has_race_goal, recent_quality_sessions, goal_distance)
    if not long_run_day_index or long_run_day_index >= days:
        return template
    long_item = next((item for item in template if item[1] == "long"), None)
    if long_item is None:
        return template
    other_items = [item for item in template if item[1] != "long"]
    position = max(0, min(days - 1, long_run_day_index - 1))
    ordered = other_items[:position] + [long_item] + other_items[position:]
    return [(index, workout_type, title, intensity) for index, (_, workout_type, title, intensity) in enumerate(ordered[:days], start=1)]


def workout_slot_role(workout_type: str) -> str:
    if workout_type == "long":
        return "long"
    if workout_type == "recovery":
        return "recovery"
    if workout_type in HARD_PLAN_WORKOUT_TYPES or workout_type in {"steady", "strides"}:
        return "quality"
    return "easy"


def slot_distance_weight(workout_type: str) -> float:
    if workout_type == "recovery":
        return 0.62
    if workout_type in HARD_PLAN_WORKOUT_TYPES:
        return 1.18
    if workout_type in {"steady", "strides"}:
        return 1.04
    return 1.0


def slot_floor_ratio(workout_type: str) -> float:
    if workout_type == "recovery":
        return 0.45
    if workout_type in HARD_PLAN_WORKOUT_TYPES:
        return 0.72
    if workout_type == "strides":
        return 0.65
    return 0.70


def allocate_week_distances(week_volume: float, long_run: float, week_workouts: list[tuple[int, str, str, str]], recent_run_median: float | None) -> dict[int, float]:
    distances: dict[int, float] = {}
    non_long = [item for item in week_workouts if item[1] != "long"]
    for day_index, workout_type, _title, _intensity in week_workouts:
        if workout_type == "long":
            distances[day_index] = long_run
    remaining = max(0.0, week_volume - long_run)
    if not non_long:
        return {day_index: round(distance, 1) for day_index, distance in distances.items()}

    weights = {day_index: slot_distance_weight(workout_type) for day_index, workout_type, _title, _intensity in non_long}
    total_weight = sum(weights.values()) or 1.0
    allocations = {day_index: remaining * weight / total_weight for day_index, weight in weights.items()}

    if recent_run_median and recent_run_median >= 6 and remaining > 0:
        floors = {
            day_index: float(recent_run_median) * slot_floor_ratio(workout_type)
            for day_index, workout_type, _title, _intensity in non_long
        }
        floor_total = sum(floors.values())
        if floor_total > 0:
            if floor_total <= remaining:
                surplus = remaining - floor_total
                allocations = {day_index: floors[day_index] + surplus * weights[day_index] / total_weight for day_index in weights}
            else:
                scale = remaining / floor_total
                allocations = {day_index: floors[day_index] * scale for day_index in weights}

    distances.update(allocations)
    rounded = {day_index: round(max(0.1, distance), 1) for day_index, distance in distances.items()}
    delta = round(week_volume - sum(rounded.values()), 1)
    if abs(delta) >= 0.1 and rounded:
        adjustable = [item for item in week_workouts if item[0] in rounded and (delta > 0 or rounded[item[0]] > 0.2)]
        if adjustable:
            preferred = [item for item in adjustable if item[1] != "long"] or adjustable
            target_day = max(preferred, key=lambda item: rounded[item[0]] * (1.0 if item[1] != "recovery" else 0.5))[0]
            rounded[target_day] = round(max(0.1, rounded[target_day] + delta), 1)
    return rounded


def requested_support_sessions(requested: int | None, enabled: bool, default_value: int, maximum: int) -> int:
    if not enabled:
        return 0
    if requested is not None:
        return max(0, min(maximum, int(requested)))
    return default_value if enabled else 0


def support_session_settings(request: PlanGenerateRequest, training_age_level: str, conservative: bool) -> dict[str, int]:
    default_strength = 1 if request.include_strength else 0
    if request.include_strength and training_age_level in {"intermediate", "advanced"} and not conservative:
        default_strength = 2
    strength_sessions = requested_support_sessions(request.strength_sessions_per_week, request.include_strength, default_strength, 3)
    if conservative or request.injury:
        strength_sessions = min(strength_sessions, 1)
    mobility_sessions = requested_support_sessions(request.mobility_sessions_per_week, request.include_mobility, 1 if request.include_mobility else 0, 4)

    if conservative or request.injury:
        strength_duration = 20 * 60
    elif training_age_level == "advanced":
        strength_duration = 35 * 60
    elif training_age_level == "intermediate":
        strength_duration = 30 * 60
    else:
        strength_duration = 25 * 60
    mobility_duration = 15 * 60 if training_age_level != "beginner" else 12 * 60
    return {
        "strength_sessions": strength_sessions,
        "mobility_sessions": mobility_sessions,
        "strength_duration_seconds": strength_duration,
        "mobility_duration_seconds": mobility_duration,
    }


def support_settings_duration_seconds(settings: dict[str, int]) -> int:
    return (
        settings["strength_sessions"] * settings["strength_duration_seconds"]
        + settings["mobility_sessions"] * settings["mobility_duration_seconds"]
    )


def fit_support_settings_to_time_budget(settings: dict[str, int], time_budget_minutes: int | None, easy_pace_seconds_per_km: float) -> tuple[dict[str, int], bool]:
    if not time_budget_minutes:
        return dict(settings), False
    adjusted = dict(settings)
    max_support_seconds = max(0, int(time_budget_minutes * 60 - easy_pace_seconds_per_km))
    limited = False
    while support_settings_duration_seconds(adjusted) > max_support_seconds and (adjusted["strength_sessions"] or adjusted["mobility_sessions"]):
        if adjusted["strength_sessions"] and (not adjusted["mobility_sessions"] or adjusted["strength_duration_seconds"] >= adjusted["mobility_duration_seconds"]):
            adjusted["strength_sessions"] -= 1
        elif adjusted["mobility_sessions"]:
            adjusted["mobility_sessions"] -= 1
        limited = True
    return adjusted, limited


def support_workout_description(workout_type: str, equipment: str | None = None) -> str:
    if workout_type == "mobility":
        return "Mobility/prehab: ankle and hip mobility, foot activation, glute activation and relaxed breathing. Keep it easy; stop if pain changes gait."
    equipment_text = f" Equipment: {equipment}." if equipment else " Use bodyweight or simple home equipment."
    return (
        "Runner strength/OFP: calves/soleus, glutes, hamstrings, single-leg stability and trunk control. "
        "Keep technique clean, avoid failure and leave 1-2 reps in reserve."
        f"{equipment_text}"
    )


def support_anchor_dates(week_workouts: list[dict[str, object]], sessions: int, fallback_start: date) -> list[date]:
    if sessions <= 0:
        return []
    candidates = [
        workout
        for workout in week_workouts
        if not preview_workout_is_hard(workout) and workout.get("workout_type") != "long" and isinstance(workout.get("scheduled_date"), date)
    ]
    if not candidates:
        candidates = [workout for workout in week_workouts if isinstance(workout.get("scheduled_date"), date)]
    dates: list[date] = []
    for workout in candidates:
        scheduled = workout.get("scheduled_date")
        if isinstance(scheduled, date) and scheduled not in dates:
            dates.append(scheduled)
        if len(dates) >= sessions:
            return dates
    while len(dates) < sessions:
        dates.append(fallback_start)
    return dates


def support_workouts_for_week(
    week: int,
    days: int,
    week_start: date,
    week_workouts: list[dict[str, object]],
    settings: dict[str, int],
    request: PlanGenerateRequest,
    phase: str = "build",
) -> list[dict[str, object]]:
    support: list[dict[str, object]] = []
    strength_dates = support_anchor_dates(week_workouts, settings["strength_sessions"], week_start)
    for index, scheduled in enumerate(strength_dates, start=1):
        support.append({
            "week_index": week,
            "day_index": days + len(support) + 1,
            "scheduled_date": scheduled,
            "phase": phase,
            "workout_type": "strength",
            "title": f"ОФП / силовая {'A' if index == 1 else 'B'}",
            "distance_km": None,
            "duration_seconds": settings["strength_duration_seconds"],
            "intensity": "strength",
            "description": support_workout_description("strength", request.strength_equipment),
        })
    mobility_dates: list[date] = []
    long_dates = [workout["scheduled_date"] for workout in week_workouts if workout.get("workout_type") == "long" and isinstance(workout.get("scheduled_date"), date)]
    if long_dates:
        mobility_dates.append(min(long_dates[0] + timedelta(days=1), week_start + timedelta(days=6)))
    mobility_dates.extend(support_anchor_dates(week_workouts, max(0, settings["mobility_sessions"] - len(mobility_dates)), week_start))
    for scheduled in mobility_dates[:settings["mobility_sessions"]]:
        support.append({
            "week_index": week,
            "day_index": days + len(support) + 1,
            "scheduled_date": scheduled,
            "phase": phase,
            "workout_type": "mobility",
            "title": "Mobility / prehab",
            "distance_km": None,
            "duration_seconds": settings["mobility_duration_seconds"],
            "intensity": "recovery",
            "description": support_workout_description("mobility"),
        })
    return support


def workout_description(workout_type: str, intensity: str, zones: dict, conservative: bool) -> str:
    if workout_type == "strength":
        return support_workout_description("strength")
    if workout_type in {"mobility", "prehab"}:
        return support_workout_description("mobility")
    if workout_type == "interval":
        target = target_text(zones, pace_key="interval", hr_key="z4", fallback="RPE 6-7, без выхода в максимальную интенсивность")
        return f"Работа около порога: 3-5 длинных отрезков с восстановлением. Цель: {target}."
    if workout_type == "hill":
        target = target_text(zones, hr_key="z3", fallback="RPE 5-7, короткие контролируемые подъемы")
        return f"Горки для силы и механики, хорошая замена скоростной работе при ненадежных pace zones. Цель: {target}."
    if workout_type == "tempo":
        target = target_text(zones, pace_key="threshold", hr_key="z3", fallback="RPE 5-6, контролируемый темп")
        return f"Устойчивый темп ниже порога, без закисления. Цель: {target}."
    if workout_type == "race_pace":
        target = target_text(zones, pace_key="threshold", hr_key="z3", fallback="RPE 5-7, контролируемый целевой темп")
        return f"Специфичная работа в целевом темпе гонки без all-out усилия. Цель: {target}."
    if workout_type == "strides":
        target = target_text(zones, pace_key="easy", hr_key="z2", fallback="RPE 2-3 между короткими расслабленными ускорениями")
        return f"Легкий бег плюс короткие расслабленные страйды с полным восстановлением. Цель: {target}."
    if workout_type == "recovery":
        target = target_text(zones, pace_key="easy", hr_key="z1", fallback="RPE 1-3, очень легко")
        return f"Короткое восстановление для привычки и мягкого кровотока. Цель: {target}."
    if workout_type == "steady":
        target = target_text(zones, pace_key="steady", hr_key="z2", fallback="RPE 3-4, разговорный контроль")
        suffix = " Высокоинтенсивные тренировки отключены safety gate." if conservative else ""
        return f"Аэробная работа без жестких интервалов. Цель: {target}.{suffix}"
    if workout_type == "long":
        target = target_text(zones, pace_key="easy", hr_key="z2", fallback="RPE 2-4, длинный легкий бег")
        return f"Главная тренировка недели для базы и устойчивости. Цель: {target}."
    target = target_text(zones, pace_key="easy", hr_key="z1", fallback="RPE 2-3, легко и комфортно")
    return f"Комфортный бег в разговорном темпе. Цель: {target}."


def numeric_zone_range(zones: dict[str, object], zone_type: str, zone_key: str) -> tuple[int | None, int | None]:
    for zone in zones.get(zone_type, []) or []:
        if str(zone.get("zone_key")) != zone_key:
            continue
        lower = zone.get("lower_value")
        upper = zone.get("upper_value")
        values = [round(float(value)) for value in (lower, upper) if value is not None]
        if not values:
            return None, None
        return min(values), max(values)
    return None, None


def target_race_pace_range(workout: dict[str, object]) -> tuple[int | None, int | None]:
    target = workout.get("target_race_pace_seconds_per_km")
    if target is None:
        return None, None
    seconds = max(1, round(float(target)))
    spread = max(2, round(seconds * 0.02))
    return max(1, seconds - spread), seconds + spread


def _scaled(value: float | int | None, ratio: float, digits: int = 1) -> float | None:
    if value is None:
        return None
    return round(max(0.0, float(value) * ratio), digits)


def _scaled_seconds(value: int | None, ratio: float) -> int | None:
    if value is None:
        return None
    return max(1, round(value * ratio))


def _remaining_seconds(total: int | None, *parts: int | None) -> int | None:
    if total is None:
        return None
    return max(0, int(total) - sum(int(part or 0) for part in parts))


def _remaining_distance(total: float | None, *parts: float | None) -> float | None:
    if total is None:
        return None
    return round(max(0.0, float(total) - sum(float(part or 0) for part in parts)), 2)


def _per_repeat_seconds(total: int | None, repeat_count: int) -> int | None:
    if total is None:
        return None
    return max(0, round(total / max(1, repeat_count)))


def _per_repeat_distance(total: float | None, repeat_count: int) -> float | None:
    if total is None:
        return None
    return round(max(0.0, total / max(1, repeat_count)), 2)


def block_targets_total(blocks: list[dict[str, object]], field: str) -> float:
    return sum(float(block.get(field) or 0) * int(block.get("repeat_count") or 1) for block in blocks)


def align_blocks_to_workout_targets(blocks: list[dict[str, object]], duration: int | None, distance: float | None) -> list[dict[str, object]]:
    adjustment_block = next((block for block in reversed(blocks) if int(block.get("repeat_count") or 1) == 1), blocks[-1] if blocks else None)
    if not adjustment_block:
        return blocks
    if duration is not None:
        duration_delta = int(duration) - round(block_targets_total(blocks, "target_duration_seconds"))
        if duration_delta:
            current = int(adjustment_block.get("target_duration_seconds") or 0)
            adjustment_block["target_duration_seconds"] = max(1, current + duration_delta)
    if distance is not None:
        distance_delta = round(float(distance) - block_targets_total(blocks, "target_distance_km"), 2)
        if abs(distance_delta) >= 0.01:
            current = float(adjustment_block.get("target_distance_km") or 0)
            adjustment_block["target_distance_km"] = round(max(0.0, current + distance_delta), 2)
    return blocks


def planned_block(
    block_index: int,
    block_type: str,
    description: str,
    repeat_count: int = 1,
    distance_km: float | None = None,
    duration_seconds: int | None = None,
    pace: tuple[int | None, int | None] = (None, None),
    hr: tuple[int | None, int | None] = (None, None),
    rpe: tuple[int | None, int | None] = (None, None),
) -> dict[str, object]:
    return {
        "id": None,
        "workout_id": None,
        "block_index": block_index,
        "block_type": block_type,
        "repeat_count": repeat_count,
        "target_distance_km": distance_km,
        "target_duration_seconds": duration_seconds,
        "target_pace_min_seconds_per_km": pace[0],
        "target_pace_max_seconds_per_km": pace[1],
        "target_hr_min_bpm": hr[0],
        "target_hr_max_bpm": hr[1],
        "target_rpe_min": rpe[0],
        "target_rpe_max": rpe[1],
        "description": description,
    }


def planned_workout_blocks_for_preview(workout: dict[str, object], zones: dict[str, object]) -> list[dict[str, object]]:
    workout_type = str(workout.get("workout_type") or "")
    training_age_level = str(workout.get("training_age_level") or "intermediate")
    distance = float(workout["distance_km"]) if workout.get("distance_km") is not None else None
    duration = int(workout["duration_seconds"]) if workout.get("duration_seconds") is not None else None
    easy_pace = numeric_zone_range(zones, "pace", "easy")
    steady_pace = numeric_zone_range(zones, "pace", "steady")
    threshold_pace = numeric_zone_range(zones, "pace", "threshold")
    interval_pace = numeric_zone_range(zones, "pace", "interval")
    race_pace = target_race_pace_range(workout)
    if race_pace == (None, None):
        race_pace = numeric_zone_range(zones, "pace", "race_pace")
    easy_hr = numeric_zone_range(zones, "hr", "z2")
    recovery_hr = numeric_zone_range(zones, "hr", "z1")
    quality_hr = numeric_zone_range(zones, "hr", "z3")
    interval_hr = numeric_zone_range(zones, "hr", "z4")

    if workout_type in STRENGTH_WORKOUT_TYPES:
        return [planned_block(1, "strength", "Runner strength circuit: calves/soleus, glutes, hamstrings, single-leg stability and core.", duration_seconds=duration, rpe=(4, 7))]
    if workout_type in MOBILITY_WORKOUT_TYPES:
        return [planned_block(1, "recovery", "Mobility/prehab flow with ankle, hip, glute activation and relaxed breathing.", duration_seconds=duration, rpe=(1, 3))]
    if workout_type in HARD_PLAN_WORKOUT_TYPES and duration is not None and duration < 10 * 60:
        return [planned_block(1, "work", "Workout was shortened below a safe quality duration; keep this as easy aerobic running.", distance_km=distance, duration_seconds=duration, pace=easy_pace, hr=easy_hr, rpe=(2, 4))]
    if workout_type == "interval":
        repeat_count = 4
        warmup_seconds = _scaled_seconds(duration, 0.15)
        cooldown_seconds = _scaled_seconds(duration, 0.15)
        work_seconds = capped_work_seconds(duration, "interval", training_age_level, 0.5)
        recovery_seconds = _remaining_seconds(duration, warmup_seconds, work_seconds, cooldown_seconds)
        warmup_distance = _scaled(distance, 0.15)
        cooldown_distance = _scaled(distance, 0.15)
        work_distance = capped_work_distance(distance, duration, work_seconds, 0.55, 0.5)
        recovery_distance = _remaining_distance(distance, warmup_distance, work_distance, cooldown_distance)
        return align_blocks_to_workout_targets([
            planned_block(1, "warmup", "Easy warmup before quality work.", distance_km=warmup_distance, duration_seconds=warmup_seconds, pace=easy_pace, hr=easy_hr, rpe=(2, 4)),
            planned_block(2, "work", "Long controlled work repeats near interval/threshold effort.", repeat_count=repeat_count, distance_km=_per_repeat_distance(work_distance, repeat_count), duration_seconds=_per_repeat_seconds(work_seconds, repeat_count), pace=interval_pace, hr=interval_hr, rpe=(6, 8)),
            planned_block(3, "recovery", "Easy jog or walk between work repeats; capped hard time is redistributed here.", repeat_count=repeat_count, distance_km=_per_repeat_distance(recovery_distance, repeat_count), duration_seconds=_per_repeat_seconds(recovery_seconds, repeat_count), pace=easy_pace, hr=recovery_hr, rpe=(2, 3)),
            planned_block(4, "cooldown", "Relaxed cooldown; stop early if form deteriorates.", distance_km=cooldown_distance, duration_seconds=cooldown_seconds, pace=easy_pace, hr=recovery_hr, rpe=(1, 3)),
        ], duration, distance)
    if workout_type == "hill":
        repeat_count = 6
        warmup_seconds = _scaled_seconds(duration, 0.2)
        cooldown_seconds = _scaled_seconds(duration, 0.2)
        work_seconds = capped_work_seconds(duration, "hill", training_age_level, 0.35)
        recovery_seconds = _remaining_seconds(duration, warmup_seconds, work_seconds, cooldown_seconds)
        warmup_distance = _scaled(distance, 0.2)
        cooldown_distance = _scaled(distance, 0.2)
        work_distance = capped_work_distance(distance, duration, work_seconds, 0.3, 0.35)
        recovery_distance = _remaining_distance(distance, warmup_distance, work_distance, cooldown_distance)
        return align_blocks_to_workout_targets([
            planned_block(1, "warmup", "Easy warmup before hill mechanics.", distance_km=warmup_distance, duration_seconds=warmup_seconds, pace=easy_pace, hr=easy_hr, rpe=(2, 4)),
            planned_block(2, "work", "Short controlled uphill repeats; walk or jog down fully recovered.", repeat_count=repeat_count, distance_km=_per_repeat_distance(work_distance, repeat_count), duration_seconds=_per_repeat_seconds(work_seconds, repeat_count), hr=quality_hr, rpe=(5, 7)),
            planned_block(3, "recovery", "Easy downhill/walk recovery after each repeat; capped hard time is redistributed here.", repeat_count=repeat_count, distance_km=_per_repeat_distance(recovery_distance, repeat_count), duration_seconds=_per_repeat_seconds(recovery_seconds, repeat_count), pace=easy_pace, hr=recovery_hr, rpe=(1, 3)),
            planned_block(4, "cooldown", "Easy cooldown on flat terrain.", distance_km=cooldown_distance, duration_seconds=cooldown_seconds, pace=easy_pace, hr=recovery_hr, rpe=(1, 3)),
        ], duration, distance)
    if workout_type in {"tempo", "threshold", "race_pace"}:
        quality_pace = race_pace if workout_type == "race_pace" and race_pace != (None, None) else threshold_pace
        warmup_seconds = _scaled_seconds(duration, 0.15)
        cooldown_seconds = _scaled_seconds(duration, 0.15)
        work_seconds = capped_work_seconds(duration, workout_type, training_age_level, 0.7)
        easy_seconds = _remaining_seconds(duration, warmup_seconds, work_seconds, cooldown_seconds)
        warmup_distance = _scaled(distance, 0.15)
        cooldown_distance = _scaled(distance, 0.15)
        work_distance = capped_work_distance(distance, duration, work_seconds, 0.7, 0.7)
        easy_distance = _remaining_distance(distance, warmup_distance, work_distance, cooldown_distance)
        blocks = [
            planned_block(1, "warmup", "Easy warmup and drills before sustained quality.", distance_km=warmup_distance, duration_seconds=warmup_seconds, pace=easy_pace, hr=easy_hr, rpe=(2, 4)),
            planned_block(2, "work", "Sustained controlled quality block below all-out effort.", distance_km=work_distance, duration_seconds=work_seconds, pace=quality_pace, hr=quality_hr, rpe=(5, 7)),
        ]
        if easy_seconds or easy_distance:
            blocks.append(planned_block(len(blocks) + 1, "recovery", "Easy aerobic time added so capped hard work still matches the workout target.", distance_km=easy_distance, duration_seconds=easy_seconds, pace=easy_pace, hr=easy_hr, rpe=(2, 4)))
        blocks.append(planned_block(len(blocks) + 1, "cooldown", "Easy cooldown to bring HR down.", distance_km=cooldown_distance, duration_seconds=cooldown_seconds, pace=easy_pace, hr=recovery_hr, rpe=(1, 3)))
        return align_blocks_to_workout_targets(blocks, duration, distance)
    if workout_type == "strides":
        if duration is not None and duration < 8 * 60:
            return [planned_block(1, "work", "Workout was shortened below a safe strides duration; keep this as easy aerobic running.", distance_km=distance, duration_seconds=duration, pace=easy_pace, hr=easy_hr, rpe=(2, 4))]
        repeat_count = min(6, max(2, int((duration or 12 * 60) // (2 * 60))))
        easy_seconds = _scaled_seconds(duration, 0.7)
        cooldown_seconds = _scaled_seconds(duration, 0.1)
        strides_seconds = min(20, max(10, round((duration or 20 * repeat_count) * 0.12 / repeat_count)))
        recovery_seconds = _remaining_seconds(duration, easy_seconds, strides_seconds * repeat_count, cooldown_seconds)
        strides_distance = _scaled(distance, 0.02, 2)
        cooldown_distance = _scaled(distance, 0.08)
        recovery_distance = _scaled(distance, 0.18 / repeat_count, 2)
        easy_distance = _remaining_distance(distance, (strides_distance or 0) * repeat_count, (recovery_distance or 0) * repeat_count, cooldown_distance)
        return align_blocks_to_workout_targets([
            planned_block(1, "work", "Continuous easy aerobic running before strides.", distance_km=easy_distance, duration_seconds=easy_seconds, pace=easy_pace, hr=easy_hr, rpe=(2, 4)),
            planned_block(2, "strides", "Short fast relaxed strides; never sprint all-out.", repeat_count=repeat_count, distance_km=strides_distance, duration_seconds=strides_seconds, rpe=(5, 7)),
            planned_block(3, "recovery", "Full easy jog or walk recovery between strides.", repeat_count=repeat_count, distance_km=recovery_distance, duration_seconds=_per_repeat_seconds(recovery_seconds, repeat_count), pace=easy_pace, hr=recovery_hr, rpe=(1, 3)),
            planned_block(4, "cooldown", "Easy cooldown after strides.", distance_km=cooldown_distance, duration_seconds=cooldown_seconds, pace=easy_pace, hr=recovery_hr, rpe=(1, 3)),
        ], duration, distance)
    if workout_type == "recovery":
        return [planned_block(1, "recovery", "Very easy short recovery run; keep it restorative.", distance_km=distance, duration_seconds=duration, pace=easy_pace, hr=recovery_hr, rpe=(1, 3))]
    if workout_type == "steady":
        return [
            planned_block(1, "warmup", "Easy start before aerobic steady work.", distance_km=_scaled(distance, 0.15), duration_seconds=_scaled_seconds(duration, 0.15), pace=easy_pace, hr=easy_hr, rpe=(2, 4)),
            planned_block(2, "work", "Controlled aerobic block without hard intensity.", distance_km=_scaled(distance, 0.7), duration_seconds=_scaled_seconds(duration, 0.7), pace=steady_pace, hr=easy_hr, rpe=(3, 5)),
            planned_block(3, "cooldown", "Relaxed finish.", distance_km=_scaled(distance, 0.15), duration_seconds=_scaled_seconds(duration, 0.15), pace=easy_pace, hr=recovery_hr, rpe=(1, 3)),
        ]
    if workout_type == "long":
        return [
            planned_block(1, "warmup", "Easy opening segment; keep it conversational.", distance_km=_scaled(distance, 0.25), duration_seconds=_scaled_seconds(duration, 0.25), pace=easy_pace, hr=easy_hr, rpe=(2, 4)),
            planned_block(2, "work", "Steady middle segment with fueling and hydration checks.", distance_km=_scaled(distance, 0.6), duration_seconds=_scaled_seconds(duration, 0.6), pace=easy_pace, hr=easy_hr, rpe=(2, 5)),
            planned_block(3, "cooldown", "Easy finish; do not force pace late.", distance_km=_scaled(distance, 0.15), duration_seconds=_scaled_seconds(duration, 0.15), pace=easy_pace, hr=recovery_hr, rpe=(1, 4)),
        ]
    return [planned_block(1, "work", "Continuous easy aerobic running in a relaxed conversational effort.", distance_km=distance, duration_seconds=duration, pace=easy_pace, hr=easy_hr, rpe=(2, 4))]


def block_to_dict(block: TrainingPlanWorkoutBlock) -> dict[str, object]:
    return {
        "id": block.id,
        "workout_id": block.workout_id,
        "block_index": block.block_index,
        "block_type": block.block_type,
        "repeat_count": block.repeat_count,
        "target_distance_km": block.target_distance_km,
        "target_duration_seconds": block.target_duration_seconds,
        "target_pace_min_seconds_per_km": block.target_pace_min_seconds_per_km,
        "target_pace_max_seconds_per_km": block.target_pace_max_seconds_per_km,
        "target_hr_min_bpm": block.target_hr_min_bpm,
        "target_hr_max_bpm": block.target_hr_max_bpm,
        "target_rpe_min": block.target_rpe_min,
        "target_rpe_max": block.target_rpe_max,
        "description": block.description,
    }


def create_workout_block_from_dict(block: dict[str, object]) -> TrainingPlanWorkoutBlock:
    return TrainingPlanWorkoutBlock(
        block_index=int(block["block_index"]),
        block_type=str(block["block_type"]),
        repeat_count=int(block.get("repeat_count") or 1),
        target_distance_km=float(block["target_distance_km"]) if block.get("target_distance_km") is not None else None,
        target_duration_seconds=int(block["target_duration_seconds"]) if block.get("target_duration_seconds") is not None else None,
        target_pace_min_seconds_per_km=int(block["target_pace_min_seconds_per_km"]) if block.get("target_pace_min_seconds_per_km") is not None else None,
        target_pace_max_seconds_per_km=int(block["target_pace_max_seconds_per_km"]) if block.get("target_pace_max_seconds_per_km") is not None else None,
        target_hr_min_bpm=int(block["target_hr_min_bpm"]) if block.get("target_hr_min_bpm") is not None else None,
        target_hr_max_bpm=int(block["target_hr_max_bpm"]) if block.get("target_hr_max_bpm") is not None else None,
        target_rpe_min=int(block["target_rpe_min"]) if block.get("target_rpe_min") is not None else None,
        target_rpe_max=int(block["target_rpe_max"]) if block.get("target_rpe_max") is not None else None,
        description=str(block["description"]) if block.get("description") is not None else None,
    )


def feedback_to_dict(feedback: TrainingPlanWorkoutFeedback | None, workout: TrainingPlanWorkout | None = None) -> dict[str, object] | None:
    if feedback is None:
        return None
    activity_id = feedback.activity_id
    completion_status = feedback.completion_status
    if workout is not None:
        activity_id = workout.completed_activity_id or (workout.completed_activity.id if workout.completed_activity else None)
        completion_status = workout.status
    soreness = feedback.soreness_0_10 if feedback.soreness_0_10 is not None else feedback.fatigue
    sleep_quality = feedback.sleep_quality_0_10 if feedback.sleep_quality_0_10 is not None else feedback.sleep_quality
    user_notes = feedback.user_notes if feedback.user_notes is not None else feedback.notes
    return {
        "id": feedback.id,
        "workout_id": feedback.workout_id,
        "activity_id": activity_id,
        "completion_status": completion_status,
        "rpe": feedback.rpe,
        "soreness_0_10": soreness,
        "fatigue": feedback.fatigue,
        "pain": feedback.pain,
        "pain_level": feedback.pain_level,
        "sleep_quality_0_10": sleep_quality,
        "sleep_quality": feedback.sleep_quality,
        "pain_notes": feedback.pain_notes,
        "user_notes": user_notes,
        "weather_notes": feedback.weather_notes,
        "notes": feedback.notes,
        "created_at": feedback.created_at,
        "updated_at": feedback.updated_at,
    }


def workout_execution_score(workout: TrainingPlanWorkout) -> dict[str, object]:
    activity = workout.completed_activity
    feedback = workout.feedback
    flags: list[str] = []
    volume_score: float | None = None
    intensity_score: float | None = None
    intensity_over_target = False
    subjective_risk = "unknown"
    adherence_status = "unknown"
    if feedback:
        subjective_risk = "low"
        if feedback.pain or (feedback.pain_level is not None and feedback.pain_level >= 4):
            subjective_risk = "high"
            flags.append("pain reported")
        elif (feedback.rpe is not None and feedback.rpe >= 8) or (feedback.fatigue is not None and feedback.fatigue >= 8):
            subjective_risk = "high"
            flags.append("high fatigue or RPE")
        elif (feedback.rpe is not None and feedback.rpe >= 7) or (feedback.fatigue is not None and feedback.fatigue >= 7):
            subjective_risk = "moderate"
            flags.append("moderate fatigue or RPE")
        if feedback.sleep_quality is not None and feedback.sleep_quality <= 3:
            flags.append("poor sleep")
            if subjective_risk == "low":
                subjective_risk = "moderate"
        if feedback.rpe is not None:
            if workout_is_hard(workout):
                target_low, target_high = 6, 8
            elif workout.workout_type in STRENGTH_WORKOUT_TYPES:
                target_low, target_high = 4, 7
            elif workout.workout_type in MOBILITY_WORKOUT_TYPES:
                target_low, target_high = 1, 3
            elif workout.workout_type in {"steady", "tempo"} or (workout.intensity or "") == "steady":
                target_low, target_high = 3, 6
            else:
                target_low, target_high = 2, 4
            if target_low <= feedback.rpe <= target_high:
                intensity_score = 1.0
            else:
                miss = min(abs(feedback.rpe - target_low), abs(feedback.rpe - target_high))
                intensity_score = 0.7 if miss == 1 else 0.4
                flags.append("RPE outside target range")
                if feedback.rpe > target_high:
                    intensity_over_target = True
    if workout.status in {"missed", "skipped"}:
        flags.append(f"workout {workout.status}")
        return {"score": 0.0, "status": workout.status, "volume_score": 0.0, "intensity_score": intensity_score, "adherence_status": workout.status, "subjective_risk": subjective_risk, "flags": flags}
    if workout.status == "rescheduled" and not activity:
        return {"score": None, "status": "moved", "volume_score": None, "intensity_score": intensity_score, "adherence_status": "moved", "subjective_risk": subjective_risk, "flags": flags}
    if activity and workout.distance_km and activity.distance_km is not None:
        target_ratio = activity.distance_km / max(workout.distance_km, 0.001)
        relative_delta = abs(target_ratio - 1)
        volume_score = max(0.0, min(1.0, 1 - relative_delta / 0.5))
        if target_ratio > 1.2:
            flags.append("actual volume above plan")
            adherence_status = "overdone"
        elif target_ratio >= 0.8:
            adherence_status = "completed"
        elif target_ratio >= 0.4:
            flags.append("actual volume below plan")
            adherence_status = "partial"
        else:
            flags.append("actual volume far below plan")
            adherence_status = "missed"
    elif activity and workout.duration_seconds and activity.duration_seconds:
        target_ratio = activity.duration_seconds / max(workout.duration_seconds, 1)
        relative_delta = abs(target_ratio - 1)
        volume_score = max(0.0, min(1.0, 1 - relative_delta / 0.5))
        if target_ratio > 1.2:
            flags.append("actual duration above plan")
            adherence_status = "overdone"
        elif target_ratio >= 0.8:
            adherence_status = "completed"
        elif target_ratio >= 0.4:
            flags.append("actual duration below plan")
            adherence_status = "partial"
        else:
            flags.append("actual duration far below plan")
            adherence_status = "missed"
    elif activity:
        adherence_status = "completed"
    subjective_score: float | None = None
    if feedback:
        subjective_score = 1.0
        if feedback.pain or (feedback.pain_level is not None and feedback.pain_level >= 4):
            subjective_risk = "high"
            subjective_score = 0.35
        elif (feedback.rpe is not None and feedback.rpe >= 8) or (feedback.fatigue is not None and feedback.fatigue >= 8):
            subjective_risk = "high"
            subjective_score = 0.45
        elif (feedback.rpe is not None and feedback.rpe >= 7) or (feedback.fatigue is not None and feedback.fatigue >= 7):
            subjective_risk = "moderate"
            subjective_score = 0.7
        if feedback.sleep_quality is not None and feedback.sleep_quality <= 3:
            if subjective_risk == "low":
                subjective_risk = "moderate"
            subjective_score = min(subjective_score, 0.75)
    components = [score for score in (volume_score, intensity_score, subjective_score) if score is not None]
    score = round(sum(components) / len(components), 2) if components else None
    if intensity_over_target:
        flags.append("intensity above target")
        adherence_status = "overdone"
    if score is not None:
        if adherence_status == "unknown":
            adherence_status = "completed" if score >= 0.8 else "partial"
    status = adherence_status if adherence_status in {"completed", "partial", "overdone", "missed", "moved"} else "unknown"
    return {
        "score": score,
        "status": status,
        "volume_score": round(volume_score, 2) if volume_score is not None else None,
        "intensity_score": round(intensity_score, 2) if intensity_score is not None else None,
        "adherence_status": adherence_status,
        "subjective_risk": subjective_risk,
        "flags": flags,
    }


def workout_to_dict(workout: TrainingPlanWorkout) -> dict[str, object]:
    activity = workout.completed_activity
    blocks = sorted(getattr(workout, "blocks", []) or [], key=lambda block: (block.block_index, block.id or 0))
    return {
        "id": workout.id,
        "plan_id": workout.plan_id,
        "week_index": workout.week_index,
        "day_index": workout.day_index,
        "scheduled_date": workout.scheduled_date,
        "status": workout.status,
        "completed_activity_id": workout.completed_activity_id,
        "actual_distance_km": activity.distance_km if activity else None,
        "actual_duration_seconds": activity.duration_seconds if activity else None,
        "workout_type": workout.workout_type,
        "title": workout.title,
        "distance_km": workout.distance_km,
        "duration_seconds": workout.duration_seconds,
        "intensity": workout.intensity,
        "description": workout.description,
        "blocks": [block_to_dict(block) for block in blocks],
        "feedback": feedback_to_dict(workout.feedback, workout),
        "execution_score": workout_execution_score(workout),
    }


def planned_workout_duration_seconds(workout: TrainingPlanWorkout, pace_seconds_per_km: float = 420.0) -> int:
    if workout.duration_seconds:
        return workout.duration_seconds
    if workout.distance_km:
        return int(workout.distance_km * pace_seconds_per_km)
    return 0


def adherence_summary(workouts: list[TrainingPlanWorkout], pace_seconds_per_km: float = 420.0) -> dict[str, object]:
    total = len(workouts)
    done = [workout for workout in workouts if workout.status == "done"]
    missed = [workout for workout in workouts if workout.status == "missed"]
    skipped = [workout for workout in workouts if workout.status == "skipped"]
    linked = [workout for workout in done if workout.completed_activity]
    planned_distance = sum(workout.distance_km or 0 for workout in workouts)
    completed_distance = sum((workout.completed_activity.distance_km or 0) for workout in linked)
    planned_duration = sum(planned_workout_duration_seconds(workout, pace_seconds_per_km) for workout in workouts)
    completed_duration = sum(workout.completed_activity.duration_seconds or 0 for workout in linked)
    support = [workout for workout in workouts if is_support_workout_type(workout.workout_type)]
    support_workouts = len(support)
    due_support = [workout for workout in support if workout.status in {"done", "missed", "skipped"}]
    support_done = [workout for workout in due_support if workout.status == "done" and workout.completed_activity]
    planned_support_duration = sum(planned_workout_duration_seconds(workout, pace_seconds_per_km) for workout in due_support)
    completed_support_duration = sum(workout.completed_activity.duration_seconds or 0 for workout in support_done)
    warnings = []
    if done and len(linked) < len(done):
        warnings.append("Есть выполненные тренировки без привязанной фактической активности")
    distance_rate = completed_distance / planned_distance if planned_distance else 0
    duration_rate = completed_duration / planned_duration if planned_duration else 0
    if distance_rate >= 1.2:
        warnings.append("Фактический объем заметно выше плана")
    elif planned_distance and distance_rate <= 0.75 and done:
        warnings.append("Фактический объем заметно ниже плана")
    elif not planned_distance and planned_duration and done:
        if duration_rate >= 1.2:
            warnings.append("Фактическая длительность заметно выше плана")
        elif duration_rate <= 0.75:
            warnings.append("Фактическая длительность заметно ниже плана")
    if planned_support_duration and due_support:
        support_duration_rate = completed_support_duration / planned_support_duration
        if support_duration_rate >= 1.2:
            warnings.append("ОФП/support длительность заметно выше плана")
        elif support_duration_rate <= 0.75:
            warnings.append("ОФП/support длительность заметно ниже плана")
    return {
        "total_workouts": total,
        "planned_sessions": total,
        "done_workouts": len(done),
        "completed_sessions": len(done),
        "missed_workouts": len(missed),
        "skipped_workouts": len(skipped),
        "linked_workouts": len(linked),
        "unlinked_done_workouts": len(done) - len(linked),
        "planned_distance_km": round(planned_distance, 1),
        "completed_distance_km": round(completed_distance, 1),
        "planned_duration_seconds": planned_duration,
        "completed_duration_seconds": completed_duration,
        "completion_rate": round(len(done) / total, 2) if total else 0,
        "session_adherence": round(len(done) / total, 2) if total else 0,
        "distance_completion_rate": round(distance_rate, 2) if planned_distance else 0,
        "distance_adherence": round(distance_rate, 2) if planned_distance else 0,
        "duration_completion_rate": round(duration_rate, 2) if planned_duration else 0,
        "duration_adherence": round(duration_rate, 2) if planned_duration else 0,
        "support_workouts": support_workouts,
        "warnings": warnings,
    }


def weekly_adherence_summary(workouts: list[TrainingPlanWorkout], pace_seconds_per_km: float = 420.0) -> list[dict[str, object]]:
    summaries = []
    week_indexes = sorted({workout.week_index for workout in workouts})
    for week_index in week_indexes:
        week_workouts = [workout for workout in workouts if workout.week_index == week_index]
        summary = adherence_summary(week_workouts, pace_seconds_per_km)
        summary["week_index"] = week_index
        summary["planned_workouts"] = summary.pop("total_workouts")
        summaries.append(summary)
    return summaries


def plan_detail_pace_seconds_per_km(plan: TrainingPlan) -> float:
    if plan.target_time_seconds and plan.race_distance_km and plan.race_distance_km > 0:
        return max(300.0, plan.target_time_seconds / plan.race_distance_km * 1.25)
    return 420.0


def format_duration_label(seconds: int | None) -> str:
    if not seconds:
        return "--"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m"


def workout_is_hard(workout: TrainingPlanWorkout) -> bool:
    if (workout.intensity or "") in LOW_PLAN_INTENSITIES:
        return False
    return (workout.workout_type or "") in HARD_PLAN_WORKOUT_TYPES or (workout.intensity or "") in HARD_PLAN_INTENSITIES


def workout_is_easy_run(workout: TrainingPlanWorkout) -> bool:
    workout_type = workout.workout_type or ""
    if workout_type == "long" or workout_is_hard(workout) or is_support_workout_type(workout_type):
        return False
    return workout_type in {"easy", "recovery", "strides"} or (workout.intensity or "") in {"easy", "recovery", "strides"}


def hard_workout_near_date(workouts: list[TrainingPlanWorkout], target_date: date, days: int = 3, exclude_id: int | None = None) -> TrainingPlanWorkout | None:
    for workout in workouts:
        if exclude_id is not None and workout.id == exclude_id:
            continue
        if workout.scheduled_date and workout_is_hard(workout) and abs((workout.scheduled_date - target_date).days) <= days:
            return workout
    return None


def coach_skip_note_present(workout: TrainingPlanWorkout) -> bool:
    return SKIP_MISSED_WORKOUT_NOTE in (workout.description or "")


def plan_week_summaries(plan: TrainingPlan) -> list[dict[str, object]]:
    pace_seconds_per_km = plan_detail_pace_seconds_per_km(plan)
    summaries: list[dict[str, object]] = []
    previous_planned_distance: float | None = None
    workouts = sorted(plan.workouts, key=lambda workout: (workout.week_index, workout.day_index, workout.id))
    for week_index in sorted({workout.week_index for workout in workouts}):
        week_workouts = [workout for workout in workouts if workout.week_index == week_index]
        planned_distance = sum(workout.distance_km or 0 for workout in week_workouts)
        completed = [workout for workout in week_workouts if workout.status == "done"]
        linked = [workout for workout in completed if workout.completed_activity]
        completed_distance = sum(workout.completed_activity.distance_km or 0 for workout in linked)
        completed_duration = sum(workout.completed_activity.duration_seconds or 0 for workout in linked)
        planned_duration = sum(planned_workout_duration_seconds(workout, pace_seconds_per_km) for workout in week_workouts) or None
        long_candidates = [workout.distance_km or 0 for workout in week_workouts if workout.workout_type == "long"]
        long_run = max(long_candidates or [workout.distance_km or 0 for workout in week_workouts] or [0])
        adherence = adherence_summary(week_workouts, pace_seconds_per_km)
        support_workouts = [workout for workout in week_workouts if is_support_workout_type(workout.workout_type)]
        summary = {
            "week_index": week_index,
            "planned_distance_km": round(planned_distance, 1),
            "planned_duration_seconds": planned_duration,
            "completed_distance_km": round(completed_distance, 1),
            "completed_duration_seconds": completed_duration,
            "completion_rate": round(len(completed) / len(week_workouts), 2) if week_workouts else 0,
            "distance_completion_rate": adherence["distance_completion_rate"],
            "planned_time_label": format_duration_label(planned_duration),
            "hard_sessions": sum(1 for workout in week_workouts if workout_is_hard(workout)),
            "support_workouts": len(support_workouts),
            "support_duration_seconds": sum(workout.duration_seconds or 0 for workout in support_workouts),
            "long_run_km": round(long_run, 1) if long_run else None,
            "deload": previous_planned_distance is not None and planned_distance < previous_planned_distance * 0.9,
            "workouts": [workout_to_dict(workout) for workout in week_workouts],
            "warnings": adherence["warnings"],
        }
        summaries.append(summary)
        previous_planned_distance = planned_distance
    return summaries


def recommendation_item(
    item_type: str,
    severity: str,
    title: str,
    message: str,
    reasons: list[str],
    workout_id: int | None = None,
    week_index: int | None = None,
    suggested_payload: dict | None = None,
) -> dict[str, object]:
    return {
        "type": item_type,
        "severity": severity,
        "title": title,
        "message": message,
        "workout_id": workout_id,
        "week_index": week_index,
        "reasons": reasons,
        "suggested_payload": suggested_payload,
    }


def adaptation_risk_snapshot(status: str, metrics: dict[str, object], recommendations: list[dict[str, object]], changes_count: int = 0) -> dict[str, object]:
    severity_score = {"info": 1, "warning": 2, "critical": 3}
    score = 0 if status == "ok" else 1
    reasons: list[str] = []
    for recommendation in recommendations:
        severity = str(recommendation.get("severity") or "info")
        score = max(score, severity_score.get(severity, 1))
        if recommendation.get("title"):
            reasons.append(str(recommendation["title"]))
    has_elapsed_workouts = bool(metrics.get("elapsed_workouts") or metrics.get("planned_distance_km") or metrics.get("missed_recent_workouts") or metrics.get("low_adherence_weeks"))
    if float(metrics.get("completion_rate") or 0) < 0.7 and has_elapsed_workouts:
        score = max(score, 2)
        reasons.append("plan adherence below threshold")
    if changes_count:
        reasons.append(f"{changes_count} safe automatic changes available")
    level = "low" if score <= 0 else "moderate" if score == 1 else "high" if score == 2 else "critical"
    return {"level": level, "score": score, "reasons": reasons[:5]}


def adaptation_summary_text(summary: str, changes_count: int | None = None, skipped_count: int = 0) -> str:
    if changes_count is None:
        return summary
    if changes_count:
        return f"{summary} Preview proposes {changes_count} safe automatic change(s); review before applying."
    if skipped_count:
        return f"{summary} No automatic changes were applied; {skipped_count} recommendation(s) need manual review."
    return f"{summary} No automatic adaptation changes are needed."


def applied_adaptation_summary_text(summary: str, changes_count: int, skipped_count: int = 0) -> str:
    suffix = f"Applied {changes_count} coach recommendation change(s)."
    if skipped_count:
        suffix = f"{suffix} {skipped_count} recommendation(s) still need manual review."
    return f"{summary} {suffix}"


def prioritize_recommendations(recommendations: list[dict[str, object]]) -> list[dict[str, object]]:
    severity_rank = {"critical": 0, "warning": 1, "info": 2}
    return [
        item
        for _index, item in sorted(
            enumerate(recommendations),
            key=lambda pair: (severity_rank.get(str(pair[1].get("severity") or "info"), 2), pair[0]),
        )
    ]


def recommendation_status(recommendations: list[dict[str, object]]) -> str:
    if any(item.get("severity") == "critical" for item in recommendations):
        return "adjust"
    if any(item.get("severity") == "warning" for item in recommendations):
        return "watch"
    return "ok"


def payload_bool(payload: dict[str, object], key: str, default: bool) -> bool:
    value = payload.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def today_for_user(db: Session, user: User) -> date:
    timezone_name = db.scalar(select(AthleteProfile.timezone).where(AthleteProfile.user_id == user.id)) or "Europe/Moscow"
    try:
        return datetime.now(ZoneInfo(timezone_name)).date()
    except (ZoneInfoNotFoundError, ValueError):
        return datetime.now(UTC).date()


def plan_adjustment_recommendations(db: Session, user: User, plan: TrainingPlan, limit: int | None = 6) -> dict[str, object]:
    workouts = sorted(plan.workouts, key=lambda workout: (workout.week_index, workout.day_index, workout.id))
    today = today_for_user(db, user)
    recent_start = today - timedelta(days=14)
    next_week_end = today + timedelta(days=7)
    unscheduled = [workout for workout in workouts if workout.scheduled_date is None]
    elapsed = [workout for workout in workouts if workout.scheduled_date and workout.scheduled_date <= today]
    recent = [workout for workout in workouts if workout.scheduled_date and recent_start <= workout.scheduled_date <= today]
    upcoming = [workout for workout in workouts if workout.scheduled_date and today < workout.scheduled_date <= next_week_end]
    summary = adherence_summary(elapsed)
    recommendations: list[dict[str, object]] = []

    missed_recent = [workout for workout in recent if workout.status in {"missed", "skipped"}]
    unresolved_missed_recent = [workout for workout in missed_recent if not (workout.status == "skipped" and coach_skip_note_present(workout))]
    missed_key = [workout for workout in unresolved_missed_recent if workout.workout_type == "long" or workout_is_hard(workout)]
    missed_easy = [workout for workout in unresolved_missed_recent if workout.id not in {item.id for item in missed_key} and workout_is_easy_run(workout)]
    recent_linked = [workout for workout in recent if workout.status == "done" and workout.completed_activity]
    actionable_upcoming = [workout for workout in upcoming if workout.status in MATCHABLE_WORKOUT_STATUSES and workout.completed_activity_id is None]
    weekly_elapsed = weekly_adherence_summary(elapsed)
    recent_low_adherence_weeks = [week for week in weekly_elapsed[-2:] if int(week.get("planned_workouts") or 0) > 0 and float(week.get("session_adherence") or 0) < 0.7]
    risky_feedback = [
        workout
        for workout in recent
        if workout.feedback and (
            workout.feedback.pain
            or (workout.feedback.pain_level is not None and workout.feedback.pain_level >= 4)
            or (workout.feedback.rpe is not None and workout.feedback.rpe >= 8)
            or (workout.feedback.fatigue is not None and workout.feedback.fatigue >= 8)
        )
    ]
    high_fatigue_feedback = [
        workout
        for workout in recent
        if workout.feedback and (
            (workout.feedback.rpe is not None and workout.feedback.rpe >= 8)
            or (workout.feedback.fatigue is not None and workout.feedback.fatigue >= 8)
        )
    ]
    pain_feedback = [
        workout
        for workout in recent
        if workout.feedback and (workout.feedback.pain or (workout.feedback.pain_level is not None and workout.feedback.pain_level >= 4))
    ]
    risky_feedback_ids = {workout.id for workout in risky_feedback}
    overdone_hard = [workout for workout in recent if workout.id not in risky_feedback_ids and workout_is_hard(workout) and workout_execution_score(workout)["adherence_status"] == "overdone"]
    recent_completed_distance = sum(workout.completed_activity.distance_km or 0 for workout in recent_linked)
    upcoming_planned_distance = sum(workout.distance_km or 0 for workout in actionable_upcoming)
    upcoming_hard = [workout for workout in actionable_upcoming if workout_is_hard(workout)]
    safety_gated = bool(plan.explanation and "Safety gates:" in plan.explanation and "Safety gates: no active safety gates" not in plan.explanation)

    if plan.status != "active":
        recommendations.append(recommendation_item(
            "resume_plan",
            "warning",
            "Activate before adapting",
            "Adaptive coaching is most useful on the active training plan.",
            [f"plan status is {plan.status}"],
        ))

    if unscheduled:
        recommendations.append(recommendation_item(
            "schedule_workouts",
            "info",
            "Schedule unscheduled workouts",
            "Workouts without dates are excluded from due-load calculations until they are scheduled.",
            [f"{len(unscheduled)} workouts have no scheduled date"],
            suggested_payload={"action": "schedule_unscheduled_workouts"},
        ))

    if not elapsed and any(workout.scheduled_date for workout in workouts):
        recommendations.append(recommendation_item(
            "resume_plan",
            "info",
            "Plan has not started yet",
            "Keep the first week easy and start with the next scheduled workout.",
            ["no scheduled workouts are due yet"],
        ))

    if summary["unlinked_done_workouts"]:
        recommendations.append(recommendation_item(
            "link_activity",
            "warning",
            "Link actual activities",
            "Some done workouts have no linked activity, so distance-based adjustments are unreliable.",
            [f"{summary['unlinked_done_workouts']} done workouts are unlinked"],
        ))

    if len(unresolved_missed_recent) >= 2:
        recommendations.append(recommendation_item(
            "hold_volume",
            "warning",
            "Hold next-week volume",
            "Several recent workouts were missed or skipped. Do not try to catch up; keep the next week controlled.",
            [f"{len(unresolved_missed_recent)} missed/skipped workouts in the last 14 days"],
            week_index=unresolved_missed_recent[-1].week_index if unresolved_missed_recent else None,
            suggested_payload={"action": "hold_next_week_volume"},
        ))

    if missed_easy:
        workout = missed_easy[-1]
        recommendations.append(recommendation_item(
            "skip_workout",
            "warning",
            "Missed easy run should not be stacked",
            "Skip the missed easy run rather than adding it to the next training window.",
            [f"missed {workout.workout_type} workout"],
            workout_id=workout.id,
            week_index=workout.week_index,
            suggested_payload={"action": "skip_missed_easy_workout", "workout_id": workout.id},
        ))

    if missed_key:
        workout = missed_key[-1]
        proposed_target_date = next_available_workout_date(today, workouts)
        original_nearby_quality = next((item for item in upcoming_hard if workout.scheduled_date and item.scheduled_date and 0 <= (item.scheduled_date - workout.scheduled_date).days <= 3), None)
        target_nearby_quality = hard_workout_near_date(upcoming_hard, proposed_target_date, days=3, exclude_id=workout.id)
        next_quality = original_nearby_quality or target_nearby_quality
        if next_quality:
            recommendations.append(recommendation_item(
                "skip_quality",
                "warning",
                "Missed quality should not be stacked",
                "Another hard workout is within 72 hours of the missed or proposed move date, so do not move this key session into the same window.",
                [f"missed {workout.workout_type} workout", f"nearby quality: {next_quality.scheduled_date}"],
                workout_id=workout.id,
                week_index=workout.week_index,
                suggested_payload={"action": "skip_missed_key_workout", "workout_id": workout.id},
            ))
        else:
            recommendations.append(recommendation_item(
                "move_workout",
                "warning",
                "Key workout was missed",
                "Treat the next hard session cautiously. Prefer moving the key session only if recovery is good.",
                [f"missed {workout.workout_type} workout"],
                workout_id=workout.id,
                week_index=workout.week_index,
                suggested_payload={"action": "review_or_move_key_workout", "workout_id": workout.id, "target_date": proposed_target_date.isoformat()},
            ))

    if pain_feedback:
        workout = pain_feedback[-1]
        recommendations.append(recommendation_item(
            "pain_safety",
            "critical",
            "Pain note requires safety-first adjustment",
            "Keep the next run easy or rest, and avoid high-intensity work until pain is resolved.",
            [f"pain reported on workout #{workout.id}"],
            workout_id=workout.id,
            week_index=workout.week_index,
            suggested_payload={"action": "reduce_intensity", "days": 7, "first_only": False},
        ))

    if risky_feedback:
        recommendations.append(recommendation_item(
            "reduce_intensity",
            "warning",
            "Recovery feedback is high",
            "Recent RPE, fatigue or pain feedback suggests keeping the next hard workout easier.",
            [f"{len(risky_feedback)} recent workouts with high subjective risk"],
            workout_id=risky_feedback[-1].id,
            week_index=risky_feedback[-1].week_index,
            suggested_payload={"action": "reduce_intensity", "days": 7, "first_only": False},
        ))

    if high_fatigue_feedback:
        workout = high_fatigue_feedback[-1]
        recommendations.append(recommendation_item(
            "reduce_volume",
            "warning",
            "High fatigue score reported",
            "Reduce next-week volume 15% and remove high-intensity until fatigue normalizes.",
            [f"fatigue/RPE risk on workout #{workout.id}"],
            workout_id=workout.id,
            week_index=workout.week_index,
            suggested_payload={"action": "reduce_next_week_volume", "percent": 15},
        ))

    if overdone_hard:
        workout = overdone_hard[-1]
        recommendations.append(recommendation_item(
            "reduce_intensity",
            "warning",
            "Hard workout was overdone",
            "A recent hard workout exceeded target volume or intensity; ease the next hard session before adding load.",
            [f"overdone {workout.workout_type} workout"],
            workout_id=workout.id,
            week_index=workout.week_index,
            suggested_payload={"action": "reduce_intensity", "days": 7, "first_only": True},
        ))

    if summary["planned_distance_km"] and summary["distance_completion_rate"] >= 1.2:
        recommendations.append(recommendation_item(
            "recovery",
            "warning",
            "Actual volume is above plan",
            "Add recovery emphasis before increasing distance or intensity.",
            [f"distance completion rate {summary['distance_completion_rate']:.0%}"],
            suggested_payload={"action": "reduce_intensity", "days": 2},
        ))
    elif summary["planned_distance_km"] and summary["distance_completion_rate"] <= 0.75 and summary["linked_workouts"] > 0:
        recommendations.append(recommendation_item(
            "reduce_volume",
            "warning",
            "Actual volume is below plan",
            "Reduce the next-week target rather than stacking missed kilometers.",
            [f"distance completion rate {summary['distance_completion_rate']:.0%}"],
            suggested_payload={"action": "reduce_next_week_volume", "percent": 15},
        ))

    if upcoming_planned_distance and recent_completed_distance and upcoming_planned_distance > recent_completed_distance * 1.25:
        recommendations.append(recommendation_item(
            "hold_volume",
            "warning",
            "Upcoming week may jump too much",
            "The next 7 days are more than 25% above recent linked volume. Keep easy days easy or reduce one workout.",
            [f"next 7 days {upcoming_planned_distance:.1f} km vs recent linked {recent_completed_distance:.1f} km"],
            week_index=upcoming[0].week_index if upcoming else None,
            suggested_payload={"action": "cap_next_week_growth", "max_growth_percent": 25},
        ))

    if len(upcoming_hard) >= 3:
        recommendations.append(recommendation_item(
            "training_load_risk",
            "warning",
            "Upcoming intensity concentration is high",
            "Several hard sessions are scheduled in the next week; reduce intensity concentration to lower monotony/strain risk.",
            [f"{len(upcoming_hard)} hard workouts in next 7 days"],
            week_index=upcoming_hard[0].week_index if upcoming_hard else None,
            suggested_payload={"action": "reduce_intensity", "days": 7, "first_only": False},
        ))

    if len(recent_low_adherence_weeks) >= 2:
        recommendations.append(recommendation_item(
            "regenerate_plan",
            "warning",
            "Adherence is low for two weeks",
            "Regenerate the plan from the current baseline instead of repeatedly patching the old workload.",
            [f"week {week['week_index']} adherence {float(week['session_adherence']):.0%}" for week in recent_low_adherence_weeks],
            suggested_payload={"action": "regenerate_from_current_baseline"},
        ))

    if safety_gated:
        recommendations.append(recommendation_item(
            "review_zones",
            "info",
            "Safety gate is active",
            "Avoid adding intensity until profile data and recent adherence support it.",
            ["plan explanation contains active safety gates"],
        ))

    if not recommendations:
        recommendations.append(recommendation_item(
            "resume_plan",
            "info",
            "Continue current plan",
            "No major adherence or load risks detected. Follow the next scheduled workout.",
            ["completion and distance rates are within expected range"],
        ))

    highest = recommendation_status(recommendations)
    plan_summary = {
        "ok": "Plan looks stable based on current linked activities.",
        "watch": "Coach recommends watching the next week before increasing load.",
        "adjust": "Coach recommends adjusting the plan before the next hard workout.",
    }[highest]
    metrics = {
        "completion_rate": summary["completion_rate"],
        "distance_completion_rate": summary["distance_completion_rate"],
        "missed_recent_workouts": len(unresolved_missed_recent),
        "unlinked_done_workouts": summary["unlinked_done_workouts"],
        "planned_distance_km": summary["planned_distance_km"],
        "completed_distance_km": summary["completed_distance_km"],
        "elapsed_workouts": len(elapsed),
        "recent_completed_distance_km": round(recent_completed_distance, 1),
        "upcoming_planned_distance_km": round(upcoming_planned_distance, 1),
        "low_adherence_weeks": len(recent_low_adherence_weeks),
        "upcoming_hard_workouts": len(upcoming_hard),
    }
    ordered_recommendations = prioritize_recommendations(recommendations)
    returned_recommendations = ordered_recommendations if limit is None else ordered_recommendations[:limit]
    risk_before = adaptation_risk_snapshot(highest, metrics, ordered_recommendations)
    return {
        "plan_id": plan.id,
        "status": highest,
        "generated_at": datetime.now(UTC),
        "summary": plan_summary,
        "adaptation_summary": adaptation_summary_text(plan_summary, None),
        "risk_before": risk_before,
        "risk_after": risk_before,
        "metrics": metrics,
        "recommendations": returned_recommendations,
    }


def json_safe(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


def mutable_upcoming_workouts(workouts: list[TrainingPlanWorkout], today: date) -> list[TrainingPlanWorkout]:
    next_week_end = today + timedelta(days=7)
    return [
        workout
        for workout in workouts
        if workout.scheduled_date
        and today < workout.scheduled_date <= next_week_end
        and workout.status in MATCHABLE_WORKOUT_STATUSES
        and workout.completed_activity_id is None
    ]


def append_coach_note(description: str | None, note: str) -> str:
    current = description or ""
    if note in current:
        return current
    separator = " " if current else ""
    return f"{current}{separator}{note}"[:2000]


def next_available_workout_date(today: date, workouts: list[TrainingPlanWorkout]) -> date:
    occupied = {
        workout.scheduled_date
        for workout in workouts
        if workout.scheduled_date and workout.status in {"planned", "rescheduled", "done"}
    }
    for offset in range(1, 8):
        candidate = today + timedelta(days=offset)
        if candidate not in occupied:
            return candidate
    return today + timedelta(days=1)


def plan_recommendation_preview_changes(db: Session, user: User, plan: TrainingPlan) -> dict[str, object]:
    recommendation_result = plan_adjustment_recommendations(db, user, plan, limit=None)
    recommendations = list(recommendation_result["recommendations"])
    workouts = sorted(plan.workouts, key=lambda workout: (workout.week_index, workout.day_index, workout.id))
    today = today_for_user(db, user)
    upcoming = mutable_upcoming_workouts(workouts, today)
    workouts_by_id = {workout.id: workout for workout in workouts}
    preview_values: dict[tuple[int, str], Any] = {}
    changes: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []
    resolved_recommendation_indexes: set[int] = set()
    reduce_volume_note = "Coach adjustment: reduce volume until adherence stabilizes."
    cap_growth_note = "Coach adjustment: cap next-week growth until recent volume catches up."
    skip_note = SKIP_MISSED_WORKOUT_NOTE

    def current_value(workout: TrainingPlanWorkout, field: str) -> Any:
        return preview_values.get((workout.id, field), getattr(workout, field))

    def preview_workout_is_hard(workout: TrainingPlanWorkout) -> bool:
        intensity = str(current_value(workout, "intensity") or "")
        workout_type = str(current_value(workout, "workout_type") or workout.workout_type or "")
        if intensity in LOW_PLAN_INTENSITIES:
            return False
        return workout_type in HARD_PLAN_WORKOUT_TYPES or intensity in HARD_PLAN_INTENSITIES

    def add_change(workout: TrainingPlanWorkout, field: str, after: Any, reason: str) -> bool:
        before = current_value(workout, field)
        if before == after:
            return False
        preview_values[(workout.id, field)] = after
        changes.append({
            "workout_id": workout.id,
            "field": field,
            "before": json_safe(before),
            "after": json_safe(after),
            "reason": reason,
        })
        return True

    def skip(action: str, recommendation: dict[str, object], reason: str) -> None:
        skipped.append({
            "action": action,
            "recommendation_type": recommendation.get("type"),
            "reason": reason,
        })

    def scale_upcoming_distances(percent: float, reason: str, note: str) -> tuple[bool, bool]:
        changed = False
        factor = max(0.0, 1 - percent / 100)
        eligible = [workout for workout in upcoming if current_value(workout, "distance_km")]
        covered = bool(eligible)
        for workout in upcoming:
            if note in (current_value(workout, "description") or ""):
                continue
            current_distance = current_value(workout, "distance_km")
            if not current_distance:
                continue
            covered = False
            after = round(max(1.0, float(current_distance) * factor), 1)
            changed = add_change(workout, "distance_km", after, reason) or changed
            changed = add_change(workout, "description", append_coach_note(current_value(workout, "description"), note), reason) or changed
        return changed, covered

    def ease_upcoming_hard_workouts(reason: str, days: int = 7, first_only: bool = False) -> tuple[bool, bool]:
        changed = False
        note = "Coach adjustment: keep this session easy until adherence stabilizes."
        window_end = today + timedelta(days=max(1, days))
        original_hard_workouts = [
            workout
            for workout in upcoming
            if workout.scheduled_date and workout.scheduled_date <= window_end
            and workout_is_hard(workout)
        ]
        original_hard_workouts.sort(key=lambda workout: (workout.scheduled_date or today, workout.week_index, workout.day_index, workout.id))
        if first_only:
            original_hard_workouts = original_hard_workouts[:1]
        hard_workouts = [workout for workout in original_hard_workouts if preview_workout_is_hard(workout)]
        for workout in hard_workouts:
            changed = add_change(workout, "intensity", "easy", reason) or changed
            changed = add_change(workout, "description", append_coach_note(current_value(workout, "description"), note), reason) or changed
        covered_by_existing_preview = bool(original_hard_workouts) and not hard_workouts
        return changed, covered_by_existing_preview

    for index, recommendation in enumerate(recommendations):
        payload = recommendation.get("suggested_payload") or {}
        action = payload.get("action") if isinstance(payload, dict) else None
        if not action:
            skip("none", recommendation, "recommendation has no applicable action")
            continue
        if action not in APPLICABLE_RECOMMENDATION_ACTIONS:
            skip(str(action), recommendation, "manual flow required")
            continue
        if action == "hold_next_week_volume":
            changed, covered = ease_upcoming_hard_workouts("hold volume after recent missed or skipped workouts")
            if changed or covered:
                resolved_recommendation_indexes.add(index)
            else:
                skip(action, recommendation, "no upcoming hard workouts to ease")
        elif action == "reduce_next_week_volume":
            percent = float(payload.get("percent") or 15)
            changed, covered = scale_upcoming_distances(percent, f"reduce next 7 days by {percent:g}%", reduce_volume_note)
            if changed or covered:
                resolved_recommendation_indexes.add(index)
            else:
                skip(action, recommendation, "no mutable upcoming distance to reduce")
        elif action == "reduce_intensity":
            days = int(payload.get("days") or 3)
            first_only = payload_bool(payload, "first_only", True)
            changed, covered = ease_upcoming_hard_workouts("reduce intensity while safety or recovery risk is active", days=days, first_only=first_only)
            if changed or covered:
                resolved_recommendation_indexes.add(index)
            else:
                skip(action, recommendation, f"no hard workout in the next {days} days")
        elif action == "cap_next_week_growth":
            max_growth_percent = float(payload.get("max_growth_percent") or 25)
            recent_completed = float(recommendation_result["metrics"]["recent_completed_distance_km"] or 0)
            if recent_completed <= 0:
                skip(action, recommendation, "no recent linked distance baseline")
                continue
            upcoming_distance = sum(float(current_value(workout, "distance_km") or 0) for workout in upcoming)
            cap = recent_completed * (1 + max_growth_percent / 100)
            if upcoming_distance <= cap:
                skip(action, recommendation, "upcoming mutable volume is already within cap")
                continue
            factor = cap / upcoming_distance if upcoming_distance else 1
            changed = False
            for workout in upcoming:
                if cap_growth_note in (current_value(workout, "description") or ""):
                    continue
                current_distance = current_value(workout, "distance_km")
                if not current_distance:
                    continue
                after = round(max(1.0, float(current_distance) * factor), 1)
                changed = add_change(workout, "distance_km", after, f"cap next 7 days growth at {max_growth_percent:g}%") or changed
                changed = add_change(workout, "description", append_coach_note(current_value(workout, "description"), cap_growth_note), f"cap next 7 days growth at {max_growth_percent:g}%") or changed
            if not changed:
                skip(action, recommendation, "no mutable upcoming distance to cap")
            else:
                resolved_recommendation_indexes.add(index)
        elif action == "review_or_move_key_workout":
            workout_id = payload.get("workout_id")
            workout = workouts_by_id.get(workout_id) if isinstance(workout_id, int) else None
            if not workout or workout.status not in {"missed", "skipped"} or workout.completed_activity_id is not None:
                skip(action, recommendation, "key workout cannot be safely rescheduled")
                continue
            payload_target = payload.get("target_date")
            target_date = date.fromisoformat(payload_target) if isinstance(payload_target, str) else next_available_workout_date(today, workouts)
            nearby_quality = hard_workout_near_date(upcoming, target_date, days=3, exclude_id=workout.id)
            if nearby_quality:
                skip(action, recommendation, "proposed reschedule would stack hard workouts within 72 hours")
                continue
            add_change(workout, "scheduled_date", target_date, "reschedule missed key workout cautiously")
            add_change(workout, "status", "rescheduled", "reschedule missed key workout cautiously")
            resolved_recommendation_indexes.add(index)
        elif action in {"skip_missed_key_workout", "skip_missed_easy_workout"}:
            workout_id = payload.get("workout_id")
            workout = workouts_by_id.get(workout_id) if isinstance(workout_id, int) else None
            if not workout or workout.status not in {"missed", "skipped"} or workout.completed_activity_id is not None:
                skip(action, recommendation, "missed workout cannot be safely skipped")
                continue
            reason = "skip missed key workout to avoid quality stacking" if action == "skip_missed_key_workout" else "skip missed easy workout; do not stack volume"
            changed = add_change(workout, "status", "skipped", reason)
            changed = add_change(workout, "description", append_coach_note(current_value(workout, "description"), skip_note), reason) or changed
            if not changed:
                skip(action, recommendation, "missed workout is already marked skipped")
            else:
                resolved_recommendation_indexes.add(index)

    unresolved_recommendations = [recommendation for index, recommendation in enumerate(recommendations) if index not in resolved_recommendation_indexes]
    risk_after = adaptation_risk_snapshot(recommendation_status(unresolved_recommendations), dict(recommendation_result["metrics"]), unresolved_recommendations, len(changes))
    return {
        "plan_id": plan.id,
        "generated_at": datetime.now(UTC),
        "summary": recommendation_result["summary"],
        "adaptation_summary": adaptation_summary_text(str(recommendation_result["summary"]), len(changes), len(skipped)),
        "risk_before": recommendation_result["risk_before"],
        "risk_after": risk_after,
        "changes": changes,
        "skipped": skipped,
        "recommendations": recommendations[:6],
    }


def normalize_preview_changes(changes: list[Any] | None) -> list[dict[str, object]] | None:
    if changes is None:
        return None
    normalized = []
    for change in changes:
        if hasattr(change, "model_dump"):
            normalized.append(change.model_dump())
        else:
            normalized.append(dict(change))
    return json_safe(normalized)


def apply_plan_recommendations(db: Session, user: User, plan: TrainingPlan, expected_changes: list[Any] | None = None) -> dict[str, object]:
    db.scalar(select(User.id).where(User.id == user.id).with_for_update())
    locked_plan = db.scalar(
        select(TrainingPlan)
        .where(TrainingPlan.id == plan.id, TrainingPlan.user_id == user.id)
        .options(
            selectinload(TrainingPlan.workouts).selectinload(TrainingPlanWorkout.completed_activity),
            selectinload(TrainingPlan.workouts).selectinload(TrainingPlanWorkout.feedback),
            selectinload(TrainingPlan.workouts).selectinload(TrainingPlanWorkout.blocks),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked_plan is None:
        raise ValueError("Plan not found")
    list(db.scalars(
        select(TrainingPlanWorkout)
        .where(TrainingPlanWorkout.plan_id == locked_plan.id)
        .options(
            selectinload(TrainingPlanWorkout.completed_activity),
            selectinload(TrainingPlanWorkout.feedback),
            selectinload(TrainingPlanWorkout.blocks),
        )
        .order_by(TrainingPlanWorkout.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ))
    plan = locked_plan
    preview = plan_recommendation_preview_changes(db, user, plan)
    changes = list(preview["changes"])
    skipped = list(preview["skipped"])
    if not changes:
        raise ValueError("No automatic recommendation changes to apply")
    expected = normalize_preview_changes(expected_changes)
    if expected is not None and expected != json_safe(changes):
        raise ValueError("Recommendation preview is stale; refresh preview before applying")
    workouts_by_id = {workout.id: workout for workout in plan.workouts}
    allowed_fields = {"distance_km", "intensity", "description", "scheduled_date", "status"}
    applied_summary = applied_adaptation_summary_text(str(preview.get("summary") or "Coach recommendations applied."), len(changes), len(skipped))
    try:
        for change in changes:
            workout_id = change.get("workout_id")
            field = str(change.get("field"))
            workout = workouts_by_id.get(workout_id) if isinstance(workout_id, int) else None
            if not workout or field not in allowed_fields:
                skipped.append({"action": "apply_change", "recommendation_type": None, "reason": "change target is no longer mutable"})
                continue
            after = change.get("after")
            if field == "scheduled_date" and isinstance(after, str):
                after = date.fromisoformat(after)
            setattr(workout, field, after)
        audit = TrainingPlanRecommendationAudit(
            user_id=user.id,
            plan_id=plan.id,
            action="apply_recommendations",
            status="applied",
            recommendations_snapshot=json_safe({
                "recommendations": preview["recommendations"],
                "adaptation_summary": applied_summary,
                "risk_before": preview.get("risk_before"),
                "risk_after": preview.get("risk_after"),
            }),
            preview_changes={"changes": json_safe(changes), "skipped": json_safe(preview["skipped"])},
            applied_changes={"changes": json_safe(changes), "skipped": json_safe(skipped)},
        )
        db.add(audit)
        db.flush()
        audit_id = audit.id
        version = create_plan_version(db, user, plan, "auto_adaptation", f"Applied {len(changes)} coach recommendation changes")
        db.flush()
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {
        "plan_id": plan.id,
        "audit_id": audit_id,
        "plan_version_id": version.id,
        "plan_version_number": version.version_number,
        "adaptation_summary": applied_summary,
        "risk_before": preview.get("risk_before"),
        "risk_after": preview.get("risk_after"),
        "changes": changes,
        "skipped": skipped,
    }


def activity_has_interval_structure(activity: Activity) -> bool:
    blocks = getattr(activity, "workout_blocks", []) or []
    return any(block.block_type in {"work", "recovery"} for block in blocks)


def date_score(delta_days: int | None) -> float:
    if delta_days is None:
        return 0.35
    delta = abs(delta_days)
    if delta == 0:
        return 1.0
    if delta == 1:
        return 0.86
    if delta == 2:
        return 0.68
    if delta == 3:
        return 0.5
    if delta <= CANDIDATE_DATE_WINDOW_DAYS:
        return 0.25
    return 0.0


def distance_score(actual_km: float | None, planned_km: float | None) -> float:
    if not actual_km or not planned_km:
        return 0.45
    relative_delta = abs(actual_km - planned_km) / max(planned_km, 1)
    return max(0.0, min(1.0, 1 - relative_delta / 0.6))


def duration_score(actual_seconds: int | None, planned_seconds: int | None) -> float:
    if not actual_seconds or not planned_seconds:
        return 0.45
    relative_delta = abs(actual_seconds - planned_seconds) / max(planned_seconds, 1)
    return max(0.0, min(1.0, 1 - relative_delta / 0.6))


def workout_type_score(activity: Activity, workout: TrainingPlanWorkout) -> tuple[float, list[str]]:
    reasons = []
    workout_type = workout.workout_type or ""
    title = (activity.title or "").lower()
    activity_type = (activity.activity_type or "").lower()
    has_intervals = activity_has_interval_structure(activity)
    if workout_type in SUPPORT_WORKOUT_TYPES:
        if activity_matches_support_marker(activity, workout_type):
            return 1.0, ["тип активности совпадает с support-тренировкой"]
        if activity.distance_km is None:
            return 0.35, ["duration-only активность без явного support-маркера требует ручного подтверждения"]
        return 0.2, ["план support-типа, но активность похожа на беговую"]
    if workout_type == "interval":
        if has_intervals:
            return 1.0, ["интервальная структура активности совпадает с планом"]
        if "interval" in title or "интервал" in title:
            return 0.75, ["название активности похоже на интервальную работу"]
        return 0.25, ["план интервальный, но структура активности не найдена"]
    if workout_type == "long":
        if activity.distance_km and workout.distance_km and activity.distance_km >= workout.distance_km * 0.85:
            return 0.9, ["дистанция похожа на длинную тренировку"]
        return 0.55, ["тип long в основном проверяется по дате и дистанции"]
    if workout_type in {"tempo", "steady"}:
        score = 0.45 if has_intervals else 0.7
        reasons.append("аэробная/темповая работа без интервальной структуры" if not has_intervals else "активность интервальная, совпадение типа слабее")
        return score, reasons
    if workout_type == "easy":
        score = 0.35 if has_intervals else 0.72
        reasons.append("легкая тренировка без интервальной структуры" if not has_intervals else "интервальная активность хуже совпадает с easy")
        return score, reasons
    return 0.55, ["универсальная проверка типа тренировки"]


def score_activity_workout_match(activity: Activity, workout: TrainingPlanWorkout) -> dict[str, object]:
    activity_date = activity.started_at.date() if activity.started_at else None
    delta_days = (activity_date - workout.scheduled_date).days if activity_date and workout.scheduled_date else None
    distance_delta = None
    if activity.distance_km is not None and workout.distance_km is not None:
        distance_delta = round(activity.distance_km - workout.distance_km, 2)
    duration_delta = None
    if activity.duration_seconds is not None and workout.duration_seconds is not None:
        duration_delta = int(activity.duration_seconds - workout.duration_seconds)

    reasons = []
    if delta_days is None:
        reasons.append("дата активности или плановой тренировки не указана")
    elif abs(delta_days) <= 1:
        reasons.append("дата активности близка к плановой")
    elif abs(delta_days) <= 3:
        reasons.append("активность в допустимом окне +/-3 дня")
    else:
        reasons.append("активность далеко от плановой даты")

    if workout.distance_km is not None:
        volume_component = distance_score(activity.distance_km, workout.distance_km)
        if distance_delta is None:
            reasons.append("дистанция не задана для одной из сторон")
        elif abs(distance_delta) <= max(0.75, (workout.distance_km or 0) * 0.12):
            reasons.append("дистанция близка к плану")
        elif distance_delta > 0:
            reasons.append("фактическая дистанция выше плановой")
        else:
            reasons.append("фактическая дистанция ниже плановой")
    else:
        volume_component = duration_score(activity.duration_seconds, workout.duration_seconds)
        if duration_delta is None:
            reasons.append("длительность не задана для одной из сторон")
        elif abs(duration_delta) <= max(300, int((workout.duration_seconds or 0) * 0.15)):
            reasons.append("длительность близка к плану")
        elif duration_delta > 0:
            reasons.append("фактическая длительность выше плановой")
        else:
            reasons.append("фактическая длительность ниже плановой")

    type_score, type_reasons = workout_type_score(activity, workout)
    reasons.extend(type_reasons)
    score = round(
        date_score(delta_days) * 0.48
        + volume_component * 0.34
        + type_score * 0.18,
        2,
    )
    if is_support_workout_type(workout.workout_type) and not activity_matches_support_marker(activity, workout.workout_type or ""):
        score = min(score, AUTO_MATCH_MIN_SCORE - 0.01)
        reasons.append("auto-link отключен без явного support-маркера")
    confidence = "high" if score >= AUTO_MATCH_MIN_SCORE else "medium" if score >= 0.55 else "low"
    return {
        "score": score,
        "confidence": confidence,
        "reasons": reasons,
        "date_delta_days": delta_days,
        "distance_delta_km": distance_delta,
        "duration_delta_seconds": duration_delta,
    }


def linked_activity_ids(db: Session, user: User, exclude_workout_id: int | None = None) -> set[int]:
    query = (
        select(TrainingPlanWorkout.completed_activity_id)
        .join(TrainingPlan)
        .where(TrainingPlan.user_id == user.id, TrainingPlanWorkout.completed_activity_id.is_not(None))
    )
    if exclude_workout_id is not None:
        query = query.where(TrainingPlanWorkout.id != exclude_workout_id)
    return {activity_id for activity_id in db.scalars(query) if activity_id is not None}


def activity_match_candidates_for_workout(db: Session, user: User, workout: TrainingPlanWorkout, limit: int = 6) -> list[dict[str, object]]:
    already_linked = linked_activity_ids(db, user, exclude_workout_id=workout.id)
    activities = list(db.scalars(
        select(Activity)
        .where(Activity.user_id == user.id)
        .options(selectinload(Activity.segments), selectinload(Activity.split_blocks), selectinload(Activity.workout_blocks), selectinload(Activity.derived_metrics))
        .order_by(Activity.started_at.desc().nullslast(), Activity.id.desc())
        .limit(200)
    ))
    candidates = []
    for activity in activities:
        if activity.id in already_linked:
            continue
        match = score_activity_workout_match(activity, workout)
        delta_days = match["date_delta_days"]
        if delta_days is not None and abs(int(delta_days)) > CANDIDATE_DATE_WINDOW_DAYS:
            continue
        if float(match["score"]) < CANDIDATE_MIN_SCORE and activity.id != workout.completed_activity_id:
            continue
        candidates.append({"activity": activity, **match})
    candidates.sort(key=lambda candidate: (-float(candidate["score"]), abs(candidate["date_delta_days"] or 0), candidate["activity"].id))
    return candidates[:limit]


def workout_match_candidates_for_activity(
    db: Session,
    user: User,
    activity: Activity,
    limit: int = 6,
    active_only: bool = False,
    min_score: float = CANDIDATE_MIN_SCORE,
    date_window_days: int = CANDIDATE_DATE_WINDOW_DAYS,
) -> list[dict[str, object]]:
    if activity_is_linked(db, user, activity.id):
        return []
    query = (
        select(TrainingPlanWorkout)
        .join(TrainingPlan)
        .where(
            TrainingPlan.user_id == user.id,
            TrainingPlanWorkout.status.in_(MATCHABLE_WORKOUT_STATUSES),
            TrainingPlanWorkout.completed_activity_id.is_(None),
        )
        .options(selectinload(TrainingPlanWorkout.completed_activity), selectinload(TrainingPlanWorkout.blocks))
        .order_by(TrainingPlanWorkout.scheduled_date.asc().nullslast(), TrainingPlanWorkout.id.asc())
    )
    if active_only:
        query = query.where(TrainingPlan.status == "active")
    workouts = list(db.scalars(query))
    candidates = []
    for workout in workouts:
        match = score_activity_workout_match(activity, workout)
        delta_days = match["date_delta_days"]
        if delta_days is not None and abs(int(delta_days)) > date_window_days:
            continue
        if float(match["score"]) < min_score:
            continue
        candidates.append({"workout": workout, **match})
    candidates.sort(key=lambda candidate: (-float(candidate["score"]), abs(candidate["date_delta_days"] or 0), candidate["workout"].id))
    return candidates[:limit]


def activity_is_linked(db: Session, user: User, activity_id: int, exclude_workout_id: int | None = None) -> bool:
    query = (
        select(TrainingPlanWorkout.id)
        .join(TrainingPlan)
        .where(TrainingPlan.user_id == user.id, TrainingPlanWorkout.completed_activity_id == activity_id)
    )
    if exclude_workout_id is not None:
        query = query.where(TrainingPlanWorkout.id != exclude_workout_id)
    return db.scalar(query.limit(1)) is not None


def link_activity_to_workout(db: Session, user: User, workout: TrainingPlanWorkout, activity_id: int) -> TrainingPlanWorkout:
    activity = db.scalar(select(Activity).where(Activity.id == activity_id, Activity.user_id == user.id))
    if activity is None:
        raise ValueError("Activity not found")
    if workout.completed_activity_id is not None and workout.completed_activity_id != activity.id:
        raise ValueError("Workout already linked to another activity")
    if workout.completed_activity_id is None and workout.status not in MATCHABLE_WORKOUT_STATUSES:
        raise ValueError("Workout status cannot be linked")
    if activity_is_linked(db, user, activity.id, exclude_workout_id=workout.id):
        raise ValueError("Activity already linked to another workout")
    newly_completed = workout.completed_activity_id is None
    workout.completed_activity_id = activity.id
    workout.completed_activity = activity
    workout.status = "done"
    if workout.feedback:
        sync_feedback_context(workout.feedback, workout)
    if newly_completed:
        record_workout_completed_event(db, user, workout, activity, "manual_activity_link")
    sync_daily_training_loads_for_activity(db, user, activity)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise ValueError("Activity already linked to another workout") from error
    db.refresh(workout)
    return workout


def auto_match_activity_to_plan(db: Session, user: User, activity: Activity) -> TrainingPlanWorkout | None:
    # FOR NO KEY UPDATE serializes plan writers without conflicting with the
    # foreign-key key-share lock held by an activity inserted in this transaction.
    db.scalar(select(User.id).where(User.id == user.id).with_for_update(key_share=True))
    if activity_is_linked(db, user, activity.id):
        return None
    candidates = workout_match_candidates_for_activity(
        db,
        user,
        activity,
        limit=2,
        active_only=True,
        min_score=AUTO_MATCH_MIN_SCORE,
        date_window_days=AUTO_MATCH_DATE_WINDOW_DAYS,
    )
    if not candidates:
        return None
    if len(candidates) > 1 and float(candidates[1]["score"]) >= float(candidates[0]["score"]) - 0.08:
        return None
    workout = candidates[0]["workout"]
    db.scalar(select(TrainingPlan.id).where(TrainingPlan.id == workout.plan_id, TrainingPlan.user_id == user.id).with_for_update())
    workout = db.scalar(
        select(TrainingPlanWorkout)
        .where(TrainingPlanWorkout.id == workout.id, TrainingPlanWorkout.plan_id == workout.plan_id)
        .options(
            selectinload(TrainingPlanWorkout.completed_activity),
            selectinload(TrainingPlanWorkout.feedback),
            selectinload(TrainingPlanWorkout.blocks),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if workout is None:
        return None
    if workout.completed_activity_id is not None or workout.status not in MATCHABLE_WORKOUT_STATUSES:
        return None
    workout.completed_activity_id = activity.id
    workout.completed_activity = activity
    workout.status = "done"
    if workout.feedback:
        sync_feedback_context(workout.feedback, workout)
    db.flush()
    record_workout_completed_event(db, user, workout, activity, "activity_import")
    sync_daily_training_loads_for_activity(db, user, activity)
    return workout


def plan_to_dict(plan: TrainingPlan) -> dict[str, object]:
    workouts = sorted(plan.workouts, key=lambda workout: (workout.week_index, workout.day_index, workout.id))
    pace_seconds_per_km = plan_detail_pace_seconds_per_km(plan)
    return {
        "id": plan.id,
        "title": plan.title,
        "goal_type": plan.goal_type,
        "race_distance_km": plan.race_distance_km,
        "target_date": plan.target_date,
        "target_time_seconds": plan.target_time_seconds,
        "available_days_per_week": plan.available_days_per_week,
        "status": plan.status,
        "explanation": plan.explanation,
        "workouts": [workout_to_dict(workout) for workout in workouts],
        "adherence": adherence_summary(workouts, pace_seconds_per_km),
        "weekly_adherence": weekly_adherence_summary(workouts, pace_seconds_per_km),
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
    }


def preview_workout_is_hard(workout: dict[str, object]) -> bool:
    return str(workout.get("workout_type") or "") in HARD_PLAN_WORKOUT_TYPES or str(workout.get("intensity") or "") in HARD_PLAN_INTENSITIES


def preview_intensity_category(workout: dict[str, object]) -> str:
    workout_type = str(workout.get("workout_type") or "")
    if workout_type in STRENGTH_WORKOUT_TYPES:
        return "strength"
    if workout_type in MOBILITY_WORKOUT_TYPES:
        return "mobility"
    if preview_workout_is_hard(workout):
        return "hard"
    if "steady" in str(workout.get("intensity") or "") or workout.get("workout_type") == "steady":
        return "steady"
    return "easy"


def wizard_workout_description(description: str, request: PlanGenerateRequest, goal_distance: float) -> str:
    notes = []
    if request.intensity_mode == "rpe":
        notes.append("Use RPE as the primary intensity target.")
    elif request.intensity_mode == "hr":
        notes.append("Use HR zones as the primary intensity target.")
    elif request.intensity_mode == "pace":
        notes.append("Use pace targets as the primary intensity target.")
    if request.target_time_seconds:
        target_pace = request.target_time_seconds / max(goal_distance, 1)
        notes.append(f"Target race pace: {format_pace(target_pace)}.")
    if request.terrain:
        notes.append(f"Terrain constraint: {request.terrain}.")
    return f"{description} {' '.join(notes)}"[:2000]


def goal_distance_for_request(request: PlanGenerateRequest) -> float:
    if request.goal_type == "base_building":
        return 10.0
    return request.race_distance_km or 10.0


def estimated_easy_pace_seconds_per_km(request: PlanGenerateRequest, zones: dict[str, object], goal_distance: float) -> float:
    pace_zones = zones.get("pace") or []
    for zone in pace_zones:
        if str(zone.get("zone_key")) == "easy" and zone.get("lower_value") and zone.get("upper_value"):
            return (float(zone["lower_value"]) + float(zone["upper_value"])) / 2
    if request.target_time_seconds and goal_distance > 0:
        return max(300.0, request.target_time_seconds / goal_distance * 1.25)
    if request.recent_race_time_seconds and request.recent_race_distance_km:
        return max(300.0, request.recent_race_time_seconds / request.recent_race_distance_km * 1.25)
    return 420.0


def builder_risk_flags(
    request: PlanGenerateRequest,
    baseline: dict[str, object],
    weekly_curve: list[dict[str, object]],
    workouts: list[dict[str, object]],
    safety: dict[str, object],
    completeness: dict[str, object],
    goal_distance: float,
    weeks: int,
    start_date: date,
) -> list[dict[str, object]]:
    flags: list[dict[str, object]] = []
    max_days = max_running_days_for_level(str(baseline.get("training_age_level") or "beginner"))
    if request.available_days_per_week > max_days:
        flags.append({
            "code": "running_days_capped_by_experience",
            "severity": "warning",
            "message": "Requested running frequency is above the safe level for current training age.",
            "reasons": [
                f"requested days/week: {request.available_days_per_week}",
                f"effective cap for {baseline.get('training_age_level')}: {max_days}",
            ],
        })
    if request.target_date:
        min_weeks = 16 if goal_distance >= 42 else 10 if goal_distance >= 21 else 6 if goal_distance >= 10 else 4
        if request.priority in {"a", "high"}:
            min_weeks += 2
        available_days = max(0, (request.target_date - start_date).days)
        available_weeks = ceil(available_days / 7) if available_days else 0
        if available_days < min_weeks * 7:
            flags.append({
                "code": "target_too_close",
                "severity": "warning",
                "message": "Цель слишком близко для полной безопасной подготовки.",
                "reasons": [
                    f"available days: {available_days}",
                    f"available weeks: {available_weeks}",
                    f"generated plan length: {weeks} weeks",
                    f"recommended minimum for goal: {min_weeks} weeks",
                ],
            })
    current_volume = float(baseline["current_weekly_volume_km"] or 0)
    if goal_distance >= 42 and current_volume < 20:
        flags.append({
            "code": "marathon_low_volume",
            "severity": "warning",
            "message": "Marathon requested при объеме меньше 20 км/нед.",
            "reasons": [f"current volume: {current_volume:.1f} km/week"],
        })
    if goal_distance >= 42 and request.available_days_per_week < 3:
        flags.append({
            "code": "marathon_low_frequency",
            "severity": "warning",
            "message": "Марафонский план на 2 беговых дня ограничен: это минимум, а не полноценная подготовка.",
            "reasons": [
                f"requested days/week: {request.available_days_per_week}",
                "recommended marathon minimum: 3 running days/week",
            ],
        })
    elif goal_distance >= 21 and request.available_days_per_week < 3:
        flags.append({
            "code": "long_goal_low_frequency",
            "severity": "warning",
            "message": "Для длинной цели лучше иметь минимум 3 беговых дня в неделю.",
            "reasons": [f"requested days/week: {request.available_days_per_week}"],
        })
    if request.target_time_seconds and request.recent_race_distance_km and request.recent_race_time_seconds:
        target_pace = request.target_time_seconds / max(goal_distance, 1)
        recent_pace = request.recent_race_time_seconds / max(request.recent_race_distance_km, 1)
        if target_pace < recent_pace * 0.92:
            flags.append({
                "code": "ambitious_target_time",
                "severity": "warning",
                "message": "Target time is substantially faster than recent race pace.",
                "reasons": [f"target pace: {format_pace(target_pace)}", f"recent race pace: {format_pace(recent_pace)}"],
            })
    recent_long = baseline.get("recent_long_run_km")
    peak_long = max((float(week["long_run_km"] or 0) for week in weekly_curve), default=0.0)
    if goal_distance >= 21 and not recent_long:
        flags.append({
            "code": "no_recent_long_run",
            "severity": "warning",
            "message": "Нет recent long run для проверки длинной прогрессии.",
            "reasons": ["no long run detected in the last 8 weeks"],
        })
    elif recent_long and peak_long > float(recent_long) * 1.5 and peak_long > float(recent_long) + 5:
        flags.append({
            "code": "long_run_progression",
            "severity": "warning",
            "message": "Long run progression выглядит слишком резкой.",
            "reasons": [f"recent long run: {float(recent_long):.1f} km", f"planned peak long run: {peak_long:.1f} km"],
        })
    max_hard_sessions = max((int(week["hard_sessions"] or 0) for week in weekly_curve), default=0)
    if max_hard_sessions > 2:
        flags.append({
            "code": "too_many_hard_sessions",
            "severity": "critical",
            "message": "Больше 2 hard sessions в неделю.",
            "reasons": [f"max hard sessions: {max_hard_sessions}"],
        })
    first_week_hard = sorted(
        [workout for workout in workouts if workout["week_index"] == 1 and preview_workout_is_hard(workout) and isinstance(workout.get("scheduled_date"), date)],
        key=lambda item: item["scheduled_date"],
    )
    for index, workout in enumerate(first_week_hard[:-1]):
        next_workout = first_week_hard[index + 1]
        delta_days = (next_workout["scheduled_date"] - workout["scheduled_date"]).days
        if 0 <= delta_days <= 1:
            flags.append({
                "code": "missing_recovery_after_hard",
                "severity": "warning",
                "message": "Нет recovery day после hard session.",
                "reasons": [f"{workout['scheduled_date']} followed by {next_workout['scheduled_date']}"],
            })
            break
    if request.intensity_mode in {"pace", "mixed"} and not completeness["can_calculate_pace_zones"]:
        flags.append({
            "code": "missing_pace_zones",
            "severity": "info",
            "message": "Нет исходных данных для темповых зон.",
            "reasons": ["lactate threshold pace is missing"],
        })
    recent_median = float(baseline.get("recent_run_distance_median_km") or 0)
    if recent_median >= 8:
        short_primary = [
            workout for workout in workouts
            if workout.get("week_index") in {1, 2}
            and workout_slot_role(str(workout.get("workout_type") or "")) in {"easy", "quality"}
            and float(workout.get("distance_km") or 0) < recent_median * 0.58
        ]
        if short_primary:
            shortest = min(float(workout.get("distance_km") or 0) for workout in short_primary)
            flags.append({
                "code": "short_runs_vs_recent_pattern",
                "severity": "warning",
                "message": "Некоторые primary runs заметно короче recent typical run.",
                "reasons": [f"typical run: {recent_median:.1f} km", f"shortest primary run: {shortest:.1f} km"],
            })
    if safety["reasons"]:
        flags.append({
            "code": "safety_gates",
            "severity": "info",
            "message": "Активны safety gates для conservative planning.",
            "reasons": list(safety["reasons"]),
        })
    return flags[:8]


def build_plan_preview_blueprint(
    request: PlanGenerateRequest,
    profile: AthleteProfile,
    completeness: dict[str, object],
    profile_safety: dict[str, object],
    zones: dict[str, object],
    context: dict[str, object],
    start_date: date,
) -> dict[str, object]:
    weeks = plan_weeks_for_request(request, start_date)
    goal_distance = goal_distance_for_request(request)
    if request.current_weekly_distance_km is not None:
        current_volume = request.current_weekly_distance_km
        volume_source = "manual_override"
    else:
        current_volume = float(context["current_weekly_volume_km"] or DEFAULT_WEEKLY_VOLUME_KM)
        volume_source = str(context["current_weekly_volume_source"])
    current_volume = round(max(3.0, current_volume), 1)
    observed_weekly_volume = [float(volume or 0) for volume in (context.get("observed_weekly_volume_km") or [])]
    recent_long_run = request.longest_recent_run_km if request.longest_recent_run_km is not None else context.get("recent_long_run_km")
    if "consistent_weeks" in context and context["consistent_weeks"] is not None:
        consistent_weeks = int(context["consistent_weeks"])
    else:
        consistent_weeks = observed_consistent_weeks(observed_weekly_volume, int(context.get("history_span_days") or 0))
    quality_sessions_8w = int(context.get("quality_sessions_8w") or 0)
    recent_run_distance_median = context.get("recent_run_distance_median_km")
    recent_run_distance_median_float = float(recent_run_distance_median) if recent_run_distance_median is not None else None
    detected_training_age_level = classify_training_age_level(current_volume, float(recent_long_run) if recent_long_run is not None else None, consistent_weeks, quality_sessions_8w)
    training_age_level = apply_aggressiveness_override(detected_training_age_level, request.aggressiveness)
    requested_days = request.available_days_per_week
    max_running_days = max_running_days_for_level(training_age_level)
    days, running_days_capped_by_pattern = effective_running_days_for_pattern(requested_days, max_running_days, current_volume, recent_run_distance_median_float, goal_distance)
    baseline = {
        "observed_weekly_volume_km": context["observed_weekly_volume_km"],
        "current_weekly_volume_km": current_volume,
        "current_weekly_volume_source": volume_source,
        "recent_long_run_km": recent_long_run,
        "recent_run_distance_median_km": recent_run_distance_median,
        "recent_run_count_4w": int(context.get("recent_run_count_4w") or 0),
        "history_span_days": context["history_span_days"],
        "consistent_weeks": consistent_weeks,
        "activity_count": context["activity_count"],
        "training_age_level": training_age_level,
        "detected_training_age_level": detected_training_age_level,
        "quality_sessions_8w": quality_sessions_8w,
        "confidence": "medium" if volume_source == "manual_override" else context["confidence"],
    }
    safety_context = {**context, "recent_weekly_distance_km": current_volume, "current_weekly_volume_km": current_volume}
    safety = build_safety_context(profile, completeness, safety_context, goal_distance, request)
    conservative = bool(safety["conservative"])
    has_pace_zones = bool(completeness["can_calculate_pace_zones"])
    has_hr_zones = bool(completeness["can_calculate_hr_zones"] or completeness["can_calculate_hrr_zones"])
    has_threshold_zones = bool(
        completeness["can_calculate_pace_zones"]
        or profile.lactate_threshold_hr_bpm
        or any(str(zone.get("method") or "") in {"threshold_hr", "threshold_pace"} for zone in (zones.get("hr") or []) + (zones.get("pace") or []))
    )
    has_precise_zones = bool(has_pace_zones or has_hr_zones or request.intensity_mode == "rpe")
    has_quality_history = quality_sessions_8w > 0
    rpe_quality_ready = ready_for_controlled_rpe_quality(context, current_volume)
    can_prescribe_hard = bool((has_precise_zones or has_quality_history or rpe_quality_ready) and (training_age_level != "beginner" or has_threshold_zones or has_quality_history or rpe_quality_ready))
    easy_pace_seconds_per_km = estimated_easy_pace_seconds_per_km(request, zones, goal_distance)
    support_settings = support_session_settings(request, str(baseline["training_age_level"]), conservative)
    support_settings, support_limited_by_budget = fit_support_settings_to_time_budget(support_settings, request.time_budget_minutes_per_week, easy_pace_seconds_per_km)
    weekly_support_duration_seconds = support_settings_duration_seconds(support_settings)
    request_preferred_weekdays = request.preferred_weekdays or []
    preferred_weekdays = request_preferred_weekdays or profile.preferred_weekdays or []
    profile_long_run_weekday = profile.long_run_weekday if profile.long_run_weekday and 1 <= profile.long_run_weekday <= 7 else None
    long_run_weekday = profile_long_run_weekday if profile_long_run_weekday and (not request_preferred_weekdays or profile_long_run_weekday in preferred_weekdays) else None
    default_max_long_run_km = default_long_run_distance_cap_km(goal_distance, training_age_level)
    default_max_long_run_duration_minutes = default_long_run_duration_cap_minutes(goal_distance, training_age_level)
    max_long_run_km = smallest_cap([request.max_long_run_km, default_max_long_run_km])
    max_run_duration_minutes = smallest_cap([request.max_long_run_duration_minutes, profile.max_run_duration_minutes, default_max_long_run_duration_minutes])
    schedule_offsets = schedule_offsets_for_plan(start_date, days, preferred_weekdays, long_run_weekday)
    long_run_day_index = None
    if long_run_weekday:
        long_offset = (long_run_weekday - start_date.isoweekday()) % 7
        if long_offset in schedule_offsets:
            long_run_day_index = schedule_offsets.index(long_offset) + 1
    priority_multiplier = 1.05 if request.priority in {"a", "high"} else 0.95 if request.priority in {"c", "low"} else 1.0
    target_time_multiplier = 1.03 if request.target_time_seconds else 1.0
    days_multiplier = max(0.75, min(1.15, days / 4))
    length_multiplier = max(0.75, min(1.1, weeks / 12))
    growth_factor = (1.16 if conservative else 1.35) * priority_multiplier * length_multiplier
    goal_factor = (0.75 if conservative else (1.15 if goal_distance >= 21 else 0.9)) * priority_multiplier * target_time_multiplier * days_multiplier * length_multiplier
    peak_volume = max(current_volume * growth_factor, goal_distance * goal_factor)
    if conservative:
        peak_volume = min(peak_volume, current_volume * growth_factor)
    max_weekly_growth = max_weekly_growth_for_level(training_age_level)
    long_run_share = long_run_share_for_goal_frequency(training_age_level, conservative, goal_distance, days)

    workouts: list[dict[str, object]] = []
    weekly_curve: list[dict[str, object]] = []
    intensity_volume = {"easy": 0.0, "steady": 0.0, "hard": 0.0, "strength": 0.0, "mobility": 0.0}
    running_floor_limited_by_budget = False
    last_build_week_volume = current_volume
    has_race_goal = request.goal_type != "base_building"
    periodization_goal_distance = goal_distance if has_race_goal else None
    taper_weeks = taper_weeks_for_goal(periodization_goal_distance, weeks)
    for week in range(1, weeks + 1):
        phase = phase_for_week(week, weeks, periodization_goal_distance)
        progression = week / weeks
        week_volume = current_volume + (peak_volume - current_volume) * min(1, progression * 1.15)
        week_volume = min(week_volume, last_build_week_volume * (1 + max_weekly_growth))
        if phase != "taper" and week % 4 == 0:
            week_volume *= 0.78
        if phase == "taper":
            week_volume *= taper_volume_multiplier(week, weeks, periodization_goal_distance)
        if request.time_budget_minutes_per_week:
            running_budget_seconds = max(0, request.time_budget_minutes_per_week * 60 - weekly_support_duration_seconds)
            budget_distance = running_budget_seconds / easy_pace_seconds_per_km
            week_volume = min(week_volume, max(1.0, budget_distance))
        goal_long_cap = default_max_long_run_km if default_max_long_run_km is not None else goal_distance * (0.62 if conservative else 0.75)
        if default_max_long_run_km is None and recent_long_run and volume_source != "manual_override":
            goal_long_cap = max(goal_long_cap, min(goal_distance * 1.2, float(recent_long_run) * 1.05))
        long_run = min(goal_long_cap, week_volume * long_run_share)
        if max_long_run_km:
            long_run = min(long_run, max_long_run_km)
        if max_run_duration_minutes:
            long_run = min(long_run, max_run_duration_minutes * 60 / easy_pace_seconds_per_km)
        long_run = min(long_run, week_volume)
        if week == 1 and recent_long_run and volume_source != "manual_override":
            recent_long_floor = min(float(recent_long_run) * 0.85, week_volume, goal_long_cap)
            if max_long_run_km:
                recent_long_floor = min(recent_long_floor, max_long_run_km)
            if max_run_duration_minutes:
                recent_long_floor = min(recent_long_floor, max_run_duration_minutes * 60 / easy_pace_seconds_per_km)
            long_run = max(long_run, recent_long_floor)
        week_start = start_date + timedelta(days=(week - 1) * 7)
        week_workouts = workout_template_for_schedule(
            days,
            conservative=conservative,
            can_prescribe_hard=can_prescribe_hard,
            training_age_level=training_age_level,
            has_pace_zones=has_pace_zones,
            long_run_day_index=long_run_day_index,
            week_index=week,
            weeks=weeks,
            has_target_time=bool(request.target_time_seconds),
            phase=phase,
            has_race_goal=has_race_goal,
            recent_quality_sessions=quality_sessions_8w if int(context.get("recent_run_count_4w") or 0) > 0 else 0,
            goal_distance=goal_distance,
        )
        week_distances = allocate_week_distances(week_volume, long_run, week_workouts, recent_run_distance_median_float)
        week_preview_workouts: list[dict[str, object]] = []
        for day_index, workout_type, title, intensity in week_workouts:
            distance = week_distances.get(day_index, 0.1)
            slot_role = workout_slot_role(workout_type)
            workout = {
                "week_index": week,
                "day_index": day_index,
                "scheduled_date": scheduled_workout_date(start_date, week, day_index, days, preferred_weekdays, long_run_weekday),
                "slot_role": slot_role,
                "workout_type": workout_type,
                "title": title,
                "distance_km": distance,
                "duration_seconds": max(1, round(distance * easy_pace_seconds_per_km)),
                "intensity": intensity,
                "description": wizard_workout_description(workout_description(workout_type, intensity, zones, conservative), request, goal_distance),
                "training_age_level": training_age_level,
                "target_race_pace_seconds_per_km": round(request.target_time_seconds / goal_distance) if request.target_time_seconds and goal_distance > 0 else None,
                "phase": phase,
            }
            week_preview_workouts.append(workout)
        if request.time_budget_minutes_per_week:
            running_budget_seconds = max(0, request.time_budget_minutes_per_week * 60 - weekly_support_duration_seconds)
            while sum(int(workout.get("duration_seconds") or 0) for workout in week_preview_workouts) > running_budget_seconds:
                adjustable = [workout for workout in week_preview_workouts if float(workout.get("distance_km") or 0) > 0.1]
                if not adjustable:
                    break
                current_running_distance = round(sum(float(workout.get("distance_km") or 0) for workout in week_preview_workouts), 1)
                if current_running_distance <= 1.0 or current_running_distance - 0.1 <= 1.0:
                    running_floor_limited_by_budget = True
                    break
                workout = max(adjustable, key=lambda item: float(item.get("distance_km") or 0))
                workout["distance_km"] = round(max(0.1, float(workout.get("distance_km") or 0) - 0.1), 1)
                workout["duration_seconds"] = max(1, round(float(workout["distance_km"]) * easy_pace_seconds_per_km))
            rounded_distance = round(sum(float(workout.get("distance_km") or 0) for workout in week_preview_workouts), 1)
            if rounded_distance < 1.0 and week_preview_workouts:
                workout = max(week_preview_workouts, key=lambda item: float(item.get("distance_km") or 0))
                workout["distance_km"] = round(float(workout.get("distance_km") or 0) + (1.0 - rounded_distance), 1)
                workout["duration_seconds"] = max(1, round(float(workout["distance_km"]) * easy_pace_seconds_per_km))
                if sum(int(workout.get("duration_seconds") or 0) for workout in week_preview_workouts) > running_budget_seconds:
                    running_floor_limited_by_budget = True
        week_distance = sum(float(workout.get("distance_km") or 0) for workout in week_preview_workouts)
        long_run = max((float(workout.get("distance_km") or 0) for workout in week_preview_workouts if workout.get("workout_type") == "long"), default=0.0)
        hard_sessions = sum(1 for workout in week_preview_workouts if preview_workout_is_hard(workout))
        if phase != "taper" and week % 4 != 0:
            last_build_week_volume = week_distance
        for workout in week_preview_workouts:
            intensity_volume[preview_intensity_category(workout)] += int(workout.get("duration_seconds") or 0)
        workouts.extend(week_preview_workouts)
        support_workouts = support_workouts_for_week(week, days, week_start, week_preview_workouts, support_settings, request, phase)
        workouts.extend(support_workouts)
        support_duration = sum(int(workout.get("duration_seconds") or 0) for workout in support_workouts)
        for support_workout in support_workouts:
            category = preview_intensity_category(support_workout)
            intensity_volume[category] = intensity_volume.get(category, 0.0) + int(support_workout.get("duration_seconds") or 0)
        weekly_curve.append({
            "week_index": week,
            "phase": phase,
            "is_taper": phase == "taper",
            "taper_week_index": taper_week_index(week, weeks, periodization_goal_distance),
            "planned_distance_km": round(week_distance, 1),
            "long_run_km": round(long_run, 1),
            "hard_sessions": hard_sessions,
            "support_sessions": len(support_workouts),
            "support_duration_seconds": support_duration,
        })

    for workout in workouts:
        workout["blocks"] = planned_workout_blocks_for_preview(workout, zones)

    total_intensity_volume = sum(intensity_volume.values())
    intensity_split = {key: round(value / total_intensity_volume, 3) if total_intensity_volume else 0.0 for key, value in intensity_volume.items()}
    effective_peak_volume = max((float(week["planned_distance_km"] or 0) for week in weekly_curve), default=round(peak_volume, 1))
    safety_text = "; ".join(safety["reasons"]) if safety["reasons"] else "no active safety gates"
    zone_text = []
    if zones["pace"]:
        zone_text.append(f"pace zones: {len(zones['pace'])}")
    if zones["hr"]:
        zone_text.append(f"HR zones: {len(zones['hr'])}")
    zone_summary = ", ".join(zone_text) if zone_text else "no precise zones, using RPE targets"
    risk_flags = builder_risk_flags(request, baseline, weekly_curve, workouts, safety, completeness, goal_distance, weeks, start_date)
    if running_days_capped_by_pattern:
        risk_flags.append({
            "code": "running_days_capped_by_recent_pattern",
            "severity": "warning",
            "message": "Running frequency reduced to avoid unrealistically short runs.",
            "reasons": [
                f"requested days/week: {requested_days}",
                f"effective running days/week: {days}",
                f"typical run: {float(recent_run_distance_median_float or 0):.1f} km",
                f"current volume: {current_volume:.1f} km/week",
            ],
        })
    if support_limited_by_budget:
        risk_flags.append({
            "code": "support_limited_by_time_budget",
            "severity": "warning",
            "message": "ОФП/support sessions reduced to fit the weekly time budget.",
            "reasons": [
                f"time budget: {request.time_budget_minutes_per_week} min/week",
                f"reserved running time: at least {round(easy_pace_seconds_per_km / 60)} min/week",
                f"adjusted support duration: {round(weekly_support_duration_seconds / 60)} min/week",
            ],
        })
    if running_floor_limited_by_budget:
        risk_flags.append({
            "code": "time_budget_below_running_floor",
            "severity": "warning",
            "message": "Weekly time budget is too tight to fit support and the minimum running floor.",
            "reasons": [
                f"time budget: {request.time_budget_minutes_per_week} min/week",
                "minimum running floor: 1.0 km/week",
                f"adjusted support duration: {round(weekly_support_duration_seconds / 60)} min/week",
            ],
        })
    return {
        "title": request.title or f"План на {race_name(goal_distance)}",
        "goal_type": request.goal_type,
        "race_distance_km": goal_distance,
        "target_date": request.target_date,
        "target_time_seconds": request.target_time_seconds,
        "priority": request.priority,
        "weeks": weeks,
        "available_days_per_week": days,
        "preferred_weekdays": preferred_weekdays,
        "intensity_mode": request.intensity_mode,
        "start_date": start_date,
        "current_weekly_distance_km": current_volume,
        "peak_weekly_distance_km": round(effective_peak_volume, 1),
        "constraints": {
            "injury": request.injury,
            "no_hard_workouts": request.no_hard_workouts,
            "requested_available_days_per_week": requested_days,
            "max_running_days_for_level": max_running_days,
            "running_days_capped_by_experience": requested_days > max_running_days,
            "running_days_capped_by_recent_pattern": running_days_capped_by_pattern,
            "max_long_run_km": max_long_run_km,
            "requested_max_long_run_km": request.max_long_run_km,
            "default_max_long_run_km": default_max_long_run_km,
            "max_long_run_duration_minutes": max_run_duration_minutes,
            "default_max_long_run_duration_minutes": default_max_long_run_duration_minutes,
            "profile_max_run_duration_minutes": profile.max_run_duration_minutes,
            "max_weekly_growth": max_weekly_growth,
            "long_run_share": long_run_share,
            "periodization_phases": ["base", "build", "specific", "taper"],
            "taper_weeks": taper_weeks,
            "time_budget_minutes_per_week": request.time_budget_minutes_per_week,
            "include_strength": request.include_strength,
            "plan_length_weeks": request.plan_length_weeks,
            "requested_aggressiveness": request.aggressiveness,
            "detected_training_age_level": detected_training_age_level,
            "effective_training_age_level": training_age_level,
            "aggressiveness_capped": request.aggressiveness != "auto" and training_age_level != request.aggressiveness,
            "strength_sessions_per_week": support_settings["strength_sessions"],
            "include_mobility": request.include_mobility,
            "mobility_sessions_per_week": support_settings["mobility_sessions"],
            "weekly_support_duration_seconds": weekly_support_duration_seconds,
            "support_limited_by_time_budget": support_limited_by_budget,
            "strength_equipment": request.strength_equipment,
            "estimated_easy_pace_seconds_per_km": round(easy_pace_seconds_per_km),
            "terrain": request.terrain,
            "recent_race_distance_km": request.recent_race_distance_km,
            "recent_race_time_seconds": request.recent_race_time_seconds,
        },
        "baseline": baseline,
        "weekly_volume_curve": weekly_curve,
        "intensity_split": intensity_split,
        "risk_flags": risk_flags,
        "workouts": workouts,
        "explanation": (
            f"Plan Builder Preview: план построен от текущего объема {current_volume:.1f} км/нед до пика {effective_peak_volume:.1f} км/нед. "
            f"Support sessions: strength {support_settings['strength_sessions']}/week, mobility {support_settings['mobility_sessions']}/week. "
            f"Baseline source: {volume_source}, training age={baseline['training_age_level']} (detected={detected_training_age_level}, consistent weeks={consistent_weeks}, quality sessions 8w={quality_sessions_8w}), confidence={baseline['confidence']}. "
            f"Safety gates: {safety_text}. Zones: {zone_summary}. "
            f"Profile completeness: {float(completeness['score']):.0%}, confidence={completeness['confidence']}. "
            f"Medical safety: {profile_safety['message']}"
        ),
    }


def plan_builder_preview(db: Session, user: User, request: PlanGenerateRequest, persist_profile: bool = False) -> dict[str, object]:
    profile = profile_for_plan_builder(db, user, persist=persist_profile)
    completeness = profile_completeness(profile)
    profile_safety = safety_check(profile)
    zones = zones_for_plan_builder(db, user, profile)
    start_date = today_for_user(db, user)
    context = plan_builder_training_context(db, user, profile, start_date, requested_days=request.available_days_per_week)
    return build_plan_preview_blueprint(request, profile, completeness, profile_safety, zones, context, start_date)


def apply_generated_plan_status(db: Session, user: User, plan: TrainingPlan, activate: bool) -> None:
    db.scalar(select(User.id).where(User.id == user.id).with_for_update())
    current_plans = list(db.scalars(
        select(TrainingPlan)
        .where(TrainingPlan.user_id == user.id, TrainingPlan.status.in_(("active", "draft")))
        .with_for_update()
    ))
    for current_plan in current_plans:
        if current_plan.id != plan.id:
            current_plan.status = "archived"
            create_plan_version(db, user, current_plan, "manual_edit", "Archived because another program was created")
    db.flush()
    plan.status = "active" if activate else "draft"


def generate_plan(db: Session, user: User, request: PlanGenerateRequest) -> TrainingPlan:
    preview = plan_builder_preview(db, user, request, persist_profile=True)

    plan = TrainingPlan(
        user_id=user.id,
        title=str(preview["title"]),
        goal_type=str(preview["goal_type"]),
        race_distance_km=float(preview["race_distance_km"] or 0),
        target_date=preview["target_date"],
        target_time_seconds=request.target_time_seconds,
        available_days_per_week=int(preview["available_days_per_week"]),
        status="draft",
        explanation=str(preview["explanation"]).replace("Plan Builder Preview", "Profile-aware MVP"),
    )
    apply_generated_plan_status(db, user, plan, request.activate)
    db.add(plan)
    db.flush()

    for workout in preview["workouts"]:
        plan_workout = TrainingPlanWorkout(
            plan_id=plan.id,
            week_index=int(workout["week_index"]),
            day_index=int(workout["day_index"]),
            scheduled_date=workout["scheduled_date"],
            status="planned",
            workout_type=str(workout["workout_type"]),
            title=str(workout["title"]),
            distance_km=float(workout["distance_km"]) if workout["distance_km"] is not None else None,
            duration_seconds=int(workout["duration_seconds"]) if workout.get("duration_seconds") is not None else None,
            intensity=str(workout["intensity"]) if workout["intensity"] is not None else None,
            description=str(workout["description"]) if workout["description"] is not None else None,
        )
        plan.workouts.append(plan_workout)
        db.add(plan_workout)
        for block in workout.get("blocks") or []:
            plan_workout.blocks.append(create_workout_block_from_dict(block))

    create_plan_version(db, user, plan, "initial", "Generated from Plan Builder")
    db.commit()
    db.refresh(plan)
    return plan


def activate_plan(db: Session, user: User, plan: TrainingPlan) -> TrainingPlan:
    db.scalar(select(User.id).where(User.id == user.id).with_for_update())
    current_plans = list(db.scalars(
        select(TrainingPlan)
        .where(TrainingPlan.user_id == user.id, TrainingPlan.status.in_(("active", "draft")))
        .with_for_update()
    ))
    for current_plan in current_plans:
        if current_plan.id != plan.id:
            current_plan.status = "archived"
            create_plan_version(db, user, current_plan, "manual_edit", f"Archived because plan #{plan.id} was activated")
    db.flush()
    plan.status = "active"
    create_plan_version(db, user, plan, "manual_edit", "Activated plan")
    db.commit()
    db.refresh(plan)
    return plan


def update_plan(db: Session, user: User, plan: TrainingPlan, payload: PlanUpdate) -> TrainingPlan:
    updates = payload.model_dump(exclude_unset=True)
    changed_fields = []
    if "title" in updates and updates["title"] is not None:
        if plan.title != updates["title"]:
            plan.title = updates["title"]
            changed_fields.append("title")
    if updates.get("status") == "active":
        return activate_plan(db, user, plan)
    if "status" in updates and updates["status"] is not None:
        if plan.status != updates["status"]:
            if updates["status"] == "draft":
                apply_generated_plan_status(db, user, plan, activate=False)
            else:
                plan.status = updates["status"]
            changed_fields.append("status")
    if changed_fields:
        create_plan_version(db, user, plan, "manual_edit", f"Updated {', '.join(changed_fields)}")
    db.commit()
    db.refresh(plan)
    return plan


def duplicate_plan(db: Session, user: User, plan: TrainingPlan) -> TrainingPlan:
    raise ValueError("Only one current training program is supported; rebuild the current program instead")


def delete_plan(db: Session, user: User, plan: TrainingPlan) -> int:
    if plan.status == "active":
        raise ValueError("Active plan cannot be deleted; archive it first")
    plan_id = plan.id
    db.delete(plan)
    db.commit()
    return plan_id


def update_workout(db: Session, user: User, workout: TrainingPlanWorkout, payload: PlanWorkoutUpdate) -> TrainingPlanWorkout:
    updates = payload.model_dump(exclude_unset=True)
    previous_status = workout.status
    previous_activity_id = workout.completed_activity_id
    if updates.get("status") == "missed" and previous_status != "missed":
        raise ValueError("Use the missed workout action to record a reason")
    version_summary = None
    next_completed_activity_id = workout.completed_activity_id
    target_fields = {"workout_type", "title", "distance_km", "duration_seconds", "intensity", "description"}
    target_updates = {field: updates[field] for field in target_fields if field in updates}
    if "completed_activity_id" in updates:
        activity_id = updates["completed_activity_id"]
        if activity_id is None:
            workout.completed_activity_id = None
            workout.completed_activity = None
            next_completed_activity_id = None
            if "status" not in updates and workout.status == "done":
                workout.status = "planned"
        else:
            activity = db.scalar(select(Activity).where(Activity.id == activity_id, Activity.user_id == user.id))
            if activity is None:
                raise ValueError("Activity not found")
            if workout.completed_activity_id is not None and workout.completed_activity_id != activity.id:
                raise ValueError("Workout already linked to another activity")
            if workout.completed_activity_id is None and workout.status not in MATCHABLE_WORKOUT_STATUSES:
                raise ValueError("Workout status cannot be linked")
            if activity_is_linked(db, user, activity.id, exclude_workout_id=workout.id):
                raise ValueError("Activity already linked to another workout")
            workout.completed_activity_id = activity.id
            workout.completed_activity = activity
            next_completed_activity_id = activity.id
            if "status" not in updates:
                workout.status = "done"
            elif updates["status"] != "done":
                raise ValueError("Linked workout status must be done")
    if "scheduled_date" in updates:
        if next_completed_activity_id is not None or workout.status == "done":
            raise ValueError("Linked or completed workout must be unlinked before rescheduling")
        if workout.scheduled_date != updates["scheduled_date"]:
            version_summary = f"Rescheduled workout #{workout.id}"
        workout.scheduled_date = updates["scheduled_date"]
        if workout.status in {"planned", "missed", "skipped"}:
            workout.status = "rescheduled"
    if "status" in updates and updates["status"] is not None:
        if updates["status"] == "done" and next_completed_activity_id is None:
            raise ValueError("Done workout requires linked activity")
        if updates["status"] != "done" and next_completed_activity_id is not None:
            raise ValueError("Linked workout status must be done")
        workout.status = updates["status"]
    if target_updates:
        if next_completed_activity_id is not None or workout.status == "done":
            raise ValueError("Linked or completed workout must be unlinked before editing targets")
        for field, value in target_updates.items():
            if field in {"workout_type", "title"} and value is None:
                continue
            setattr(workout, field, value)
        profile = profile_for_plan_builder(db, user, persist=False)
        zones = zones_for_plan_builder(db, user, profile)
        preview_workout = {
            "workout_type": workout.workout_type,
            "distance_km": workout.distance_km,
            "duration_seconds": workout.duration_seconds,
            "training_age_level": "intermediate",
            "target_race_pace_seconds_per_km": None,
        }
        for block in list(workout.blocks):
            workout.blocks.remove(block)
            db.delete(block)
        db.flush()
        for block in planned_workout_blocks_for_preview(preview_workout, zones):
            workout.blocks.append(create_workout_block_from_dict(block))
        version_summary = f"Edited workout #{workout.id} target"
    if workout.feedback:
        sync_feedback_context(workout.feedback, workout)
    if version_summary and workout.plan is not None:
        create_plan_version(db, user, workout.plan, "manual_edit", version_summary)
    if previous_activity_id is None and workout.completed_activity_id is not None and workout.completed_activity is not None:
        record_workout_completed_event(db, user, workout, workout.completed_activity, "manual_activity_link")
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise ValueError("Activity already linked to another workout") from error
    db.refresh(workout)
    return workout


def normalize_feedback(feedback: TrainingPlanWorkoutFeedback) -> None:
    if feedback.soreness_0_10 is not None:
        feedback.fatigue = feedback.soreness_0_10
    elif feedback.fatigue is not None:
        feedback.soreness_0_10 = feedback.fatigue
    if feedback.sleep_quality_0_10 is not None:
        feedback.sleep_quality = feedback.sleep_quality_0_10
    elif feedback.sleep_quality is not None:
        feedback.sleep_quality_0_10 = feedback.sleep_quality
    if feedback.user_notes is not None:
        feedback.notes = feedback.user_notes
    elif feedback.notes is not None:
        feedback.user_notes = feedback.notes
    if feedback.pain_level is not None and feedback.pain_level > 0:
        feedback.pain = True
    elif not feedback.pain:
        feedback.pain_level = None


def normalize_feedback_updates(updates: dict[str, object], explicit_fields: set[str] | None = None) -> dict[str, object]:
    normalized = dict(updates)
    explicit = explicit_fields or set(normalized)

    def sync_alias(spec_field: str, legacy_field: str) -> None:
        if spec_field in explicit:
            normalized[legacy_field] = normalized.get(spec_field)
        elif legacy_field in explicit:
            normalized[spec_field] = normalized.get(legacy_field)
        elif normalized.get(spec_field) is not None:
            normalized[legacy_field] = normalized.get(spec_field)
        elif normalized.get(legacy_field) is not None:
            normalized[spec_field] = normalized.get(legacy_field)

    sync_alias("soreness_0_10", "fatigue")
    sync_alias("sleep_quality_0_10", "sleep_quality")
    sync_alias("user_notes", "notes")
    return normalized


def sync_feedback_context(feedback: TrainingPlanWorkoutFeedback, workout: TrainingPlanWorkout) -> None:
    feedback.activity_id = workout.completed_activity_id or (workout.completed_activity.id if workout.completed_activity else None)
    feedback.completion_status = workout.status


def feedback_event_snapshot(feedback: TrainingPlanWorkoutFeedback, workout: TrainingPlanWorkout) -> dict[str, object]:
    snapshot = feedback_to_dict(feedback, workout) or {}
    return {
        key: value
        for key, value in snapshot.items()
        if key not in {"created_at", "updated_at"}
    }


def record_feedback_events(
    db: Session,
    user: User,
    workout: TrainingPlanWorkout,
    feedback: TrainingPlanWorkoutFeedback,
    *,
    operation: str,
    pain_was_reported: bool,
) -> None:
    db.flush()
    snapshot = feedback_event_snapshot(feedback, workout)
    record_coaching_event(
        db,
        user_id=user.id,
        event_type="workout_feedback_saved",
        category="user_input",
        source="post_workout_feedback",
        plan_id=workout.plan_id,
        workout_id=workout.id,
        activity_id=feedback.activity_id,
        feedback_id=feedback.id,
        payload={
            "operation": operation,
            "feedback": snapshot,
            "execution_score": workout_execution_score(workout),
        },
    )
    if feedback.pain and not pain_was_reported:
        record_coaching_event(
            db,
            user_id=user.id,
            event_type="pain_reported",
            category="user_input",
            source="post_workout_feedback",
            plan_id=workout.plan_id,
            workout_id=workout.id,
            activity_id=feedback.activity_id,
            feedback_id=feedback.id,
            payload={"pain_level_0_10": feedback.pain_level, "notes": feedback.pain_notes},
        )


def record_workout_completed_event(
    db: Session,
    user: User,
    workout: TrainingPlanWorkout,
    activity: Activity,
    source: str,
) -> None:
    record_coaching_event(
        db,
        user_id=user.id,
        event_type="workout_completed",
        category="outcome",
        source=source,
        occurred_at=activity.started_at or datetime.now(UTC),
        plan_id=workout.plan_id,
        workout_id=workout.id,
        activity_id=activity.id,
        payload={
            "scheduled_date": workout.scheduled_date,
            "workout_type": workout.workout_type,
            "actual_distance_km": activity.distance_km,
            "actual_duration_seconds": activity.duration_seconds,
        },
    )


def upsert_workout_feedback(db: Session, user: User, workout: TrainingPlanWorkout, updates: dict[str, object], explicit_fields: set[str] | None = None) -> TrainingPlanWorkoutFeedback:
    if workout.status not in {"done", "missed", "skipped"}:
        raise ValueError("Workout feedback requires completed, missed or skipped workout")
    if workout.plan.user_id != user.id:
        raise ValueError("Workout not found")
    feedback = workout.feedback
    if feedback is None:
        feedback = TrainingPlanWorkoutFeedback(user_id=user.id, workout_id=workout.id)
        db.add(feedback)
        workout.feedback = feedback
    for field, value in normalize_feedback_updates(updates, explicit_fields).items():
        setattr(feedback, field, value)
    sync_feedback_context(feedback, workout)
    normalize_feedback(feedback)
    return feedback


def save_workout_feedback(db: Session, user: User, workout: TrainingPlanWorkout, payload: PlanWorkoutFeedbackIn) -> TrainingPlanWorkoutFeedback:
    existed = workout.feedback is not None
    pain_was_reported = bool(workout.feedback and workout.feedback.pain)
    previous_snapshot = feedback_event_snapshot(workout.feedback, workout) if workout.feedback else None
    feedback = upsert_workout_feedback(db, user, workout, payload.model_dump(), set(payload.model_fields_set))
    if workout.completed_activity:
        sync_daily_training_loads_for_activity(db, user, workout.completed_activity)
    if feedback_event_snapshot(feedback, workout) != previous_snapshot:
        record_feedback_events(db, user, workout, feedback, operation="replaced" if existed else "created", pain_was_reported=pain_was_reported)
    db.commit()
    db.refresh(feedback)
    return feedback


def patch_workout_feedback(db: Session, user: User, workout: TrainingPlanWorkout, payload: PlanWorkoutFeedbackPatchIn) -> TrainingPlanWorkoutFeedback:
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise ValueError("Feedback patch is empty")
    pain_was_reported = bool(workout.feedback and workout.feedback.pain)
    previous_snapshot = feedback_event_snapshot(workout.feedback, workout) if workout.feedback else None
    feedback = upsert_workout_feedback(db, user, workout, updates, set(payload.model_fields_set))
    if workout.completed_activity:
        sync_daily_training_loads_for_activity(db, user, workout.completed_activity)
    if feedback_event_snapshot(feedback, workout) != previous_snapshot:
        record_feedback_events(db, user, workout, feedback, operation="patched", pain_was_reported=pain_was_reported)
    db.commit()
    db.refresh(feedback)
    return feedback


def manual_activity_type_for_workout(workout: TrainingPlanWorkout) -> str:
    workout_type = workout.workout_type or ""
    if workout_type in SUPPORT_WORKOUT_TYPES:
        return f"manual_{workout_type}"
    return "manual_workout"


def complete_workout(db: Session, user: User, workout: TrainingPlanWorkout, payload: PlanWorkoutCompleteIn) -> TrainingPlanWorkout:
    if workout.plan.user_id != user.id:
        raise ValueError("Workout not found")
    if workout.completed_activity_id is not None:
        raise ValueError("Workout already has a linked activity; unlink it before manual completion")
    if workout.status == "done":
        raise ValueError("Workout is already completed")
    if workout.status not in {"planned", "rescheduled", "missed", "skipped"}:
        raise ValueError("Workout status cannot be completed")
    completed_at = payload.completed_at or datetime.now(UTC)
    average_pace = None
    if payload.actual_distance_km and payload.actual_distance_km > 0:
        average_pace = round(payload.actual_duration_seconds / payload.actual_distance_km)
    activity = Activity(
        user_id=user.id,
        activity_type=manual_activity_type_for_workout(workout),
        title=f"Manual completion: {workout.title}",
        started_at=completed_at,
        distance_km=payload.actual_distance_km,
        duration_seconds=payload.actual_duration_seconds,
        average_pace_seconds_per_km=average_pace,
        average_heart_rate_bpm=payload.average_heart_rate_bpm,
        source_note="manual workout completion",
    )
    db.add(activity)
    db.flush()
    profile = db.scalar(select(AthleteProfile).where(AthleteProfile.user_id == user.id))
    sync_derived_activity_metrics(db, activity, profile)
    workout.completed_activity_id = activity.id
    workout.completed_activity = activity
    workout.status = "done"
    pain_was_reported = bool(workout.feedback and workout.feedback.pain)
    feedback_existed = workout.feedback is not None
    feedback_updates = payload.model_dump(
        include={"rpe", "soreness_0_10", "fatigue", "pain", "pain_level", "sleep_quality_0_10", "sleep_quality", "pain_notes", "user_notes", "weather_notes", "notes"},
        exclude_unset=True,
    )
    feedback_updates["pain"] = payload.pain
    feedback_fields_set = set(payload.model_fields_set) | {"pain"}
    if not payload.pain and payload.pain_level is None:
        feedback_updates["pain_level"] = None
        feedback_fields_set.add("pain_level")
    feedback = None
    if feedback_updates:
        feedback = upsert_workout_feedback(db, user, workout, feedback_updates, feedback_fields_set)
    record_workout_completed_event(db, user, workout, activity, "manual_completion")
    if feedback is not None:
        record_feedback_events(db, user, workout, feedback, operation="replaced" if feedback_existed else "created", pain_was_reported=pain_was_reported)
    sync_daily_training_loads_for_activity(db, user, activity)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise ValueError("Manual completion could not be saved") from error
    db.refresh(workout)
    workout.completed_activity = activity
    return workout


def mark_workout_missed(db: Session, user: User, workout: TrainingPlanWorkout, payload: PlanWorkoutMissIn) -> TrainingPlanWorkout:
    if workout.plan.user_id != user.id:
        raise ValueError("Workout not found")
    if workout.completed_activity_id is not None or workout.status == "done":
        raise ValueError("Completed workout cannot be marked missed")
    if workout.status not in {"planned", "rescheduled", "missed"}:
        raise ValueError("Workout status cannot be marked missed")
    if workout.status == "missed":
        previous_event = db.scalar(
            select(CoachingEvent)
            .where(
                CoachingEvent.user_id == user.id,
                CoachingEvent.workout_id == workout.id,
                CoachingEvent.event_type == "workout_missed",
            )
            .order_by(CoachingEvent.id.desc())
            .limit(1)
        )
        if previous_event is not None:
            previous_payload = previous_event.payload_json or {}
            if previous_payload.get("reason") == payload.reason and previous_payload.get("notes") == payload.notes:
                return workout
            raise ValueError("Workout is already marked missed with another reason")
    else:
        workout.status = "missed"
    if workout.feedback:
        sync_feedback_context(workout.feedback, workout)
    record_coaching_event(
        db,
        user_id=user.id,
        event_type="workout_missed",
        category="outcome",
        source="user",
        plan_id=workout.plan_id,
        workout_id=workout.id,
        payload={
            "reason": payload.reason,
            "notes": payload.notes,
            "scheduled_date": workout.scheduled_date,
            "workout_type": workout.workout_type,
        },
    )
    if payload.reason in {"pain", "illness"}:
        record_coaching_event(
            db,
            user_id=user.id,
            event_type="pain_reported" if payload.reason == "pain" else "illness_reported",
            category="user_input",
            source="user",
            plan_id=workout.plan_id,
            workout_id=workout.id,
            payload={"notes": payload.notes, "context": "missed_workout"},
        )
    db.commit()
    db.refresh(workout)
    return workout
