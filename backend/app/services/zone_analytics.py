from __future__ import annotations

from collections import defaultdict
from datetime import date
from zoneinfo import ZoneInfo

from sqlalchemy import case, select
from sqlalchemy.orm import Session, selectinload

from app.models import Activity, AthleteProfile, TrainingPlan, TrainingPlanWorkout, User
from app.services.analytics import activity_local_date, bucket_label, bucket_start, date_range_label, load_activities, load_planned_workouts, profile_timezone
from app.services.training_load import linked_workout_map
from app.services.zones import zones_response


FIVE_ZONE_LABELS = {
    "z1": "Recovery / Easy",
    "z2": "Aerobic",
    "z3": "Tempo / Threshold",
    "z4": "Interval",
    "z5": "Race / Repetition",
}
SEILER_LABELS = {
    "low": "Seiler Z1 low",
    "moderate": "Seiler Z2 moderate",
    "high": "Seiler Z3 high",
}
SEILER_BY_FIVE_ZONE = {"z1": "low", "z2": "low", "z3": "moderate", "z4": "high", "z5": "high"}
PACE_TO_FIVE_ZONE = {"easy": "z1", "steady": "z2", "threshold": "z3", "interval": "z4", "rep": "z5"}
PLANNED_INTENSITY_TO_FIVE_ZONE = {
    "recovery": "z1",
    "rest": "z1",
    "mobility": "z1",
    "prehab": "z1",
    "easy": "z2",
    "base": "z2",
    "long": "z2",
    "strength": "z2",
    "ofp": "z2",
    "core": "z2",
    "cross_training": "z2",
    "steady": "z3",
    "moderate": "z3",
    "tempo": "z3",
    "threshold": "z3",
    "interval": "z4",
    "repetition": "z5",
    "rep": "z5",
    "race": "z5",
    "time_trial": "z5",
    "hard": "z5",
}


def support_activity_zone(activity: Activity, workout: TrainingPlanWorkout | None) -> str | None:
    markers = " ".join([activity.activity_type or "", activity.title or "", workout.workout_type if workout else "", workout.title if workout else ""]).lower().replace("_", " ").replace("-", " ")
    if any(marker in markers for marker in ("mobility", "prehab", "stretch", "моб")):
        return "z1"
    if any(marker in markers for marker in ("strength", "ofp", "сил", "офп", "core", "gym", "cross training")):
        return "z2"
    return None


def zone_value_matches(zone: dict[str, object], value: float) -> bool:
    lower = zone.get("lower_value")
    upper = zone.get("upper_value")
    if lower is not None and value < float(lower):
        return False
    if upper is not None and value > float(upper):
        return False
    return True


def classify_value(zones: list[dict[str, object]], value: float | int | None) -> dict[str, object] | None:
    if value is None:
        return None
    for zone in zones:
        if zone_value_matches(zone, float(value)):
            return zone
    return None


def five_zone_key(zone_type: str, zone_key: str) -> str | None:
    if zone_type in {"hr", "rpe"} and zone_key in FIVE_ZONE_LABELS:
        return zone_key
    if zone_type == "pace":
        return PACE_TO_FIVE_ZONE.get(zone_key)
    return None


def empty_duration_maps(keys: list[str]) -> tuple[dict[str, int], dict[str, int]]:
    return {key: 0 for key in keys}, {key: 0 for key in keys}


def distribution_items(durations: dict[str, int], counts: dict[str, int], labels: dict[str, str], total: int | None = None) -> list[dict[str, object]]:
    denominator = sum(durations.values()) if total is None else total
    return [
        {
            "zone_key": key,
            "label": labels.get(key, key),
            "duration_seconds": int(durations.get(key, 0)),
            "percentage": round(durations.get(key, 0) / denominator * 100, 1) if denominator else 0.0,
            "source_count": int(counts.get(key, 0)),
        }
        for key in labels
    ]


def zone_labels(zones: list[dict[str, object]]) -> dict[str, str]:
    return {str(zone["zone_key"]): str(zone.get("label") or zone["zone_key"]) for zone in zones}


def add_duration(durations: dict[str, int], counts: dict[str, int], key: str | None, duration: int) -> None:
    if key is None or duration <= 0:
        return
    durations[key] = durations.get(key, 0) + duration
    counts[key] = counts.get(key, 0) + 1


