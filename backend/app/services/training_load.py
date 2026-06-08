from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Activity, AthleteProfile, DailyTrainingLoad, TrainingPlan, TrainingPlanWorkout, User
from app.services.analytics import activity_local_date, date_range_label, load_activities, profile_timezone
from app.services.calculations import BANISTER_REF, CalculationResult, FOSTER_REF, calculate_hr_trimp, calculate_monotony_strain, calculate_srpe_load, ewma_load


LOAD_LOOKBACK_DAYS = 84
DEFAULT_PERIOD_DAYS = 28
MAX_DAILY_TRAINING_LOAD_BACKFILL_DAYS = 366
RECOVERY_LOAD_THRESHOLD = 10.0
SUPPORT_LOAD_FACTORS = {
    "strength": 0.75,
    "manual_strength": 0.75,
    "ofp": 0.7,
    "manual_ofp": 0.7,
    "core": 0.5,
    "manual_core": 0.5,
    "mobility": 0.25,
    "manual_mobility": 0.25,
    "prehab": 0.25,
    "manual_prehab": 0.25,
    "cross_training": 0.9,
    "manual_cross_training": 0.9,
}


def date_span(start: date, end: date) -> list[date]:
    if end < start:
        return []
    return [start + timedelta(days=index) for index in range((end - start).days + 1)]


def week_start(value: date) -> date:
    return value - timedelta(days=value.weekday())


def calculation_dict(value: float, method: str, source_reference: str, confidence: str = "low") -> dict[str, object]:
    return CalculationResult(round(value, 1), "au", method, confidence, source_reference).as_dict()


def primary_method(methods: set[str]) -> str:
    if not methods:
        return "unavailable"
    if len(methods) == 1:
        return next(iter(methods))
    return "mixed"


def load_planned_workouts_with_feedback(db: Session, user: User, activity_ids: list[int]) -> list[TrainingPlanWorkout]:
    if not activity_ids:
        return []
    return list(db.scalars(
        select(TrainingPlanWorkout)
        .join(TrainingPlan)
        .where(
            TrainingPlan.user_id == user.id,
            TrainingPlanWorkout.completed_activity_id.in_(activity_ids),
        )
        .options(selectinload(TrainingPlanWorkout.feedback), selectinload(TrainingPlanWorkout.completed_activity))
    ))


def hr_trimp_load(activity: Activity, profile: AthleteProfile | None) -> float | None:
    if not profile or not activity.average_heart_rate_bpm or not activity.duration_seconds:
        return None
    result = calculate_hr_trimp(
        activity.duration_seconds / 60,
        activity.average_heart_rate_bpm,
        profile.resting_heart_rate_bpm,
        profile.max_heart_rate_bpm,
        profile.sex,
    )
    return float(result.value) if result.value is not None else None


def activity_pace_seconds(activity: Activity) -> int | None:
    if activity.average_pace_seconds_per_km:
        return activity.average_pace_seconds_per_km
    if activity.distance_km and activity.duration_seconds:
        return round(activity.duration_seconds / activity.distance_km)
    return None


def pace_based_load(activity: Activity, profile: AthleteProfile | None) -> float | None:
    if not activity.duration_seconds:
        return None
    factor = 1.0
    pace = activity_pace_seconds(activity)
    threshold = profile.lactate_threshold_pace_seconds_per_km if profile else None
    if pace and threshold and pace > 0:
        factor = min(max(threshold / pace, 0.75), 1.6)
    return round((activity.duration_seconds / 60) * factor, 1)


def support_duration_load(activity: Activity) -> tuple[float, str] | None:
    if not activity.duration_seconds:
        return None
    activity_type = (activity.activity_type or "").lower()
    for marker, factor in SUPPORT_LOAD_FACTORS.items():
        if marker in activity_type:
            return round((activity.duration_seconds / 60) * factor, 1), "support_duration_fallback"
    return None


def linked_workout_map(workouts: list[TrainingPlanWorkout]) -> dict[int, TrainingPlanWorkout]:
    return {workout.completed_activity_id: workout for workout in workouts if workout.completed_activity_id is not None}


