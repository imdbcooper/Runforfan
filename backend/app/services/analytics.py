from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Activity, AthleteMeasurement, AthleteProfile, TrainingPlan, TrainingPlanWorkout, User
from app.services.calculations import CalculationResult, calculate_vdot


BEST_EFFORT_TARGETS_KM = (1.0, 5.0, 10.0, 21.1)


def date_range_label(from_date: date | None, to_date: date | None) -> str:
    if from_date and to_date:
        return f"{from_date.isoformat()}..{to_date.isoformat()}"
    if from_date:
        return f"from {from_date.isoformat()}"
    if to_date:
        return f"until {to_date.isoformat()}"
    return "all_time"


def profile_timezone(db: Session, user: User) -> ZoneInfo:
    profile = db.scalar(select(AthleteProfile).where(AthleteProfile.user_id == user.id))
    try:
        return ZoneInfo(profile.timezone if profile and profile.timezone else "UTC")
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def period_bounds(from_date: date | None, to_date: date | None, timezone: ZoneInfo = ZoneInfo("UTC")) -> tuple[datetime | None, datetime | None]:
    start = datetime.combine(from_date, time.min, tzinfo=timezone).astimezone(UTC) if from_date else None
    end = datetime.combine(to_date + timedelta(days=1), time.min, tzinfo=timezone).astimezone(UTC) if to_date else None
    return start, end


def activity_local_date(activity: Activity, timezone: ZoneInfo = ZoneInfo("UTC")) -> date | None:
    if not activity.started_at:
        return None
    started_at = activity.started_at
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone)
    return started_at.astimezone(timezone).date()


def measurement_local_date(measurement: AthleteMeasurement, timezone: ZoneInfo = ZoneInfo("UTC")) -> date | None:
    if not measurement.measured_at:
        return None
    measured_at = measurement.measured_at
    if measured_at.tzinfo is None:
        measured_at = measured_at.replace(tzinfo=timezone)
    return measured_at.astimezone(timezone).date()


def load_activities(db: Session, user: User, from_date: date | None = None, to_date: date | None = None, timezone: ZoneInfo = ZoneInfo("UTC")) -> list[Activity]:
    query = (
        select(Activity)
        .where(Activity.user_id == user.id)
        .options(selectinload(Activity.segments))
        .order_by(Activity.started_at.desc().nullslast(), Activity.id.desc())
    )
    start, end = period_bounds(from_date, to_date, timezone)
    if start:
        query = query.where(Activity.started_at >= start - timedelta(days=1))
    if end:
        query = query.where(Activity.started_at < end + timedelta(days=1))
    activities = list(db.scalars(query))
    if from_date or to_date:
        return [activity for activity in activities if (activity_date := activity_local_date(activity, timezone)) and (from_date is None or activity_date >= from_date) and (to_date is None or activity_date <= to_date)]
    return activities


def load_planned_workouts(db: Session, user: User, from_date: date | None = None, to_date: date | None = None) -> list[TrainingPlanWorkout]:
    query = (
        select(TrainingPlanWorkout)
        .join(TrainingPlan)
        .where(TrainingPlan.user_id == user.id, TrainingPlan.status == "active")
        .options(selectinload(TrainingPlanWorkout.completed_activity))
        .order_by(TrainingPlanWorkout.scheduled_date.asc().nullslast(), TrainingPlanWorkout.id.asc())
    )
    if from_date:
        query = query.where(TrainingPlanWorkout.scheduled_date >= from_date)
    if to_date:
        query = query.where(TrainingPlanWorkout.scheduled_date <= to_date)
    return list(db.scalars(query))


