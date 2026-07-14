from datetime import UTC, date, datetime, timedelta
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RecoverySignalObservation, User


NORMALIZATION_VERSION = "recovery-signals-v1"
RECOVERY_RULE_VERSION = "recovery-rules-v1"
METRICS = {
    "sleep_duration_seconds": {"unit": "seconds", "minimum": 0, "maximum": 86400, "direction": "lower", "relative_threshold": 0.2},
    "sleep_efficiency_pct": {"unit": "percent", "minimum": 0, "maximum": 100, "direction": "lower", "absolute_threshold": 10},
    "hrv_rmssd_ms": {"unit": "ms", "minimum": 1, "maximum": 300, "direction": "lower", "relative_threshold": 0.2},
    "resting_heart_rate_bpm": {"unit": "bpm", "minimum": 20, "maximum": 250, "direction": "higher", "absolute_threshold": 8},
}


def utc_value(value: datetime | str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).astimezone(UTC)


def validate_metric(metric_key: str, unit: str, value: float) -> None:
    metric = METRICS[metric_key]
    if unit != metric["unit"]:
        raise ValueError(f"{metric_key} requires canonical unit {metric['unit']}")
    if not float(metric["minimum"]) <= value <= float(metric["maximum"]):
        raise ValueError(f"{metric_key} is outside the accepted physiological range")


def observation_input(item: RecoverySignalObservation) -> dict[str, object]:
    return {
        "id": item.id,
        "metric_key": item.metric_key,
        "value": item.value_numeric,
        "unit": item.unit,
        "observed_at": item.observed_at,
        "received_at": item.received_at,
        "source_kind": item.source_kind,
        "source_system": item.source_system,
        "source_label": item.source_label,
        "quality": item.quality,
        "quality_score": item.quality_score,
        "normalization_version": item.normalization_version,
    }


def decision_quality(item: dict[str, object]) -> str:
    score = item.get("quality_score")
    if isinstance(score, int | float) and not isinstance(score, bool) and float(score) < 0.5:
        return "low"
    return str(item["quality"])


def recovery_inputs(db: Session, user: User, cutoff: datetime, *, days: int = 35) -> list[dict[str, object]]:
    end = utc_value(cutoff)
    rows = db.scalars(
        select(RecoverySignalObservation)
        .where(
            RecoverySignalObservation.user_id == user.id,
            RecoverySignalObservation.observed_at >= end - timedelta(days=days),
            RecoverySignalObservation.observed_at <= end,
            RecoverySignalObservation.received_at <= end,
        )
        .order_by(RecoverySignalObservation.observed_at.asc(), RecoverySignalObservation.id.asc())
    )
    return [observation_input(item) for item in rows]


def _is_anomaly(metric_key: str, value: float, baseline: float) -> bool:
    metric = METRICS[metric_key]
    if "relative_threshold" in metric:
        delta = abs(baseline) * float(metric["relative_threshold"])
    else:
        delta = float(metric["absolute_threshold"])
    return value <= baseline - delta if metric["direction"] == "lower" else value >= baseline + delta


