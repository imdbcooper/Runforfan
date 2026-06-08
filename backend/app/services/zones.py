from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import AthleteProfile, TrainingZone, User
from app.services.calculations import (
    age_from_birthdate,
    calculate_hrmax_zones,
    calculate_hrr_zones,
    calculate_rpe_zones,
    calculate_threshold_hr_zones,
    calculate_threshold_pace_zones,
    estimate_hrmax_tanaka,
)
from app.services.performance import estimate_threshold_pace_from_result, load_results, select_vdot_source
from app.services.profile import get_or_create_profile


ZONE_INPUT_FIELDS = {
    "date_of_birth",
    "resting_heart_rate_bpm",
    "max_heart_rate_bpm",
    "max_hr_source",
    "lactate_threshold_hr_bpm",
    "lactate_threshold_pace_seconds_per_km",
}


def _effective_max_hr(profile: AthleteProfile) -> tuple[int | None, str]:
    if profile.max_heart_rate_bpm:
        return profile.max_heart_rate_bpm, profile.max_hr_source or "manual"
    if profile.date_of_birth:
        age = age_from_birthdate(profile.date_of_birth, date.today())
        estimate = estimate_hrmax_tanaka(age)
        return int(estimate.value or 0), "tanaka_estimated"
    return None, "missing"


def calculated_zones(profile: AthleteProfile, vdot_threshold_pace: int | None = None, vdot_confidence: str = "low") -> list[dict[str, object]]:
    zones: list[dict[str, object]] = []
    max_hr, max_hr_source = _effective_max_hr(profile)
    if profile.lactate_threshold_hr_bpm:
        zones.extend(calculate_threshold_hr_zones(profile.lactate_threshold_hr_bpm))
    elif max_hr and profile.resting_heart_rate_bpm:
        hrr_confidence = "low" if max_hr_source == "tanaka_estimated" else "medium"
        zones.extend(calculate_hrr_zones(profile.resting_heart_rate_bpm, max_hr, confidence=hrr_confidence))
    elif max_hr:
        hrmax_zones = calculate_hrmax_zones(max_hr)
        if max_hr_source == "manual":
            for zone in hrmax_zones:
                zone["confidence"] = "medium"
        zones.extend(hrmax_zones)
    if profile.lactate_threshold_pace_seconds_per_km:
        zones.extend(calculate_threshold_pace_zones(profile.lactate_threshold_pace_seconds_per_km))
    elif vdot_threshold_pace:
        zones.extend({**zone, "method": "vdot_threshold_estimate", "confidence": vdot_confidence} for zone in calculate_threshold_pace_zones(vdot_threshold_pace))
    zones.extend(calculate_rpe_zones())
    return zones


def vdot_threshold_pace(db: Session, user: User) -> tuple[int | None, str]:
    source = select_vdot_source(load_results(db, user))
    if source is None:
        return None, "low"
    return estimate_threshold_pace_from_result(source)


def zone_to_dict(zone: TrainingZone) -> dict[str, object]:
    return {
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


def zones_response(db: Session, user: User) -> dict:
    profile = get_or_create_profile(db, user, commit=True)
    pace, pace_confidence = vdot_threshold_pace(db, user)
    stored = list(db.scalars(select(TrainingZone).where(TrainingZone.user_id == user.id, TrainingZone.is_active.is_(True))))
    stored_dicts = [zone_to_dict(zone) for zone in stored]
    manual_types = {zone.zone_type for zone in stored if zone.method == "manual"}
    stored_signatures = {(zone.zone_type, zone.method, zone.zone_key) for zone in stored}
    calculated = [
        zone for zone in calculated_zones(profile, pace, pace_confidence)
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


def zone_type_for_unit(unit: str) -> str:
    if unit == "bpm":
        return "hr"
    if unit == "seconds_per_km":
        return "pace"
    if unit == "rpe":
        return "rpe"
    return "custom"


def invalidate_calculated_zones(db: Session, user_id: int, zone_types: set[str] | None = None) -> None:
    statement = delete(TrainingZone).where(TrainingZone.user_id == user_id, TrainingZone.method != "manual")
    if zone_types:
        statement = statement.where(TrainingZone.zone_type.in_(zone_types))
    db.execute(statement)


def recalculate_and_store_zones(db: Session, user: User) -> dict:
    profile = get_or_create_profile(db, user)
    pace, pace_confidence = vdot_threshold_pace(db, user)
    manual_zone_types = set(db.scalars(
        select(TrainingZone.zone_type)
        .where(TrainingZone.user_id == user.id, TrainingZone.method == "manual", TrainingZone.is_active.is_(True))
    ).all())
    db.execute(delete(TrainingZone).where(TrainingZone.user_id == user.id, TrainingZone.method != "manual"))
    for zone in calculated_zones(profile, pace, pace_confidence):
        zone_type = zone_type_for_unit(str(zone["unit"]))
        if zone_type in manual_zone_types:
            continue
        db.add(TrainingZone(
            user_id=user.id,
            zone_type=zone_type,
            method=str(zone["method"]),
            zone_key=str(zone["zone_key"]),
            label=str(zone.get("label") or zone["zone_key"]),
            lower_value=zone.get("lower_value"),
            upper_value=zone.get("upper_value"),
            unit=str(zone["unit"]),
            confidence=str(zone["confidence"]),
            source_reference=str(zone["source_reference"]),
        ))
    db.commit()
    return zones_response(db, user)


def replace_manual_zones(db: Session, user: User, zone_type: str, zones: list[dict]) -> dict:
    db.execute(delete(TrainingZone).where(TrainingZone.user_id == user.id, TrainingZone.zone_type == zone_type, TrainingZone.method == "manual"))
    for zone in zones:
        db.add(TrainingZone(
            user_id=user.id,
            zone_type=zone_type,
            method="manual",
            zone_key=zone["zone_key"],
            label=zone.get("label") or zone["zone_key"],
            lower_value=zone.get("lower_value"),
            upper_value=zone.get("upper_value"),
            unit=zone["unit"],
            confidence="high",
            source_reference="manual user override",
        ))
    db.commit()
    return zones_response(db, user)