def latest_manual_vo2max(db: Session, user: User, from_date: date | None = None, to_date: date | None = None, timezone: ZoneInfo = ZoneInfo("UTC")) -> dict[str, object] | None:
    measurements = list(db.scalars(
        select(AthleteMeasurement)
        .where(AthleteMeasurement.user_id == user.id, AthleteMeasurement.measurement_type == "vo2max", AthleteMeasurement.value_numeric.is_not(None))
        .order_by(AthleteMeasurement.measured_at.desc().nullslast(), AthleteMeasurement.id.desc())
    ))
    for candidate in measurements:
        measurement_date = measurement_local_date(candidate, timezone)
        if measurement_date is None and (from_date or to_date):
            continue
        if measurement_date and from_date and measurement_date < from_date:
            continue
        if measurement_date and to_date and measurement_date > to_date:
            continue
        measurement = candidate
        break
    else:
        measurement = None
    if measurement is None or measurement.value_numeric is None:
        return None
    return CalculationResult(
        round(measurement.value_numeric, 1),
        "ml/kg/min",
        f"{measurement.source}_measurement",
        "high" if measurement.source == "lab" else "medium",
        measurement.notes or "User-provided VO2max measurement",
    ).as_dict()


def weighted_average_hr(activities: list[Activity]) -> int | None:
    weighted = [
        ((activity.average_heart_rate_bpm or 0) * max(activity.duration_seconds or 0, 0), max(activity.duration_seconds or 0, 0))
        for activity in activities
        if activity.average_heart_rate_bpm and activity.duration_seconds
    ]
    weight = sum(item[1] for item in weighted)
    return round(sum(item[0] for item in weighted) / weight) if weight else None


def weighted_average_pace(activities: list[Activity]) -> int | None:
    distance = sum(activity.distance_km or 0 for activity in activities if activity.distance_km and activity.duration_seconds)
    duration = sum(activity.duration_seconds or 0 for activity in activities if activity.distance_km and activity.duration_seconds)
    return round(duration / distance) if distance else None


def activity_highlight(activity: Activity | None) -> dict[str, object] | None:
    if activity is None:
        return None
    return {
        "id": activity.id,
        "title": activity.title,
        "started_at": activity.started_at,
        "distance_km": activity.distance_km,
        "duration_seconds": activity.duration_seconds,
        "average_pace_seconds_per_km": activity.average_pace_seconds_per_km,
        "average_heart_rate_bpm": activity.average_heart_rate_bpm,
    }


def adherence_from_workouts(workouts: list[TrainingPlanWorkout]) -> dict[str, object] | None:
    if not workouts:
        return None
    done = [workout for workout in workouts if workout.status == "done"]
    missed = [workout for workout in workouts if workout.status == "missed"]
    skipped = [workout for workout in workouts if workout.status == "skipped"]
    linked = [workout for workout in workouts if workout.completed_activity_id is not None]
    planned_distance = sum(workout.distance_km or 0 for workout in workouts)
    completed_distance = sum((workout.completed_activity.distance_km if workout.completed_activity else 0) or 0 for workout in linked)
    warnings: list[str] = []
    if missed:
        warnings.append(f"{len(missed)} missed planned workouts")
    if skipped:
        warnings.append(f"{len(skipped)} skipped planned workouts")
    return {
        "total_workouts": len(workouts),
        "done_workouts": len(done),
        "missed_workouts": len(missed),
        "skipped_workouts": len(skipped),
        "linked_workouts": len(linked),
        "unlinked_done_workouts": len([workout for workout in done if workout.completed_activity_id is None]),
        "planned_distance_km": round(planned_distance, 2),
        "completed_distance_km": round(completed_distance, 2),
        "completion_rate": round(len(done) / len(workouts), 2) if workouts else 0,
        "distance_completion_rate": round(completed_distance / planned_distance, 2) if planned_distance else 0,
        "warnings": warnings,
    }


