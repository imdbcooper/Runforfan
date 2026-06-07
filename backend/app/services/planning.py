from datetime import date, timedelta
from math import ceil

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models import Activity, TrainingPlan, TrainingPlanWorkout, User
from app.schemas.common import PlanGenerateRequest, PlanWorkoutUpdate
from app.services.profile import get_or_create_profile, profile_completeness, safety_check
from app.services.zones import zones_response


MATCHABLE_WORKOUT_STATUSES = ("planned", "rescheduled")
CANDIDATE_MIN_SCORE = 0.25
CANDIDATE_DATE_WINDOW_DAYS = 7
AUTO_MATCH_MIN_SCORE = 0.78
AUTO_MATCH_DATE_WINDOW_DAYS = 3


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


def scheduled_workout_date(start_date: date, week_index: int, day_index: int, days: int) -> date:
    offsets = schedule_offsets(days)
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


def generate_plan(db: Session, user: User, request: PlanGenerateRequest) -> TrainingPlan:
    weeks = weeks_until(request.target_date)
    days = request.available_days_per_week
    profile = get_or_create_profile(db, user)
    completeness = profile_completeness(profile)
    profile_safety = safety_check(profile)
    zones = zones_response(db, user)
    context = recent_training_context(db, user)
    goal_distance = request.race_distance_km or 10.0
    start_date = date.today()
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
                scheduled_date=scheduled_workout_date(start_date, week, day_index, days),
                status="planned",
                workout_type=workout_type,
                title=title,
                distance_km=round(distance, 1),
                intensity=intensity,
                description=workout_description(workout_type, intensity, zones, conservative),
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
