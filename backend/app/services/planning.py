from datetime import date
from math import ceil

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Activity, TrainingPlan, TrainingPlanWorkout, User
from app.schemas.common import PlanGenerateRequest
from app.services.profile import get_or_create_profile, profile_completeness, safety_check
from app.services.zones import zones_response


def weeks_until(target_date: date | None) -> int:
    if not target_date:
        return 8
    return max(4, min(24, ceil((target_date - date.today()).days / 7)))


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


def build_safety_context(profile, completeness: dict, context: dict[str, object], goal_distance: float) -> dict[str, object]:
    reasons = []
    if profile.conservative_mode:
        reasons.append("profile conservative mode")
    if profile.injury_notes:
        reasons.append("injury notes present")
    if int(context["history_span_days"] or 0) < 14:
        reasons.append("training history shorter than 14 days")
    if not completeness["can_calculate_pace_zones"]:
        reasons.append("no threshold pace zones")
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


def generate_plan(db: Session, user: User, request: PlanGenerateRequest) -> TrainingPlan:
    weeks = weeks_until(request.target_date)
    days = request.available_days_per_week
    profile = get_or_create_profile(db, user)
    completeness = profile_completeness(profile)
    profile_safety = safety_check(profile)
    zones = zones_response(db, user)
    context = recent_training_context(db, user)
    goal_distance = request.race_distance_km or 10.0
    current_volume = request.current_weekly_distance_km or context["recent_weekly_distance_km"] or 15.0
    safety = build_safety_context(profile, completeness, context, goal_distance)
    conservative = bool(safety["conservative"])
    has_precise_zones = bool(completeness["can_calculate_pace_zones"] or completeness["can_calculate_hrr_zones"])
    growth_factor = 1.16 if conservative else 1.35
    goal_factor = 0.75 if conservative else (1.15 if goal_distance >= 21 else 0.9)
    peak_volume = max(current_volume * growth_factor, goal_distance * goal_factor)
    if conservative:
        peak_volume = min(peak_volume, current_volume * growth_factor)
    safety_text = "; ".join(safety["reasons"]) if safety["reasons"] else "no active safety gates"
    zone_text = []
    if zones["pace"]:
        zone_text.append(f"pace zones: {len(zones['pace'])}")
    if zones["hr"]:
        zone_text.append(f"HR zones: {len(zones['hr'])}")
    zone_summary = ", ".join(zone_text) if zone_text else "no precise zones, using RPE targets"

    plan = TrainingPlan(
        user_id=user.id,
        title=request.title or f"План на {race_name(goal_distance)}",
        goal_type=request.goal_type,
        race_distance_km=goal_distance,
        target_date=request.target_date,
        available_days_per_week=days,
        status="draft",
        explanation=(
            f"Profile-aware MVP: план построен от текущего объема {current_volume:.1f} км/нед до пика {peak_volume:.1f} км/нед. "
            f"Safety gates: {safety_text}. Zones: {zone_summary}. "
            f"Profile completeness: {completeness['score']:.0%}, confidence={completeness['confidence']}. "
            f"Medical safety: {profile_safety['message']}"
        ),
    )
    db.add(plan)
    db.flush()

    for week in range(1, weeks + 1):
        progression = week / weeks
        week_volume = current_volume + (peak_volume - current_volume) * min(1, progression * 1.15)
        if week % 4 == 0:
            week_volume *= 0.78
        long_cap = 0.62 if conservative else 0.75
        long_run = min(goal_distance * long_cap, week_volume * (0.34 if conservative else 0.38))
        easy_distance = max(3.0, (week_volume - long_run) / max(1, days - 1))
        workouts = workout_template(days, conservative=conservative, has_precise_zones=has_precise_zones)
        for day_index, workout_type, title, intensity in workouts:
            distance = long_run if workout_type == "long" else easy_distance
            db.add(TrainingPlanWorkout(
                plan_id=plan.id,
                week_index=week,
                day_index=day_index,
                workout_type=workout_type,
                title=title,
                distance_km=round(distance, 1),
                intensity=intensity,
                description=workout_description(workout_type, intensity, zones, conservative),
            ))

    db.commit()
    db.refresh(plan)
    return plan