def month_buckets(activities: list[Activity], timezone: ZoneInfo = ZoneInfo("UTC")) -> list[dict[str, object]]:
    months = defaultdict(lambda: {"distance_km": 0.0, "duration_seconds": 0, "count": 0})
    for activity in activities:
        activity_date = activity_local_date(activity, timezone)
        key = activity_date.strftime("%Y-%m") if activity_date else "unknown"
        months[key]["distance_km"] += activity.distance_km or 0
        months[key]["duration_seconds"] += activity.duration_seconds or 0
        months[key]["count"] += 1
    return [
        {"month": key, "distance_km": round(value["distance_km"], 2), "duration_seconds": value["duration_seconds"], "count": value["count"]}
        for key, value in sorted(months.items(), reverse=True)
    ]


def effort_candidate(activity: Activity, target_distance_km: float, source: str, source_distance_km: float, source_duration_seconds: int) -> dict[str, object] | None:
    if source_distance_km <= 0 or source_duration_seconds <= 0:
        return None
    target_duration = round(source_duration_seconds / source_distance_km * target_distance_km)
    if target_duration <= 0:
        return None
    ratio = source_distance_km / target_distance_km
    race_like = any(marker in (activity.title or "").lower() for marker in ("race", "time trial", "забег", "соревн", "тест"))
    if source == "activity_average" and not race_like:
        confidence = "low"
    elif 0.95 <= ratio <= 1.05 and target_distance_km >= 3:
        confidence = "high"
    else:
        confidence = "medium" if 0.95 <= ratio <= 1.05 else "low"
    vdot = calculate_vdot(target_distance_km, target_duration)
    return {
        "target_distance_km": target_distance_km,
        "activity_id": activity.id,
        "title": activity.title,
        "started_at": activity.started_at,
        "source": source,
        "confidence": confidence,
        "distance_km": round(source_distance_km, 3),
        "duration_seconds": target_duration,
        "pace_seconds_per_km": round(target_duration / target_distance_km),
        "estimated_vdot": vdot.as_dict() if vdot.value is not None else None,
    }


def best_efforts(activities: list[Activity]) -> list[dict[str, object]]:
    efforts: list[dict[str, object]] = []
    for target in BEST_EFFORT_TARGETS_KM:
        candidates: list[dict[str, object]] = []
        for activity in activities:
            if activity.distance_km and activity.duration_seconds and target * 0.95 <= activity.distance_km <= target * 1.05:
                candidate = effort_candidate(activity, target, "activity_average", activity.distance_km, activity.duration_seconds)
                if candidate:
                    candidates.append(candidate)
            if target == 1.0:
                for segment in activity.segments or []:
                    if 0.95 <= segment.distance_km <= 1.05:
                        candidate = effort_candidate(activity, target, "best_split", segment.distance_km, segment.duration_seconds)
                        if candidate:
                            candidates.append(candidate)
        if candidates:
            efforts.append(min(candidates, key=lambda item: (int(item["duration_seconds"]), {"high": 0, "medium": 1, "low": 2}.get(str(item["confidence"]), 3))))
    return efforts


def select_estimated_vdot(efforts: list[dict[str, object]]) -> tuple[dict[str, object] | None, int | None]:
    eligible = [
        effort for effort in efforts
        if effort.get("estimated_vdot") and float(effort["target_distance_km"]) >= 3 and effort.get("confidence") in {"high", "medium"}
    ]
    if not eligible:
        return None, None
    best = max(eligible, key=lambda effort: float(effort["estimated_vdot"]["value"] or 0))
    return best["estimated_vdot"], int(best["activity_id"])


def consistency_summary(activities: list[Activity], workouts: list[TrainingPlanWorkout], from_date: date | None, to_date: date | None, timezone: ZoneInfo = ZoneInfo("UTC")) -> dict[str, object]:
    days = {activity_date for activity in activities if (activity_date := activity_local_date(activity, timezone))}
    if from_date and to_date:
        span_days = max((to_date - from_date).days + 1, 1)
    elif days:
        span_days = max((max(days) - min(days)).days + 1, 1)
    else:
        span_days = 0
    weeks = max(span_days / 7, 1) if span_days else 0
    missed = len([workout for workout in workouts if workout.status in {"missed", "skipped"}])
    return {
        "training_days": len(days),
        "training_days_per_week": round(len(days) / weeks, 1) if weeks else 0,
        "missed_planned_sessions": missed,
    }