def activity_load(activity: Activity, workout: TrainingPlanWorkout | None, profile: AthleteProfile | None) -> tuple[float, str, int]:
    if activity.aerobic_training_stress is not None:
        return round(float(activity.aerobic_training_stress), 1), "aerobic_training_stress", 0
    if workout and workout.feedback and workout.feedback.rpe is not None and activity.duration_seconds:
        load = calculate_srpe_load(activity.duration_seconds / 60, workout.feedback.rpe)
        return float(load.value or 0), "session_rpe", 1
    hr_load = hr_trimp_load(activity, profile)
    if hr_load is not None:
        return hr_load, "hr_trimp", 0
    support_load = support_duration_load(activity)
    if support_load is not None:
        return support_load[0], support_load[1], 0
    pace_load = pace_based_load(activity, profile)
    if pace_load is not None:
        return pace_load, "pace_based_fallback", 0
    return 0.0, "unavailable", 0


def hard_session_reasons(activity: Activity, workout: TrainingPlanWorkout | None, load: float) -> list[str]:
    reasons: list[str] = []
    feedback = workout.feedback if workout else None
    if load >= 80:
        reasons.append("load >= 80")
    if feedback and feedback.rpe is not None and feedback.rpe >= 7:
        reasons.append("RPE >= 7")
    if feedback and feedback.fatigue is not None and feedback.fatigue >= 8:
        reasons.append("fatigue >= 8")
    workout_markers = {"interval", "tempo", "threshold", "race", "time_trial", "hard"}
    if workout and (workout.workout_type in workout_markers or workout.intensity in workout_markers):
        reasons.append("hard planned intensity")
    effect = (activity.aerobic_training_effect or "").lower()
    if "anaerobic" in effect or "threshold" in effect:
        reasons.append("hard training effect")
    return reasons


def empty_bucket(day: date) -> dict[str, object]:
    return {
        "date": day,
        "load": 0.0,
        "load_methods": set(),
        "distance_km": 0.0,
        "duration_seconds": 0,
        "activity_ids": [],
        "activity_count": 0,
        "srpe_count": 0,
        "hard_session": False,
        "hard_reasons": [],
        "recovery_day": True,
    }


def bucket_activity(bucket: dict[str, object], activity: Activity, workout: TrainingPlanWorkout | None, profile: AthleteProfile | None) -> None:
    load, method, srpe_count = activity_load(activity, workout, profile)
    bucket["load"] = round(float(bucket["load"]) + load, 1)
    if method != "unavailable":
        bucket["load_methods"].add(method)
    bucket["distance_km"] = round(float(bucket["distance_km"]) + (activity.distance_km or 0), 2)
    bucket["duration_seconds"] = int(bucket["duration_seconds"]) + max(activity.duration_seconds or 0, 0)
    if activity.id is not None:
        bucket["activity_ids"].append(int(activity.id))
    bucket["activity_count"] = int(bucket["activity_count"]) + 1
    bucket["srpe_count"] = int(bucket["srpe_count"]) + srpe_count
    reasons = hard_session_reasons(activity, workout, load)
    if reasons:
        bucket["hard_session"] = True
        bucket["hard_reasons"].extend(reasons)
    bucket["recovery_day"] = float(bucket["load"]) <= RECOVERY_LOAD_THRESHOLD


def daily_point(bucket: dict[str, object]) -> dict[str, object]:
    methods = sorted(bucket["load_methods"])
    return {
        "date": bucket["date"],
        "load": round(float(bucket["load"]), 1),
        "load_method": primary_method(set(methods)),
        "load_methods": methods,
        "distance_km": round(float(bucket["distance_km"]), 2),
        "duration_seconds": int(bucket["duration_seconds"]),
        "duration_minutes": round(int(bucket["duration_seconds"]) / 60, 1),
        "activity_ids": sorted(set(int(activity_id) for activity_id in bucket["activity_ids"])),
        "activity_count": int(bucket["activity_count"]),
        "srpe_count": int(bucket["srpe_count"]),
        "hard_session": bool(bucket["hard_session"]),
        "hard_reasons": sorted(set(bucket["hard_reasons"])),
        "recovery_day": bool(bucket["recovery_day"]),
        "ctl": None,
        "atl": None,
        "tsb": None,
        "monotony_window_value": None,
        "strain_window_value": None,
    }