def summarize_recovery(
    observations: list[dict[str, object]],
    as_of_at: datetime,
    checkins: list[dict[str, object]] | None = None,
    *,
    current_checkin_date: date | None = None,
) -> dict[str, object]:
    cutoff = utc_value(as_of_at)
    recent_checkin = max(checkins or [], key=lambda item: item["checkin_date"], default=None)
    metrics: list[dict[str, object]] = []
    for metric_key in METRICS:
        candidates = sorted(
            (item for item in observations if item["metric_key"] == metric_key and utc_value(item["observed_at"]) <= cutoff),
            key=lambda item: (utc_value(item["observed_at"]), int(item["id"])),
        )
        if not candidates:
            continue
        latest_reported = candidates[-1]
        eligible = [
            item for item in candidates
            if decision_quality(item) != "low" and (cutoff - utc_value(item["observed_at"])).total_seconds() / 3600 <= 72
        ]
        latest = eligible[-1] if eligible else latest_reported
        age_hours = (cutoff - utc_value(latest["observed_at"])).total_seconds() / 3600
        history_by_date: dict[date, list[float]] = {}
        for item in candidates:
            observed_at = utc_value(item["observed_at"])
            if decision_quality(item) == "low" or not cutoff - timedelta(days=28) <= observed_at < utc_value(latest["observed_at"]):
                continue
            history_by_date.setdefault(observed_at.date(), []).append(float(item["value"]))
        history = [float(median(values)) for _, values in sorted(history_by_date.items())]
        baseline = round(float(median(history)), 2) if len(history) >= 7 else None
        usable = decision_quality(latest) != "low" and age_hours <= 72
        anomaly = bool(usable and baseline is not None and _is_anomaly(metric_key, float(latest["value"]), baseline))
        metrics.append({
            "id": latest["id"],
            "metric_key": latest["metric_key"],
            "value": latest["value"],
            "unit": latest["unit"],
            "observed_at": latest["observed_at"],
            "source_kind": latest["source_kind"],
            "source_system": latest["source_system"],
            "quality": decision_quality(latest),
            "quality_score": latest.get("quality_score"),
            "normalization_version": latest["normalization_version"],
            "age_hours": round(max(age_hours, 0), 1),
            "freshness": "fresh" if age_hours <= 36 else "aging" if age_hours <= 72 else "stale",
            "baseline": baseline,
            "baseline_samples": len(history),
            "anomaly": anomaly,
            "usable": usable,
        })

    usable = [item for item in metrics if item["usable"]]
    calibrated = [item for item in usable if item["baseline"] is not None]
    anomalies = [item for item in calibrated if item["anomaly"]]
    self_report_current = bool(recent_checkin and (
        current_checkin_date is None
        or recent_checkin.get("checkin_date") == current_checkin_date
        or str(recent_checkin.get("checkin_date")) == current_checkin_date.isoformat()
    ))
    self_report_concern = bool(self_report_current and recent_checkin and (
        recent_checkin.get("pain")
        or recent_checkin.get("illness_symptoms")
        or int(recent_checkin.get("fatigue_0_10") or 0) >= 6
        or int(recent_checkin.get("soreness_0_10") or 0) >= 5
        or int(recent_checkin.get("stress_0_10") or 0) >= 7
        or (recent_checkin.get("sleep_quality_0_10") is not None and int(recent_checkin["sleep_quality_0_10"]) <= 4)
    ))
    wearable_concern = bool(anomalies)
    conflict = bool(self_report_current and calibrated and self_report_concern != wearable_concern)
    return {
        "rule_version": RECOVERY_RULE_VERSION,
        "metrics": metrics,
        "usable_metrics": len(usable),
        "anomaly_metrics": [str(item["metric_key"]) for item in anomalies],
        "self_report_concern": self_report_concern,
        "self_report_current": self_report_current,
        "wearable_concern": wearable_concern,
        "conflict": conflict,
        "progression_blocked": wearable_concern or conflict,
    }


def recovery_freshness_marker(observations: list[dict[str, object]], as_of_at: datetime) -> dict[str, str]:
    cutoff = utc_value(as_of_at)
    marker = {}
    for metric_key in METRICS:
        candidates = [item for item in observations if item["metric_key"] == metric_key and utc_value(item["observed_at"]) <= cutoff]
        if not candidates:
            continue
        qualified = [item for item in candidates if decision_quality(item) != "low"]
        latest = max(qualified or candidates, key=lambda item: (utc_value(item["observed_at"]), int(item["id"])))
        age_hours = (cutoff - utc_value(latest["observed_at"])).total_seconds() / 3600
        marker[metric_key] = "fresh" if age_hours <= 36 else "aging" if age_hours <= 72 else "stale"
    return marker
