from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from statistics import pstdev
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import Activity, DerivedActivityMetric


def _round(value: float, digits: int = 1) -> float:
    return round(float(value), digits)


def activity_metric_input_hash(activity: Activity) -> str:
    payload = {
        "distance_km": activity.distance_km,
        "duration_seconds": activity.duration_seconds,
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


def compute_derived_activity_metrics(activity: Activity) -> list[dict[str, Any]]:
    input_hash = activity_metric_input_hash(activity)
    metrics: list[dict[str, Any]] = []
    distance = float(activity.distance_km or 0)
    duration = int(activity.duration_seconds or 0)
    duration_minutes = duration / 60 if duration > 0 else 0

    if duration > 0:
        metrics.append(metric_row("duration_minutes", _round(duration_minutes, 1), "minutes", "duration_seconds", "activities.duration_seconds", input_hash))
    if distance > 0 and duration > 0:
        metrics.append(metric_row("average_pace_seconds_per_km", round(duration / distance), "seconds_per_km", "distance_duration", "activities.distance_km,duration_seconds", input_hash))
        metrics.append(metric_row("average_speed_kmh", _round(distance / (duration / 3600), 2), "kmh", "distance_duration", "activities.distance_km,duration_seconds", input_hash))

    if activity.elevation_gain_m is not None or activity.elevation_loss_m is not None:
        gain = float(activity.elevation_gain_m or 0)
        loss = float(activity.elevation_loss_m or 0)
        metrics.append(metric_row("vertical_balance_m", _round(gain - loss, 1), "m", "elevation_delta", "activities.elevation_gain_m,elevation_loss_m", input_hash))

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


def sync_derived_activity_metrics(db: Session, activity: Activity) -> list[DerivedActivityMetric]:
    db.flush()
    if activity.id is None:
        return []
    metric_dicts = compute_derived_activity_metrics(activity)
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


def backfill_derived_activity_metrics(db: Session, *, limit: int = 500, repair_existing: bool = False) -> int:
    if limit <= 0:
        return 0
    if repair_existing:
        activity_ids = list(db.scalars(select(Activity.id).order_by(Activity.id.asc()).limit(limit)))
    else:
        activity_ids = list(db.scalars(
            select(Activity.id)
            .outerjoin(DerivedActivityMetric, DerivedActivityMetric.activity_id == Activity.id)
            .group_by(Activity.id)
            .having(func.count(DerivedActivityMetric.metric_key) == 0)
            .order_by(Activity.id.asc())
            .limit(limit)
        ))
    activities = _load_backfill_candidates(db, activity_ids)
    synced_count = 0
    for activity in activities:
        expected_metrics = compute_derived_activity_metrics(activity)
        if _metric_rows_are_current(activity, expected_metrics):
            continue
        sync_derived_activity_metrics(db, activity)
        synced_count += 1
    return synced_count
