from datetime import UTC, date, datetime, timedelta
from math import ceil
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models import Activity, AthleteProfile, TrainingPlan, TrainingPlanRecommendationAudit, TrainingPlanWorkout, TrainingPlanWorkoutFeedback, TrainingZone, User
from app.schemas.common import PlanGenerateRequest, PlanUpdate, PlanWorkoutFeedbackIn, PlanWorkoutUpdate
from app.services.profile import get_or_create_profile, profile_completeness, safety_check
from app.services.zones import calculated_zones, zone_type_for_unit


MATCHABLE_WORKOUT_STATUSES = ("planned", "rescheduled")
CANDIDATE_MIN_SCORE = 0.25
CANDIDATE_DATE_WINDOW_DAYS = 7
AUTO_MATCH_MIN_SCORE = 0.78
AUTO_MATCH_DATE_WINDOW_DAYS = 3
DEFAULT_WEEKLY_VOLUME_KM = 15.0
HARD_PLAN_WORKOUT_TYPES = {"interval", "tempo", "threshold", "hill", "race_pace"}
HARD_PLAN_INTENSITIES = {"interval", "tempo", "threshold", "race_pace", "hard"}
APPLICABLE_RECOMMENDATION_ACTIONS = {
    "hold_next_week_volume",
    "reduce_next_week_volume",
    "reduce_intensity",
    "cap_next_week_growth",
    "review_or_move_key_workout",
}


def weeks_until(target_date: date | None, today: date | None = None) -> int:
    if not target_date:
        return 8
    reference_date = today or date.today()
    return max(4, min(24, ceil((target_date - reference_date).days / 7)))


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


def schedule_offsets_for_plan(start_date: date, days: int, preferred_weekdays: list[int] | None = None) -> list[int]:
    default_offsets = schedule_offsets(days)
    if not preferred_weekdays:
        return default_offsets
    start_weekday = start_date.isoweekday()
    preferred_offsets = sorted({(weekday - start_weekday) % 7 for weekday in preferred_weekdays})
    offsets = preferred_offsets[:days]
    for offset in default_offsets:
        if len(offsets) >= days:
            break
        if offset not in offsets:
            offsets.append(offset)
    return sorted(offsets[:days])


def scheduled_workout_date(start_date: date, week_index: int, day_index: int, days: int, preferred_weekdays: list[int] | None = None) -> date:
    offsets = schedule_offsets_for_plan(start_date, days, preferred_weekdays)
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
    return AthleteProfile(user_id=user.id, sex="unspecified", timezone="Europe/Moscow", locale="ru-RU", conservative_mode=False)


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


