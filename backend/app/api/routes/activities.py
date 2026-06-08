from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.models import Activity, ActivityScreenshot, AthleteProfile, User
from app.schemas.common import ActivityCreate, ActivityOut, ActivityUpdate, ActivityValidationOut
from app.services.activity_metrics import sync_derived_activity_metrics
from app.services.analytics import activity_local_date, profile_timezone
from app.services.auth import get_current_user
from app.services.training_load import sync_daily_training_loads_for_dates


router = APIRouter(prefix="/activities", tags=["activities"])
ACTIVITY_WRITE_FIELDS = (
    "activity_type",
    "title",
    "started_at",
    "distance_km",
    "duration_seconds",
    "calories_kcal",
    "average_pace_seconds_per_km",
    "fastest_pace_seconds_per_km",
    "average_speed_kmh",
    "average_cadence_spm",
    "average_stride_cm",
    "steps_count",
    "average_heart_rate_bpm",
    "elevation_gain_m",
    "elevation_loss_m",
    "aerobic_training_stress",
    "aerobic_training_effect",
    "source_note",
)
DERIVED_SUMMARY_FIELDS = {"average_pace_seconds_per_km", "average_speed_kmh"}


def validation_issue(code: str, severity: str, message: str, metric: str | None = None, expected: float | None = None, actual: float | None = None, unit: str | None = None) -> dict[str, object]:
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "metric": metric,
        "expected": expected,
        "actual": actual,
        "unit": unit,
    }


