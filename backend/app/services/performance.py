from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Activity, AthleteProfile, PerformanceResult, User
from app.services.analytics import period_bounds, profile_timezone
from app.services.calculations import (
    CalculationResult,
    calculate_threshold_pace_zones,
    calculate_vdot,
    predict_riegel_time,
)


PB_TARGETS: tuple[tuple[float, str], ...] = (
    (1.0, "1K"),
    (5.0, "5K"),
    (10.0, "10K"),
    (21.1, "Half marathon"),
    (42.2, "Marathon"),
)
OLD_SOURCE_DAYS = 84
CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}


def result_date_utc(result: PerformanceResult) -> datetime:
    value = result.result_date
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def result_pace_seconds(result: PerformanceResult) -> int:
    return round(result.duration_seconds / result.distance_km)


def result_age_days(result: PerformanceResult, today: date | None = None) -> int | None:
    current = today or datetime.now(UTC).date()
    return max((current - result_date_utc(result).date()).days, 0)


def noisy_reasons(result: PerformanceResult) -> list[str]:
    reasons: list[str] = []
    if result.is_noisy:
        reasons.append("manual noisy flag")
    if result.terrain == "trail":
        reasons.append("trail terrain")
    if result.temperature_c is not None and result.temperature_c >= 27:
        reasons.append("hot conditions")
    if result.elevation_gain_m is not None:
        gain_per_km = result.elevation_gain_m / max(result.distance_km, 0.1)
        if result.elevation_gain_m >= 300 or gain_per_km >= 20:
            reasons.append("large elevation gain")
    return reasons


def result_is_noisy(result: PerformanceResult) -> bool:
    return bool(noisy_reasons(result))


def degrade_confidence(confidence: str) -> str:
    if confidence == "high":
        return "medium"
    if confidence == "medium":
        return "low"
    return "low"


def vdot_confidence(result: PerformanceResult, today: date | None = None) -> str:
    confidence = "high" if result.result_type == "race" else "medium"
    if result_is_noisy(result):
        confidence = degrade_confidence(confidence)
    age = result_age_days(result, today)
    if age is not None and age > OLD_SOURCE_DAYS:
        confidence = degrade_confidence(confidence)
    return confidence


def calculation_with_confidence(calculation: CalculationResult | dict[str, object] | None, confidence: str) -> dict[str, object] | None:
    if calculation is None:
        return None
    data = calculation.as_dict() if isinstance(calculation, CalculationResult) else dict(calculation)
    if data.get("value") is None:
        return None
    data["confidence"] = confidence
    return data


def estimated_vdot_for_result(result: PerformanceResult, today: date | None = None) -> dict[str, object] | None:
    return calculation_with_confidence(calculate_vdot(result.distance_km, result.duration_seconds), vdot_confidence(result, today))


def performance_result_to_dict(result: PerformanceResult, today: date | None = None) -> dict[str, object]:
    return {
        "id": result.id,
        "user_id": result.user_id,
        "activity_id": result.activity_id,
        "result_type": result.result_type,
        "name": result.name,
        "result_date": result.result_date,
        "distance_km": result.distance_km,
        "duration_seconds": result.duration_seconds,
        "pace_seconds_per_km": result_pace_seconds(result),
        "source": result.source,
        "terrain": result.terrain,
        "weather": result.weather,
        "elevation_gain_m": result.elevation_gain_m,
        "temperature_c": result.temperature_c,
        "is_noisy": result_is_noisy(result),
        "noisy_reasons": noisy_reasons(result),
        "age_days": result_age_days(result, today),
        "estimated_vdot": estimated_vdot_for_result(result, today),
        "notes": result.notes,
        "created_at": result.created_at,
        "updated_at": result.updated_at,
    }


def list_performance_results(db: Session, user: User, from_date: date | None = None, to_date: date | None = None) -> list[dict[str, object]]:
    timezone = profile_timezone(db, user)
    query = select(PerformanceResult).where(PerformanceResult.user_id == user.id).order_by(PerformanceResult.result_date.desc(), PerformanceResult.id.desc())
    start, end = period_bounds(from_date, to_date, timezone)
    if start:
        query = query.where(PerformanceResult.result_date >= start)
    if end:
        query = query.where(PerformanceResult.result_date < end)
    return [performance_result_to_dict(result) for result in db.scalars(query)]