def plan_builder_training_context(db: Session, user: User, profile: AthleteProfile, today: date) -> dict[str, object]:
    activities = list(db.scalars(
        select(Activity)
        .where(Activity.user_id == user.id, Activity.started_at.is_not(None))
        .order_by(Activity.started_at.desc(), Activity.id.desc())
        .limit(240)
    ))
    dated = [
        (activity, started_date)
        for activity in activities
        if (started_date := activity_started_date(activity, profile)) is not None and started_date <= today
    ]
    history_span_days = (max(started_date for _, started_date in dated) - min(started_date for _, started_date in dated)).days + 1 if dated else 0
    observed_weekly_volume = [0.0 for _ in range(6)]
    observed_start = today - timedelta(days=41)
    recent_long_run = 0.0
    recent_long_start = today - timedelta(days=55)
    for activity, started_date in dated:
        distance = float(activity.distance_km or 0)
        if observed_start <= started_date <= today:
            bucket = min(5, max(0, (started_date - observed_start).days // 7))
            observed_weekly_volume[bucket] += distance
        if recent_long_start <= started_date <= today:
            recent_long_run = max(recent_long_run, distance)

    active_recent_weeks = [volume for volume in observed_weekly_volume[-4:] if volume > 0]
    if len(active_recent_weeks) >= 2:
        current_volume = float(median(active_recent_weeks))
        source = "observed_median_4w"
    else:
        current_volume = DEFAULT_WEEKLY_VOLUME_KM
        source = "fallback"

    if history_span_days >= 180 and current_volume >= 45:
        training_age_level = "advanced"
    elif history_span_days >= 56 and current_volume >= 18:
        training_age_level = "intermediate"
    else:
        training_age_level = "beginner"

    if source == "observed_median_4w" and history_span_days >= 42:
        confidence = "high"
    elif source == "observed_median_4w" or history_span_days >= 14:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "activity_count": len(dated),
        "history_span_days": history_span_days,
        "observed_weekly_volume_km": [round(volume, 1) for volume in observed_weekly_volume],
        "current_weekly_volume_km": round(current_volume, 1),
        "current_weekly_volume_source": source,
        "recent_weekly_distance_km": round(current_volume, 1),
        "recent_long_run_km": round(recent_long_run, 1) if recent_long_run else None,
        "training_age_level": training_age_level,
        "confidence": confidence,
    }


def build_safety_context(profile, completeness: dict, context: dict[str, object], goal_distance: float, request: PlanGenerateRequest | None = None) -> dict[str, object]:
    reasons = []
    if profile.conservative_mode:
        reasons.append("profile conservative mode")
    if profile.injury_notes:
        reasons.append("injury notes present")
    if request and request.injury:
        reasons.append("wizard injury constraint")
    if request and request.no_hard_workouts:
        reasons.append("wizard no hard workouts constraint")
    if int(context["history_span_days"] or 0) < 14:
        reasons.append("training history shorter than 14 days")
    intensity_mode = request.intensity_mode if request else "mixed"
    if intensity_mode in {"pace", "mixed"} and not completeness["can_calculate_pace_zones"]:
        reasons.append("no threshold pace zones")
    if intensity_mode == "hr" and not (completeness["can_calculate_hr_zones"] or completeness["can_calculate_hrr_zones"]):
        reasons.append("no HR zones")
    if goal_distance >= 21 and (context["recent_weekly_distance_km"] or 0) < 25:
        reasons.append("low current volume for long-distance goal")
    return {
        "conservative": bool(reasons),
        "reasons": reasons,
    }


def workout_template(days: int, conservative: bool, has_precise_zones: bool) -> list[tuple[int, str, str, str]]:
    hard_allowed = (not conservative) and has_precise_zones
    if days <= 2:
        return [
            (1, "easy", "Легкий бег", "easy"),
            (days, "long", "Длинная тренировка", "easy-long"),
        ]
    template = [(1, "easy", "Легкий бег", "easy")]
    if hard_allowed:
        template.append((2, "interval", "Длинные интервалы", "threshold"))
    else:
        template.append((2, "steady", "Аэробная работа", "steady-rpe"))
    if days >= 4:
        template.append((3, "tempo" if hard_allowed else "easy", "Темповая работа" if hard_allowed else "Восстановительный бег", "steady" if hard_allowed else "easy"))
    for day in range(4, days):
        template.append((day, "easy", "Легкий бег", "easy"))
    template.append((days, "long", "Длинная тренировка", "easy-long"))
    return template[:days]


def workout_description(workout_type: str, intensity: str, zones: dict, conservative: bool) -> str:
    if workout_type == "interval":
        target = target_text(zones, pace_key="interval", hr_key="z4", fallback="RPE 6-7, без выхода в максимальную интенсивность")
        return f"Работа около порога: 3-5 длинных отрезков с восстановлением. Цель: {target}."
    if workout_type == "tempo":
        target = target_text(zones, pace_key="threshold", hr_key="z3", fallback="RPE 5-6, контролируемый темп")
        return f"Устойчивый темп ниже порога, без закисления. Цель: {target}."
    if workout_type == "steady":
        target = target_text(zones, pace_key="steady", hr_key="z2", fallback="RPE 3-4, разговорный контроль")
        suffix = " Высокоинтенсивные тренировки отключены safety gate." if conservative else ""
        return f"Аэробная работа без жестких интервалов. Цель: {target}.{suffix}"
    if workout_type == "long":
        target = target_text(zones, pace_key="easy", hr_key="z2", fallback="RPE 2-4, длинный легкий бег")
        return f"Главная тренировка недели для базы и устойчивости. Цель: {target}."
    target = target_text(zones, pace_key="easy", hr_key="z1", fallback="RPE 2-3, легко и комфортно")
    return f"Комфортный бег в разговорном темпе. Цель: {target}."


def feedback_to_dict(feedback: TrainingPlanWorkoutFeedback | None) -> dict[str, object] | None:
    if feedback is None:
        return None
    return {
        "id": feedback.id,
        "workout_id": feedback.workout_id,
        "rpe": feedback.rpe,
        "fatigue": feedback.fatigue,
        "pain": feedback.pain,
        "pain_level": feedback.pain_level,
        "sleep_quality": feedback.sleep_quality,
        "notes": feedback.notes,
        "created_at": feedback.created_at,
        "updated_at": feedback.updated_at,
    }


def workout_execution_score(workout: TrainingPlanWorkout) -> dict[str, object]:
    activity = workout.completed_activity
    feedback = workout.feedback
    flags: list[str] = []
    volume_score: float | None = None
    subjective_risk = "unknown"
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
    if workout.status in {"missed", "skipped"}:
        flags.append(f"workout {workout.status}")
        return {"score": 0.0, "status": workout.status, "volume_score": 0.0, "subjective_risk": subjective_risk, "flags": flags}
    if activity and workout.distance_km and activity.distance_km is not None:
        relative_delta = abs(activity.distance_km - workout.distance_km) / max(workout.distance_km, 1)
        volume_score = max(0.0, min(1.0, 1 - relative_delta / 0.5))
        if activity.distance_km >= workout.distance_km * 1.2:
            flags.append("actual volume above plan")
        elif activity.distance_km <= workout.distance_km * 0.75:
            flags.append("actual volume below plan")
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
    components = [score for score in (volume_score, subjective_score) if score is not None]
    score = round(sum(components) / len(components), 2) if components else None
    status = "unknown"
    if score is not None:
        status = "completed" if score >= 0.8 else "partial" if score >= 0.45 else "at_risk"
    return {
        "score": score,
        "status": status,
        "volume_score": round(volume_score, 2) if volume_score is not None else None,
        "subjective_risk": subjective_risk,
        "flags": flags,
    }


def workout_to_dict(workout: TrainingPlanWorkout) -> dict[str, object]:
    activity = workout.completed_activity
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
        "feedback": feedback_to_dict(workout.feedback),
        "execution_score": workout_execution_score(workout),
    }