def analytics_summary_from_data(activities: list[Activity], workouts: list[TrainingPlanWorkout] | None = None, from_date: date | None = None, to_date: date | None = None, manual_vo2max: dict[str, object] | None = None, timezone: ZoneInfo = ZoneInfo("UTC")) -> dict[str, object]:
    workouts = workouts or []
    total_distance = sum(activity.distance_km or 0 for activity in activities)
    total_duration = sum(activity.duration_seconds or 0 for activity in activities)
    longest = max(activities, key=lambda activity: activity.distance_km or 0, default=None)
    fastest = min(
        [activity for activity in activities if activity.average_pace_seconds_per_km],
        key=lambda activity: activity.average_pace_seconds_per_km or 99999,
        default=None,
    )
    efforts = best_efforts(activities)
    estimated_vdot, estimated_vdot_activity_id = select_estimated_vdot(efforts)
    load_values = [activity.aerobic_training_stress for activity in activities if activity.aerobic_training_stress is not None]
    return {
        "period": {"from_date": from_date, "to_date": to_date, "label": date_range_label(from_date, to_date)},
        "activity_count": len(activities),
        "total_distance_km": round(total_distance, 2),
        "total_duration_seconds": total_duration,
        "weighted_average_pace_seconds_per_km": weighted_average_pace(activities),
        "average_heart_rate_bpm": weighted_average_hr(activities),
        "training_load": round(sum(load_values), 1) if load_values else None,
        "load_method": "aerobic_training_stress" if load_values else "unavailable",
        "longest_activity_id": longest.id if longest else None,
        "longest_distance_km": longest.distance_km if longest else None,
        "fastest_activity_id": fastest.id if fastest else None,
        "fastest_average_pace_seconds_per_km": fastest.average_pace_seconds_per_km if fastest else None,
        "longest_activity": activity_highlight(longest),
        "fastest_activity": activity_highlight(fastest),
        "adherence": adherence_from_workouts(workouts),
        "consistency": consistency_summary(activities, workouts, from_date, to_date, timezone),
        "best_efforts": efforts,
        "estimated_vdot": estimated_vdot,
        "estimated_vdot_activity_id": estimated_vdot_activity_id,
        "manual_vo2max": manual_vo2max,
        "months": month_buckets(activities, timezone),
    }


def user_analytics(db: Session, user: User, from_date: date | None = None, to_date: date | None = None) -> dict[str, object]:
    timezone = profile_timezone(db, user)
    activities = load_activities(db, user, from_date, to_date, timezone)
    workouts = load_planned_workouts(db, user, from_date, to_date)
    return analytics_summary_from_data(activities, workouts, from_date, to_date, latest_manual_vo2max(db, user, from_date, to_date, timezone), timezone)


def bucket_start(value: date, granularity: str) -> date:
    if granularity == "month":
        return date(value.year, value.month, 1)
    return value - timedelta(days=value.weekday())


def bucket_label(value: date, granularity: str) -> str:
    if granularity == "month":
        return value.strftime("%Y-%m")
    return f"{value.isoformat()} week"