def create_performance_result(db: Session, user: User, payload) -> dict[str, object]:
    if payload.activity_id is not None:
        activity = db.scalar(select(Activity).where(Activity.id == payload.activity_id, Activity.user_id == user.id))
        if activity is None:
            raise ValueError("Activity not found")
    result = PerformanceResult(
        user_id=user.id,
        activity_id=payload.activity_id,
        result_type=payload.result_type,
        name=payload.name,
        result_date=payload.result_date or datetime.now(UTC),
        distance_km=payload.distance_km,
        duration_seconds=payload.duration_seconds,
        source=payload.source,
        terrain=payload.terrain,
        weather=payload.weather,
        elevation_gain_m=payload.elevation_gain_m,
        temperature_c=payload.temperature_c,
        is_noisy=payload.is_noisy,
        notes=payload.notes,
    )
    db.add(result)
    db.commit()
    db.refresh(result)
    return performance_result_to_dict(result)


def load_results(db: Session, user: User) -> list[PerformanceResult]:
    return list(db.scalars(
        select(PerformanceResult)
        .where(PerformanceResult.user_id == user.id)
        .order_by(PerformanceResult.result_date.desc(), PerformanceResult.id.desc())
    ))


def select_vdot_source(results: list[PerformanceResult], today: date | None = None) -> PerformanceResult | None:
    eligible = [result for result in results if result.distance_km >= 3 and result.duration_seconds > 0 and result.result_type in {"race", "time_trial"}]
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda result: (
            CONFIDENCE_RANK.get(vdot_confidence(result, today), 0),
            result_date_utc(result),
            float(estimated_vdot_for_result(result, today)["value"] or 0),
        ),
    )


def estimate_threshold_pace_from_result(result: PerformanceResult) -> tuple[int | None, str]:
    if result.distance_km <= 0 or result.duration_seconds <= 0:
        return None, "low"
    threshold_distance_km = result.distance_km * (3600 / result.duration_seconds) ** (1 / 1.06)
    if threshold_distance_km <= 0:
        return None, "low"
    confidence = "high" if 1200 <= result.duration_seconds <= 5400 else "medium"
    if result.distance_km < 3 or result_is_noisy(result):
        confidence = degrade_confidence(confidence)
    return round(3600 / threshold_distance_km), confidence


def threshold_trend(results: list[PerformanceResult]) -> list[dict[str, object]]:
    points: list[dict[str, object]] = []
    for result in sorted(results, key=lambda item: result_date_utc(item)):
        pace, confidence = estimate_threshold_pace_from_result(result)
        if pace is None:
            continue
        points.append({
            "result_id": result.id,
            "result_date": result.result_date,
            "distance_km": result.distance_km,
            "duration_seconds": result.duration_seconds,
            "threshold_pace_seconds_per_km": pace,
            "source": result.name,
            "confidence": confidence,
        })
    return points[-10:]


def pace_zones_from_profile_or_results(db: Session, user: User, results: list[PerformanceResult], selected: PerformanceResult | None) -> list[dict[str, object]]:
    profile = db.scalar(select(AthleteProfile).where(AthleteProfile.user_id == user.id))
    if profile and profile.lactate_threshold_pace_seconds_per_km:
        return calculate_threshold_pace_zones(profile.lactate_threshold_pace_seconds_per_km)
    source = selected
    if source is None and results:
        source = max(results, key=lambda result: result_date_utc(result))
    if source is None:
        return []
    threshold_pace, confidence = estimate_threshold_pace_from_result(source)
    if threshold_pace is None:
        return []
    zones = calculate_threshold_pace_zones(threshold_pace)
    return [{**zone, "method": "vdot_threshold_estimate", "confidence": confidence} for zone in zones]