def adherence_summary(workouts: list[TrainingPlanWorkout]) -> dict[str, object]:
    total = len(workouts)
    done = [workout for workout in workouts if workout.status == "done"]
    missed = [workout for workout in workouts if workout.status == "missed"]
    skipped = [workout for workout in workouts if workout.status == "skipped"]
    linked = [workout for workout in done if workout.completed_activity]
    planned_distance = sum(workout.distance_km or 0 for workout in workouts)
    completed_distance = sum((workout.completed_activity.distance_km or 0) for workout in linked)
    warnings = []
    if done and len(linked) < len(done):
        warnings.append("Есть выполненные тренировки без привязанной фактической активности")
    distance_rate = completed_distance / planned_distance if planned_distance else 0
    if distance_rate >= 1.2:
        warnings.append("Фактический объем заметно выше плана")
    elif planned_distance and distance_rate <= 0.75 and done:
        warnings.append("Фактический объем заметно ниже плана")
    return {
        "total_workouts": total,
        "done_workouts": len(done),
        "missed_workouts": len(missed),
        "skipped_workouts": len(skipped),
        "linked_workouts": len(linked),
        "unlinked_done_workouts": len(done) - len(linked),
        "planned_distance_km": round(planned_distance, 1),
        "completed_distance_km": round(completed_distance, 1),
        "completion_rate": round(len(done) / total, 2) if total else 0,
        "distance_completion_rate": round(distance_rate, 2) if planned_distance else 0,
        "warnings": warnings,
    }


def weekly_adherence_summary(workouts: list[TrainingPlanWorkout]) -> list[dict[str, object]]:
    summaries = []
    week_indexes = sorted({workout.week_index for workout in workouts})
    for week_index in week_indexes:
        week_workouts = [workout for workout in workouts if workout.week_index == week_index]
        summary = adherence_summary(week_workouts)
        summary["week_index"] = week_index
        summary["planned_workouts"] = summary.pop("total_workouts")
        summaries.append(summary)
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


def today_for_user(db: Session, user: User) -> date:
    timezone_name = db.scalar(select(AthleteProfile.timezone).where(AthleteProfile.user_id == user.id)) or "Europe/Moscow"
    try:
        return datetime.now(ZoneInfo(timezone_name)).date()
    except (ZoneInfoNotFoundError, ValueError):
        return datetime.now(UTC).date()


