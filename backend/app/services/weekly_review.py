import secrets
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.orm.attributes import set_committed_value

from app.models import (
    AthleteProfile,
    CoachingEvent,
    DailyReadinessCheckIn,
    TrainingPlan,
    TrainingPlanRecommendationAudit,
    TrainingPlanWorkout,
    User,
    WeeklyReview,
    WeeklyStrategyPreview,
)
from app.services.athlete_state import canonical_fingerprint, resolved_timezone, source_ref
from app.services.audit import log_audit_event
from app.services.coaching_events import record_coaching_event
from app.services.constraint_engine import CONSTRAINT_RULE_VERSION, is_hard_workout
from app.services.historical_state import HISTORICAL_RESOLVER_VERSION, HistoricalStateConflict, resolve_historical_week
from app.services.plan_rollbacks import PlanRollbackConflict, validate_rollback_target
from app.services.plan_versions import action_plan_snapshot, create_plan_version, json_safe, workout_snapshot
from app.services.planning import PLANNING_HARD_POLICY, today_for_user, workout_is_hard
from app.services.profile import safety_check
from app.services.readiness import apply_target, daily_readiness_recommendation, preview_block, recovery_summary_for_today
from app.services.recovery_signals import summarize_recovery


WEEKLY_REVIEW_VERSION = "weekly-review-v3"
WEEKLY_REVIEW_RULE_VERSION = "weekly-review-rules-v3"
WEEKLY_STRATEGY_RULE_VERSION = "weekly-strategy-rules-v3"
WEEKLY_STRATEGY_PREVIEW_TTL_MINUTES = 10
WEEKLY_STRATEGIES = {"hold", "deload", "resume", "conservative_progression"}


class WeeklyReviewConflict(ValueError):
    def __init__(self, message: str, reason: str):
        super().__init__(message)
        self.reason = reason


def numeric(value: object) -> float:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0.0


