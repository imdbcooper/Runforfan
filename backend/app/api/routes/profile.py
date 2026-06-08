from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import AthleteMeasurement, AthleteProfile, LactateThresholdMeasurement, User
from app.schemas.common import (
    AthleteMeasurementCreate,
    AthleteMeasurementTimelineOut,
    AthleteProfileOut,
    AthleteProfileUpdate,
    ProfileCompletenessOut,
    SafetyCheckOut,
)
from app.services.auth import get_current_user
from app.services.profile import get_or_create_profile, profile_completeness, profile_estimated_hrmax, safety_check
from app.services.zones import ZONE_INPUT_FIELDS, invalidate_calculated_zones


router = APIRouter(prefix="/profile", tags=["profile"])


def profile_out(profile: AthleteProfile) -> dict:
    return {
        "id": profile.id,
        "user_id": profile.user_id,
        "date_of_birth": profile.date_of_birth,
        "sex": profile.sex,
        "height_cm": profile.height_cm,
        "weight_kg": profile.weight_kg,
        "timezone": profile.timezone,
        "locale": profile.locale,
        "unit_system": profile.unit_system or "metric",
        "preferred_weekdays": profile.preferred_weekdays or [],
        "long_run_weekday": profile.long_run_weekday,
        "max_run_duration_minutes": profile.max_run_duration_minutes,
        "resting_heart_rate_bpm": profile.resting_heart_rate_bpm,
        "max_heart_rate_bpm": profile.max_heart_rate_bpm,
        "max_hr_source": profile.max_hr_source,
        "lactate_threshold_hr_bpm": profile.lactate_threshold_hr_bpm,
        "lactate_threshold_pace_seconds_per_km": profile.lactate_threshold_pace_seconds_per_km,
        "vo2max": profile.vo2max,
        "conservative_mode": profile.conservative_mode,
        "injury_notes": profile.injury_notes,
        "health_conditions": profile.health_conditions,
        "recovery_status": profile.recovery_status or "normal",
        "estimated_max_heart_rate": profile_estimated_hrmax(profile),
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
    }


@router.get("", response_model=AthleteProfileOut)
def get_profile(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return profile_out(get_or_create_profile(db, user, commit=True))


@router.put("", response_model=AthleteProfileOut)
def update_profile(payload: AthleteProfileUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = get_or_create_profile(db, user)
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(profile, key, value)
    if ZONE_INPUT_FIELDS.intersection(updates):
        invalidate_calculated_zones(db, user.id)
    db.commit()
    db.refresh(profile)
    return profile_out(profile)


@router.get("/completeness", response_model=ProfileCompletenessOut)
def get_profile_completeness(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return profile_completeness(get_or_create_profile(db, user, commit=True))


@router.post("/safety-check", response_model=SafetyCheckOut)
def run_safety_check(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return safety_check(get_or_create_profile(db, user, commit=True))


@router.get("/measurements", response_model=list[AthleteMeasurementTimelineOut])
def list_measurements(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=10000),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    window = limit + offset
    manual_measurements = list(db.scalars(
        select(AthleteMeasurement)
        .where(AthleteMeasurement.user_id == user.id)
        .order_by(AthleteMeasurement.measured_at.desc().nullslast(), AthleteMeasurement.created_at.desc())
        .limit(window)
    ))
    legacy_thresholds = list(db.scalars(
        select(LactateThresholdMeasurement)
        .where(LactateThresholdMeasurement.user_id == user.id)
        .order_by(LactateThresholdMeasurement.measured_at.desc().nullslast(), LactateThresholdMeasurement.created_at.desc())
        .limit(window)
    ))
    timeline = [measurement_to_timeline(item) for item in manual_measurements]
    timeline.extend(threshold_to_timeline(item) for item in legacy_thresholds)
    timeline.sort(key=lambda item: item["measured_at"] or item["created_at"], reverse=True)
    return timeline[offset:offset + limit]


@router.post("/measurements", response_model=AthleteMeasurementTimelineOut)
def create_measurement(payload: AthleteMeasurementCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    measurement = AthleteMeasurement(
        user_id=user.id,
        measurement_type=payload.measurement_type,
        measured_at=payload.measured_at or datetime.now(UTC),
        value_numeric=payload.value_numeric,
        value_json=payload.value_json,
        source=payload.source,
        confidence=payload.confidence,
        notes=payload.notes,
    )
    db.add(measurement)
    profile = get_or_create_profile(db, user)
    if apply_measurement_to_profile(profile, payload):
        invalidate_calculated_zones(db, user.id)
    db.commit()
    db.refresh(measurement)
    return measurement_to_timeline(measurement)


def measurement_to_timeline(measurement: AthleteMeasurement) -> dict:
    return {
        "id": measurement.id,
        "user_id": measurement.user_id,
        "source_model": "athlete_measurement",
        "measurement_type": measurement.measurement_type,
        "measured_at": measurement.measured_at,
        "value_numeric": measurement.value_numeric,
        "value_json": measurement.value_json,
        "source": measurement.source,
        "confidence": measurement.confidence,
        "notes": measurement.notes,
        "created_at": measurement.created_at,
        "updated_at": measurement.updated_at,
    }


def threshold_to_timeline(threshold: LactateThresholdMeasurement) -> dict:
    return {
        "id": threshold.id,
        "user_id": threshold.user_id,
        "source_model": "lactate_threshold_measurement",
        "measurement_type": "lactate_threshold",
        "measured_at": threshold.measured_at,
        "value_numeric": threshold.threshold_heart_rate_bpm,
        "value_json": {
            "threshold_heart_rate_bpm": threshold.threshold_heart_rate_bpm,
            "threshold_pace_seconds_per_km": threshold.threshold_pace_seconds_per_km,
            "average_pace_seconds_per_km": threshold.average_pace_seconds_per_km,
            "average_heart_rate_bpm": threshold.average_heart_rate_bpm,
            "source_id": threshold.source_id,
        },
        "source": "screenshot" if threshold.source_id else "manual",
        "confidence": 1,
        "notes": threshold.notes,
        "created_at": threshold.created_at,
        "updated_at": threshold.updated_at,
    }


def apply_measurement_to_profile(profile: AthleteProfile, payload: AthleteMeasurementCreate) -> bool:
    value = payload.value_numeric
    data = payload.value_json or {}
    if payload.measurement_type == "weight" and value is not None:
        profile.weight_kg = value
        return False
    elif payload.measurement_type == "resting_hr" and value is not None:
        profile.resting_heart_rate_bpm = round(value)
        return True
    elif payload.measurement_type == "max_hr" and value is not None:
        profile.max_heart_rate_bpm = round(value)
        profile.max_hr_source = "manual" if payload.source == "manual" else "measured"
        return True
    elif payload.measurement_type == "lactate_threshold":
        threshold_hr = data.get("threshold_heart_rate_bpm") or data.get("lactate_threshold_hr_bpm") or value
        threshold_pace = data.get("threshold_pace_seconds_per_km") or data.get("lactate_threshold_pace_seconds_per_km")
        if threshold_hr:
            profile.lactate_threshold_hr_bpm = round(float(threshold_hr))
        if threshold_pace:
            profile.lactate_threshold_pace_seconds_per_km = round(float(threshold_pace))
        return bool(threshold_hr or threshold_pace)
    elif payload.measurement_type == "vo2max" and value is not None:
        profile.vo2max = float(value)
        return False
    return False