def append_fitness(points: list[dict[str, object]], all_daily: list[dict[str, object]]) -> list[dict[str, object]]:
    ctl = 0.0
    atl = 0.0
    fitness_points: list[dict[str, object]] = []
    selected_dates = {point["date"] for point in points}
    for point in all_daily:
        load = float(point["load"])
        ctl = ewma_load(ctl, load, 42)
        atl = ewma_load(atl, load, 7)
        if point["date"] in selected_dates:
            fitness_points.append({"date": point["date"], "load": round(load, 1), "ctl": round(ctl, 1), "atl": round(atl, 1), "tsb": round(ctl - atl, 1)})
    return fitness_points


def weekly_points(daily: list[dict[str, object]]) -> list[dict[str, object]]:
    weeks: dict[date, list[dict[str, object]]] = defaultdict(list)
    for point in daily:
        weeks[week_start(point["date"])].append(point)
    result: list[dict[str, object]] = []
    for start, points in sorted(weeks.items()):
        loads = [float(point["load"]) for point in points]
        monotony = calculate_monotony_strain(loads)
        distance = sum(float(point["distance_km"]) for point in points)
        duration = sum(int(point["duration_seconds"]) for point in points)
        max_day_distance = max((float(point["distance_km"]) for point in points), default=0)
        long_run_share = max_day_distance / distance if distance else None
        methods = {method for point in points for method in point["load_methods"]}
        result.append({
            "week_start": start,
            "week_label": f"{start.isoformat()} week",
            "load": round(sum(loads), 1),
            "load_method": primary_method(methods),
            "distance_km": round(distance, 2),
            "duration_seconds": duration,
            "activity_count": sum(int(point["activity_count"]) for point in points),
            "hard_sessions": sum(1 for point in points if point["hard_session"]),
            "recovery_days": sum(1 for point in points if point["recovery_day"]),
            "long_run_share": round(long_run_share, 2) if long_run_share is not None else None,
            "monotony": monotony["monotony"].value,
            "strain": monotony["strain"].value,
        })
    return result


def annotate_daily_training_loads(selected_daily: list[dict[str, object]], all_daily: list[dict[str, object]], fitness_points: list[dict[str, object]]) -> None:
    fitness_by_date = {point["date"]: point for point in fitness_points}
    all_by_date = {point["date"]: index for index, point in enumerate(all_daily)}
    for point in selected_daily:
        fitness = fitness_by_date.get(point["date"])
        if fitness:
            point["ctl"] = fitness["ctl"]
            point["atl"] = fitness["atl"]
            point["tsb"] = fitness["tsb"]
        index = all_by_date.get(point["date"])
        if index is None:
            continue
        window = all_daily[max(0, index - 6):index + 1]
        monotony = calculate_monotony_strain([float(item["load"]) for item in window])
        point["monotony_window_value"] = monotony["monotony"].value
        point["strain_window_value"] = monotony["strain"].value


def warning(severity: str, title: str, message: str, reasons: list[str], metric: str | None = None, value: float | None = None, threshold: float | None = None) -> dict[str, object]:
    return {"severity": severity, "title": title, "message": message, "reasons": reasons, "metric": metric, "value": value, "threshold": threshold}