def activity_efforts(activity: Activity) -> list[dict[str, object]]:
    activity_duration = max(activity.duration_seconds or 0, 0)
    block_efforts = [
        {
            "duration_seconds": max(block.duration_seconds or 0, 0),
            "pace_seconds_per_km": block.pace_seconds_per_km,
            "heart_rate_bpm": block.average_heart_rate_bpm,
        }
        for block in activity.workout_blocks or []
    ]
    segment_efforts = [
        {
            "duration_seconds": max(segment.duration_seconds or 0, 0),
            "pace_seconds_per_km": segment.pace_seconds_per_km,
            "heart_rate_bpm": segment.average_heart_rate_bpm,
        }
        for segment in activity.segments or []
    ]
    block_duration = sum(int(effort["duration_seconds"]) for effort in block_efforts)
    segment_duration = sum(int(effort["duration_seconds"]) for effort in segment_efforts)
    if block_efforts and (activity_duration == 0 or block_duration >= activity_duration * 0.9):
        return block_efforts
    if segment_efforts and (activity_duration == 0 or segment_duration >= activity_duration * 0.9):
        return segment_efforts
    if block_efforts:
        uncovered_duration = max(activity_duration - block_duration, 0)
        if uncovered_duration:
            block_efforts.append({
                "duration_seconds": uncovered_duration,
                "pace_seconds_per_km": activity.average_pace_seconds_per_km or (round(activity.duration_seconds / activity.distance_km) if activity.distance_km and activity.duration_seconds else None),
                "heart_rate_bpm": activity.average_heart_rate_bpm,
            })
        return block_efforts
    if segment_efforts:
        return segment_efforts
    return [{
        "duration_seconds": activity_duration,
        "pace_seconds_per_km": activity.average_pace_seconds_per_km or (round(activity.duration_seconds / activity.distance_km) if activity.distance_km and activity.duration_seconds else None),
        "heart_rate_bpm": activity.average_heart_rate_bpm,
    }]


def planned_workout_zone(workout: TrainingPlanWorkout) -> str:
    markers = [workout.intensity, workout.workout_type, workout.title]
    for marker in markers:
        value = (marker or "").lower().replace("-", "_").replace(" ", "_")
        if value in PLANNED_INTENSITY_TO_FIVE_ZONE:
            return PLANNED_INTENSITY_TO_FIVE_ZONE[value]
        tokens = {token for token in value.split("_") if token}
        for key, zone in PLANNED_INTENSITY_TO_FIVE_ZONE.items():
            if key in tokens:
                return zone
    return "z2"


def planned_workout_duration(workout: TrainingPlanWorkout, profile: AthleteProfile | None = None) -> int:
    if workout.duration_seconds:
        return max(workout.duration_seconds, 0)
    if workout.distance_km:
        pace = profile.lactate_threshold_pace_seconds_per_km + 75 if profile and profile.lactate_threshold_pace_seconds_per_km else 360
        return round(workout.distance_km * pace)
    return 0


def load_linked_workouts_with_feedback(db: Session, user: User, activity_ids: list[int]) -> list[TrainingPlanWorkout]:
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
        .order_by(case((TrainingPlan.status == "active", 0), else_=1), TrainingPlanWorkout.scheduled_date.desc().nullslast(), TrainingPlanWorkout.id.desc())
    ))


def compare_planned_actual(planned: dict[str, int], actual: dict[str, int]) -> list[dict[str, object]]:
    planned_total = sum(planned.values())
    actual_total = sum(actual.values())
    rows: list[dict[str, object]] = []
    for key, label in FIVE_ZONE_LABELS.items():
        planned_pct = round(planned.get(key, 0) / planned_total * 100, 1) if planned_total else 0.0
        actual_pct = round(actual.get(key, 0) / actual_total * 100, 1) if actual_total else 0.0
        rows.append({
            "zone_key": key,
            "label": label,
            "planned_duration_seconds": int(planned.get(key, 0)),
            "planned_percentage": planned_pct,
            "actual_duration_seconds": int(actual.get(key, 0)),
            "actual_percentage": actual_pct,
            "diff_percentage": round(actual_pct - planned_pct, 1),
        })
    return rows