def int_value(value: object) -> int:
    return int(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0


def historical_workout_is_hard(workout: dict[str, object]) -> bool:
    return is_hard_workout(str(workout.get("workout_type") or ""), str(workout.get("intensity") or ""), policy=PLANNING_HARD_POLICY)


def prior_safe_baseline(events: list[dict[str, object]]) -> dict[str, object] | None:
    deloads = [item for item in events if item.get("event_type") == "weekly_strategy_applied" and (item.get("payload") or {}).get("strategy") == "deload"]
    if not deloads:
        return None
    changes = (deloads[-1].get("payload") or {}).get("changes") or []
    before_distance = sum(numeric(item.get("before")) for item in changes if isinstance(item, dict) and item.get("field") == "distance_km")
    before_duration = sum(int_value(item.get("before")) for item in changes if isinstance(item, dict) and item.get("field") == "duration_seconds")
    return {"planned_distance_km": round(before_distance, 2), "planned_duration_seconds": before_duration}


def workout_metrics(workouts: list[dict[str, object]]) -> dict[str, object]:
    done = [item for item in workouts if item.get("status") == "done"]
    missed = [item for item in workouts if item.get("status") == "missed"]
    skipped = [item for item in workouts if item.get("status") == "skipped"]
    linked = [item for item in done if item.get("actual")]
    executions = [item.get("execution") for item in workouts if isinstance(item.get("execution"), dict)]
    planned_distance = round(sum(numeric(item.get("distance_km")) for item in workouts), 2)
    planned_duration = sum(int_value(item.get("duration_seconds")) for item in workouts)
    actual_distance = round(sum(numeric((item.get("actual") or {}).get("distance_km")) for item in linked), 2)
    actual_duration = sum(int_value((item.get("actual") or {}).get("duration_seconds")) for item in linked)
    return {
        "planned_sessions": len(workouts),
        "completed_sessions": len(done),
        "missed_sessions": len(missed),
        "skipped_sessions": len(skipped),
        "linked_sessions": len(linked),
        "unlinked_completed_sessions": len(done) - len(linked),
        "session_adherence": round(len(done) / len(workouts), 2) if workouts else None,
        "planned_distance_km": planned_distance,
        "actual_distance_km": actual_distance,
        "distance_adherence": round(actual_distance / planned_distance, 2) if planned_distance else None,
        "planned_duration_seconds": planned_duration,
        "actual_duration_seconds": actual_duration,
        "duration_adherence": round(actual_duration / planned_duration, 2) if planned_duration else None,
        "hard_sessions": sum(1 for item in workouts if historical_workout_is_hard(item)),
        "execution_samples": len(executions),
        "execution_average": round(sum(numeric(item.get("score")) for item in executions if item.get("score") is not None) / len([item for item in executions if item.get("score") is not None]), 2) if any(item.get("score") is not None for item in executions) else None,
        "overdone_sessions": sum(1 for item in executions if item.get("adherence_status") == "overdone"),
        "high_risk_feedback": sum(1 for item in executions if item.get("subjective_risk") == "high"),
    }


def readiness_metrics(events: list[dict[str, object]]) -> dict[str, object]:
    readiness_events = [item for item in events if item.get("event_type") == "readiness_checkin_saved"]
    latest_by_date: dict[str, dict[str, object]] = {}
    for event in readiness_events:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        checkin_date = str(payload.get("checkin_date") or "")
        if checkin_date:
            latest_by_date[checkin_date] = event
    signals = [event.get("payload", {}).get("signals", {}) for event in latest_by_date.values()]
    scored = [item for item in signals if all(item.get(key) is not None for key in ("sleep_quality_0_10", "fatigue_0_10", "soreness_0_10", "stress_0_10"))]
    severe_recovery_days = sum(1 for item in signals if (
        numeric(item.get("fatigue_0_10")) >= 9
        or (item.get("sleep_quality_0_10") is not None and numeric(item.get("sleep_quality_0_10")) <= 2 and numeric(item.get("fatigue_0_10")) >= 7)
    ))
    reduced_load_days = sum(1 for item in signals if (
        numeric(item.get("fatigue_0_10")) >= 6
        or numeric(item.get("soreness_0_10")) >= 5
        or numeric(item.get("stress_0_10")) >= 7
        or (item.get("sleep_quality_0_10") is not None and numeric(item.get("sleep_quality_0_10")) <= 4)
    ))
    return {
        "checkin_days": len(signals),
        "complete_checkin_days": len(scored),
        "pain_days": sum(1 for item in signals if item.get("pain")),
        "illness_days": sum(1 for item in signals if item.get("illness_symptoms")),
        "severe_recovery_days": severe_recovery_days,
        "reduced_load_days": reduced_load_days,
        "average_sleep_quality": round(sum(numeric(item.get("sleep_quality_0_10")) for item in scored) / len(scored), 1) if scored else None,
        "average_fatigue": round(sum(numeric(item.get("fatigue_0_10")) for item in scored) / len(scored), 1) if scored else None,
        "average_soreness": round(sum(numeric(item.get("soreness_0_10")) for item in scored) / len(scored), 1) if scored else None,
        "average_stress": round(sum(numeric(item.get("stress_0_10")) for item in scored) / len(scored), 1) if scored else None,
    }


def latest_readiness_events(events: list[dict[str, object]]) -> list[dict[str, object]]:
    latest: dict[str, dict[str, object]] = {}
    for event in sorted(events, key=lambda item: (str(item.get("occurred_at") or ""), int(item.get("id") or 0))):
        if event.get("event_type") != "readiness_checkin_saved":
            continue
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        checkin_date = str(payload.get("checkin_date") or "")
        if checkin_date:
            latest[checkin_date] = event
    return list(latest.values())


def event_refs(events: list[dict[str, object]], event_types: set[str] | None = None) -> list[dict[str, object]]:
    return [source_ref("coaching_events", int(item["id"])) for item in events if event_types is None or item.get("event_type") in event_types]


def select_strategy(context: dict[str, object], metrics: dict[str, object], readiness: dict[str, object], recovery: dict[str, object]) -> tuple[str, str, list[str], list[dict[str, object]]]:
    events = list(context["events"])
    resolution = context["resolution"]
    profile = context.get("profile") or {}
    safety_events = [item for item in events if item.get("event_type") in {"pain_reported", "illness_reported"}]
    profile_risk = profile.get("recovery_status") in {"tired", "strained", "injured"} or any(bool(profile.get(key)) for key in ("conservative_mode", "injury_notes", "health_conditions"))
    feedback_risk = int(metrics["high_risk_feedback"]) > 0
    readiness_risk = int(readiness["pain_days"]) > 0 or int(readiness["illness_days"]) > 0 or int(readiness["severe_recovery_days"]) > 0
    readiness_concern = int(readiness["reduced_load_days"]) > 0
    prior_deload = any(item.get("event_type") == "weekly_strategy_applied" and (item.get("payload") or {}).get("strategy") == "deload" for item in events)
    evidence = event_refs(events, {"pain_reported", "illness_reported", "readiness_checkin_saved", "workout_feedback_saved", "workout_completed", "workout_missed", "weekly_strategy_applied"})
    evidence.extend(source_ref("recovery_signal_observations", int(item["id"]), str(item["metric_key"])) for item in recovery["metrics"])

    if safety_events or profile_risk or feedback_risk or readiness_risk:
        return "deload", "Current safety or recovery evidence requires reducing next-week load.", ["hold", "resume", "conservative_progression"], evidence
    if resolution.get("status") != "complete":
        return "hold", "Historical coverage is partial, so missing evidence is not treated as readiness to progress.", ["deload", "resume", "conservative_progression"], evidence
    if metrics["planned_sessions"] == 0 or int(readiness["complete_checkin_days"]) < 2:
        return "hold", "The week lacks enough planned or current self-report evidence for progression.", ["deload", "resume", "conservative_progression"], evidence
    if int(metrics["unlinked_completed_sessions"]) > 0 or metrics["session_adherence"] is None or numeric(metrics["session_adherence"]) < 0.7:
        return "hold", "Adherence or execution evidence is incomplete; hold rather than catch up missed load.", ["deload", "resume", "conservative_progression"], evidence
    if int(metrics["overdone_sessions"]) > 0:
        return "hold", "At least one session exceeded its planned target, so progression is paused.", ["deload", "resume", "conservative_progression"], evidence
    if readiness_concern:
        return "hold", "Sleep, fatigue, soreness, or stress evidence supports holding load rather than progressing.", ["deload", "resume", "conservative_progression"], evidence
    if recovery["progression_blocked"]:
        return "hold", "Qualified recovery evidence is anomalous or conflicts with self-report, so progression is paused without diagnosing or changing the plan automatically.", ["deload", "resume", "conservative_progression"], evidence
    if prior_deload and numeric(metrics["session_adherence"]) >= 0.8:
        return "resume", "The safety-deload week was completed without a current risk signal; resume only toward the prior safe baseline.", ["deload", "hold", "conservative_progression"], evidence
    if numeric(metrics["session_adherence"]) >= 0.9 and int(readiness["complete_checkin_days"]) >= 3:
        return "conservative_progression", "High adherence and complete current evidence allow a capped 5% progression.", ["deload", "hold", "resume"], evidence
    return "hold", "The available evidence supports maintaining, not increasing, next-week load.", ["deload", "resume", "conservative_progression"], evidence


def compute_weekly_review(context: dict[str, object]) -> dict[str, object]:
    context = {
        **context,
        "events": sorted(list(context["events"]), key=lambda item: (str(item.get("occurred_at") or ""), int(item.get("id") or 0))),
        "review_workouts": sorted(list(context["review_workouts"]), key=lambda item: (str(item.get("scheduled_date") or ""), int(item.get("id") or 0))),
    }
    metrics = workout_metrics(list(context["review_workouts"]))
    metrics["prior_safe_baseline"] = prior_safe_baseline(list(context["events"]))
    current_readiness_events = latest_readiness_events(list(context["events"]))
    readiness = readiness_metrics(current_readiness_events)
    checkin_signals = [
        {**event.get("payload", {}).get("signals", {}), "checkin_date": event.get("payload", {}).get("checkin_date", "")}
        for event in current_readiness_events
    ]
    recovery = summarize_recovery(
        list(context.get("recovery_observations") or []),
        datetime.fromisoformat(str(context.get("recovery_as_of_at") or context["as_of_at"])),
        checkin_signals,
        current_checkin_date=date.fromisoformat(str(context["week_end"])),
    )
    strategy, reason, rejected, evidence = select_strategy(context, metrics, readiness, recovery)
    resolution = context["resolution"]
    coverage_score = 0.0
    if resolution.get("status") == "complete":
        coverage_score += 0.4
    if int(metrics["planned_sessions"]) > 0:
        coverage_score += 0.2
    if int(metrics["linked_sessions"]) == int(metrics["completed_sessions"]):
        coverage_score += 0.2
    if int(readiness["complete_checkin_days"]) >= 2:
        coverage_score += 0.2
    coverage_score = round(coverage_score, 2)
    confidence = "high" if coverage_score >= 0.8 else "medium" if coverage_score >= 0.6 else "low"
    freshness = "current" if int(readiness["complete_checkin_days"]) >= 3 else "aging" if int(readiness["checkin_days"]) else "missing"
    limitations = sorted(set(resolution.get("limitations") or []))
    if not context.get("profile"):
        limitations.append("Missing athlete profile prevents a positive progression conclusion.")
    if int(metrics["planned_sessions"]) == 0:
        limitations.append("No planned workouts were resolved for the completed local week.")
    if int(readiness["checkin_days"]) == 0:
        limitations.append("No readiness check-ins were recorded for the reviewed week.")
    if int(metrics["unlinked_completed_sessions"]) > 0:
        limitations.append("Completed workouts without linked activities lower adherence confidence.")
    return json_safe({
        "window": {
            "week_start": context["week_start"],
            "week_end": context["week_end"],
            "target_week_start": context["target_week_start"],
            "target_week_end": context["target_week_end"],
            "timezone": context["timezone"],
            "as_of_at": context["as_of_at"],
        },
        "historical_resolution": resolution,
        "plan": context.get("plan"),
        "metrics": metrics,
        "plan_changes": context.get("plan_changes") or [],
        "readiness_trends": readiness,
        "recovery_trends": recovery,
        "recommended_strategy": strategy,
        "strategy_reason": reason,
        "rejected_strategies": rejected,
        "evidence": evidence,
        "coverage": {"score": coverage_score, "confidence": confidence, "freshness": freshness},
        "limitations": sorted(set(limitations)),
        "disclaimer": "Weekly Review is a deterministic coaching summary, not a diagnosis or injury prediction.",
    })


def weekly_review_input_fingerprint(context: dict[str, object]) -> str:
    normalized = {key: value for key, value in context.items() if key != "as_of_at"}
    return canonical_fingerprint({
        "resolver_version": HISTORICAL_RESOLVER_VERSION,
        "review_version": WEEKLY_REVIEW_VERSION,
        "review_rule_version": WEEKLY_REVIEW_RULE_VERSION,
        "strategy_rule_version": WEEKLY_STRATEGY_RULE_VERSION,
        "constraint_rule_version": CONSTRAINT_RULE_VERSION,
        "context": normalized,
    })


def assert_review_current(db: Session, user: User, review: WeeklyReview) -> None:
    if review.review_version != WEEKLY_REVIEW_VERSION or review.rule_version != WEEKLY_REVIEW_RULE_VERSION:
        raise WeeklyReviewConflict("Weekly Review uses obsolete decision rules; refresh it before previewing or applying a strategy", "review_stale")
    try:
        context = resolve_historical_week(db, user, as_of_at=datetime.now(UTC), requested_week_start=review.week_start)
    except HistoricalStateConflict as error:
        raise WeeklyReviewConflict(str(error), error.reason) from error
    if weekly_review_input_fingerprint(context) != review.input_fingerprint:
        raise WeeklyReviewConflict("Weekly Review has new historical inputs; refresh it before previewing or applying a strategy", "review_stale")


def weekly_review_response(review: WeeklyReview) -> dict[str, object]:
    return {
        "review_id": review.id,
        "review_version": review.review_version,
        "rule_version": review.rule_version,
        "input_fingerprint": review.input_fingerprint,
        "resolution_status": review.resolution_status,
        "computed_at": review.computed_at,
        **review.snapshot_json,
    }


def materialize_weekly_review(db: Session, user: User, *, week_start: date | None = None, as_of_at: datetime | None = None) -> dict[str, object]:
    db.scalar(select(User.id).where(User.id == user.id).with_for_update())
    cutoff = as_of_at or datetime.now(UTC)
    context = resolve_historical_week(db, user, as_of_at=cutoff, requested_week_start=week_start)
    fingerprint = weekly_review_input_fingerprint(context)
    existing = db.scalar(select(WeeklyReview).where(
        WeeklyReview.user_id == user.id,
        WeeklyReview.week_start == date.fromisoformat(str(context["week_start"])),
        WeeklyReview.review_version == WEEKLY_REVIEW_VERSION,
        WeeklyReview.input_fingerprint == fingerprint,
    ))
    if existing is None:
        snapshot = compute_weekly_review(context)
        existing = WeeklyReview(
            user_id=user.id,
            plan_id=(context.get("plan") or {}).get("id"),
            week_start=date.fromisoformat(str(context["week_start"])),
            week_end=date.fromisoformat(str(context["week_end"])),
            timezone=str(context["timezone"]),
            review_version=WEEKLY_REVIEW_VERSION,
            rule_version=WEEKLY_REVIEW_RULE_VERSION,
            input_fingerprint=fingerprint,
            resolution_status=str(context["resolution"]["status"]),
            snapshot_json=snapshot,
            as_of_at=datetime.fromisoformat(str(context["as_of_at"])),
            trigger_type="on_read",
        )
        db.add(existing)
        db.commit()
        db.refresh(existing)
    return weekly_review_response(existing)


def current_plan(db: Session, user: User, *, lock: bool) -> TrainingPlan:
    query = select(TrainingPlan).where(TrainingPlan.user_id == user.id, TrainingPlan.status == "active").execution_options(populate_existing=True)
    if lock:
        query = query.with_for_update()
    plan = db.scalar(query)
    if plan is None:
        raise WeeklyReviewConflict("No active plan is available for this weekly strategy", "no_current_plan")
    workouts_query = (
        select(TrainingPlanWorkout)
        .where(TrainingPlanWorkout.plan_id == plan.id)
        .options(selectinload(TrainingPlanWorkout.completed_activity), selectinload(TrainingPlanWorkout.feedback), selectinload(TrainingPlanWorkout.blocks))
        .order_by(TrainingPlanWorkout.id.asc())
        .execution_options(populate_existing=True)
    )
    if lock:
        workouts_query = workouts_query.with_for_update()
    set_committed_value(plan, "workouts", list(db.scalars(workouts_query)))
    return plan


def scale_target(workout: TrainingPlanWorkout, scale: float, *, make_easy: bool = False, marker: str) -> dict[str, object]:
    duration = max(1, round((workout.duration_seconds or 0) * scale)) if workout.duration_seconds is not None else None
    distance = round((workout.distance_km or 0) * scale, 2) if workout.distance_km is not None else None
    description = workout.description or ""
    if marker not in description:
        description = f"{description.rstrip()}\n\n{marker}" if description else marker
    if make_easy:
        return {
            "workout_type": "easy",
            "title": "Лёгкий восстановительный бег",
            "distance_km": distance,
            "duration_seconds": duration,
            "intensity": "easy",
            "description": description,
            "blocks": [{
                "block_index": 1,
                "block_type": "work",
                "repeat_count": 1,
                "target_distance_km": distance,
                "target_duration_seconds": duration,
                "target_pace_min_seconds_per_km": None,
                "target_pace_max_seconds_per_km": None,
                "target_hr_min_bpm": None,
                "target_hr_max_bpm": None,
                "target_rpe_min": 2,
                "target_rpe_max": 3,
                "description": "Лёгкая непрерывная работа без ускорений.",
            }],
        }
    return {
        "workout_type": workout.workout_type,
        "title": workout.title,
        "distance_km": distance,
        "duration_seconds": duration,
        "intensity": workout.intensity,
        "description": description,
        "blocks": [preview_block(block, scale=scale) for block in sorted(workout.blocks, key=lambda item: (item.block_index, item.id or 0))],
    }


def cap_target_duration(target: dict[str, object], maximum_seconds: int) -> dict[str, object]:
    duration = int_value(target.get("duration_seconds"))
    if duration <= maximum_seconds or duration <= 0:
        return target
    ratio = maximum_seconds / duration
    target["duration_seconds"] = maximum_seconds
    if target.get("distance_km") is not None:
        target["distance_km"] = round(numeric(target["distance_km"]) * ratio, 2)
    for block in target.get("blocks") or []:
        if not isinstance(block, dict):
            continue
        if block.get("target_duration_seconds") is not None:
            block["target_duration_seconds"] = max(1, round(int_value(block["target_duration_seconds"]) * ratio))
        if block.get("target_distance_km") is not None:
            block["target_distance_km"] = round(numeric(block["target_distance_km"]) * ratio, 2)
    return target


def strategy_targets(db: Session, user: User, review: WeeklyReview, plan: TrainingPlan, strategy: str) -> tuple[list[dict[str, object]], list[str]]:
    if strategy not in WEEKLY_STRATEGIES:
        raise WeeklyReviewConflict("Weekly strategy is not supported", "strategy_not_supported")
    if strategy != review.snapshot_json.get("recommended_strategy"):
        raise WeeklyReviewConflict("Only the deterministic recommended strategy can be previewed", "strategy_not_recommended")
    today = today_for_user(db, user)
    target_start = date.fromisoformat(str(review.snapshot_json["window"]["target_week_start"]))
    target_end = date.fromisoformat(str(review.snapshot_json["window"]["target_week_end"]))
    candidates = [
        item for item in plan.workouts
        if item.scheduled_date and max(today, target_start) <= item.scheduled_date <= target_end and item.status in {"planned", "rescheduled"} and item.completed_activity_id is None
    ]
    if strategy == "hold":
        return [], ["Hold records the reviewed strategy without changing the plan."]
    if not candidates:
        raise WeeklyReviewConflict("No mutable workouts remain in the target local week", "no_mutable_target_workouts")

    profile = db.scalar(select(AthleteProfile).where(AthleteProfile.user_id == user.id))
    checkin = db.scalar(select(DailyReadinessCheckIn).where(DailyReadinessCheckIn.user_id == user.id, DailyReadinessCheckIn.checkin_date == today))
    next_workout = candidates[0] if candidates else None
    readiness_action = str(daily_readiness_recommendation(checkin, profile, next_workout, recovery_summary_for_today(db, user, today, checkin)).get("action")) if profile else "checkin_required"
    _timezone_name, timezone = resolved_timezone(profile)
    target_start_utc = datetime.combine(target_start, datetime.min.time(), tzinfo=timezone).astimezone(UTC)
    current_week_safety_event = db.scalar(select(CoachingEvent.id).where(
        CoachingEvent.user_id == user.id,
        CoachingEvent.event_type.in_({"pain_reported", "illness_reported"}),
        CoachingEvent.occurred_at >= target_start_utc,
    ).limit(1))
    if strategy in {"resume", "conservative_progression"} and (
        profile is None
        or safety_check(profile)["conservative_mode"]
        or readiness_action != "proceed_as_planned"
        or current_week_safety_event is not None
        or review.resolution_status != "complete"
    ):
        raise WeeklyReviewConflict("Current safety or historical coverage blocks increasing weekly load", "safety_blocks_strategy")

    scale = 1.05
    if strategy == "resume":
        baseline = review.snapshot_json.get("metrics", {}).get("prior_safe_baseline")
        target_week = [item for item in plan.workouts if item.scheduled_date and target_start <= item.scheduled_date <= target_end and item.status in {"planned", "rescheduled", "done"}]
        immutable = [item for item in target_week if item not in candidates]
        current_distance = sum(item.distance_km or 0 for item in candidates)
        current_duration = sum(item.duration_seconds or 0 for item in candidates)
        scale_caps = [1.05]
        if isinstance(baseline, dict) and current_distance > 0 and numeric(baseline.get("planned_distance_km")) > 0:
            scale_caps.append(max(0.0, numeric(baseline.get("planned_distance_km")) - sum(item.distance_km or 0 for item in immutable)) / current_distance)
        if isinstance(baseline, dict) and current_duration > 0 and int_value(baseline.get("planned_duration_seconds")) > 0:
            scale_caps.append(max(0, int_value(baseline.get("planned_duration_seconds")) - sum(item.duration_seconds or 0 for item in immutable)) / current_duration)
        scale = max(1.0, min(scale_caps))
        if scale <= 1.0:
            return [], ["Current targets already meet the prior safe baseline; resume records acknowledgment without increasing load."]

    targets = []
    marker = f"Weekly strategy: {strategy} ({review.week_start.isoformat()})"
    for workout in candidates:
        before = workout_snapshot(workout)
        if strategy == "deload":
            target = scale_target(workout, 0.7 if workout_is_hard(workout) else 0.8, make_easy=workout_is_hard(workout), marker=marker)
        else:
            target = scale_target(workout, scale, marker=marker)
            if profile and profile.max_run_duration_minutes is not None and int_value(target.get("duration_seconds")) > profile.max_run_duration_minutes * 60:
                target = cap_target_duration(target, profile.max_run_duration_minutes * 60)
        changes = [
            {"workout_id": workout.id, "field": field, "before": before.get(field), "after": json_safe(target.get(field))}
            for field in ("workout_type", "title", "distance_km", "duration_seconds", "intensity", "description", "blocks")
            if before.get(field) != json_safe(target.get(field))
        ]
        if changes:
            targets.append({"workout_id": workout.id, "target": target, "changes": changes})
    return targets, [
        "Completed workouts and past dates are immutable.",
        f"Only mutable workouts from {max(today, target_start).isoformat()} through {target_end.isoformat()} are included.",
        "No missed volume is moved or stacked.",
        "Resume is capped by the prior safe baseline and 5%." if strategy == "resume" else "Progression is capped at 5%." if strategy == "conservative_progression" else "Hard sessions become easy and total targets are reduced by 20-30%.",
    ]


def preview_effect(plan: TrainingPlan, review: WeeklyReview, targets: list[dict[str, object]], *, effective_from: date) -> dict[str, object]:
    target_start = date.fromisoformat(str(review.snapshot_json["window"]["target_week_start"]))
    target_end = date.fromisoformat(str(review.snapshot_json["window"]["target_week_end"]))
    by_id = {int(item["workout_id"]): item["target"] for item in targets}
    effective_from = max(effective_from, target_start)
    week = [item for item in plan.workouts if item.scheduled_date and effective_from <= item.scheduled_date <= target_end and item.status in {"planned", "rescheduled"}]
    return {
        "week_start": target_start,
        "week_end": target_end,
        "effective_from": effective_from,
        "planned_distance_km_before": round(sum(item.distance_km or 0 for item in week), 2),
        "planned_distance_km_after": round(sum(numeric((by_id.get(item.id) or {}).get("distance_km", item.distance_km)) for item in week), 2),
        "planned_duration_seconds_before": sum(item.duration_seconds or 0 for item in week),
        "planned_duration_seconds_after": sum(int_value((by_id.get(item.id) or {}).get("duration_seconds", item.duration_seconds)) for item in week),
        "hard_sessions_before": sum(1 for item in week if workout_is_hard(item)),
        "hard_sessions_after": sum(1 for item in week if not (item.id in by_id and by_id[item.id].get("intensity") == "easy") and workout_is_hard(item)),
    }


def strategy_state(review: WeeklyReview, plan: TrainingPlan, strategy: str) -> dict[str, object]:
    return json_safe({
        "rule_version": WEEKLY_STRATEGY_RULE_VERSION,
        "review_version": WEEKLY_REVIEW_VERSION,
        "review_rule_version": WEEKLY_REVIEW_RULE_VERSION,
        "resolver_version": HISTORICAL_RESOLVER_VERSION,
        "constraint_rule_version": CONSTRAINT_RULE_VERSION,
        "review_id": review.id,
        "review_fingerprint": review.input_fingerprint,
        "strategy": strategy,
        "plan": action_plan_snapshot(plan),
    })


def create_weekly_strategy_preview(db: Session, user: User, review_id: int, strategy: str) -> dict[str, object]:
    db.scalar(select(User.id).where(User.id == user.id).with_for_update())
    review = db.scalar(select(WeeklyReview).where(WeeklyReview.id == review_id, WeeklyReview.user_id == user.id).with_for_update())
    if review is None:
        raise WeeklyReviewConflict("Weekly Review was not found", "review_not_found")
    assert_review_current(db, user, review)
    plan = current_plan(db, user, lock=True)
    if review.plan_id != plan.id:
        raise WeeklyReviewConflict("Weekly Review no longer matches the active plan", "review_stale")
    targets, facts = strategy_targets(db, user, review, plan, strategy)
    preview_id = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(minutes=WEEKLY_STRATEGY_PREVIEW_TTL_MINUTES)
    changes = [change for item in targets for change in item["changes"]]
    preview_snapshot = json_safe({
        "preview_id": preview_id,
        "expires_at": expires_at,
        "review_id": review.id,
        "plan_id": plan.id,
        "strategy": strategy,
        "rule_version": WEEKLY_STRATEGY_RULE_VERSION,
        "review": weekly_review_response(review),
        "changes": changes,
        "weekly_effect": preview_effect(plan, review, targets, effective_from=today_for_user(db, user)),
        "constraint_facts": facts,
        "summary": "Weekly strategy will be recorded without changing the plan." if strategy == "hold" else f"Weekly strategy {strategy} will update {len(targets)} future workouts after confirmation.",
        "targets": targets,
    })
    preview = WeeklyStrategyPreview(
        id=preview_id,
        user_id=user.id,
        review_id=review.id,
        plan_id=plan.id,
        strategy=strategy,
        rule_version=WEEKLY_STRATEGY_RULE_VERSION,
        request_snapshot={"strategy": strategy, "review_fingerprint": review.input_fingerprint},
        preview_snapshot=preview_snapshot,
        state_fingerprint=canonical_fingerprint(strategy_state(review, plan, strategy)),
        expires_at=expires_at,
    )
    db.add(preview)
    db.commit()
    return {key: value for key, value in preview_snapshot.items() if key != "targets"}


def find_preview(db: Session, user: User, preview_id: str, *, lock: bool) -> WeeklyStrategyPreview | None:
    query = select(WeeklyStrategyPreview).where(WeeklyStrategyPreview.id == preview_id, WeeklyStrategyPreview.user_id == user.id).execution_options(populate_existing=True)
    if lock:
        query = query.with_for_update()
    return db.scalar(query)


def target_snapshot(plan: TrainingPlan, targets: list[dict[str, object]]) -> dict[str, object]:
    snapshot = action_plan_snapshot(plan)
    target_by_id = {int(item["workout_id"]): item["target"] for item in targets}
    for workout in snapshot["workouts"]:
        target = target_by_id.get(int(workout["id"]))
        if target:
            for field in ("workout_type", "title", "distance_km", "duration_seconds", "intensity", "description", "blocks"):
                workout[field] = json_safe(target.get(field))
    return snapshot


def apply_weekly_strategy_preview(db: Session, user: User, preview_id: str) -> dict[str, object]:
    db.scalar(select(User.id).where(User.id == user.id).with_for_update())
    preview = find_preview(db, user, preview_id, lock=True)
    if preview is None:
        raise WeeklyReviewConflict("Weekly strategy preview is invalid or expired", "preview_invalid_or_expired")
    if preview.applied_at is not None and preview.applied_response_json:
        return {**preview.applied_response_json, "status": "already_applied"}
    now = datetime.now(UTC)
    if preview.expires_at < now:
        raise WeeklyReviewConflict("Weekly strategy preview is invalid or expired", "preview_invalid_or_expired")
    plan = current_plan(db, user, lock=True)
    review = db.scalar(select(WeeklyReview).where(WeeklyReview.id == preview.review_id, WeeklyReview.user_id == user.id)) if preview else None
    if preview is None or review is None or plan.id != preview.plan_id:
        raise WeeklyReviewConflict("Weekly strategy preview is stale", "preview_stale")
    if preview.applied_at is not None and preview.applied_response_json:
        return {**preview.applied_response_json, "status": "already_applied"}
    assert_review_current(db, user, review)
    targets, _facts = strategy_targets(db, user, review, plan, preview.strategy)
    if canonical_fingerprint(strategy_state(review, plan, preview.strategy)) != preview.state_fingerprint or json_safe(targets) != preview.preview_snapshot.get("targets"):
        raise WeeklyReviewConflict("Weekly strategy preview is stale", "preview_stale")

    changes = [change for item in targets for change in item["changes"]]
    pre_snapshot = action_plan_snapshot(plan)
    if targets:
        try:
            validate_rollback_target(db, user, plan, target_snapshot(plan, targets))
        except PlanRollbackConflict as error:
            raise WeeklyReviewConflict(str(error), error.reason) from error
        by_id = {item.id: item for item in plan.workouts}
        for item in targets:
            apply_target(db, by_id[int(item["workout_id"])], item["target"])
        db.flush()

    recommendation_audit = TrainingPlanRecommendationAudit(
        user_id=user.id,
        plan_id=plan.id,
        action="apply_weekly_strategy",
        status="applied",
        recommendations_snapshot={"review_id": review.id, "review_fingerprint": review.input_fingerprint, "strategy": preview.strategy, "rule_version": preview.rule_version},
        preview_changes={"preview_id": preview.id, "changes": changes},
        applied_changes={"preview_id": preview.id, "changes": changes},
    )
    db.add(recommendation_audit)
    db.flush()
    version = None
    if targets:
        version = create_plan_version(db, user, plan, f"weekly_strategy_{preview.strategy}", f"Applied weekly strategy {preview.strategy} from review #{review.id}", pre_snapshot=pre_snapshot)
        db.flush()
    event = record_coaching_event(
        db,
        user_id=user.id,
        event_type="weekly_strategy_applied",
        category="outcome",
        source="weekly_strategy_preview",
        plan_id=plan.id,
        correlation_id=preview.id,
        payload={"review_id": review.id, "review_fingerprint": review.input_fingerprint, "strategy": preview.strategy, "rule_version": preview.rule_version, "changes": changes, "plan_version_id": version.id if version else None},
    )
    db.flush()
    audit_event = log_audit_event(
        db,
        user.id,
        "weekly_strategy_applied",
        "weekly_review",
        review.id,
        {"preview_id": preview.id, "plan_id": plan.id, "strategy": preview.strategy, "rule_version": preview.rule_version, "recommendation_audit_id": recommendation_audit.id, "plan_version_id": version.id if version else None, "coaching_event_id": event.id, "changes": changes},
    )
    db.flush()
    response = json_safe({
        "status": "applied",
        "preview_id": preview.id,
        "review_id": review.id,
        "plan_id": plan.id,
        "strategy": preview.strategy,
        "changes": changes,
        "weekly_effect": preview.preview_snapshot["weekly_effect"],
        "plan_version_id": version.id if version else None,
        "plan_version_number": version.version_number if version else None,
        "recommendation_audit_id": recommendation_audit.id,
        "audit_log_id": audit_event.id,
        "coaching_event_id": event.id,
        "summary": preview.preview_snapshot["summary"],
    })
    preview.applied_at = now
    preview.recommendation_audit_id = recommendation_audit.id
    preview.plan_version_id = version.id if version else None
    preview.audit_log_id = audit_event.id
    preview.coaching_event_id = event.id
    preview.applied_response_json = response
    db.commit()
    return response
