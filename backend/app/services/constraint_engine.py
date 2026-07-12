from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import date
from typing import Literal


CONSTRAINT_RULE_VERSION = "coach-constraints-v1"


@dataclass(frozen=True)
class HardWorkoutPolicy:
    workout_types: frozenset[str]
    intensities: frozenset[str]
    non_hard_intensities: frozenset[str] = frozenset()
    normalize_case: bool = False


@dataclass(frozen=True)
class ConstraintEvaluation:
    decision: Literal["allowed", "blocked"]
    rule_version: str = CONSTRAINT_RULE_VERSION
    reason: str | None = None
    message: str | None = None

    @property
    def allowed(self) -> bool:
        return self.decision == "allowed"


def is_hard_workout(workout_type: str | None, intensity: str | None, *, policy: HardWorkoutPolicy) -> bool:
    normalized_type = workout_type or ""
    normalized_intensity = intensity or ""
    if policy.normalize_case:
        normalized_type = normalized_type.lower()
        normalized_intensity = normalized_intensity.lower()
    if normalized_intensity in policy.non_hard_intensities:
        return False
    return normalized_type in policy.workout_types or normalized_intensity in policy.intensities


def dates_within_days(first_date: date, second_date: date, *, max_days: int, absolute: bool = False) -> bool:
    if max_days < 0:
        raise ValueError("max_days cannot be negative")
    delta = (second_date - first_date).days
    if absolute:
        delta = abs(delta)
    return 0 <= delta <= max_days


def validate_readiness_action_target(
    *,
    action: str,
    prescription: object,
    applicable_actions: Collection[str],
    completed_activity_id: int | None,
    status: str | None,
    workout_is_hard: bool,
    block_target_rpe_maxes: Iterable[int | float | None],
) -> ConstraintEvaluation:
    if action not in applicable_actions or not isinstance(prescription, dict):
        return ConstraintEvaluation("blocked", reason="action_not_applicable", message="Today's readiness recommendation cannot be applied")
    if completed_activity_id is not None or status not in {"planned", "rescheduled"}:
        return ConstraintEvaluation("blocked", reason="workout_not_mutable", message="Today's workout is no longer mutable")
    if action == "shorten_easy":
        if workout_is_hard or any((value or 0) > 5 for value in block_target_rpe_maxes):
            return ConstraintEvaluation("blocked", reason="safety_blocks_action", message="Today's workout cannot be safely shortened automatically")
        if prescription.get("distance_km") is None and prescription.get("duration_seconds") is None:
            return ConstraintEvaluation("blocked", reason="safety_blocks_action", message="Today's workout has no measurable target to shorten")
    return ConstraintEvaluation("allowed")


def validate_coach_action_target(
    *,
    action: str,
    target_date: date | None,
    current_date: date | None,
    status: str | None,
    completed_activity_id: int | None,
    workout_is_hard: bool,
    other_hard_workout_dates: Iterable[date],
    reason: str | None = None,
    today: date | None = None,
    plan_end_date: date | None = None,
    hard_spacing_days: int = 2,
) -> ConstraintEvaluation:
    if action not in {"skip", "reschedule"}:
        return ConstraintEvaluation("blocked", reason="action_not_applicable", message="Coach action is not supported")
    if completed_activity_id is not None or status == "done":
        return ConstraintEvaluation("blocked", reason="workout_not_mutable", message="Completed workout is no longer mutable")
    if action == "skip":
        if status not in {"planned", "rescheduled"}:
            return ConstraintEvaluation("blocked", reason="workout_not_mutable", message="Only a planned workout can be skipped")
        return ConstraintEvaluation("allowed")
    if reason in {"pain", "illness"}:
        return ConstraintEvaluation("blocked", reason="safety_blocks_action", message="Pain or illness cannot be handled by moving the planned load")
    if target_date is None:
        return ConstraintEvaluation("blocked", reason="target_date_required", message="A target date is required to reschedule a workout")
    if today is not None and target_date < today:
        return ConstraintEvaluation("blocked", reason="target_date_in_past", message="A workout cannot be rescheduled into the past")
    if plan_end_date is not None and target_date > plan_end_date:
        return ConstraintEvaluation("blocked", reason="target_date_outside_plan", message="A workout cannot be rescheduled beyond the current plan horizon")
    if current_date == target_date:
        return ConstraintEvaluation("blocked", reason="no_effect", message="The workout is already scheduled for this date")
    if status not in {"planned", "rescheduled", "missed", "skipped"}:
        return ConstraintEvaluation("blocked", reason="workout_not_mutable", message="Workout cannot be rescheduled from its current status")
    if workout_is_hard and any(dates_within_days(target_date, item, max_days=hard_spacing_days, absolute=True) for item in other_hard_workout_dates):
        return ConstraintEvaluation("blocked", reason="hard_session_spacing", message="Hard workouts must not be scheduled within the protected recovery window")
    return ConstraintEvaluation("allowed")