def plan_adjustment_recommendations(db: Session, user: User, plan: TrainingPlan) -> dict[str, object]:
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
    missed_key = [workout for workout in missed_recent if workout.workout_type in {"long", "interval", "tempo"}]
    recent_linked = [workout for workout in recent if workout.status == "done" and workout.completed_activity]
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
    recent_completed_distance = sum(workout.completed_activity.distance_km or 0 for workout in recent_linked)
    upcoming_planned_distance = sum(workout.distance_km or 0 for workout in upcoming)
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

    if len(missed_recent) >= 2:
        recommendations.append(recommendation_item(
            "hold_volume",
            "warning",
            "Hold next-week volume",
            "Several recent workouts were missed or skipped. Do not try to catch up; keep the next week controlled.",
            [f"{len(missed_recent)} missed/skipped workouts in the last 14 days"],
            week_index=missed_recent[-1].week_index if missed_recent else None,
            suggested_payload={"action": "hold_next_week_volume"},
        ))

    if missed_key:
        workout = missed_key[-1]
        recommendations.append(recommendation_item(
            "move_workout",
            "warning",
            "Key workout was missed",
            "Treat the next hard session cautiously. Prefer moving the key session only if recovery is good.",
            [f"missed {workout.workout_type} workout"],
            workout_id=workout.id,
            week_index=workout.week_index,
            suggested_payload={"action": "review_or_move_key_workout", "workout_id": workout.id},
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
            suggested_payload={"action": "reduce_intensity", "days": 3},
        ))

    if summary["distance_completion_rate"] >= 1.2:
        recommendations.append(recommendation_item(
            "recovery",
            "warning",
            "Actual volume is above plan",
            "Add recovery emphasis before increasing distance or intensity.",
            [f"distance completion rate {summary['distance_completion_rate']:.0%}"],
            suggested_payload={"action": "reduce_intensity", "days": 2},
        ))
    elif summary["distance_completion_rate"] <= 0.75 and summary["linked_workouts"] > 0:
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

    highest = "ok"
    if any(item["severity"] == "critical" for item in recommendations):
        highest = "adjust"
    elif any(item["severity"] == "warning" for item in recommendations):
        highest = "watch"
    plan_summary = {
        "ok": "Plan looks stable based on current linked activities.",
        "watch": "Coach recommends watching the next week before increasing load.",
        "adjust": "Coach recommends adjusting the plan before the next hard workout.",
    }[highest]
    return {
        "plan_id": plan.id,
        "status": highest,
        "generated_at": datetime.now(UTC),
        "summary": plan_summary,
        "metrics": {
            "completion_rate": summary["completion_rate"],
            "distance_completion_rate": summary["distance_completion_rate"],
            "missed_recent_workouts": len(missed_recent),
            "unlinked_done_workouts": summary["unlinked_done_workouts"],
            "planned_distance_km": summary["planned_distance_km"],
            "completed_distance_km": summary["completed_distance_km"],
            "recent_completed_distance_km": round(recent_completed_distance, 1),
            "upcoming_planned_distance_km": round(upcoming_planned_distance, 1),
        },
        "recommendations": recommendations[:6],
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
    recommendation_result = plan_adjustment_recommendations(db, user, plan)
    recommendations = list(recommendation_result["recommendations"])
    workouts = sorted(plan.workouts, key=lambda workout: (workout.week_index, workout.day_index, workout.id))
    today = today_for_user(db, user)
    upcoming = mutable_upcoming_workouts(workouts, today)
    workouts_by_id = {workout.id: workout for workout in workouts}
    preview_values: dict[tuple[int, str], Any] = {}
    changes: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []
    reduce_volume_note = "Coach adjustment: reduce volume until adherence stabilizes."
    cap_growth_note = "Coach adjustment: cap next-week growth until recent volume catches up."

    def current_value(workout: TrainingPlanWorkout, field: str) -> Any:
        return preview_values.get((workout.id, field), getattr(workout, field))

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

    def scale_upcoming_distances(percent: float, reason: str, note: str) -> bool:
        changed = False
        factor = max(0.0, 1 - percent / 100)
        for workout in upcoming:
            if note in (current_value(workout, "description") or ""):
                continue
            current_distance = current_value(workout, "distance_km")
            if not current_distance:
                continue
            after = round(max(1.0, float(current_distance) * factor), 1)
            changed = add_change(workout, "distance_km", after, reason) or changed
            changed = add_change(workout, "description", append_coach_note(current_value(workout, "description"), note), reason) or changed
        return changed

    def ease_upcoming_hard_workouts(reason: str, days: int = 7, first_only: bool = False) -> bool:
        changed = False
        note = "Coach adjustment: keep this session easy until adherence stabilizes."
        window_end = today + timedelta(days=max(1, days))
        hard_workouts = [
            workout
            for workout in upcoming
            if workout.scheduled_date and workout.scheduled_date <= window_end
            and (workout.workout_type in {"interval", "tempo"} or (workout.intensity or "") in {"threshold", "interval", "tempo"})
        ]
        hard_workouts.sort(key=lambda workout: (workout.scheduled_date or today, workout.week_index, workout.day_index, workout.id))
        if first_only:
            hard_workouts = hard_workouts[:1]
        for workout in hard_workouts:
            changed = add_change(workout, "intensity", "easy", reason) or changed
            changed = add_change(workout, "description", append_coach_note(current_value(workout, "description"), note), reason) or changed
        return changed

    for recommendation in recommendations:
        payload = recommendation.get("suggested_payload") or {}
        action = payload.get("action") if isinstance(payload, dict) else None
        if not action:
            skip("none", recommendation, "recommendation has no applicable action")
            continue
        if action not in APPLICABLE_RECOMMENDATION_ACTIONS:
            skip(str(action), recommendation, "manual flow required")
            continue
        if action == "hold_next_week_volume":
            if not ease_upcoming_hard_workouts("hold volume after recent missed or skipped workouts"):
                skip(action, recommendation, "no upcoming hard workouts to ease")
        elif action == "reduce_next_week_volume":
            percent = float(payload.get("percent") or 15)
            if not scale_upcoming_distances(percent, f"reduce next 7 days by {percent:g}%", reduce_volume_note):
                skip(action, recommendation, "no mutable upcoming distance to reduce")
        elif action == "reduce_intensity":
            days = int(payload.get("days") or 3)
            if not ease_upcoming_hard_workouts("reduce intensity while safety or recovery risk is active", days=days, first_only=True):
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
        elif action == "review_or_move_key_workout":
            workout_id = payload.get("workout_id")
            workout = workouts_by_id.get(workout_id) if isinstance(workout_id, int) else None
            if not workout or workout.status not in {"missed", "skipped"} or workout.completed_activity_id is not None:
                skip(action, recommendation, "key workout cannot be safely rescheduled")
                continue
            target_date = next_available_workout_date(today, workouts)
            add_change(workout, "scheduled_date", target_date, "reschedule missed key workout cautiously")
            add_change(workout, "status", "rescheduled", "reschedule missed key workout cautiously")

    return {
        "plan_id": plan.id,
        "generated_at": datetime.now(UTC),
        "changes": changes,
        "skipped": skipped,
        "recommendations": recommendations,
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
    preview = plan_recommendation_preview_changes(db, user, plan)
    changes = list(preview["changes"])
    skipped = list(preview["skipped"])
    expected = normalize_preview_changes(expected_changes)
    if expected is not None and expected != json_safe(changes):
        raise ValueError("Recommendation preview is stale; refresh preview before applying")
    workouts_by_id = {workout.id: workout for workout in plan.workouts}
    allowed_fields = {"distance_km", "intensity", "description", "scheduled_date", "status"}
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
            }),
            preview_changes={"changes": json_safe(changes), "skipped": json_safe(preview["skipped"])},
            applied_changes={"changes": json_safe(changes), "skipped": json_safe(skipped)},
        )
        db.add(audit)
        db.flush()
        audit_id = audit.id
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {
        "plan_id": plan.id,
        "audit_id": audit_id,
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


def workout_type_score(activity: Activity, workout: TrainingPlanWorkout) -> tuple[float, list[str]]:
    reasons = []
    workout_type = workout.workout_type or ""
    title = (activity.title or "").lower()
    has_intervals = activity_has_interval_structure(activity)
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

    reasons = []
    if delta_days is None:
        reasons.append("дата активности или плановой тренировки не указана")
    elif abs(delta_days) <= 1:
        reasons.append("дата активности близка к плановой")
    elif abs(delta_days) <= 3:
        reasons.append("активность в допустимом окне +/-3 дня")
    else:
        reasons.append("активность далеко от плановой даты")

    if distance_delta is None:
        reasons.append("дистанция не задана для одной из сторон")
    elif abs(distance_delta) <= max(0.75, (workout.distance_km or 0) * 0.12):
        reasons.append("дистанция близка к плану")
    elif distance_delta > 0:
        reasons.append("фактическая дистанция выше плановой")
    else:
        reasons.append("фактическая дистанция ниже плановой")

    type_score, type_reasons = workout_type_score(activity, workout)
    reasons.extend(type_reasons)
    score = round(
        date_score(delta_days) * 0.48
        + distance_score(activity.distance_km, workout.distance_km) * 0.34
        + type_score * 0.18,
        2,
    )
    confidence = "high" if score >= AUTO_MATCH_MIN_SCORE else "medium" if score >= 0.55 else "low"
    return {
        "score": score,
        "confidence": confidence,
        "reasons": reasons,
        "date_delta_days": delta_days,
        "distance_delta_km": distance_delta,
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
        .options(selectinload(Activity.segments), selectinload(Activity.split_blocks), selectinload(Activity.workout_blocks))
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
        .options(selectinload(TrainingPlanWorkout.completed_activity))
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
    workout.completed_activity_id = activity.id
    workout.status = "done"
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise ValueError("Activity already linked to another workout") from error
    db.refresh(workout)
    return workout


def auto_match_activity_to_plan(db: Session, user: User, activity: Activity) -> TrainingPlanWorkout | None:
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
    if workout.completed_activity_id is not None or workout.status not in MATCHABLE_WORKOUT_STATUSES:
        return None
    workout.completed_activity_id = activity.id
    workout.status = "done"
    db.flush()
    return workout


def plan_to_dict(plan: TrainingPlan) -> dict[str, object]:
    workouts = sorted(plan.workouts, key=lambda workout: (workout.week_index, workout.day_index, workout.id))
    return {
        "id": plan.id,
        "title": plan.title,
        "goal_type": plan.goal_type,
        "race_distance_km": plan.race_distance_km,
        "target_date": plan.target_date,
        "available_days_per_week": plan.available_days_per_week,
        "status": plan.status,
        "explanation": plan.explanation,
        "workouts": [workout_to_dict(workout) for workout in workouts],
        "adherence": adherence_summary(workouts),
        "weekly_adherence": weekly_adherence_summary(workouts),
    }


def preview_workout_is_hard(workout: dict[str, object]) -> bool:
    return str(workout.get("workout_type") or "") in HARD_PLAN_WORKOUT_TYPES or str(workout.get("intensity") or "") in HARD_PLAN_INTENSITIES


def preview_intensity_category(workout: dict[str, object]) -> str:
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
    weeks = weeks_until(request.target_date, start_date)
    days = request.available_days_per_week
    goal_distance = goal_distance_for_request(request)
    if request.current_weekly_distance_km is not None:
        current_volume = request.current_weekly_distance_km
        volume_source = "manual_override"
    else:
        current_volume = float(context["current_weekly_volume_km"] or DEFAULT_WEEKLY_VOLUME_KM)
        volume_source = str(context["current_weekly_volume_source"])
    current_volume = round(max(3.0, current_volume), 1)
    baseline = {
        "observed_weekly_volume_km": context["observed_weekly_volume_km"],
        "current_weekly_volume_km": current_volume,
        "current_weekly_volume_source": volume_source,
        "recent_long_run_km": request.longest_recent_run_km if request.longest_recent_run_km is not None else context["recent_long_run_km"],
        "history_span_days": context["history_span_days"],
        "activity_count": context["activity_count"],
        "training_age_level": context["training_age_level"],
        "confidence": "medium" if volume_source == "manual_override" else context["confidence"],
    }
    safety_context = {**context, "recent_weekly_distance_km": current_volume, "current_weekly_volume_km": current_volume}
    safety = build_safety_context(profile, completeness, safety_context, goal_distance, request)
    conservative = bool(safety["conservative"])
    has_precise_zones = bool(completeness["can_calculate_pace_zones"] or completeness["can_calculate_hr_zones"] or completeness["can_calculate_hrr_zones"] or request.intensity_mode == "rpe")
    preferred_weekdays = request.preferred_weekdays or []
    priority_multiplier = 1.05 if request.priority in {"a", "high"} else 0.95 if request.priority in {"c", "low"} else 1.0
    target_time_multiplier = 1.03 if request.target_time_seconds else 1.0
    growth_factor = (1.16 if conservative else 1.35) * priority_multiplier
    goal_factor = (0.75 if conservative else (1.15 if goal_distance >= 21 else 0.9)) * priority_multiplier * target_time_multiplier
    peak_volume = max(current_volume * growth_factor, goal_distance * goal_factor)
    if conservative:
        peak_volume = min(peak_volume, current_volume * growth_factor)

    workouts: list[dict[str, object]] = []
    weekly_curve: list[dict[str, object]] = []
    intensity_distance = {"easy": 0.0, "steady": 0.0, "hard": 0.0}
    easy_pace_seconds_per_km = estimated_easy_pace_seconds_per_km(request, zones, goal_distance)
    for week in range(1, weeks + 1):
        progression = week / weeks
        week_volume = current_volume + (peak_volume - current_volume) * min(1, progression * 1.15)
        if week % 4 == 0:
            week_volume *= 0.78
        if request.time_budget_minutes_per_week:
            budget_distance = request.time_budget_minutes_per_week * 60 / easy_pace_seconds_per_km
            week_volume = min(week_volume, max(1.0, budget_distance))
        long_cap = 0.62 if conservative else 0.75
        long_run = min(goal_distance * long_cap, week_volume * (0.34 if conservative else 0.38))
        if request.max_long_run_km:
            long_run = min(long_run, request.max_long_run_km)
        if request.max_long_run_duration_minutes:
            long_run = min(long_run, request.max_long_run_duration_minutes * 60 / easy_pace_seconds_per_km)
        long_run = min(long_run, week_volume)
        easy_distance = max(0.0, (week_volume - long_run) / max(1, days - 1))
        week_workouts = workout_template(days, conservative=conservative, has_precise_zones=has_precise_zones)
        week_distance = 0.0
        hard_sessions = 0
        for day_index, workout_type, title, intensity in week_workouts:
            distance = round(long_run if workout_type == "long" else easy_distance, 1)
            workout = {
                "week_index": week,
                "day_index": day_index,
                "scheduled_date": scheduled_workout_date(start_date, week, day_index, days, preferred_weekdays),
                "workout_type": workout_type,
                "title": title,
                "distance_km": distance,
                "intensity": intensity,
                "description": wizard_workout_description(workout_description(workout_type, intensity, zones, conservative), request, goal_distance),
            }
            workouts.append(workout)
            week_distance += distance
            if preview_workout_is_hard(workout):
                hard_sessions += 1
            intensity_distance[preview_intensity_category(workout)] += distance
        weekly_curve.append({
            "week_index": week,
            "planned_distance_km": round(week_distance, 1),
            "long_run_km": round(long_run, 1),
            "hard_sessions": hard_sessions,
        })

    total_distance = sum(intensity_distance.values())
    intensity_split = {key: round(value / total_distance, 3) if total_distance else 0.0 for key, value in intensity_distance.items()}
    effective_peak_volume = max((float(week["planned_distance_km"] or 0) for week in weekly_curve), default=round(peak_volume, 1))
    safety_text = "; ".join(safety["reasons"]) if safety["reasons"] else "no active safety gates"
    zone_text = []
    if zones["pace"]:
        zone_text.append(f"pace zones: {len(zones['pace'])}")
    if zones["hr"]:
        zone_text.append(f"HR zones: {len(zones['hr'])}")
    zone_summary = ", ".join(zone_text) if zone_text else "no precise zones, using RPE targets"
    risk_flags = builder_risk_flags(request, baseline, weekly_curve, workouts, safety, completeness, goal_distance, weeks, start_date)
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
            "max_long_run_km": request.max_long_run_km,
            "max_long_run_duration_minutes": request.max_long_run_duration_minutes,
            "time_budget_minutes_per_week": request.time_budget_minutes_per_week,
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
            f"Baseline source: {volume_source}, training age={baseline['training_age_level']}, confidence={baseline['confidence']}. "
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
    context = plan_builder_training_context(db, user, profile, start_date)
    return build_plan_preview_blueprint(request, profile, completeness, profile_safety, zones, context, start_date)


def apply_generated_plan_status(db: Session, user: User, plan: TrainingPlan, activate: bool) -> None:
    if not activate:
        plan.status = "draft"
        return
    active_plans = list(db.scalars(select(TrainingPlan).where(TrainingPlan.user_id == user.id, TrainingPlan.status == "active")))
    for active_plan in active_plans:
        if active_plan.id != plan.id:
            active_plan.status = "archived"
    plan.status = "active"


def generate_plan(db: Session, user: User, request: PlanGenerateRequest) -> TrainingPlan:
    preview = plan_builder_preview(db, user, request, persist_profile=True)

    plan = TrainingPlan(
        user_id=user.id,
        title=str(preview["title"]),
        goal_type=str(preview["goal_type"]),
        race_distance_km=float(preview["race_distance_km"] or 0),
        target_date=preview["target_date"],
        available_days_per_week=int(preview["available_days_per_week"]),
        status="draft",
        explanation=str(preview["explanation"]).replace("Plan Builder Preview", "Profile-aware MVP"),
    )
    apply_generated_plan_status(db, user, plan, request.activate)
    db.add(plan)
    db.flush()

    for workout in preview["workouts"]:
        db.add(TrainingPlanWorkout(
            plan_id=plan.id,
            week_index=int(workout["week_index"]),
            day_index=int(workout["day_index"]),
            scheduled_date=workout["scheduled_date"],
            status="planned",
            workout_type=str(workout["workout_type"]),
            title=str(workout["title"]),
            distance_km=float(workout["distance_km"]) if workout["distance_km"] is not None else None,
            intensity=str(workout["intensity"]) if workout["intensity"] is not None else None,
            description=str(workout["description"]) if workout["description"] is not None else None,
        ))

    db.commit()
    db.refresh(plan)
    return plan


def activate_plan(db: Session, user: User, plan: TrainingPlan) -> TrainingPlan:
    active_plans = list(db.scalars(select(TrainingPlan).where(TrainingPlan.user_id == user.id, TrainingPlan.status == "active")))
    for active_plan in active_plans:
        if active_plan.id != plan.id:
            active_plan.status = "archived"
    plan.status = "active"
    db.commit()
    db.refresh(plan)
    return plan


def update_plan(db: Session, user: User, plan: TrainingPlan, payload: PlanUpdate) -> TrainingPlan:
    updates = payload.model_dump(exclude_unset=True)
    if "title" in updates and updates["title"] is not None:
        plan.title = updates["title"]
    if updates.get("status") == "active":
        return activate_plan(db, user, plan)
    if "status" in updates and updates["status"] is not None:
        plan.status = updates["status"]
    db.commit()
    db.refresh(plan)
    return plan


def duplicate_plan(db: Session, user: User, plan: TrainingPlan) -> TrainingPlan:
    duplicate = TrainingPlan(
        user_id=user.id,
        title=f"{plan.title} copy",
        goal_type=plan.goal_type,
        race_distance_km=plan.race_distance_km,
        target_date=plan.target_date,
        available_days_per_week=plan.available_days_per_week,
        status="draft",
        explanation=plan.explanation,
    )
    db.add(duplicate)
    db.flush()
    for workout in sorted(plan.workouts, key=lambda item: (item.week_index, item.day_index, item.id)):
        copied_workout = TrainingPlanWorkout(
            plan_id=duplicate.id,
            scheduled_date=workout.scheduled_date,
            status="planned",
            week_index=workout.week_index,
            day_index=workout.day_index,
            workout_type=workout.workout_type,
            title=workout.title,
            distance_km=workout.distance_km,
            duration_seconds=workout.duration_seconds,
            intensity=workout.intensity,
            description=workout.description,
        )
        duplicate.workouts.append(copied_workout)
        db.add(copied_workout)
    db.commit()
    db.refresh(duplicate)
    return duplicate


def delete_plan(db: Session, user: User, plan: TrainingPlan) -> int:
    if plan.status == "active":
        raise ValueError("Active plan cannot be deleted; archive it first")
    plan_id = plan.id
    db.delete(plan)
    db.commit()
    return plan_id


def update_workout(db: Session, user: User, workout: TrainingPlanWorkout, payload: PlanWorkoutUpdate) -> TrainingPlanWorkout:
    updates = payload.model_dump(exclude_unset=True)
    next_completed_activity_id = workout.completed_activity_id
    if "completed_activity_id" in updates:
        activity_id = updates["completed_activity_id"]
        if activity_id is None:
            workout.completed_activity_id = None
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
            next_completed_activity_id = activity.id
            if "status" not in updates:
                workout.status = "done"
            elif updates["status"] != "done":
                raise ValueError("Linked workout status must be done")
    if "scheduled_date" in updates:
        workout.scheduled_date = updates["scheduled_date"]
        if workout.status == "planned":
            workout.status = "rescheduled"
    if "status" in updates and updates["status"] is not None:
        if updates["status"] == "done" and next_completed_activity_id is None:
            raise ValueError("Done workout requires linked activity")
        if updates["status"] != "done" and next_completed_activity_id is not None:
            raise ValueError("Linked workout status must be done")
        workout.status = updates["status"]
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise ValueError("Activity already linked to another workout") from error
    db.refresh(workout)
    return workout


def save_workout_feedback(db: Session, user: User, workout: TrainingPlanWorkout, payload: PlanWorkoutFeedbackIn) -> TrainingPlanWorkoutFeedback:
    if workout.status not in {"done", "missed", "skipped"}:
        raise ValueError("Workout feedback requires completed, missed or skipped workout")
    if workout.plan.user_id != user.id:
        raise ValueError("Workout not found")
    feedback = workout.feedback
    if feedback is None:
        feedback = TrainingPlanWorkoutFeedback(user_id=user.id, workout_id=workout.id)
        db.add(feedback)
        workout.feedback = feedback
    updates = payload.model_dump()
    for field, value in updates.items():
        setattr(feedback, field, value)
    if feedback.pain_level is not None and feedback.pain_level > 0:
        feedback.pain = True
    elif not feedback.pain:
        feedback.pain_level = None
    db.commit()
    db.refresh(feedback)
    return feedback
