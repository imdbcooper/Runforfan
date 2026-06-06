from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import exp
from statistics import mean, pstdev


TANAKA_REF = "Tanaka, Monahan, Seals 2001, PMID 11153730"
KARVONEN_REF = "Karvonen et al. 1957 heart-rate reserve method"
ACSM_REF = "ACSM Position Stand 2011, PMID 21694556"
DANIELS_REF = "Daniels/Gilbert oxygen power VDOT model"
RIEGEL_REF = "Riegel 1981 race prediction power law"
FOSTER_REF = "Foster et al. 2001 session RPE, PMID 11708692"
BANISTER_REF = "Banister impulse-response fitness/fatigue model"


@dataclass(frozen=True)
class CalculationResult:
    value: float | int | None
    unit: str
    method: str
    confidence: str
    source_reference: str

    def as_dict(self) -> dict[str, float | int | str | None]:
        return {
            "value": self.value,
            "unit": self.unit,
            "method": self.method,
            "confidence": self.confidence,
            "source_reference": self.source_reference,
        }


def age_from_birthdate(date_of_birth: date, today: date | None = None) -> int:
    current = today or date.today()
    years = current.year - date_of_birth.year
    if (current.month, current.day) < (date_of_birth.month, date_of_birth.day):
        years -= 1
    return max(0, years)


def calculate_pace_seconds_per_km(duration_seconds: int | float, distance_km: int | float) -> CalculationResult:
    if not distance_km or distance_km <= 0:
        return CalculationResult(None, "seconds_per_km", "duration_distance", "low", ACSM_REF)
    return CalculationResult(round(duration_seconds / distance_km), "seconds_per_km", "duration_distance", "high", ACSM_REF)


def calculate_speed_kmh(distance_km: int | float, duration_seconds: int | float) -> CalculationResult:
    if not duration_seconds or duration_seconds <= 0:
        return CalculationResult(None, "kmh", "distance_duration", "low", ACSM_REF)
    return CalculationResult(round(distance_km / (duration_seconds / 3600), 2), "kmh", "distance_duration", "high", ACSM_REF)


def calculate_weighted_average_pace(items: list[tuple[float, int]]) -> CalculationResult:
    distance = sum(item[0] for item in items if item[0] and item[1])
    duration = sum(item[1] for item in items if item[0] and item[1])
    return calculate_pace_seconds_per_km(duration, distance)


def estimate_hrmax_tanaka(age: int) -> CalculationResult:
    return CalculationResult(round(208 - 0.7 * age), "bpm", "tanaka", "low", TANAKA_REF)


def calculate_hrr_zones(resting_hr: int, max_hr: int) -> list[dict[str, object]]:
    hrr = max_hr - resting_hr
    ranges = [
        ("z1", 0.30, 0.39, "Recovery"),
        ("z2", 0.40, 0.59, "Aerobic"),
        ("z3", 0.60, 0.74, "Steady"),
        ("z4", 0.75, 0.84, "Threshold"),
        ("z5", 0.85, 0.95, "Very hard"),
    ]
    return [
        {
            "zone_key": key,
            "label": label,
            "lower_value": round(resting_hr + low * hrr),
            "upper_value": round(resting_hr + high * hrr),
            "unit": "bpm",
            "method": "hrr",
            "confidence": "medium",
            "source_reference": KARVONEN_REF,
        }
        for key, low, high, label in ranges
    ]


def calculate_hrmax_zones(max_hr: int) -> list[dict[str, object]]:
    ranges = [
        ("z1", 0.60, 0.69, "Easy"),
        ("z2", 0.70, 0.79, "Aerobic"),
        ("z3", 0.80, 0.87, "Steady"),
        ("z4", 0.88, 0.92, "Threshold"),
        ("z5", 0.93, 1.00, "Hard"),
    ]
    return [
        {
            "zone_key": key,
            "label": label,
            "lower_value": round(low * max_hr),
            "upper_value": round(high * max_hr),
            "unit": "bpm",
            "method": "hrmax",
            "confidence": "low",
            "source_reference": ACSM_REF,
        }
        for key, low, high, label in ranges
    ]