def load_warnings(daily: list[dict[str, object]], weekly: list[dict[str, object]], fitness: list[dict[str, object]]) -> list[dict[str, object]]:
    warnings: list[dict[str, object]] = []
    current = fitness[-1] if fitness else None
    if current:
        tsb = float(current["tsb"])
        if tsb <= -20:
            warnings.append(warning("critical", "High fatigue balance", "TSB is deeply negative; treat CTL/ATL/TSB as a heuristic and consider easier days.", ["TSB <= -20"], "tsb", tsb, -20))
        elif tsb <= -10:
            warnings.append(warning("warning", "Fatigue trending high", "ATL is materially above CTL, which can indicate short-term fatigue.", ["TSB <= -10"], "tsb", tsb, -10))
    latest_week = weekly[-1] if weekly else None
    if latest_week:
        monotony = latest_week.get("monotony")
        if monotony is not None and float(monotony) >= 2:
            warnings.append(warning("warning", "High monotony", "Recent daily load is too uniform; monotony is a warning signal, not a hard stop.", ["monotony >= 2"], "monotony", float(monotony), 2))
        share = latest_week.get("long_run_share")
        if share is not None and float(share) >= 0.35:
            warnings.append(warning("warning", "Long run share high", "The largest day takes too much of weekly distance/time.", ["long_run_share >= 35%"], "long_run_share", float(share), 0.35))
    recent = daily[-7:]
    hard_days = [point for point in recent if point["hard_session"]]
    activity_days = [point for point in recent if int(point["activity_count"]) > 0]
    if activity_days and len(hard_days) / len(activity_days) > 0.4:
        warnings.append(warning("warning", "Too much intensity", "Hard sessions make up more than 40% of recent training days.", ["hard_days / activity_days > 0.4"], "hard_session_share", round(len(hard_days) / len(activity_days), 2), 0.4))
    period_hard_days = [point for point in daily if point["hard_session"]]
    close_pairs = []
    for previous, current_day in zip(period_hard_days, period_hard_days[1:]):
        delta = (current_day["date"] - previous["date"]).days
        if delta < 2:
            close_pairs.append(f"{previous['date'].isoformat()} -> {current_day['date'].isoformat()}")
    if close_pairs:
        warnings.append(warning("warning", "Hard sessions too close", "Hard sessions are spaced closer than 48 hours.", close_pairs, "hard_session_spacing_days", 1, 2))
    recovery_days = sum(1 for point in recent if point["recovery_day"])
    if recent and recovery_days < 2:
        warnings.append(warning("warning", "Few recovery days", "Recent week has fewer than two low-load recovery days.", ["recovery_days < 2"], "recovery_days", recovery_days, 2))
    if not warnings:
        warnings.append(warning("info", "No load alerts", "No high monotony, intensity concentration or fatigue-balance alerts for the selected period.", ["heuristics within current thresholds"]))
    return warnings[:6]


def training_load_from_data(activities: list[Activity], workouts: list[TrainingPlanWorkout], profile: AthleteProfile | None, from_date: date, to_date: date, timezone: ZoneInfo = ZoneInfo("UTC")) -> dict[str, object]:
    warmup_start = from_date - timedelta(days=LOAD_LOOKBACK_DAYS)
    buckets = {day: empty_bucket(day) for day in date_span(warmup_start, to_date)}
    workout_by_activity_id = linked_workout_map(workouts)
    for activity in activities:
        activity_date = activity_local_date(activity, timezone)
        if activity_date is None or activity_date not in buckets:
            continue
        bucket_activity(buckets[activity_date], activity, workout_by_activity_id.get(activity.id), profile)
    all_daily = [daily_point(buckets[day]) for day in sorted(buckets)]
    selected_daily = [point for point in all_daily if from_date <= point["date"] <= to_date]
    fitness_points = append_fitness(selected_daily, all_daily)
    annotate_daily_training_loads(selected_daily, all_daily, fitness_points)
    weekly = weekly_points(selected_daily)
    method = primary_method({method for point in selected_daily for method in point["load_methods"]})
    current_fitness = fitness_points[-1] if fitness_points else {"ctl": 0.0, "atl": 0.0, "tsb": 0.0}
    period = {"from_date": from_date, "to_date": to_date, "label": date_range_label(from_date, to_date)}
    return {
        "period": period,
        "method": method,
        "daily": {"period": period, "method": method, "points": selected_daily},
        "weekly": {"period": period, "method": method, "points": weekly},
        "fitness_fatigue": {
            "period": period,
            "method": method,
            "explanation": "CTL/ATL/TSB are EWMA heuristics over daily training load, not medical predictions.",
            "current": {
                "ctl": calculation_dict(float(current_fitness["ctl"]), "ewma_42d", BANISTER_REF),
                "atl": calculation_dict(float(current_fitness["atl"]), "ewma_7d", BANISTER_REF),
                "tsb": calculation_dict(float(current_fitness["tsb"]), "ctl_minus_atl", BANISTER_REF),
            },
            "points": fitness_points,
        },
        "warnings": load_warnings(selected_daily, weekly, fitness_points),
    }


def training_load_context(db: Session, user: User, from_date: date | None = None, to_date: date | None = None) -> dict[str, object]:
    timezone = profile_timezone(db, user)
    end_date = to_date or datetime.now(timezone).date()
    start_date = from_date or end_date - timedelta(days=DEFAULT_PERIOD_DAYS - 1)
    warmup_start = start_date - timedelta(days=LOAD_LOOKBACK_DAYS)
    profile = db.scalar(select(AthleteProfile).where(AthleteProfile.user_id == user.id))
    activities = load_activities(db, user, warmup_start, end_date, timezone)
    workouts = load_planned_workouts_with_feedback(db, user, [activity.id for activity in activities])
    return training_load_from_data(activities, workouts, profile, start_date, end_date, timezone)


