import hashlib
import json
import secrets
from datetime import UTC, datetime

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.models import CoachEvaluationRun, CoachLlmAttempt, SafetyEscalation, SafetyReviewEvent, TrainingPlanVersion, WeeklyReview


EVALUATION_VERSION = "coach-evaluation-v1"
THRESHOLD_VERSION = "coach-release-thresholds-v1"
MIN_COMPLETE_REVIEWS = 20
MIN_EXECUTION_SAMPLES = 10
MIN_LLM_ATTEMPTS = 20
MIN_SESSION_ADHERENCE = 0.70
MIN_COMPLETION_QUALITY = 0.75
MAX_PAIN_FLAG_RATE = 0.10
MAX_OVERLOAD_FLAG_RATE = 0.10
MAX_LLM_FAILURE_RATE = 0.05
PROGRESSION_REASONS = {"weekly_strategy_conservative_progression", "weekly_strategy_resume"}


def _number(value: object) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return None


def _average(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _rate(count: int, total: int) -> float | None:
    return round(count / total, 4) if total else None


def _latest_reviews(db: Session, start: datetime, end: datetime) -> list[WeeklyReview]:
    reviews = list(db.scalars(select(WeeklyReview).where(WeeklyReview.week_end >= start.date(), WeeklyReview.week_end < end.date()).order_by(WeeklyReview.user_id, WeeklyReview.week_start, WeeklyReview.computed_at.desc(), WeeklyReview.id.desc())))
    latest: dict[tuple[int, object], WeeklyReview] = {}
    for review in reviews:
        latest.setdefault((review.user_id, review.week_start), review)
    return list(latest.values())


def _gate(metric: object, *, minimum: float | None = None, maximum: float | None = None, samples: int | None = None, required_samples: int | None = None) -> dict[str, object]:
    if metric is None or (required_samples is not None and (samples or 0) < required_samples):
        return {"status": "insufficient_data", "value": metric, "samples": samples, "required_samples": required_samples, "minimum": minimum, "maximum": maximum}
    passed = (minimum is None or float(metric) >= minimum) and (maximum is None or float(metric) <= maximum)
    return {"status": "pass" if passed else "block", "value": metric, "samples": samples, "required_samples": required_samples, "minimum": minimum, "maximum": maximum}


def evaluate_window(db: Session, start: datetime, end: datetime) -> dict[str, object]:
    if start.tzinfo is None or end.tzinfo is None or end <= start:
        raise ValueError("Evaluation window must use aware timestamps with end after start")
    start = start.astimezone(UTC)
    end = end.astimezone(UTC)
    if any((start.hour, start.minute, start.second, start.microsecond, end.hour, end.minute, end.second, end.microsecond)):
        raise ValueError("Evaluation window must use UTC midnight boundaries")
    reviews = _latest_reviews(db, start, end)
    complete = [item for item in reviews if item.resolution_status == "complete"]
    adherence_values: list[float] = []
    execution_values: list[float] = []
    pain_weeks = 0
    overload_weeks = 0
    rule_versions: dict[str, int] = {}
    for review in complete:
        snapshot = review.snapshot_json if isinstance(review.snapshot_json, dict) else {}
        metrics = snapshot.get("metrics") if isinstance(snapshot.get("metrics"), dict) else {}
        readiness = snapshot.get("readiness_trends") if isinstance(snapshot.get("readiness_trends"), dict) else {}
        adherence = _number(metrics.get("session_adherence"))
        execution = _number(metrics.get("execution_average"))
        if adherence is not None:
            adherence_values.append(adherence)
        if execution is not None:
            execution_values.append(execution)
        pain_weeks += int((_number(readiness.get("pain_days")) or 0) > 0 or (_number(metrics.get("high_risk_feedback")) or 0) > 0)
        overload_weeks += int((_number(metrics.get("overdone_sessions")) or 0) > 0)
        rule_versions[review.rule_version] = rule_versions.get(review.rule_version, 0) + 1

    progression_count = int(db.scalar(select(func.count()).select_from(TrainingPlanVersion).where(TrainingPlanVersion.created_at >= start, TrainingPlanVersion.created_at < end, TrainingPlanVersion.reason.in_(PROGRESSION_REASONS))) or 0)
    unsafe_progression_count = int(db.scalar(select(func.count()).select_from(TrainingPlanVersion).where(
        TrainingPlanVersion.created_at >= start,
        TrainingPlanVersion.created_at < end,
        TrainingPlanVersion.reason.in_(PROGRESSION_REASONS),
        select(SafetyEscalation.id).where(
            SafetyEscalation.user_id == TrainingPlanVersion.user_id,
            SafetyEscalation.created_at <= TrainingPlanVersion.created_at,
            or_(SafetyEscalation.superseded_at.is_(None), SafetyEscalation.superseded_at > TrainingPlanVersion.created_at),
        ).exists(),
    )) or 0)
    llm_attempts = int(db.scalar(select(func.count()).select_from(CoachLlmAttempt).where(CoachLlmAttempt.created_at >= start, CoachLlmAttempt.created_at < end)) or 0)
    llm_failures = int(db.scalar(select(func.count()).select_from(CoachLlmAttempt).where(CoachLlmAttempt.created_at >= start, CoachLlmAttempt.created_at < end, CoachLlmAttempt.status == "failed")) or 0)
    review_outcomes = {event_type: int(count) for event_type, count in db.execute(select(SafetyReviewEvent.event_type, func.count()).where(SafetyReviewEvent.occurred_at >= start, SafetyReviewEvent.occurred_at < end).group_by(SafetyReviewEvent.event_type)).all()}
    llm_failure_classes = {failure_class or "unknown": int(count) for failure_class, count in db.execute(select(CoachLlmAttempt.failure_class, func.count()).where(CoachLlmAttempt.created_at >= start, CoachLlmAttempt.created_at < end, CoachLlmAttempt.status == "failed").group_by(CoachLlmAttempt.failure_class)).all()}

    metrics = {
        "weekly_review_samples": len(reviews),
        "complete_weekly_review_samples": len(complete),
        "session_adherence": {"average": _average(adherence_values), "samples": len(adherence_values)},
        "completion_quality": {"average": _average(execution_values), "samples": len(execution_values)},
        "pain_flag_weeks": {"count": pain_weeks, "rate": _rate(pain_weeks, len(complete)), "samples": len(complete)},
        "overload_flag_weeks": {"count": overload_weeks, "rate": _rate(overload_weeks, len(complete)), "samples": len(complete)},
        "progression_mutations": progression_count,
        "unsafe_progression_mutations": unsafe_progression_count,
        "unsafe_suggestion_rate": _rate(unsafe_progression_count, progression_count),
        "llm_attempts": llm_attempts,
        "llm_failures": llm_failures,
        "llm_failure_rate": _rate(llm_failures, llm_attempts),
        "retention": {"status": "not_measured"},
        "user_trust": {"status": "not_measured"},
    }
    incidents = {
        "categories": {"unsafe_progression_during_active_safety_case": unsafe_progression_count, "llm_failed_attempt": llm_failures},
        "llm_failure_classes": dict(sorted(llm_failure_classes.items())),
        "weekly_review_rule_versions": dict(sorted(rule_versions.items())),
        "safety_review_outcomes": dict(sorted(review_outcomes.items())),
    }
    gates = {
        "unsafe_suggestion": {"status": "pass" if unsafe_progression_count == 0 else "block", "count": unsafe_progression_count, "maximum": 0},
        "review_coverage": _gate(len(complete), samples=len(complete), required_samples=MIN_COMPLETE_REVIEWS),
        "session_adherence": _gate(metrics["session_adherence"]["average"], minimum=MIN_SESSION_ADHERENCE, samples=len(adherence_values), required_samples=MIN_COMPLETE_REVIEWS),
        "completion_quality": _gate(metrics["completion_quality"]["average"], minimum=MIN_COMPLETION_QUALITY, samples=len(execution_values), required_samples=MIN_EXECUTION_SAMPLES),
        "pain_flags": _gate(metrics["pain_flag_weeks"]["rate"], maximum=MAX_PAIN_FLAG_RATE, samples=len(complete), required_samples=MIN_COMPLETE_REVIEWS),
        "overload_flags": _gate(metrics["overload_flag_weeks"]["rate"], maximum=MAX_OVERLOAD_FLAG_RATE, samples=len(complete), required_samples=MIN_COMPLETE_REVIEWS),
        "llm_reliability": _gate(metrics["llm_failure_rate"], maximum=MAX_LLM_FAILURE_RATE, samples=llm_attempts, required_samples=MIN_LLM_ATTEMPTS),
        "retention": {"status": "insufficient_data", "reason": "not_measured"},
        "user_trust": {"status": "insufficient_data", "reason": "not_measured"},
    }
    safety_gate_names = {"unsafe_suggestion", "pain_flags", "overload_flags", "llm_reliability"}
    safety_statuses = {str(gates[name]["status"]) for name in safety_gate_names}
    safety_release_status = "block" if "block" in safety_statuses else "insufficient_data" if "insufficient_data" in safety_statuses else "pass"
    product_statuses = {str(item["status"]) for name, item in gates.items() if name not in safety_gate_names}
    product_evidence_status = "block" if "block" in product_statuses else "insufficient_data" if "insufficient_data" in product_statuses else "pass"
    status = "block" if "block" in {safety_release_status, product_evidence_status} else "insufficient_data" if "insufficient_data" in {safety_release_status, product_evidence_status} else "pass"
    gates["summary"] = {"status": status, "safety_release_status": safety_release_status, "product_evidence_status": product_evidence_status}
    canonical = {"evaluation_version": EVALUATION_VERSION, "threshold_version": THRESHOLD_VERSION, "window_start": start.isoformat(), "window_end": end.isoformat(), "metrics": metrics, "incidents": incidents, "gates": gates}
    fingerprint = hashlib.sha256(json.dumps(canonical, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {**canonical, "input_fingerprint": fingerprint, "status": status, "disclaimer": "Aggregate persisted evidence only. Insufficient data is not a pass; this report does not establish clinical safety, staffing, retention improvement, or user trust."}


def materialize_evaluation(db: Session, start: datetime, end: datetime) -> CoachEvaluationRun:
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(727506682)"))
    report = evaluate_window(db, start, end)
    existing = db.scalar(select(CoachEvaluationRun).where(CoachEvaluationRun.evaluation_version == EVALUATION_VERSION, CoachEvaluationRun.threshold_version == THRESHOLD_VERSION, CoachEvaluationRun.window_start == datetime.fromisoformat(str(report["window_start"])), CoachEvaluationRun.window_end == datetime.fromisoformat(str(report["window_end"])), CoachEvaluationRun.input_fingerprint == report["input_fingerprint"]))
    if existing is not None:
        return existing
    run = CoachEvaluationRun(id=secrets.token_urlsafe(24), evaluation_version=EVALUATION_VERSION, threshold_version=THRESHOLD_VERSION, window_start=datetime.fromisoformat(str(report["window_start"])), window_end=datetime.fromisoformat(str(report["window_end"])), input_fingerprint=str(report["input_fingerprint"]), status=str(report["status"]), metrics_json=report["metrics"], incidents_json=report["incidents"], gates_json=report["gates"])
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def run_to_dict(run: CoachEvaluationRun) -> dict[str, object]:
    return {"id": run.id, "evaluation_version": run.evaluation_version, "threshold_version": run.threshold_version, "window_start": run.window_start.isoformat(), "window_end": run.window_end.isoformat(), "input_fingerprint": run.input_fingerprint, "status": run.status, "metrics": run.metrics_json, "incidents": run.incidents_json, "gates": run.gates_json, "generated_at": run.generated_at.isoformat(), "disclaimer": "Aggregate persisted evidence only. Insufficient data is not a pass; this report does not establish clinical safety, staffing, retention improvement, or user trust."}