def performance_vdot(db: Session, user: User) -> dict[str, object]:
    results = load_results(db, user)
    selected = select_vdot_source(results)
    warnings: list[str] = []
    estimate = estimated_vdot_for_result(selected) if selected else None
    confidence = str(estimate["confidence"]) if estimate else "low"
    if selected:
        age = result_age_days(selected)
        if age is not None and age > OLD_SOURCE_DAYS:
            warnings.append("Source result is older than 12 weeks; confidence downgraded.")
        reasons = noisy_reasons(selected)
        if reasons:
            warnings.append(f"Source marked noisy: {', '.join(reasons)}.")
    else:
        warnings.append("Add a race or time trial result of at least 3 km to estimate VDOT.")
    return {
        "estimate": estimate,
        "source": performance_result_to_dict(selected) if selected else None,
        "confidence": confidence,
        "warnings": warnings,
        "threshold_trend": threshold_trend(results),
        "pace_zones": pace_zones_from_profile_or_results(db, user, results, selected),
    }


def combine_confidence(*values: str) -> str:
    if not values:
        return "low"
    rank = min(CONFIDENCE_RANK.get(value, 0) for value in values)
    return {value: key for key, value in CONFIDENCE_RANK.items()}.get(rank, "low")


def performance_predictions(db: Session, user: User) -> list[dict[str, object]]:
    source = select_vdot_source(load_results(db, user))
    if source is None:
        return []
    source_confidence = vdot_confidence(source)
    source_noisy = result_is_noisy(source)
    predictions: list[dict[str, object]] = []
    age = result_age_days(source)
    for target_distance, label in PB_TARGETS:
        calculation = predict_riegel_time(source.distance_km, source.duration_seconds, target_distance)
        ratio = target_distance / source.distance_km if source.distance_km else None
        limited = bool(ratio is not None and not 0.25 <= ratio <= 4)
        confidence = combine_confidence(str(calculation.confidence), source_confidence)
        warnings: list[str] = []
        if limited:
            warnings.append("Outside recommended Riegel extrapolation range.")
            confidence = degrade_confidence(confidence)
        if age is not None and age > OLD_SOURCE_DAYS:
            warnings.append("Source result is older than 12 weeks.")
        reasons = noisy_reasons(source)
        if reasons:
            warnings.append(f"Noisy source: {', '.join(reasons)}.")
        seconds = int(calculation.value) if calculation.value is not None else None
        predictions.append({
            "target_distance_km": target_distance,
            "label": label,
            "predicted_duration_seconds": seconds,
            "predicted_pace_seconds_per_km": round(seconds / target_distance) if seconds else None,
            "source_result_id": source.id,
            "source_result_name": source.name,
            "source_distance_km": source.distance_km,
            "source_duration_seconds": source.duration_seconds,
            "method": calculation.method,
            "confidence": confidence,
            "extrapolation_ratio": round(ratio, 2) if ratio is not None else None,
            "extrapolation_limited": limited,
            "noisy": source_noisy,
            "warnings": warnings,
            "source_reference": calculation.source_reference,
        })
    return predictions


def normalized_duration(result: PerformanceResult, target_distance_km: float) -> int:
    return round(result.duration_seconds / result.distance_km * target_distance_km)


def performance_pbs(db: Session, user: User) -> list[dict[str, object]]:
    results = load_results(db, user)
    pbs: list[dict[str, object]] = []
    for target_distance, label in PB_TARGETS:
        candidates = [
            result for result in results
            if result.result_type in {"race", "time_trial"} and target_distance * 0.95 <= result.distance_km <= target_distance * 1.05
        ]
        if not candidates:
            continue
        best = min(candidates, key=lambda result: normalized_duration(result, target_distance))
        best_duration = normalized_duration(best, target_distance)
        pbs.append({
            "target_distance_km": target_distance,
            "label": label,
            "result_id": best.id,
            "name": best.name,
            "result_type": best.result_type,
            "result_date": best.result_date,
            "distance_km": best.distance_km,
            "duration_seconds": best.duration_seconds,
            "normalized_duration_seconds": best_duration,
            "pace_seconds_per_km": round(best_duration / target_distance),
            "estimated_vdot": estimated_vdot_for_result(best),
            "is_noisy": result_is_noisy(best),
            "noisy_reasons": noisy_reasons(best),
        })
    return pbs