def training_load_daily(db: Session, user: User, from_date: date | None = None, to_date: date | None = None) -> dict[str, object]:
    return training_load_context(db, user, from_date, to_date)["daily"]


def training_load_weekly(db: Session, user: User, from_date: date | None = None, to_date: date | None = None) -> dict[str, object]:
    return training_load_context(db, user, from_date, to_date)["weekly"]


def training_load_fitness_fatigue(db: Session, user: User, from_date: date | None = None, to_date: date | None = None) -> dict[str, object]:
    return training_load_context(db, user, from_date, to_date)["fitness_fatigue"]


def training_load_warning_list(db: Session, user: User, from_date: date | None = None, to_date: date | None = None) -> list[dict[str, object]]:
    return training_load_context(db, user, from_date, to_date)["warnings"]


def persisted_load_method(load_method: str) -> str:
    mapping = {
        "session_rpe": "srpe",
        "hr_trimp": "hr_trimp",
        "pace_based_fallback": "pace_fallback",
        "support_duration_fallback": "manual",
        "aerobic_training_stress": "manual",
    }
    return mapping.get(load_method, load_method)


def sync_daily_training_loads(db: Session, user: User, from_date: date, to_date: date) -> int:
    if to_date < from_date:
        return 0
    db.flush()
    timezone = profile_timezone(db, user)
    warmup_start = from_date - timedelta(days=LOAD_LOOKBACK_DAYS)
    profile = db.scalar(select(AthleteProfile).where(AthleteProfile.user_id == user.id))
    activities = load_activities(db, user, warmup_start, to_date, timezone)
    workouts = load_planned_workouts_with_feedback(db, user, [activity.id for activity in activities])
    context = training_load_from_data(activities, workouts, profile, from_date, to_date, timezone)
    points = context["daily"]["points"]
    dates = [point["date"] for point in points]
    existing = {
        row.date: row
        for row in db.scalars(
            select(DailyTrainingLoad)
            .where(DailyTrainingLoad.user_id == user.id, DailyTrainingLoad.date.in_(dates))
            .order_by(DailyTrainingLoad.date.asc())
        )
    }
    synced_count = 0
    for point in points:
        row = existing.get(point["date"])
        if row is None:
            row = DailyTrainingLoad(user_id=user.id, date=point["date"])
            db.add(row)
        row.load_value = float(point["load"])
        row.method = persisted_load_method(str(point["load_method"]))
        row.duration_minutes = float(point["duration_minutes"])
        row.activity_ids = [int(activity_id) for activity_id in point["activity_ids"]]
        row.ctl = float(point["ctl"]) if point["ctl"] is not None else None
        row.atl = float(point["atl"]) if point["atl"] is not None else None
        row.tsb = float(point["tsb"]) if point["tsb"] is not None else None
        row.monotony_window_value = float(point["monotony_window_value"]) if point["monotony_window_value"] is not None else None
        row.strain_window_value = float(point["strain_window_value"]) if point["strain_window_value"] is not None else None
        row.computed_at = datetime.now(UTC)
        synced_count += 1
    return synced_count


def _same_float(left: float | None, right: float | None, tolerance: float = 0.000001) -> bool:
    if left is None or right is None:
        return left is None and right is None
    return abs(float(left) - float(right)) <= tolerance


def daily_training_load_row_matches_point(row: DailyTrainingLoad, point: dict[str, object]) -> bool:
    return (
        _same_float(row.load_value, float(point["load"]))
        and row.method == persisted_load_method(str(point["load_method"]))
        and _same_float(row.duration_minutes, float(point["duration_minutes"]))
        and sorted(int(activity_id) for activity_id in (row.activity_ids or [])) == sorted(int(activity_id) for activity_id in point["activity_ids"])
        and _same_float(row.ctl, float(point["ctl"]) if point["ctl"] is not None else None)
        and _same_float(row.atl, float(point["atl"]) if point["atl"] is not None else None)
        and _same_float(row.tsb, float(point["tsb"]) if point["tsb"] is not None else None)
        and _same_float(row.monotony_window_value, float(point["monotony_window_value"]) if point["monotony_window_value"] is not None else None)
        and _same_float(row.strain_window_value, float(point["strain_window_value"]) if point["strain_window_value"] is not None else None)
    )