def calculate_threshold_pace_zones(threshold_pace_seconds_per_km: int) -> list[dict[str, object]]:
    ranges = [
        ("easy", threshold_pace_seconds_per_km + 45, threshold_pace_seconds_per_km + 95, "Easy"),
        ("steady", threshold_pace_seconds_per_km + 20, threshold_pace_seconds_per_km + 44, "Steady"),
        ("threshold", threshold_pace_seconds_per_km - 5, threshold_pace_seconds_per_km + 10, "Threshold"),
        ("interval", threshold_pace_seconds_per_km - 35, threshold_pace_seconds_per_km - 6, "Interval"),
        ("rep", threshold_pace_seconds_per_km - 60, threshold_pace_seconds_per_km - 36, "Repetition"),
    ]
    return [
        {
            "zone_key": key,
            "label": label,
            "lower_value": lower,
            "upper_value": upper,
            "unit": "seconds_per_km",
            "method": "threshold_pace",
            "confidence": "medium",
            "source_reference": DANIELS_REF,
        }
        for key, lower, upper, label in ranges
    ]


def calculate_vdot(distance_km: float, duration_seconds: int) -> CalculationResult:
    if not distance_km or not duration_seconds:
        return CalculationResult(None, "vdot", "daniels_gilbert", "low", DANIELS_REF)
    time_min = duration_seconds / 60
    velocity_m_min = distance_km * 1000 / time_min
    vo2 = -4.60 + 0.182258 * velocity_m_min + 0.000104 * velocity_m_min**2
    percent_vo2max = 0.8 + 0.1894393 * exp(-0.012778 * time_min) + 0.2989558 * exp(-0.1932605 * time_min)
    return CalculationResult(round(vo2 / percent_vo2max, 1), "vdot", "daniels_gilbert", "medium", DANIELS_REF)


def predict_riegel_time(source_distance_km: float, source_time_seconds: int, target_distance_km: float, exponent: float = 1.06) -> CalculationResult:
    if not source_distance_km or not source_time_seconds or not target_distance_km:
        return CalculationResult(None, "seconds", "riegel", "low", RIEGEL_REF)
    predicted = source_time_seconds * (target_distance_km / source_distance_km) ** exponent
    confidence = "medium" if 0.25 <= target_distance_km / source_distance_km <= 4 else "low"
    return CalculationResult(round(predicted), "seconds", "riegel", confidence, RIEGEL_REF)


def calculate_srpe_load(duration_minutes: float, rpe_0_10: float) -> CalculationResult:
    return CalculationResult(round(duration_minutes * rpe_0_10, 1), "au", "session_rpe", "medium", FOSTER_REF)


def ewma_load(previous: float, load_today: float, tau_days: int) -> float:
    alpha = 1 - exp(-1 / tau_days)
    return previous + alpha * (load_today - previous)


def calculate_ctl_atl_tsb(loads: list[float], initial_ctl: float = 0, initial_atl: float = 0) -> dict[str, CalculationResult]:
    ctl = initial_ctl
    atl = initial_atl
    for load in loads:
        ctl = ewma_load(ctl, load, 42)
        atl = ewma_load(atl, load, 7)
    return {
        "ctl": CalculationResult(round(ctl, 1), "au", "ewma_42d", "low", BANISTER_REF),
        "atl": CalculationResult(round(atl, 1), "au", "ewma_7d", "low", BANISTER_REF),
        "tsb": CalculationResult(round(ctl - atl, 1), "au", "ctl_minus_atl", "low", BANISTER_REF),
    }


def calculate_monotony_strain(daily_loads: list[float]) -> dict[str, CalculationResult]:
    if len(daily_loads) < 2:
        return {
            "monotony": CalculationResult(None, "ratio", "mean_sd", "low", FOSTER_REF),
            "strain": CalculationResult(None, "au", "weekly_load_monotony", "low", FOSTER_REF),
        }
    avg = mean(daily_loads)
    sd = pstdev(daily_loads)
    if sd == 0:
        return {
            "monotony": CalculationResult(None, "ratio", "mean_sd", "low", FOSTER_REF),
            "strain": CalculationResult(None, "au", "weekly_load_monotony", "low", FOSTER_REF),
        }
    monotony = avg / sd
    return {
        "monotony": CalculationResult(round(monotony, 2), "ratio", "mean_sd", "medium", FOSTER_REF),
        "strain": CalculationResult(round(sum(daily_loads) * monotony, 1), "au", "weekly_load_monotony", "medium", FOSTER_REF),
    }