def activity_validation_report(activity: Activity) -> dict[str, object]:
    checks: list[dict[str, object]] = []
    weighted_pace = None
    distance = float(activity.distance_km or 0)
    duration = int(activity.duration_seconds or 0)
    average_pace = activity.average_pace_seconds_per_km

    if distance > 0 and duration > 0:
        expected_pace = round(duration / distance)
        if average_pace is None:
            checks.append(validation_issue("missing_average_pace", "info", "Activity has distance and duration but no imported average pace.", "average_pace_seconds_per_km", expected_pace, None, "seconds_per_km"))
        elif abs(int(average_pace) - expected_pace) > max(5, expected_pace * 0.02):
            checks.append(validation_issue("pace_distance_duration_mismatch", "warning", "Imported average pace does not match distance and duration within tolerance.", "average_pace_seconds_per_km", expected_pace, int(average_pace), "seconds_per_km"))

    if activity.average_heart_rate_bpm is not None and not 35 <= int(activity.average_heart_rate_bpm) <= 230:
        checks.append(validation_issue("average_hr_out_of_range", "warning", "Average heart rate is outside the physiological validation range.", "average_heart_rate_bpm", None, int(activity.average_heart_rate_bpm), "bpm"))
    if activity.average_cadence_spm is not None and not 120 <= int(activity.average_cadence_spm) <= 240:
        checks.append(validation_issue("cadence_outlier", "info", "Average running cadence is outside the usual 120-240 spm range.", "average_cadence_spm", None, int(activity.average_cadence_spm), "spm"))

    segments = sorted(activity.segments or [], key=lambda segment: segment.segment_index)
    if segments:
        segment_distance = sum(float(segment.distance_km or 0) for segment in segments)
        segment_duration = sum(int(segment.duration_seconds or 0) for segment in segments)
        if segment_distance > 0 and segment_duration > 0:
            weighted_pace = round(segment_duration / segment_distance)
            if average_pace is not None and abs(int(average_pace) - weighted_pace) > max(5, weighted_pace * 0.02):
                checks.append(validation_issue("weighted_pace_mismatch", "warning", "Imported average pace differs from segment-weighted pace.", "weighted_pace_seconds_per_km", weighted_pace, int(average_pace), "seconds_per_km"))
        if distance and abs(segment_distance - distance) > max(0.05, distance * 0.01):
            checks.append(validation_issue("segment_distance_mismatch", "warning", "Segment distance sum differs from activity distance beyond tolerance.", "distance_km", distance, round(segment_distance, 3), "km"))
        if duration and abs(segment_duration - duration) > max(10, duration * 0.01):
            checks.append(validation_issue("segment_duration_mismatch", "warning", "Segment duration sum differs from activity duration beyond tolerance.", "duration_seconds", duration, segment_duration, "seconds"))
        if len(segments) >= 2:
            last_segment = segments[-1]
            previous_paces = sorted(int(segment.pace_seconds_per_km) for segment in segments[:-1] if segment.pace_seconds_per_km)
            if previous_paces and last_segment.distance_km < 0.3:
                median_pace = previous_paces[len(previous_paces) // 2]
                if last_segment.pace_seconds_per_km and int(last_segment.pace_seconds_per_km) < median_pace * 0.85:
                    checks.append(validation_issue("short_fast_final_segment", "info", "Fastest pace may be inflated by a short final partial segment.", "pace_seconds_per_km", median_pace, int(last_segment.pace_seconds_per_km), "seconds_per_km"))

    workout_blocks = list(activity.workout_blocks or [])
    if workout_blocks:
        block_distance = sum(float(block.distance_km or 0) for block in workout_blocks)
        block_duration = sum(int(block.duration_seconds or 0) for block in workout_blocks)
        if distance and block_distance and abs(block_distance - distance) > max(0.08, distance * 0.02):
            checks.append(validation_issue("workout_block_distance_mismatch", "warning", "Workout block distance sum differs from activity distance.", "distance_km", distance, round(block_distance, 3), "km"))
        if duration and block_duration and abs(block_duration - duration) > max(15, duration * 0.02):
            checks.append(validation_issue("workout_block_duration_mismatch", "warning", "Workout block duration sum differs from activity duration.", "duration_seconds", duration, block_duration, "seconds"))

    issues = [check for check in checks if check["severity"] == "warning"]
    return {
        "activity_id": activity.id,
        "status": "warning" if issues else "ok",
        "weighted_pace_seconds_per_km": weighted_pace,
        "source_counts": {
            "segments": len(segments),
            "split_blocks": len(activity.split_blocks or []),
            "workout_blocks": len(workout_blocks),
            "derived_metrics": len(activity.derived_metrics or []),
            "screenshots": len(activity.screenshots or []),
        },
        "checks": checks,
        "issues": issues,
    }


def activity_query(activity_id: int, user: User):
    return (
        select(Activity)
        .where(Activity.id == activity_id, Activity.user_id == user.id)
        .options(
            selectinload(Activity.segments),
            selectinload(Activity.split_blocks),
            selectinload(Activity.workout_blocks),
            selectinload(Activity.derived_metrics),
            selectinload(Activity.screenshots).selectinload(ActivityScreenshot.source),
        )
    )


def load_activity_for_user(db: Session, user: User, activity_id: int) -> Activity:
    activity = db.scalar(activity_query(activity_id, user))
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")
    return activity


def validate_activity_summary(activity: Activity) -> None:
    distance = float(activity.distance_km or 0)
    duration = int(activity.duration_seconds or 0)
    if duration <= 0:
        raise HTTPException(status_code=400, detail="Activity duration must be positive")
    if distance <= 0:
        return
    expected_pace = round(duration / distance)
    if activity.average_pace_seconds_per_km is not None and abs(int(activity.average_pace_seconds_per_km) - expected_pace) > max(5, expected_pace * 0.02):
        raise HTTPException(status_code=400, detail="Average pace must match distance and duration within tolerance")
    expected_speed = round(distance * 3600 / duration, 2)
    if activity.average_speed_kmh is not None and abs(float(activity.average_speed_kmh) - expected_speed) > max(0.2, expected_speed * 0.02):
        raise HTTPException(status_code=400, detail="Average speed must match distance and duration within tolerance")


def normalize_activity_summary(activity: Activity, explicit_fields: set[str], recompute_summary: bool) -> None:
    distance = float(activity.distance_km or 0)
    duration = int(activity.duration_seconds or 0)
    if duration <= 0:
        raise HTTPException(status_code=400, detail="Activity duration must be positive")
    if distance <= 0:
        if recompute_summary and "average_pace_seconds_per_km" not in explicit_fields:
            activity.average_pace_seconds_per_km = None
        if recompute_summary and "average_speed_kmh" not in explicit_fields:
            activity.average_speed_kmh = None
        return
    if recompute_summary and "average_pace_seconds_per_km" not in explicit_fields:
        activity.average_pace_seconds_per_km = round(duration / distance)
    if recompute_summary and "average_speed_kmh" not in explicit_fields:
        activity.average_speed_kmh = round(distance * 3600 / duration, 2)
    if recompute_summary or explicit_fields:
        validate_activity_summary(activity)


def apply_activity_values(activity: Activity, values: dict[str, object], explicit_fields: set[str], recompute_summary: bool) -> None:
    if "duration_seconds" in values and values.get("duration_seconds") is None:
        raise HTTPException(status_code=400, detail="Activity duration must be positive")
    explicit_summary_fields = DERIVED_SUMMARY_FIELDS & explicit_fields
    for key in ACTIVITY_WRITE_FIELDS:
        if key in values:
            setattr(activity, key, values[key])
    activity.activity_type = activity.activity_type or "outdoor_run"
    activity.title = activity.title or "Manual activity"
    normalize_activity_summary(activity, explicit_summary_fields, recompute_summary)


def sync_activity_after_write(db: Session, user: User, activity: Activity, changed_dates: list) -> None:
    profile = db.scalar(select(AthleteProfile).where(AthleteProfile.user_id == user.id))
    sync_derived_activity_metrics(db, activity, profile)
    db.flush()
    changed = list(changed_dates)
    timezone = profile_timezone(db, user)
    next_date = activity_local_date(activity, timezone)
    if next_date is not None and next_date not in changed:
        changed.append(next_date)
    if changed:
        sync_daily_training_loads_for_dates(db, user, changed)


@router.post("", response_model=ActivityOut)
def create_activity(payload: ActivityCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    values = payload.model_dump()
    values["source_note"] = values.get("source_note") or "Manually entered in admin UI."
    activity = Activity(user_id=user.id)
    apply_activity_values(activity, values, set(payload.model_fields_set), recompute_summary=True)
    db.add(activity)
    db.flush()
    sync_activity_after_write(db, user, activity, [])
    db.commit()
    return activity


@router.get("", response_model=list[ActivityOut])
def list_activities(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list(db.scalars(
        select(Activity)
        .where(Activity.user_id == user.id)
        .options(
            selectinload(Activity.segments),
            selectinload(Activity.split_blocks),
            selectinload(Activity.workout_blocks),
            selectinload(Activity.derived_metrics),
            selectinload(Activity.screenshots).selectinload(ActivityScreenshot.source),
        )
        .order_by(Activity.started_at.desc().nullslast(), Activity.id.desc())
    ))


@router.get("/{activity_id}", response_model=ActivityOut)
def get_activity(activity_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return load_activity_for_user(db, user, activity_id)


@router.patch("/{activity_id}", response_model=ActivityOut)
def update_activity(activity_id: int, payload: ActivityUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    activity = load_activity_for_user(db, user, activity_id)
    timezone = profile_timezone(db, user)
    old_date = activity_local_date(activity, timezone)
    values = payload.model_dump(exclude_unset=True)
    if values:
        summary_changed = any(key in values and getattr(activity, key) != values[key] for key in ("distance_km", "duration_seconds"))
        apply_activity_values(activity, values, set(payload.model_fields_set), recompute_summary=summary_changed)
        db.flush()
        sync_activity_after_write(db, user, activity, [old_date] if old_date is not None else [])
    db.commit()
    return activity


@router.get("/{activity_id}/validation", response_model=ActivityValidationOut)
def get_activity_validation(activity_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    activity = db.scalar(
        select(Activity)
        .where(Activity.id == activity_id, Activity.user_id == user.id)
        .options(selectinload(Activity.segments), selectinload(Activity.split_blocks), selectinload(Activity.workout_blocks), selectinload(Activity.derived_metrics), selectinload(Activity.screenshots).selectinload(ActivityScreenshot.source))
    )
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")
    return activity_validation_report(activity)


@router.delete("/{activity_id}")
def delete_activity(activity_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    activity = load_activity_for_user(db, user, activity_id)
    timezone = profile_timezone(db, user)
    changed_date = activity_local_date(activity, timezone)
    db.delete(activity)
    db.flush()
    if changed_date is not None:
        sync_daily_training_loads_for_dates(db, user, [changed_date])
    db.commit()
    return {"deleted": True, "id": activity_id}