def timeseries_from_activities(activities: list[Activity], metric: str = "distance", granularity: str = "week", timezone: ZoneInfo = ZoneInfo("UTC")) -> dict[str, object]:
    buckets: dict[date, list[Activity]] = defaultdict(list)
    for activity in activities:
        activity_date = activity_local_date(activity, timezone)
        if activity_date:
            buckets[bucket_start(activity_date, granularity)].append(activity)
    points: list[dict[str, object]] = []
    for start, bucket_activities in sorted(buckets.items()):
        distance = sum(activity.distance_km or 0 for activity in bucket_activities)
        duration = sum(activity.duration_seconds or 0 for activity in bucket_activities)
        pace = weighted_average_pace(bucket_activities)
        hr = weighted_average_hr(bucket_activities)
        load_values = [activity.aerobic_training_stress for activity in bucket_activities if activity.aerobic_training_stress is not None]
        load = round(sum(load_values), 1) if load_values else None
        value: float | int | None
        if metric == "duration":
            value = duration
        elif metric == "workouts":
            value = len(bucket_activities)
        elif metric == "pace":
            value = pace
        elif metric == "hr":
            value = hr
        elif metric == "load":
            value = load
        else:
            value = round(distance, 2)
        points.append({
            "period_start": start,
            "period_label": bucket_label(start, granularity),
            "value": value,
            "distance_km": round(distance, 2),
            "duration_seconds": duration,
            "count": len(bucket_activities),
            "weighted_average_pace_seconds_per_km": pace,
            "average_heart_rate_bpm": hr,
            "training_load": load,
        })
    return {"metric": metric, "granularity": granularity, "points": points}


def analytics_timeseries(db: Session, user: User, metric: str = "distance", granularity: str = "week", from_date: date | None = None, to_date: date | None = None) -> dict[str, object]:
    timezone = profile_timezone(db, user)
    return timeseries_from_activities(load_activities(db, user, from_date, to_date, timezone), metric, granularity, timezone)


def insights_from_summary(summary: dict[str, object]) -> list[dict[str, object]]:
    insights: list[dict[str, object]] = []
    activity_count = int(summary["activity_count"])
    distance = float(summary["total_distance_km"])
    duration = int(summary["total_duration_seconds"])
    consistency = summary["consistency"] or {}
    adherence = summary.get("adherence")
    if activity_count == 0:
        return [{"severity": "info", "title": "Недостаточно данных", "message": "За выбранный период нет активностей для надежной аналитики.", "reasons": ["activity_count = 0"]}]
    insights.append({"severity": "info", "title": "Объем периода", "message": f"За период выполнено {activity_count} тренировок, {distance:.1f} км и {round(duration / 3600, 1)} ч работы.", "reasons": ["distance and duration are aggregated from activities"]})
    if summary.get("weighted_average_pace_seconds_per_km"):
        insights.append({"severity": "info", "title": "Средний темп взвешен", "message": "Средний темп считается через общий объем и время, а не простым средним по тренировкам.", "reasons": ["duration / distance weighting"]})
    if summary.get("estimated_vdot"):
        vdot = summary["estimated_vdot"]
        insights.append({"severity": "info", "title": "Есть оценка VO2max/VDOT", "message": f"VDOT estimate: {vdot['value']} ({vdot['confidence']} confidence) по лучшему подходящему усилию.", "reasons": [str(vdot["source_reference"])]})
    if adherence and (adherence.get("missed_workouts") or adherence.get("skipped_workouts")):
        missed = int(adherence.get("missed_workouts") or 0) + int(adherence.get("skipped_workouts") or 0)
        insights.append({"severity": "warning", "title": "Есть пропуски плана", "message": f"За период {missed} planned sessions были missed/skipped.", "reasons": adherence.get("warnings") or []})
    if consistency.get("training_days_per_week") is not None:
        insights.append({"severity": "info", "title": "Стабильность", "message": f"Средняя частота: {consistency['training_days_per_week']} тренировочных дней в неделю.", "reasons": ["unique activity dates / selected weeks"]})
    if summary.get("training_load") is None:
        insights.append({"severity": "info", "title": "Load пока ограничен", "message": "Training load не рассчитан, потому что у активностей нет aerobic training stress.", "reasons": ["missing aerobic_training_stress"]})
    return insights[:5]


def analytics_insights(db: Session, user: User, from_date: date | None = None, to_date: date | None = None) -> list[dict[str, object]]:
    return insights_from_summary(user_analytics(db, user, from_date, to_date))