def zone_distribution_from_data(activities: list[Activity], linked_workouts: list[TrainingPlanWorkout], planned_workouts: list[TrainingPlanWorkout], zones: dict[str, list[dict[str, object]]], from_date: date | None = None, to_date: date | None = None, granularity: str = "week", timezone: ZoneInfo = ZoneInfo("UTC"), profile: AthleteProfile | None = None) -> dict[str, object]:
    hr_zones = zones.get("hr", [])
    pace_zones = zones.get("pace", [])
    rpe_zones = zones.get("rpe", [])
    hr_keys = list(zone_labels(hr_zones).keys())
    pace_keys = list(zone_labels(pace_zones).keys())
    rpe_keys = list(zone_labels(rpe_zones).keys())
    hr_duration, hr_counts = empty_duration_maps(hr_keys)
    pace_duration, pace_counts = empty_duration_maps(pace_keys)
    rpe_duration, rpe_counts = empty_duration_maps(rpe_keys)
    five_duration, five_counts = empty_duration_maps(list(FIVE_ZONE_LABELS))
    planned_duration, planned_counts = empty_duration_maps(list(FIVE_ZONE_LABELS))
    bucket_durations: dict[date, dict[str, int]] = defaultdict(lambda: {key: 0 for key in FIVE_ZONE_LABELS})
    bucket_counts: dict[date, dict[str, int]] = defaultdict(lambda: {key: 0 for key in FIVE_ZONE_LABELS})
    workout_by_activity = linked_workout_map(linked_workouts)

    for activity in activities:
        local_date = activity_local_date(activity, timezone)
        bucket = bucket_start(local_date, granularity) if local_date else None
        workout = workout_by_activity.get(activity.id)
        feedback_rpe = workout.feedback.rpe if workout and workout.feedback and workout.feedback.rpe is not None else None
        rpe_zone = classify_value(rpe_zones, feedback_rpe)
        if rpe_zone:
            add_duration(rpe_duration, rpe_counts, str(rpe_zone["zone_key"]), max(activity.duration_seconds or 0, 0))
        for effort in activity_efforts(activity):
            duration = int(effort["duration_seconds"])
            hr_zone = classify_value(hr_zones, effort.get("heart_rate_bpm"))
            pace_zone = classify_value(pace_zones, effort.get("pace_seconds_per_km"))
            if hr_zone:
                add_duration(hr_duration, hr_counts, str(hr_zone["zone_key"]), duration)
            if pace_zone:
                add_duration(pace_duration, pace_counts, str(pace_zone["zone_key"]), duration)
            detailed_key = five_zone_key("hr", str(hr_zone["zone_key"])) if hr_zone else None
            if detailed_key is None and pace_zone:
                detailed_key = five_zone_key("pace", str(pace_zone["zone_key"]))
            if detailed_key is None and rpe_zone:
                detailed_key = five_zone_key("rpe", str(rpe_zone["zone_key"]))
            if detailed_key is None:
                detailed_key = support_activity_zone(activity, workout)
            add_duration(five_duration, five_counts, detailed_key, duration)
            if bucket and detailed_key:
                bucket_durations[bucket][detailed_key] += duration
                bucket_counts[bucket][detailed_key] += 1

    for workout in planned_workouts:
        zone_key = planned_workout_zone(workout)
        add_duration(planned_duration, planned_counts, zone_key, planned_workout_duration(workout, profile))

    seiler_duration, seiler_counts = empty_duration_maps(list(SEILER_LABELS))
    for five_key, duration in five_duration.items():
        seiler_key = SEILER_BY_FIVE_ZONE.get(five_key)
        if seiler_key:
            seiler_duration[seiler_key] += duration
            seiler_counts[seiler_key] += five_counts.get(five_key, 0)

    time_buckets = [
        {
            "period_start": start,
            "period_label": bucket_label(start, granularity),
            "total_duration_seconds": sum(durations.values()),
            "items": distribution_items(durations, bucket_counts[start], FIVE_ZONE_LABELS),
        }
        for start, durations in sorted(bucket_durations.items())
    ]
    classified_actual = sum(five_duration.values())
    total_activity_duration = sum(max(activity.duration_seconds or 0, 0) for activity in activities)
    return {
        "period": {"from_date": from_date, "to_date": to_date, "label": date_range_label(from_date, to_date)},
        "granularity": granularity,
        "zones": zones,
        "actual_hr": distribution_items(hr_duration, hr_counts, zone_labels(hr_zones)),
        "actual_pace": distribution_items(pace_duration, pace_counts, zone_labels(pace_zones)),
        "actual_rpe": distribution_items(rpe_duration, rpe_counts, zone_labels(rpe_zones)),
        "actual_five_zone": distribution_items(five_duration, five_counts, FIVE_ZONE_LABELS),
        "seiler_three_zone": distribution_items(seiler_duration, seiler_counts, SEILER_LABELS),
        "planned_five_zone": distribution_items(planned_duration, planned_counts, FIVE_ZONE_LABELS),
        "planned_vs_actual": compare_planned_actual(planned_duration, five_duration),
        "time_buckets": time_buckets,
        "metadata": {
            "activity_count": len(activities),
            "planned_workout_count": len(planned_workouts),
            "classified_actual_duration_seconds": classified_actual,
            "unclassified_actual_duration_seconds": max(total_activity_duration - classified_actual, 0),
            "classification_priority": ["hr", "pace", "rpe"],
        },
    }


def zone_distribution(db: Session, user: User, from_date: date | None = None, to_date: date | None = None, granularity: str = "week") -> dict[str, object]:
    timezone = profile_timezone(db, user)
    profile = db.scalar(select(AthleteProfile).where(AthleteProfile.user_id == user.id))
    activities = load_activities(db, user, from_date, to_date, timezone)
    linked_workouts = load_linked_workouts_with_feedback(db, user, [activity.id for activity in activities])
    planned_workouts = load_planned_workouts(db, user, from_date, to_date)
    return zone_distribution_from_data(activities, linked_workouts, planned_workouts, zones_response(db, user), from_date, to_date, granularity, timezone, profile)
