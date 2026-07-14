import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from statistics import mean
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.timezone import resolved_zoneinfo
from app.models import (
    AthleteProfile,
    AthleteStateSnapshot,
    CoachingEvent,
    DailyReadinessCheckIn,
    RecoverySignalObservation,
    TrainingPlan,
    TrainingPlanWorkout,
    User,
)
from app.services.plan_versions import json_safe
from app.services.planning import workout_execution_score
from app.services.recovery_signals import RECOVERY_RULE_VERSION, observation_input, recovery_freshness_marker, summarize_recovery
from app.services.training_load import training_load_context


STATE_VERSION = "athlete-state-v3"
RULE_VERSION = "athlete-state-rules-v3"
SAFETY_EVENT_TYPES = {"pain_reported", "illness_reported"}


def resolved_timezone(profile: AthleteProfile | None) -> tuple[str, ZoneInfo]:
    return resolved_zoneinfo(profile.timezone if profile else None)


def local_date_for(profile: AthleteProfile | None, as_of_at: datetime) -> tuple[date, str]:
    timezone_name, timezone = resolved_timezone(profile)
    value = as_of_at if as_of_at.tzinfo else as_of_at.replace(tzinfo=UTC)
    return value.astimezone(timezone).date(), timezone_name


def canonical_fingerprint(value: dict[str, object]) -> str:
    encoded = json.dumps(json_safe(value), ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def source_ref(model: str, identifier: int | str, field: str | None = None) -> dict[str, object]:
    result: dict[str, object] = {"model": model, "id": identifier}
    if field:
        result["field"] = field
    return result


def signal(
    *,
    key: str,
    label: str,
    status: str,
    freshness: str,
    confidence: str,
    value: object,
    summary: str,
    observed_at: date | datetime | None,
    refs: list[dict[str, object]],
    limitations: list[str] | None = None,
) -> dict[str, object]:
    return {
        "key": key,
        "label": label,
        "status": status,
        "freshness": freshness,
        "confidence": confidence,
        "value": value,
        "summary": summary,
        "observed_at": observed_at,
        "source_refs": refs,
        "limitations": limitations or [],
    }


def readiness_signal(checkins: list[dict[str, object]], local_date: date) -> dict[str, object]:
    today = next((item for item in checkins if item["checkin_date"] == local_date), None)
    if today is None:
        return signal(
            key="readiness",
            label="Daily readiness",
            status="unknown",
            freshness="missing",
            confidence="none",
            value=None,
            summary="No readiness check-in exists for the athlete's current local date.",
            observed_at=None,
            refs=[],
            limitations=["Missing self-report is not interpreted as good readiness."],
        )
    pain = bool(today["pain"])
    illness = bool(today["illness_symptoms"])
    soft_constraints = [
        value for value in (
            f"weather:{today['weather_condition']}" if today.get("weather_condition") in {"heat", "cold", "storm", "poor_air"} else None,
            f"surface:{today['surface_condition']}" if today.get("surface_condition") in {"wet", "icy", "uneven"} else None,
            f"available_time:{today['available_time_minutes']}min" if today.get("available_time_minutes") is not None else None,
        ) if value is not None
    ]
    values = {
        "sleep_quality_0_10": today["sleep_quality_0_10"],
        "fatigue_0_10": today["fatigue_0_10"],
        "soreness_0_10": today["soreness_0_10"],
        "stress_0_10": today["stress_0_10"],
    }
    missing = [key for key, value in values.items() if value is None]
    if missing and not (pain or illness):
        return signal(
            key="readiness",
            label="Daily readiness",
            status="unknown",
            freshness="fresh",
            confidence="low",
            value={**values, "pain": pain, "illness_symptoms": illness},
            summary="Today's readiness check-in is incomplete.",
            observed_at=local_date,
            refs=[source_ref("daily_readiness_checkins", int(today["id"]))],
            limitations=[f"Missing scores: {', '.join(missing)}. Incomplete self-report is not interpreted as good readiness."],
        )
    fatigue = int(values["fatigue_0_10"] or 0)
    soreness = int(values["soreness_0_10"] or 0)
    sleep = int(values["sleep_quality_0_10"] or 0)
    stress = int(values["stress_0_10"] or 0)
    if pain or illness:
        status = "risk"
        summary = "Pain or illness is reported today; do not infer readiness for normal training."
    elif fatigue >= 8 or soreness >= 8 or sleep <= 2:
        status = "risk"
        summary = "Severe fatigue, soreness or poor sleep is reported today."
    elif fatigue >= 6 or soreness >= 6 or stress >= 7 or sleep <= 4 or soft_constraints:
        status = "watch"
        summary = "One or more recovery or contextual signals call for a controlled session."
    else:
        status = "ok"
        summary = "Today's self-report has no threshold-level warning; this is not an injury prediction."
    return signal(
        key="readiness",
        label="Daily readiness",
        status=status,
        freshness="fresh",
        confidence="medium" if missing else "high",
        value={
            **values,
            "pain": pain,
            "illness_symptoms": illness,
            "soft_constraints": soft_constraints,
        },
        summary=summary,
        observed_at=local_date,
        refs=[source_ref("daily_readiness_checkins", int(today["id"]))],
        limitations=["Self-reported state is subjective and applies to this local date only."],
    )


def profile_signal(profile: dict[str, object] | None) -> dict[str, object]:
    if profile is None:
        return signal(
            key="profile_safety",
            label="Profile safety",
            status="unknown",
            freshness="missing",
            confidence="none",
            value=None,
            summary="Athlete safety profile is missing.",
            observed_at=None,
            refs=[],
            limitations=["Safety constraints cannot be confirmed without a profile."],
        )
    active = bool(
        profile["conservative_mode"]
        or profile["injury_notes"]
        or profile["health_conditions"]
        or profile["recovery_status"] in {"tired", "strained", "injured"}
    )
    status = "risk" if profile["recovery_status"] == "injured" else "watch" if active else "ok"
    return signal(
        key="profile_safety",
        label="Profile safety",
        status=status,
        freshness="current",
        confidence="high",
        value={
            "recovery_status": profile["recovery_status"],
            "conservative_mode": active,
            "has_injury_notes": bool(profile["injury_notes"]),
            "has_health_conditions": bool(profile["health_conditions"]),
        },
        summary="Profile safety constraints are active." if active else "No profile-level safety constraint is active.",
        observed_at=profile["updated_at"],
        refs=[source_ref("athlete_profiles", int(profile["id"]))],
        limitations=["Profile status remains current until the athlete updates it."],
    )


def safety_event_signal(events: list[dict[str, object]], checkins: list[dict[str, object]], local_date: date) -> dict[str, object]:
    recent = [item for item in events if item["event_type"] in SAFETY_EVENT_TYPES]
    if not recent:
        today = next((item for item in checkins if item["checkin_date"] == local_date), None)
        if today is not None and not today["pain"] and not today["illness_symptoms"]:
            return signal(
                key="recent_safety_reports",
                label="Recent safety reports",
                status="ok",
                freshness="fresh",
                confidence="high",
                value={"count_7d": 0, "pain_today": False, "illness_today": False},
                summary="Today's check-in explicitly reports no pain or illness symptoms.",
                observed_at=local_date,
                refs=[source_ref("daily_readiness_checkins", int(today["id"]))],
                limitations=["This self-report applies to the current local date and is not a medical assessment."],
            )
        if today is not None:
            reported = "pain and illness" if today["pain"] and today["illness_symptoms"] else "pain" if today["pain"] else "illness"
            return signal(
                key="recent_safety_reports",
                label="Recent safety reports",
                status="risk",
                freshness="fresh",
                confidence="high",
                value={"count_7d": 1, "latest_type": f"{reported}_reported"},
                summary=f"Today's check-in reports {reported}; this remains a safety constraint.",
                observed_at=local_date,
                refs=[source_ref("daily_readiness_checkins", int(today["id"]))],
                limitations=["This is a self-reported safety signal, not a diagnosis."],
            )
        return signal(
            key="recent_safety_reports",
            label="Recent safety reports",
            status="unknown",
            freshness="missing",
            confidence="none",
            value=None,
            summary="No separate pain or illness report exists in the seven-day window.",
            observed_at=None,
            refs=[],
            limitations=["No report does not prove absence of pain or illness."],
        )
    latest = max(recent, key=lambda item: (item["local_date"], int(item["id"])))
    age_days = (local_date - latest["local_date"]).days
    return signal(
        key="recent_safety_reports",
        label="Recent safety reports",
        status="risk" if age_days <= 1 else "watch",
        freshness="fresh" if age_days <= 1 else "aging",
        confidence="high",
        value={"count_7d": len(recent), "latest_type": latest["event_type"]},
        summary="A recent pain or illness report remains relevant to training decisions.",
        observed_at=latest["occurred_at"],
        refs=[source_ref("coaching_events", int(item["id"])) for item in recent],
        limitations=["A later explicit recovery report is required before treating this signal as resolved."],
    )


def feedback_and_execution_signals(workouts: list[dict[str, object]], local_date: date) -> tuple[dict[str, object], dict[str, object]]:
    completed = [item for item in workouts if item["status"] == "done"]
    with_feedback = [item for item in completed if item["feedback"] is not None]
    feedback_refs = [source_ref("training_plan_workout_feedback", int(item["feedback"]["id"])) for item in with_feedback]
    if not with_feedback:
        feedback = signal(
            key="recent_feedback",
            label="Post-workout feedback",
            status="unknown",
            freshness="missing",
            confidence="none",
            value=None,
            summary="No post-workout feedback is available in the 28-day window.",
            observed_at=None,
            refs=[],
            limitations=["Completed activities without feedback cannot establish subjective recovery."],
        )
    else:
        risky = [item for item in with_feedback if item["execution"]["subjective_risk"] in {"high", "moderate"}]
        latest = max(with_feedback, key=lambda item: (item["feedback"].get("observed_date") or item["scheduled_date"], int(item["id"])))
        observed_date = latest["feedback"].get("observed_date") or latest["scheduled_date"]
        age_days = (local_date - observed_date).days
        feedback = signal(
            key="recent_feedback",
            label="Post-workout feedback",
            status="risk" if any(item["execution"]["subjective_risk"] == "high" for item in risky) else "watch" if risky else "ok",
            freshness="fresh" if age_days <= 2 else "aging" if age_days <= 7 else "stale",
            confidence="high" if age_days <= 7 else "medium",
            value={"feedback_count_28d": len(with_feedback), "risk_count_28d": len(risky)},
            summary="Recent feedback includes pain or high exertion." if risky else "Available feedback has no threshold-level subjective warning.",
            observed_at=latest["feedback"]["updated_at"],
            refs=feedback_refs,
            limitations=["Feedback is subjective and only covers workouts where it was submitted."],
        )
    scored = [item for item in completed if item["execution"]["score"] is not None]
    if not scored:
        execution = signal(
            key="execution_quality",
            label="Execution quality",
            status="unknown",
            freshness="missing",
            confidence="none",
            value=None,
            summary="No comparable planned-versus-actual workout execution is available.",
            observed_at=None,
            refs=[],
            limitations=["Unlinked completed workouts cannot be scored reliably."],
        )
    else:
        scores = [float(item["execution"]["score"]) for item in scored]
        statuses = [str(item["execution"]["adherence_status"]) for item in scored]
        average_score = round(mean(scores), 2)
        status = "risk" if statuses.count("overdone") >= 2 else "watch" if "overdone" in statuses or average_score < 0.7 else "ok"
        execution = signal(
            key="execution_quality",
            label="Execution quality",
            status=status,
            freshness="fresh" if (local_date - max(item["scheduled_date"] for item in scored)).days <= 7 else "aging",
            confidence="high" if len(scored) >= 3 else "medium",
            value={"average_score_28d": average_score, "scored_workouts": len(scored), "overdone_workouts": statuses.count("overdone")},
            summary="Execution shows repeated overload or low target adherence." if status != "ok" else "Recent comparable workouts are broadly aligned with targets.",
            observed_at=max(item["scheduled_date"] for item in scored),
            refs=[source_ref("training_plan_workouts", int(item["id"])) for item in scored],
            limitations=["Execution score describes target adherence, not health or injury probability."],
        )
    return feedback, execution


def adherence_signal(plan: dict[str, object] | None, due_workouts: list[dict[str, object]], summary: dict[str, object] | None, local_date: date) -> dict[str, object]:
    if plan is None:
        return signal(
            key="weekly_adherence",
            label="Weekly adherence",
            status="unknown",
            freshness="missing",
            confidence="none",
            value=None,
            summary="No active training plan is available.",
            observed_at=None,
            refs=[],
            limitations=["No plan means adherence cannot be evaluated."],
        )
    if not due_workouts:
        return signal(
            key="weekly_adherence",
            label="Weekly adherence",
            status="unknown",
            freshness="current",
            confidence="medium",
            value={"due_workouts": 0},
            summary="No planned workout is due yet in the current calendar week.",
            observed_at=local_date,
            refs=[source_ref("training_plans", int(plan["id"]))],
            limitations=["Not due is distinct from successful completion."],
        )
    assert summary is not None
    missed = int(summary["missed_workouts"]) + int(summary["skipped_workouts"])
    unlinked = int(summary["unlinked_done_workouts"])
    status = "risk" if missed >= 2 else "watch" if missed or unlinked else "ok"
    confidence = "low" if unlinked else "high"
    return signal(
        key="weekly_adherence",
        label="Weekly adherence",
        status=status,
        freshness="current",
        confidence=confidence,
        value={
            "due_workouts": len(due_workouts),
            "done_workouts": summary["done_workouts"],
            "missed_workouts": summary["missed_workouts"],
            "skipped_workouts": summary["skipped_workouts"],
            "completion_rate": summary["completion_rate"],
        },
        summary="Missed, skipped or unlinked sessions require review." if status != "ok" else "All due sessions have linked completion facts.",
        observed_at=local_date,
        refs=[source_ref("training_plan_workouts", int(item["id"])) for item in due_workouts],
        limitations=list(summary["warnings"]),
    )


def load_signal(load: dict[str, object]) -> dict[str, object]:
    points = list(load["points"])
    observed = [item for item in points if item["activity_ids"]]
    if not observed:
        return signal(
            key="training_load",
            label="Training load",
            status="unknown",
            freshness="missing",
            confidence="none",
            value=None,
            summary="No activity-derived load is available in the seven-day window.",
            observed_at=None,
            refs=[],
            limitations=["Unavailable load is not interpreted as recovery or low risk."],
        )
    latest = observed[-1]
    current = points[-1]
    methods = {str(item["load_method"]) for item in observed}
    confidence = "high" if methods <= {"srpe"} else "medium" if methods & {"srpe", "hr_trimp"} else "low"
    recent_load = round(sum(float(item["load"]) for item in points), 1)
    warnings = [item for item in load.get("warnings", []) if item.get("severity") in {"warning", "critical"}]
    status = "risk" if any(item.get("severity") == "critical" for item in warnings) else "watch" if warnings else "ok"
    return signal(
        key="training_load",
        label="Training load",
        status=status,
        freshness="fresh" if (load["to_date"] - latest["date"]).days <= 2 else "aging",
        confidence=confidence,
        value={"load_7d": recent_load, "latest_tsb": current["tsb"], "methods": sorted(methods)},
        summary=str(warnings[0]["message"]) if warnings else "Seven-day load is available for context; it is not a standalone readiness decision.",
        observed_at=latest["date"],
        refs=[source_ref("activities", int(identifier)) for item in observed for identifier in item["activity_ids"]],
        limitations=["CTL, ATL and TSB are workload heuristics, not medical predictions.", *[str(item["title"]) for item in warnings]],
    )


def recovery_signal(observations: list[dict[str, object]], checkins: list[dict[str, object]], as_of_at: datetime, local_date: date | None = None) -> dict[str, object]:
    recovery = summarize_recovery(observations, as_of_at, checkins, current_checkin_date=local_date)
    metrics = list(recovery["metrics"])
    if not metrics:
        return signal(
            key="recovery_signals",
            label="Recovery signals",
            status="unknown",
            freshness="missing",
            confidence="none",
            value={"rule_version": recovery["rule_version"], "metrics": [], "conflict": False},
            summary="No normalized recovery observations are available.",
            observed_at=None,
            refs=[],
            limitations=["Wearable data is optional and its absence is not interpreted as poor recovery or readiness."],
        )
    usable = [item for item in metrics if item["usable"]]
    calibrated = [item for item in usable if item["baseline"] is not None]
    freshest = max(usable or metrics, key=lambda item: item["observed_at"])
    status = "watch" if recovery["progression_blocked"] else "ok" if calibrated else "unknown"
    if recovery["conflict"]:
        summary = "Wearable evidence and the latest self-report disagree; self-reported symptoms and restrictions take priority."
    elif recovery["wearable_concern"]:
        summary = "A qualified deviation from the athlete's own baseline supports holding progression, not diagnosis or automatic plan changes."
    elif calibrated:
        summary = "Current qualified recovery observations show no threshold-level baseline deviation."
    elif usable:
        summary = "Qualified observations are accumulating, but a personal baseline is not available yet."
    else:
        summary = "Recovery observations are stale or low quality and cannot support a readiness conclusion."
    return signal(
        key="recovery_signals",
        label="Recovery signals",
        status=status,
        freshness=str(freshest["freshness"]),
        confidence="low" if recovery["conflict"] else "high" if len(calibrated) >= 3 else "medium" if calibrated else "low",
        value={
            "rule_version": recovery["rule_version"],
            "metrics": metrics,
            "conflict": recovery["conflict"],
            "self_report_priority": bool(recovery["conflict"] and recovery["self_report_concern"]),
            "progression_blocked": recovery["progression_blocked"],
        },
        summary=summary,
        observed_at=freshest["observed_at"],
        refs=[source_ref("recovery_signal_observations", int(item["id"]), str(item["metric_key"])) for item in metrics],
        limitations=[
            "Recovery signals are vendor-neutral context, not medical evidence or permission to increase load.",
            *(["Resolve the conflict with a current self-report before progression."] if recovery["conflict"] else []),
            *(["At least seven prior qualified observations are required for each personal baseline."] if any(item["baseline"] is None for item in metrics) else []),
        ],
    )


def readiness_trends(checkins: list[dict[str, object]]) -> dict[str, object]:
    fields = ("sleep_quality_0_10", "fatigue_0_10", "soreness_0_10", "stress_0_10")
    result: dict[str, object] = {}
    ordered = sorted(checkins, key=lambda item: item["checkin_date"])
    for field in fields:
        available = [item for item in ordered if item[field] is not None]
        values = [int(item[field]) for item in available]
        direction = "insufficient"
        if len(values) >= 4:
            recent = mean(values[-3:])
            previous = mean(values[:-3])
            delta = recent - previous
            if field == "sleep_quality_0_10":
                delta = -delta
            direction = "worsening" if delta >= 1 else "improving" if delta <= -1 else "stable"
        result[field] = {
            "samples": len(values),
            "average": round(mean(values), 1) if values else None,
            "direction": direction,
            "source_refs": [source_ref("daily_readiness_checkins", int(item["id"]), field) for item in available],
        }
    return result


def overall_state(signals: list[dict[str, object]]) -> tuple[str, str, str]:
    statuses = {str(item["status"]) for item in signals}
    if "risk" in statuses:
        return "risk", "Safety or recovery signal needs attention", "Keep training conservative and resolve the cited safety evidence before adding load."
    if "watch" in statuses:
        return "watch", "Current signals support a controlled approach", "Hold progression while aging or cautionary signals remain relevant."
    required_statuses = {str(item["status"]) for item in signals if item["key"] != "recovery_signals"}
    if "unknown" in required_statuses:
        return "unknown", "Athlete state is incomplete", "Missing evidence prevents a positive readiness conclusion."
    return "ok", "Current evidence has no threshold-level warning", "Available signals support following the plan without adding unplanned load."


def compute_athlete_state(inputs: dict[str, object]) -> dict[str, object]:
    local_date = inputs["local_date"]
    checkins = list(inputs["checkins"])
    workouts = list(inputs["recent_workouts"])
    due_workouts = list(inputs["due_workouts"])
    feedback, execution = feedback_and_execution_signals(workouts, local_date)
    signals = [
        readiness_signal(checkins, local_date),
        profile_signal(inputs["profile"]),
        safety_event_signal(list(inputs["events"]), checkins, local_date),
        feedback,
        execution,
        adherence_signal(inputs["active_plan"], due_workouts, inputs["adherence"], local_date),
        load_signal(inputs["training_load"]),
        recovery_signal(list(inputs.get("recovery_observations") or []), checkins, inputs.get("as_of_at") or datetime.now(UTC), local_date),
    ]
    status, headline, summary = overall_state(signals)
    strategy = "deload" if status == "risk" else "hold"
    limitations = sorted({str(value) for item in signals for value in item["limitations"]})
    return {
        "status": status,
        "headline": headline,
        "summary": summary,
        "signals": signals,
        "trends": readiness_trends(checkins),
        "weekly": {
            "week_start": inputs["week_start"],
            "week_end": inputs["week_end"],
            "plan_id": inputs["active_plan"]["id"] if inputs["active_plan"] else None,
            "adherence": inputs["adherence"],
            "recommended_strategy": strategy,
            "strategy_reason": "Active risk evidence requires lower load." if strategy == "deload" else "Hold progression until a complete weekly review is available.",
        },
        "limitations": limitations,
        "disclaimer": "Athlete State is a deterministic coaching summary, not a diagnosis or injury prediction.",
    }


def _profile_input(profile: AthleteProfile | None) -> dict[str, object] | None:
    if profile is None:
        return None
    return {
        "id": profile.id,
        "timezone": profile.timezone,
        "conservative_mode": profile.conservative_mode,
        "injury_notes": profile.injury_notes,
        "health_conditions": profile.health_conditions,
        "recovery_status": profile.recovery_status,
        "updated_at": profile.updated_at,
    }


def _checkin_input(checkin: DailyReadinessCheckIn) -> dict[str, object]:
    return {
        "id": checkin.id,
        "checkin_date": checkin.checkin_date,
        "sleep_quality_0_10": checkin.sleep_quality_0_10,
        "fatigue_0_10": checkin.fatigue_0_10,
        "soreness_0_10": checkin.soreness_0_10,
        "stress_0_10": checkin.stress_0_10,
        "pain": checkin.pain,
        "pain_level_0_10": checkin.pain_level_0_10,
        "illness_symptoms": checkin.illness_symptoms,
        "weather_condition": checkin.weather_condition,
        "surface_condition": checkin.surface_condition,
        "available_time_minutes": checkin.available_time_minutes,
        "updated_at": checkin.updated_at,
    }


def fact_available(observed_at: datetime | None, observation_cutoff: datetime) -> bool:
    if observed_at is None:
        return True
    value = observed_at if observed_at.tzinfo else observed_at.replace(tzinfo=UTC)
    cutoff = observation_cutoff if observation_cutoff.tzinfo else observation_cutoff.replace(tzinfo=UTC)
    return value.astimezone(UTC) <= cutoff.astimezone(UTC)


def _workout_input(workout: TrainingPlanWorkout, observation_cutoff: datetime, timezone: ZoneInfo = ZoneInfo("UTC")) -> dict[str, object]:
    raw_activity = workout.completed_activity
    activity_time = (raw_activity.started_at or raw_activity.created_at) if raw_activity else None
    activity = raw_activity if raw_activity and fact_available(activity_time, observation_cutoff) else None
    raw_feedback = workout.feedback
    feedback_time = (raw_feedback.updated_at or raw_feedback.created_at) if raw_feedback else None
    feedback = raw_feedback if raw_feedback and fact_available(feedback_time, observation_cutoff) else None
    effective_status = "planned" if workout.status == "done" and raw_activity is not None and activity is None else workout.status
    execution = workout_execution_score(SimpleNamespace(
        completed_activity=activity,
        feedback=feedback,
        status=effective_status,
        distance_km=workout.distance_km,
        duration_seconds=workout.duration_seconds,
        workout_type=workout.workout_type,
        intensity=workout.intensity,
    ))
    return {
        "id": workout.id,
        "plan_id": workout.plan_id,
        "scheduled_date": workout.scheduled_date,
        "status": effective_status,
        "workout_type": workout.workout_type,
        "intensity": workout.intensity,
        "distance_km": workout.distance_km,
        "duration_seconds": workout.duration_seconds,
        "completed_activity_id": workout.completed_activity_id,
        "completed_activity": {
            "id": activity.id,
            "started_at": activity.started_at,
            "distance_km": activity.distance_km,
            "duration_seconds": activity.duration_seconds,
            "average_heart_rate_bpm": activity.average_heart_rate_bpm,
            "aerobic_training_stress": activity.aerobic_training_stress,
        } if activity else None,
        "feedback": {
            "id": feedback.id,
            "rpe": feedback.rpe,
            "fatigue": feedback.fatigue,
            "soreness_0_10": feedback.soreness_0_10,
            "pain": feedback.pain,
            "pain_level": feedback.pain_level,
            "sleep_quality": feedback.sleep_quality,
            "updated_at": feedback.updated_at,
            "observed_date": (feedback_time if feedback_time.tzinfo else feedback_time.replace(tzinfo=timezone)).astimezone(timezone).date() if feedback_time else workout.scheduled_date,
        } if feedback else None,
        "execution": execution,
    }


def adherence_from_inputs(workouts: list[dict[str, object]]) -> dict[str, object]:
    done = [item for item in workouts if item["status"] == "done"]
    missed = [item for item in workouts if item["status"] == "missed"]
    skipped = [item for item in workouts if item["status"] == "skipped"]
    linked = [item for item in done if item["completed_activity"] is not None]
    warnings = ["Completed workouts without an activity lower adherence confidence."] if len(linked) < len(done) else []
    return {
        "total_workouts": len(workouts),
        "done_workouts": len(done),
        "missed_workouts": len(missed),
        "skipped_workouts": len(skipped),
        "linked_workouts": len(linked),
        "unlinked_done_workouts": len(done) - len(linked),
        "completion_rate": round(len(done) / len(workouts), 2) if workouts else 0,
        "warnings": warnings,
    }


def _event_input(event: CoachingEvent, timezone: ZoneInfo) -> dict[str, object]:
    occurred_at = event.occurred_at if event.occurred_at.tzinfo else event.occurred_at.replace(tzinfo=UTC)
    return {
        "id": event.id,
        "event_type": event.event_type,
        "occurred_at": occurred_at,
        "local_date": occurred_at.astimezone(timezone).date(),
        "workout_id": event.workout_id,
        "checkin_id": event.checkin_id,
    }


def build_athlete_state_inputs(db: Session, user: User, observation_cutoff: datetime) -> dict[str, object]:
    cutoff = observation_cutoff if observation_cutoff.tzinfo else observation_cutoff.replace(tzinfo=UTC)
    cutoff = cutoff.astimezone(UTC)
    profile = db.scalar(select(AthleteProfile).where(AthleteProfile.user_id == user.id, AthleteProfile.created_at <= cutoff))
    local_date, timezone_name = local_date_for(profile, cutoff)
    _, timezone = resolved_timezone(profile)
    week_start = local_date - timedelta(days=local_date.weekday())
    week_end = week_start + timedelta(days=6)
    checkins = list(db.scalars(
        select(DailyReadinessCheckIn)
        .where(
            DailyReadinessCheckIn.user_id == user.id,
            DailyReadinessCheckIn.checkin_date >= local_date - timedelta(days=6),
            DailyReadinessCheckIn.checkin_date <= local_date,
            DailyReadinessCheckIn.created_at <= cutoff,
        )
        .order_by(DailyReadinessCheckIn.checkin_date.asc(), DailyReadinessCheckIn.id.asc())
    ))
    plan = db.scalar(
        select(TrainingPlan)
        .where(TrainingPlan.user_id == user.id, TrainingPlan.status == "active", TrainingPlan.created_at <= cutoff)
        .options(
            selectinload(TrainingPlan.workouts).selectinload(TrainingPlanWorkout.completed_activity),
            selectinload(TrainingPlan.workouts).selectinload(TrainingPlanWorkout.feedback),
        )
        .order_by(TrainingPlan.created_at.desc(), TrainingPlan.id.desc())
        .limit(1)
    )
    plan_workouts = list(plan.workouts) if plan else []
    due = [item for item in plan_workouts if item.scheduled_date and week_start <= item.scheduled_date <= local_date]
    recent = list(db.scalars(
        select(TrainingPlanWorkout)
        .join(TrainingPlan, TrainingPlan.id == TrainingPlanWorkout.plan_id)
        .where(
            TrainingPlan.user_id == user.id,
            TrainingPlan.created_at <= cutoff,
            TrainingPlanWorkout.scheduled_date >= local_date - timedelta(days=27),
            TrainingPlanWorkout.scheduled_date <= local_date,
        )
        .options(
            selectinload(TrainingPlanWorkout.completed_activity),
            selectinload(TrainingPlanWorkout.feedback),
        )
        .order_by(TrainingPlanWorkout.scheduled_date.asc(), TrainingPlanWorkout.id.asc())
    ))
    events = list(db.scalars(
        select(CoachingEvent)
        .where(
            CoachingEvent.user_id == user.id,
            CoachingEvent.occurred_at >= datetime.combine(local_date - timedelta(days=6), datetime.min.time(), tzinfo=timezone).astimezone(UTC),
            CoachingEvent.occurred_at <= cutoff,
        )
        .order_by(CoachingEvent.occurred_at.asc(), CoachingEvent.id.asc())
    ))
    recovery_observations = list(db.scalars(
        select(RecoverySignalObservation)
        .where(
            RecoverySignalObservation.user_id == user.id,
            RecoverySignalObservation.observed_at >= cutoff - timedelta(days=35),
            RecoverySignalObservation.observed_at <= cutoff,
            RecoverySignalObservation.received_at <= cutoff,
        )
        .order_by(RecoverySignalObservation.observed_at.asc(), RecoverySignalObservation.id.asc())
    ))
    load_context = training_load_context(
        db,
        user,
        local_date - timedelta(days=6),
        local_date,
        as_of_at=cutoff,
        profile=profile,
        timezone=timezone,
    )
    due_inputs = [_workout_input(item, cutoff, timezone) for item in sorted(due, key=lambda value: (value.scheduled_date, value.id))]
    inputs = {
        "state_version": STATE_VERSION,
        "rule_version": RULE_VERSION,
        "recovery_rule_version": RECOVERY_RULE_VERSION,
        "as_of_at": cutoff,
        "local_date": local_date,
        "timezone": timezone_name,
        "week_start": week_start,
        "week_end": week_end,
        "profile": _profile_input(profile),
        "checkins": [_checkin_input(item) for item in checkins],
        "active_plan": {"id": plan.id, "updated_at": plan.updated_at} if plan else None,
        "due_workouts": due_inputs,
        "recent_workouts": [_workout_input(item, cutoff, timezone) for item in sorted(recent, key=lambda value: (value.scheduled_date, value.id))],
        "adherence": adherence_from_inputs(due_inputs) if due_inputs else None,
        "events": [_event_input(item, timezone) for item in events],
        "training_load": {
            "from_date": local_date - timedelta(days=6),
            "to_date": local_date,
            "points": load_context["daily"]["points"],
            "warnings": load_context["warnings"],
        },
        "recovery_observations": [observation_input(item) for item in recovery_observations],
        "recovery_freshness_marker": recovery_freshness_marker([observation_input(item) for item in recovery_observations], cutoff),
    }
    return inputs


def _utcnow() -> datetime:
    return datetime.now(UTC)


def materialize_athlete_state(db: Session, user: User) -> dict[str, object]:
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    observation_cutoff = _utcnow()
    inputs = build_athlete_state_inputs(db, user, observation_cutoff)
    inputs_collected_at = _utcnow()
    fingerprint = canonical_fingerprint({key: value for key, value in inputs.items() if key != "as_of_at"})
    existing = db.scalar(
        select(AthleteStateSnapshot).where(
            AthleteStateSnapshot.user_id == user.id,
            AthleteStateSnapshot.local_date == inputs["local_date"],
            AthleteStateSnapshot.state_version == STATE_VERSION,
            AthleteStateSnapshot.input_fingerprint == fingerprint,
        )
    )
    if existing is None:
        state = compute_athlete_state(inputs)
        computed_at = _utcnow()
        existing = AthleteStateSnapshot(
            user_id=user.id,
            local_date=inputs["local_date"],
            timezone=inputs["timezone"],
            state_version=STATE_VERSION,
            rule_version=RULE_VERSION,
            input_fingerprint=fingerprint,
            snapshot_json=json_safe(state),
            as_of_at=inputs_collected_at,
            computed_at=computed_at,
            trigger_type="on_read",
        )
        db.add(existing)
        db.flush()
        db.commit()
        db.refresh(existing)
    return {
        "snapshot_id": existing.id,
        "local_date": existing.local_date,
        "timezone": existing.timezone,
        "state_version": existing.state_version,
        "rule_version": existing.rule_version,
        "input_fingerprint": existing.input_fingerprint,
        "as_of_at": existing.as_of_at,
        "computed_at": existing.computed_at,
        **existing.snapshot_json,
    }
