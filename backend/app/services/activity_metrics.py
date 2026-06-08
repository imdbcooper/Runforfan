from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from statistics import pstdev
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import Activity, AthleteProfile, DerivedActivityMetric
from app.services.calculations import calculate_acsm_running_energy_kcal


def is_running_activity_type(activity_type: str | None) -> bool:
    value = (activity_type or "outdoor_run").strip().lower().replace("-", "_").replace(" ", "_")
    return value == "manual_workout" or "run" in value or "treadmill" in value


def running_activity_type_filter():
    value = func.replace(func.replace(func.lower(func.coalesce(Activity.activity_type, "outdoor_run")), "-", "_"), " ", "_")
    return or_(value == "manual_workout", value.like("%run%"), value.like("%treadmill%"))


def _round(value: float, digits: int = 1) -> float:
    return round(float(value), digits)


def activity_metric_input_hash(activity: Activity, weight_kg: float | None = None) -> str:
    payload = {
        "distance_km": activity.distance_km,
        "duration_seconds": activity.duration_seconds,
        "calories_kcal": activity.calories_kcal,
        "athlete_weight_kg": weight_kg,
        "average_heart_rate_bpm": activity.average_heart_rate_bpm,
        "elevation_gain_m": activity.elevation_gain_m,
        "elevation_loss_m": activity.elevation_loss_m,
        "segments": [
            {
                "distance_km": segment.distance_km,
                "duration_seconds": segment.duration_seconds,
                "pace_seconds_per_km": segment.pace_seconds_per_km,
            }
            for segment in sorted(getattr(activity, "segments", []) or [], key=lambda item: item.segment_index)
        ],
        "workout_blocks": [
            {
                "block_type": block.block_type,
                "distance_km": block.distance_km,
                "duration_seconds": block.duration_seconds,
                "pace_seconds_per_km": block.pace_seconds_per_km,
            }
            for block in sorted(getattr(activity, "workout_blocks", []) or [], key=lambda item: item.block_index)
        ],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def metric_row(metric_key: str, metric_value: float, unit: str, method: str, source_reference: str, input_hash: str) -> dict[str, Any]:
    return {
        "metric_key": metric_key,
        "metric_value": metric_value,
        "unit": unit,
        "method": method,
        "source_reference": source_reference,
        "input_hash": input_hash,
    }


def activity_grade(activity: Activity, distance_km: float) -> float | None:
    if activity.elevation_gain_m is None and activity.elevation_loss_m is None:
        return None
    net_elevation_m = float(activity.elevation_gain_m or 0) - float(activity.elevation_loss_m or 0)
    return net_elevation_m / (distance_km * 1000)


def compute_derived_activity_metrics(activity: Activity, profile: AthleteProfile | None = None) -> list[dict[str, Any]]:
    metrics: list[dict[str, Any]] = []
    distance = float(activity.distance_km or 0)
    duration = int(activity.duration_seconds or 0)
    duration_minutes = duration / 60 if duration > 0 else 0
    weight_kg = profile.weight_kg if profile and is_running_activity_type(activity.activity_type) and activity.calories_kcal is None and distance > 0 and duration > 0 else None
    input_hash = activity_metric_input_hash(activity, weight_kg)

    if duration > 0:
        metrics.append(metric_row("duration_minutes", _round(duration_minutes, 1), "minutes", "duration_seconds", "activities.duration_seconds", input_hash))
    if distance > 0 and duration > 0:
        metrics.append(metric_row("average_pace_seconds_per_km", round(duration / distance), "seconds_per_km", "distance_duration", "activities.distance_km,duration_seconds", input_hash))
        metrics.append(metric_row("average_speed_kmh", _round(distance / (duration / 3600), 2), "kmh", "distance_duration", "activities.distance_km,duration_seconds", input_hash))

    if activity.elevation_gain_m is not None or activity.elevation_loss_m is not None:
        gain = float(activity.elevation_gain_m or 0)
        loss = float(activity.elevation_loss_m or 0)
        metrics.append(metric_row("vertical_balance_m", _round(gain - loss, 1), "m", "elevation_delta", "activities.elevation_gain_m,elevation_loss_m", input_hash))

    if weight_kg:
        energy = calculate_acsm_running_energy_kcal(distance, duration, weight_kg, activity_grade(activity, distance))
        if energy.value is not None:
            metrics.append(metric_row("estimated_energy_kcal", float(energy.value), energy.unit, energy.method, energy.source_reference, input_hash))

    segments = list(getattr(activity, "segments", []) or [])
    segment_paces = [float(segment.pace_seconds_per_km) for segment in segments if segment.pace_seconds_per_km]
    if len(segment_paces) >= 2:
        metrics.append(metric_row("pace_variability_seconds_per_km", _round(pstdev(segment_paces), 1), "seconds_per_km", "segment_pace_stddev", "activity_segments.pace_seconds_per_km", input_hash))

    blocks = list(getattr(activity, "workout_blocks", []) or [])
    work_blocks = [block for block in blocks if block.block_type == "work"]
    if work_blocks:
        work_duration = sum(int(block.duration_seconds or 0) for block in work_blocks)
        metrics.append(metric_row("work_block_count", float(len(work_blocks)), "count", "workout_block_summary", "activity_workout_blocks.block_type", input_hash))
        metrics.append(metric_row("work_block_duration_seconds", float(work_duration), "seconds", "workout_block_summary", "activity_workout_blocks.duration_seconds", input_hash))
        work_distance = sum(float(block.distance_km or 0) for block in work_blocks)
        if work_distance:
            metrics.append(metric_row("work_block_distance_km", _round(work_distance, 2), "km", "workout_block_summary", "activity_workout_blocks.distance_km", input_hash))

    if duration_minutes > 0:
        if activity.average_heart_rate_bpm:
            heart_rate_factor = min(max(activity.average_heart_rate_bpm / 150, 0.5), 1.8)
            metrics.append(metric_row("training_load_proxy", _round(duration_minutes * heart_rate_factor, 1), "au", "hr_duration_proxy", "activities.average_heart_rate_bpm,duration_seconds", input_hash))
        else:
            metrics.append(metric_row("training_load_proxy", _round(duration_minutes, 1), "au", "duration_proxy", "activities.duration_seconds", input_hash))
    return metrics


def sync_derived_activity_metrics(db: Session, activity: Activity, profile: AthleteProfile | None = None) -> list[DerivedActivityMetric]:
    db.flush()
    if activity.id is None:
        return []
    metric_dicts = compute_derived_activity_metrics(activity, profile)
    activity.derived_metrics.clear()
    db.flush()
    rows = [
        DerivedActivityMetric(
            activity_id=activity.id,
            metric_key=str(metric["metric_key"]),
            metric_value=float(metric["metric_value"]),
            unit=str(metric["unit"]),
            method=str(metric["method"]),
            source_reference=str(metric["source_reference"]),
            input_hash=str(metric["input_hash"]),
            computed_at=datetime.now(UTC),
        )
        for metric in metric_dicts
    ]
    activity.derived_metrics = rows
    for row in rows:
        db.add(row)
    return rows


def _metric_rows_are_current(activity: Activity, expected_metrics: list[dict[str, Any]]) -> bool:
    expected_by_key = {str(metric["metric_key"]): metric for metric in expected_metrics}
    existing_by_key = {metric.metric_key: metric for metric in activity.derived_metrics or []}
    if set(existing_by_key) != set(expected_by_key):
        return False
    for key, expected in expected_by_key.items():
        existing = existing_by_key[key]
        if abs(float(existing.metric_value) - float(expected["metric_value"])) > 0.000001:
            return False
        if existing.unit != str(expected["unit"]):
            return False
        if existing.method != str(expected["method"]):
            return False
        if (existing.source_reference or "") != str(expected["source_reference"] or ""):
            return False
        if existing.input_hash != str(expected["input_hash"]):
            return False
    return True


def _load_backfill_candidates(db: Session, activity_ids: list[int]) -> list[Activity]:
    if not activity_ids:
        return []
    return list(db.scalars(
        select(Activity)
        .where(Activity.id.in_(activity_ids))
        .options(
            selectinload(Activity.segments),
            selectinload(Activity.workout_blocks),
            selectinload(Activity.derived_metrics),
        )
        .order_by(Activity.id.asc())
    ))


def _profiles_by_user_id(db: Session, activities: list[Activity]) -> dict[int, AthleteProfile]:
    user_ids = sorted({activity.user_id for activity in activities if activity.user_id is not None})
    if not user_ids:
        return {}
    return {profile.user_id: profile for profile in db.scalars(select(AthleteProfile).where(AthleteProfile.user_id.in_(user_ids)))}


def _activity_id_query(user_id: int | None = None):
    query = select(Activity.id)
    if user_id is not None:
        query = query.where(Activity.user_id == user_id)
    return query


def _profile_metric_activity_id_query(user_id: int | None = None):
    query = _activity_id_query(user_id).where(
        Activity.calories_kcal.is_(None),
        Activity.distance_km > 0,
        Activity.duration_seconds > 0,
        running_activity_type_filter(),
    )
    return query


def _missing_profile_metric_activity_ids(db: Session, *, user_id: int | None, limit: int) -> list[int]:
    if limit <= 0:
        return []
    query = (
        _profile_metric_activity_id_query(user_id)
        .join(AthleteProfile, AthleteProfile.user_id == Activity.user_id)
        .outerjoin(DerivedActivityMetric, (DerivedActivityMetric.activity_id == Activity.id) & (DerivedActivityMetric.metric_key == "estimated_energy_kcal"))
        .where(
            AthleteProfile.weight_kg > 0,
            DerivedActivityMetric.metric_key.is_(None),
        )
        .order_by(Activity.id.asc())
        .limit(limit)
    )
    return list(db.scalars(query))


def _backfill_activity_ids(db: Session, *, limit: int, repair_existing: bool, include_profile_metrics: bool, user_id: int | None) -> list[int]:
    if repair_existing:
        activity_ids = list(db.scalars(_activity_id_query(user_id).order_by(Activity.id.asc()).limit(limit)))
    else:
        query = (
            _activity_id_query(user_id)
            .outerjoin(DerivedActivityMetric, DerivedActivityMetric.activity_id == Activity.id)
            .group_by(Activity.id)
            .having(func.count(DerivedActivityMetric.metric_key) == 0)
            .order_by(Activity.id.asc())
            .limit(limit)
        )
        activity_ids = list(db.scalars(query))
    if include_profile_metrics and len(activity_ids) < limit:
        activity_ids.extend(_missing_profile_metric_activity_ids(db, user_id=user_id, limit=limit - len(activity_ids)))
    return list(dict.fromkeys(int(activity_id) for activity_id in activity_ids))[:limit]


def backfill_derived_activity_metrics(db: Session, *, limit: int = 500, repair_existing: bool = False, include_profile_metrics: bool = True, user_id: int | None = None) -> int:
    if limit <= 0:
        return 0
    activity_ids = _backfill_activity_ids(db, limit=limit, repair_existing=repair_existing, include_profile_metrics=include_profile_metrics, user_id=user_id)
    activities = _load_backfill_candidates(db, activity_ids)
    profiles = _profiles_by_user_id(db, activities) if include_profile_metrics else {}
    synced_count = 0
    for activity in activities:
        profile = profiles.get(activity.user_id)
        expected_metrics = compute_derived_activity_metrics(activity, profile)
        if _metric_rows_are_current(activity, expected_metrics):
            continue
        sync_derived_activity_metrics(db, activity, profile)
        synced_count += 1
    return synced_count


def invalidate_user_profile_dependent_activity_metrics(db: Session, user_id: int) -> int:
    result = db.execute(delete(DerivedActivityMetric).where(
        DerivedActivityMetric.metric_key == "estimated_energy_kcal",
        DerivedActivityMetric.activity_id.in_(_activity_id_query(user_id)),
    ))
    return int(result.rowcount or 0)


def refresh_user_profile_dependent_activity_metrics(db: Session, user_id: int, *, batch_size: int = 500) -> int:
    if batch_size <= 0:
        batch_size = 500
    invalidate_user_profile_dependent_activity_metrics(db, user_id)
    profile = db.scalar(select(AthleteProfile).where(AthleteProfile.user_id == user_id))
    if not profile or not profile.weight_kg or profile.weight_kg <= 0:
        return 0
    synced_count = 0
    while True:
        activity_ids = _missing_profile_metric_activity_ids(db, user_id=user_id, limit=batch_size)
        if not activity_ids:
            break
        for activity in _load_backfill_candidates(db, activity_ids):
            expected_metrics = compute_derived_activity_metrics(activity, profile)
            if _metric_rows_are_current(activity, expected_metrics):
                continue
            sync_derived_activity_metrics(db, activity, profile)
            synced_count += 1
    return synced_count