def validate_daily_training_load_backfill_range(start_date: date, end_date: date) -> None:
    if end_date < start_date:
        raise ValueError("to_date must be on or after from_date")
    if (end_date - start_date).days + 1 > MAX_DAILY_TRAINING_LOAD_BACKFILL_DAYS:
        raise ValueError(f"daily training load backfill is limited to {MAX_DAILY_TRAINING_LOAD_BACKFILL_DAYS} days")


def materialization_period(db: Session, user: User, from_date: date | None = None, to_date: date | None = None) -> tuple[date, date]:
    end_date = to_date
    if end_date is None:
        timezone = profile_timezone(db, user)
        end_date = datetime.now(timezone).date()
    start_date = from_date or end_date - timedelta(days=DEFAULT_PERIOD_DAYS - 1)
    validate_daily_training_load_backfill_range(start_date, end_date)
    return start_date, end_date


def daily_training_load_materialization_status(db: Session, user: User, from_date: date | None = None, to_date: date | None = None) -> dict[str, object]:
    start_date, end_date = materialization_period(db, user, from_date, to_date)
    context = training_load_context(db, user, start_date, end_date)
    points = context["daily"]["points"]
    expected_dates = [point["date"] for point in points]
    rows = {
        row.date: row
        for row in db.scalars(
            select(DailyTrainingLoad)
            .where(DailyTrainingLoad.user_id == user.id, DailyTrainingLoad.date.in_(expected_dates))
            .order_by(DailyTrainingLoad.date.asc())
        )
    }
    missing_dates: list[date] = []
    stale_dates: list[date] = []
    for point in points:
        row = rows.get(point["date"])
        if row is None:
            missing_dates.append(point["date"])
            continue
        if not daily_training_load_row_matches_point(row, point):
            stale_dates.append(point["date"])
    period = context["daily"]["period"]
    return {
        "period": period,
        "expected_days": len(points),
        "persisted_days": len(rows),
        "missing_dates": missing_dates,
        "stale_dates": stale_dates,
        "fresh": not missing_dates and not stale_dates,
    }


def backfill_daily_training_loads(db: Session, user: User, from_date: date | None = None, to_date: date | None = None) -> dict[str, object]:
    start_date, end_date = materialization_period(db, user, from_date, to_date)
    synced_rows = sync_daily_training_loads(db, user, start_date, end_date)
    db.flush()
    status = daily_training_load_materialization_status(db, user, start_date, end_date)
    return {"synced_rows": synced_rows, "status": status}


def sync_daily_training_loads_for_dates(db: Session, user: User, changed_dates: list[date]) -> int:
    if not changed_dates:
        return 0
    timezone = profile_timezone(db, user)
    start_date = min(changed_dates)
    end_date = max(datetime.now(timezone).date(), max(changed_dates))
    return sync_daily_training_loads(db, user, start_date, end_date)


def sync_daily_training_loads_for_activity(db: Session, user: User, activity: Activity) -> int:
    timezone = profile_timezone(db, user)
    activity_date = activity_local_date(activity, timezone)
    if activity_date is None:
        return 0
    return sync_daily_training_loads_for_dates(db, user, [activity_date])


def sync_daily_training_loads_for_activities(db: Session, user: User, activities: list[Activity]) -> int:
    timezone = profile_timezone(db, user)
    changed_dates = [activity_date for activity in activities if (activity_date := activity_local_date(activity, timezone)) is not None]
    return sync_daily_training_loads_for_dates(db, user, changed_dates)


def backfill_recent_daily_training_loads(db: Session, *, days: int = DEFAULT_PERIOD_DAYS, user_limit: int = 100) -> int:
    if days <= 0 or user_limit <= 0:
        return 0
    users = list(db.scalars(
        select(User)
        .where(User.id.in_(select(Activity.user_id).distinct()))
        .order_by(User.id.asc())
        .limit(user_limit)
    ))
    synced_count = 0
    for user in users:
        timezone = profile_timezone(db, user)
        end_date = datetime.now(timezone).date()
        start_date = end_date - timedelta(days=days - 1)
        synced_count += sync_daily_training_loads(db, user, start_date, end_date)
    return synced_count
