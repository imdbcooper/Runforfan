from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AthleteProfile, User
from app.services.calculations import age_from_birthdate, estimate_hrmax_tanaka


def get_or_create_profile(db: Session, user: User, commit: bool = False) -> AthleteProfile:
    profile = db.scalar(select(AthleteProfile).where(AthleteProfile.user_id == user.id))
    if profile:
        return profile
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    profile = db.scalar(select(AthleteProfile).where(AthleteProfile.user_id == user.id))
    if profile:
        return profile
    profile = AthleteProfile(user_id=user.id, sex="unspecified", timezone="Europe/Moscow", locale="ru-RU", unit_system="metric", recovery_status="normal")
    db.add(profile)
    db.flush()
    if commit:
        db.commit()
    db.refresh(profile)
    return profile


def profile_estimated_hrmax(profile: AthleteProfile) -> dict | None:
    if profile.max_heart_rate_bpm or not profile.date_of_birth:
        return None
    age = age_from_birthdate(profile.date_of_birth, date.today())
    return estimate_hrmax_tanaka(age).as_dict()


def profile_field_missing(value) -> bool:
    return value is None or value == "" or value == []


def profile_completeness(profile: AthleteProfile) -> dict:
    fields = {
        "date_of_birth": profile.date_of_birth,
        "resting_heart_rate_bpm": profile.resting_heart_rate_bpm,
        "max_heart_rate_bpm_or_birthdate": profile.max_heart_rate_bpm or profile.date_of_birth,
        "lactate_threshold_pace_seconds_per_km": profile.lactate_threshold_pace_seconds_per_km,
        "lactate_threshold_hr_bpm": profile.lactate_threshold_hr_bpm,
        "weight_kg": profile.weight_kg,
        "height_cm": profile.height_cm,
        "preferred_weekdays": profile.preferred_weekdays,
        "max_run_duration_minutes": profile.max_run_duration_minutes,
    }
    missing = [key for key, value in fields.items() if profile_field_missing(value)]
    available = len(fields) - len(missing)
    score = round(available / len(fields), 2)
    can_calculate_hr_zones = bool(profile.max_heart_rate_bpm or profile.date_of_birth)
    can_calculate_hrr_zones = bool(profile.resting_heart_rate_bpm and (profile.max_heart_rate_bpm or profile.date_of_birth))
    can_calculate_pace_zones = bool(profile.lactate_threshold_pace_seconds_per_km)
    confidence = "high" if score >= 0.8 else "medium" if score >= 0.5 else "low"
    return {
        "score": score,
        "missing": missing,
        "can_calculate_hr_zones": can_calculate_hr_zones,
        "can_calculate_hrr_zones": can_calculate_hrr_zones,
        "can_calculate_pace_zones": can_calculate_pace_zones,
        "confidence": confidence,
    }


def safety_check(profile: AthleteProfile) -> dict:
    warnings = []
    if profile.injury_notes:
        warnings.append("Указаны травмы или ограничения: планировщик должен использовать conservative mode.")
    if profile.health_conditions:
        warnings.append("Указаны медицинские состояния: планировщик должен быть консервативным, а спорные нагрузки требуют консультации специалиста.")
    if profile.recovery_status in {"tired", "strained", "injured"}:
        warnings.append(f"Recovery status: {profile.recovery_status}. Интенсивность и длительность нужно снизить до восстановления.")
    if not (profile.max_heart_rate_bpm or profile.date_of_birth):
        warnings.append("Нет HRmax или даты рождения: пульсовые зоны будут недоступны или низкой точности.")
    if not profile.lactate_threshold_pace_seconds_per_km:
        warnings.append("Нет порогового темпа: pace-зоны будут недоступны.")
    return {
        "conservative_mode": bool(profile.conservative_mode or profile.injury_notes or profile.health_conditions or profile.recovery_status in {"tired", "strained", "injured"}),
        "warnings": warnings,
        "message": "Runforfan не является медицинским устройством; при боли, головокружении или ухудшении самочувствия нужно прекратить тренировку и обратиться к специалисту.",
    }
