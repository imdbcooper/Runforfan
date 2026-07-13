import hashlib
import json
import secrets
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.orm.attributes import set_committed_value

from app.models import AthleteProfile, DailyReadinessCheckIn, PlanRollbackPreview, TrainingPlan, TrainingPlanRecommendationAudit, TrainingPlanVersion, TrainingPlanWorkout, TrainingPlanWorkoutBlock, User
from app.services.audit import log_audit_event
from app.services.coaching_events import record_coaching_event
from app.services.constraint_engine import CONSTRAINT_RULE_VERSION, dates_within_days, is_hard_workout
from app.services.plan_versions import action_plan_snapshot, create_plan_version, json_safe
from app.services.planning import PLANNING_HARD_POLICY, today_for_user
from app.services.profile import safety_check


ROLLBACK_PREVIEW_TTL_MINUTES = 10
ROLLBACK_REASONS = {"auto_adaptation", "daily_readiness_action", "coach_action_skip", "coach_action_reschedule", "weekly_strategy_deload", "weekly_strategy_resume", "weekly_strategy_conservative_progression"}
WORKOUT_FIELDS = (
    "scheduled_date",
    "status",
    "workout_type",
    "title",
    "distance_km",
    "duration_seconds",
    "intensity",
    "description",
)
BLOCK_FIELDS = (
    "block_index",
    "block_type",
    "repeat_count",
    "target_distance_km",
    "target_duration_seconds",
    "target_pace_min_seconds_per_km",
    "target_pace_max_seconds_per_km",
    "target_hr_min_bpm",
    "target_hr_max_bpm",
    "target_rpe_min",
    "target_rpe_max",
    "description",
)
REQUIRED_WORKOUT_FIELDS = {"id", "completed_activity_id", "blocks", *WORKOUT_FIELDS}
WORKOUT_STATUSES = {"planned", "done", "missed", "skipped", "rescheduled"}


class PlanRollbackConflict(ValueError):
    def __init__(self, message: str, reason: str):
        super().__init__(message)
        self.reason = reason


def snapshot_fingerprint(snapshot: dict[str, object]) -> str:
    encoded = json.dumps(json_safe(snapshot), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def valid_optional_string(value: object, *, max_length: int, allow_empty: bool = True) -> bool:
    return value is None or (isinstance(value, str) and len(value) <= max_length and (allow_empty or bool(value.strip())))


def valid_optional_int(value: object, *, minimum: int, maximum: int) -> bool:
    return value is None or (isinstance(value, int) and not isinstance(value, bool) and minimum <= value <= maximum)


def valid_optional_number(value: object, *, minimum: float, maximum: float) -> bool:
    return value is None or (isinstance(value, int | float) and not isinstance(value, bool) and minimum <= float(value) <= maximum)


def validate_action_snapshot(snapshot: dict[str, object]) -> None:
    if snapshot.get("schema_version") != "action-plan-state-v1" or not isinstance(snapshot.get("plan_id"), int):
        raise PlanRollbackConflict("Plan version has an unsupported action snapshot", "rollback_not_supported")
    workouts = snapshot.get("workouts")
    if not isinstance(workouts, list):
        raise PlanRollbackConflict("Plan version has an invalid workout snapshot", "rollback_not_supported")
    workout_ids: set[int] = set()
    for workout in workouts:
        if not isinstance(workout, dict) or not REQUIRED_WORKOUT_FIELDS.issubset(workout):
            raise PlanRollbackConflict("Plan version has an incomplete workout snapshot", "rollback_not_supported")
        workout_id = workout.get("id")
        if not isinstance(workout_id, int) or workout_id in workout_ids:
            raise PlanRollbackConflict("Plan version has invalid workout identities", "rollback_not_supported")
        workout_ids.add(workout_id)
        if workout.get("scheduled_date") is not None:
            try:
                date.fromisoformat(workout["scheduled_date"])
            except (TypeError, ValueError):
                raise PlanRollbackConflict("Plan version has an invalid workout date", "rollback_not_supported") from None
        if workout.get("status") not in WORKOUT_STATUSES:
            raise PlanRollbackConflict("Plan version has an invalid workout status", "rollback_not_supported")
        completed_activity_id = workout.get("completed_activity_id")
        if completed_activity_id is not None and (not isinstance(completed_activity_id, int) or isinstance(completed_activity_id, bool) or completed_activity_id <= 0):
            raise PlanRollbackConflict("Plan version has an invalid activity link", "rollback_not_supported")
        if not valid_optional_string(workout.get("workout_type"), max_length=64, allow_empty=False):
            raise PlanRollbackConflict("Plan version has an invalid workout type", "rollback_not_supported")
        if not valid_optional_string(workout.get("title"), max_length=255, allow_empty=False):
            raise PlanRollbackConflict("Plan version has an invalid workout title", "rollback_not_supported")
        if not valid_optional_number(workout.get("distance_km"), minimum=0, maximum=250):
            raise PlanRollbackConflict("Plan version has an invalid workout distance", "rollback_not_supported")
        if not valid_optional_int(workout.get("duration_seconds"), minimum=1, maximum=86400):
            raise PlanRollbackConflict("Plan version has an invalid workout duration", "rollback_not_supported")
        if not valid_optional_string(workout.get("intensity"), max_length=64):
            raise PlanRollbackConflict("Plan version has an invalid workout intensity", "rollback_not_supported")
        if not valid_optional_string(workout.get("description"), max_length=4000):
            raise PlanRollbackConflict("Plan version has an invalid workout description", "rollback_not_supported")
        blocks = workout.get("blocks")
        if not isinstance(blocks, list):
            raise PlanRollbackConflict("Plan version has an invalid block snapshot", "rollback_not_supported")
        block_indexes: set[int] = set()
        for block in blocks:
            if not isinstance(block, dict) or not set(BLOCK_FIELDS).issubset(block):
                raise PlanRollbackConflict("Plan version has an incomplete block snapshot", "rollback_not_supported")
            block_index = block.get("block_index")
            if not isinstance(block_index, int) or block_index < 0 or block_index in block_indexes:
                raise PlanRollbackConflict("Plan version has invalid block indexes", "rollback_not_supported")
            block_indexes.add(block_index)
            if not valid_optional_string(block.get("block_type"), max_length=64, allow_empty=False):
                raise PlanRollbackConflict("Plan version has an invalid block type", "rollback_not_supported")
            if not valid_optional_int(block.get("repeat_count"), minimum=1, maximum=1000):
                raise PlanRollbackConflict("Plan version has an invalid block repeat count", "rollback_not_supported")
            if not valid_optional_number(block.get("target_distance_km"), minimum=0, maximum=250):
                raise PlanRollbackConflict("Plan version has an invalid block distance", "rollback_not_supported")
            for field in ("target_duration_seconds", "target_pace_min_seconds_per_km", "target_pace_max_seconds_per_km"):
                if not valid_optional_int(block.get(field), minimum=1, maximum=86400):
                    raise PlanRollbackConflict(f"Plan version has an invalid block field: {field}", "rollback_not_supported")
            for field in ("target_hr_min_bpm", "target_hr_max_bpm"):
                if not valid_optional_int(block.get(field), minimum=30, maximum=240):
                    raise PlanRollbackConflict(f"Plan version has an invalid block field: {field}", "rollback_not_supported")
            for field in ("target_rpe_min", "target_rpe_max"):
                if not valid_optional_int(block.get(field), minimum=0, maximum=10):
                    raise PlanRollbackConflict(f"Plan version has an invalid block field: {field}", "rollback_not_supported")
            if not valid_optional_string(block.get("description"), max_length=4000):
                raise PlanRollbackConflict("Plan version has an invalid block description", "rollback_not_supported")
            for lower_field, upper_field in (
                ("target_pace_min_seconds_per_km", "target_pace_max_seconds_per_km"),
                ("target_hr_min_bpm", "target_hr_max_bpm"),
                ("target_rpe_min", "target_rpe_max"),
            ):
                lower = block.get(lower_field)
                upper = block.get(upper_field)
                if lower is not None and upper is not None and lower > upper:
                    raise PlanRollbackConflict(f"Plan version has an inverted block range: {lower_field}", "rollback_not_supported")


def load_plan_for_rollback(db: Session, user: User, plan_id: int) -> TrainingPlan:
    db.scalar(select(User.id).where(User.id == user.id).with_for_update())
    plan = db.scalar(
        select(TrainingPlan)
        .where(TrainingPlan.id == plan_id, TrainingPlan.user_id == user.id, TrainingPlan.status == "active")
        .options(
            selectinload(TrainingPlan.workouts).selectinload(TrainingPlanWorkout.completed_activity),
            selectinload(TrainingPlan.workouts).selectinload(TrainingPlanWorkout.feedback),
            selectinload(TrainingPlan.workouts).selectinload(TrainingPlanWorkout.blocks),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if plan is None:
        raise PlanRollbackConflict("Plan is not current or does not exist", "plan_not_found")
    workouts = list(db.scalars(
        select(TrainingPlanWorkout)
        .where(TrainingPlanWorkout.plan_id == plan.id)
        .options(selectinload(TrainingPlanWorkout.completed_activity), selectinload(TrainingPlanWorkout.feedback), selectinload(TrainingPlanWorkout.blocks))
        .order_by(TrainingPlanWorkout.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ))
    set_committed_value(plan, "workouts", workouts)
    return plan


def version_for_rollback(db: Session, user: User, plan_id: int, version_id: int) -> TrainingPlanVersion:
    version = db.scalar(
        select(TrainingPlanVersion)
        .where(TrainingPlanVersion.id == version_id, TrainingPlanVersion.plan_id == plan_id, TrainingPlanVersion.user_id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if version is None:
        raise PlanRollbackConflict("Plan version does not exist", "version_not_found")
    if version.reason not in ROLLBACK_REASONS or version.pre_snapshot_json is None or version.post_snapshot_json is None:
        raise PlanRollbackConflict("This legacy or non-action version cannot be rolled back", "rollback_not_supported")
    validate_action_snapshot(version.pre_snapshot_json)
    validate_action_snapshot(version.post_snapshot_json)
    if version.pre_snapshot_json.get("plan_id") != plan_id or version.post_snapshot_json.get("plan_id") != plan_id:
        raise PlanRollbackConflict("Plan version does not match this plan", "rollback_not_supported")
    existing = db.scalar(select(TrainingPlanVersion.id).where(TrainingPlanVersion.rollback_of_version_id == version.id))
    if existing is not None:
        raise PlanRollbackConflict("This plan version has already been rolled back", "already_rolled_back")
    return version


def snapshot_changes(before: dict[str, object], after: dict[str, object]) -> list[dict[str, object]]:
    before_workouts = {item["id"]: item for item in before.get("workouts", []) if isinstance(item, dict) and isinstance(item.get("id"), int)}
    after_workouts = {item["id"]: item for item in after.get("workouts", []) if isinstance(item, dict) and isinstance(item.get("id"), int)}
    if before_workouts.keys() != after_workouts.keys():
        raise PlanRollbackConflict("Rollback cannot add or remove workouts", "workout_set_changed")
    changes = []
    for workout_id in sorted(before_workouts):
        current = before_workouts[workout_id]
        target = after_workouts[workout_id]
        for field in (*WORKOUT_FIELDS, "blocks"):
            if current.get(field) != target.get(field):
                changes.append({"workout_id": workout_id, "field": field, "before": current.get(field), "after": target.get(field)})
    return changes


def validate_rollback_target(db: Session, user: User, plan: TrainingPlan, target_snapshot: dict[str, object]) -> None:
    current_date = today_for_user(db, user)
    profile = db.scalar(select(AthleteProfile).where(AthleteProfile.user_id == user.id))
    checkin = db.scalar(
        select(DailyReadinessCheckIn).where(DailyReadinessCheckIn.user_id == user.id, DailyReadinessCheckIn.checkin_date == current_date)
    )
    target_workouts = [item for item in target_snapshot.get("workouts", []) if isinstance(item, dict)]
    current_by_id = {item.id: item for item in plan.workouts}
    changed_workout_ids = {
        int(change["workout_id"])
        for change in snapshot_changes(action_plan_snapshot(plan), target_snapshot)
        if isinstance(change.get("workout_id"), int)
    }
    current_snapshot = action_plan_snapshot(plan)
    current_snapshot_by_id = {item["id"]: item for item in current_snapshot["workouts"]}
    profile_safety = safety_check(profile) if profile is not None else {"conservative_mode": True}
    for target in target_workouts:
        workout_id = target.get("id")
        current = current_by_id.get(workout_id)
        if current is None:
            raise PlanRollbackConflict("Rollback target no longer matches this plan", "workout_set_changed")
        if workout_id in changed_workout_ids and (current.completed_activity_id is not None or target.get("completed_activity_id") is not None):
            raise PlanRollbackConflict("Completed workouts cannot be changed by rollback", "completion_conflict")
        target_date = date.fromisoformat(target["scheduled_date"]) if isinstance(target.get("scheduled_date"), str) else None
        if workout_id in changed_workout_ids and target.get("status") in {"planned", "rescheduled"} and target_date is not None and target_date < current_date:
            raise PlanRollbackConflict("Rollback cannot restore planned load into the past", "target_date_in_past")
        if workout_id in changed_workout_ids and target_date is not None and plan.target_date is not None and target_date > plan.target_date:
            raise PlanRollbackConflict("Rollback cannot restore load beyond the plan horizon", "target_date_outside_plan")
        current_state = current_snapshot_by_id.get(workout_id) or {}
        increases_load = (
            target.get("status") in {"planned", "rescheduled"}
            and (
                current_state.get("status") not in {"planned", "rescheduled"}
                or float(target.get("distance_km") or 0) > float(current_state.get("distance_km") or 0)
                or int(target.get("duration_seconds") or 0) > int(current_state.get("duration_seconds") or 0)
                or is_hard_workout(str(target.get("workout_type") or ""), str(target.get("intensity") or ""), policy=PLANNING_HARD_POLICY)
            )
        )
        if workout_id in changed_workout_ids and increases_load:
            if profile_safety.get("conservative_mode"):
                raise PlanRollbackConflict("Current profile restrictions block restoring this load", "safety_blocks_rollback")
            max_duration = getattr(profile, "max_run_duration_minutes", None)
            if max_duration is not None and int(target.get("duration_seconds") or 0) > int(max_duration) * 60:
                raise PlanRollbackConflict("Rollback exceeds the current maximum run duration", "safety_blocks_rollback")

    restores_load = any(
        current_by_id.get(item.get("id")) is not None
        and current_by_id[item["id"]].status not in {"planned", "rescheduled"}
        and item.get("status") in {"planned", "rescheduled"}
        for item in target_workouts
    )
    if restores_load and (
        getattr(profile, "recovery_status", "normal") in {"tired", "strained", "injured"}
        or bool(getattr(checkin, "pain", False))
        or bool(getattr(checkin, "illness_symptoms", False))
    ):
        raise PlanRollbackConflict("Current recovery restrictions block restoring planned load", "safety_blocks_rollback")

    hard_dates = []
    for item in target_workouts:
        item_date = date.fromisoformat(item["scheduled_date"]) if isinstance(item.get("scheduled_date"), str) else None
        if item.get("status") in {"planned", "rescheduled"} and item_date is not None and is_hard_workout(str(item.get("workout_type") or ""), str(item.get("intensity") or ""), policy=PLANNING_HARD_POLICY):
            hard_dates.append((int(item["id"]), item_date))
    for index, (workout_id, item_date) in enumerate(hard_dates):
        if any(dates_within_days(item_date, other_date, max_days=2, absolute=True) for other_id, other_date in hard_dates[index + 1:] if other_id != workout_id):
            raise PlanRollbackConflict("Rollback would stack hard workouts inside the protected recovery window", "hard_session_spacing")


def build_rollback_preview(preview_id: str, expires_at: datetime, version: TrainingPlanVersion, current: dict[str, object]) -> dict[str, object]:
    target = version.pre_snapshot_json or {}
    changes = snapshot_changes(current, target)
    if not changes:
        raise PlanRollbackConflict("Rollback would not change the current plan", "no_effect")
    return json_safe({
        "preview_id": preview_id,
        "expires_at": expires_at,
        "plan_id": version.plan_id,
        "version_id": version.id,
        "version_number": version.version_number,
        "rule_version": CONSTRAINT_RULE_VERSION,
        "changes": changes,
        "summary": f"A compensating version will reverse plan version v{version.version_number}; history will remain unchanged.",
    })


def create_plan_rollback_preview(db: Session, user: User, plan_id: int, version_id: int) -> dict[str, object]:
    plan = load_plan_for_rollback(db, user, plan_id)
    version = version_for_rollback(db, user, plan_id, version_id)
    current = action_plan_snapshot(plan)
    if current != version.post_snapshot_json:
        raise PlanRollbackConflict("Plan changed after this version; rollback is stale", "rollback_conflict")
    validate_rollback_target(db, user, plan, version.pre_snapshot_json or {})
    preview_id = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(minutes=ROLLBACK_PREVIEW_TTL_MINUTES)
    payload = build_rollback_preview(preview_id, expires_at, version, current)
    db.add(PlanRollbackPreview(
        id=preview_id,
        user_id=user.id,
        plan_id=plan.id,
        version_id=version.id,
        preview_snapshot=payload,
        state_fingerprint=snapshot_fingerprint(current),
        expires_at=expires_at,
    ))
    db.commit()
    return payload


def restore_snapshot(db: Session, plan: TrainingPlan, snapshot: dict[str, object]) -> None:
    target_by_id = {item["id"]: item for item in snapshot.get("workouts", []) if isinstance(item, dict) and isinstance(item.get("id"), int)}
    changes = snapshot_changes(action_plan_snapshot(plan), snapshot)
    changed_fields_by_workout: dict[int, set[str]] = {}
    for change in changes:
        workout_id = change.get("workout_id")
        if isinstance(workout_id, int):
            changed_fields_by_workout.setdefault(workout_id, set()).add(str(change["field"]))
    for workout in plan.workouts:
        changed_fields = changed_fields_by_workout.get(workout.id, set())
        if not changed_fields:
            continue
        target = target_by_id[workout.id]
        for field in WORKOUT_FIELDS:
            if field not in changed_fields:
                continue
            value = target.get(field)
            if field == "scheduled_date" and isinstance(value, str):
                value = date.fromisoformat(value)
            setattr(workout, field, value)
        if "blocks" in changed_fields:
            existing_by_index = {block.block_index: block for block in workout.blocks}
            target_indexes = {block_snapshot["block_index"] for block_snapshot in target.get("blocks") or []}
            for block_index, block in existing_by_index.items():
                if block_index not in target_indexes:
                    workout.blocks.remove(block)
                    db.delete(block)
            for block_snapshot in target.get("blocks") or []:
                block = existing_by_index.get(block_snapshot["block_index"])
                if block is None:
                    block = TrainingPlanWorkoutBlock()
                    workout.blocks.append(block)
                for field in BLOCK_FIELDS:
                    setattr(block, field, block_snapshot.get(field))
    db.flush()


def apply_plan_rollback_preview(db: Session, user: User, preview_id: str) -> dict[str, object]:
    db.scalar(select(User.id).where(User.id == user.id).with_for_update())
    preview = db.scalar(
        select(PlanRollbackPreview)
        .where(PlanRollbackPreview.id == preview_id, PlanRollbackPreview.user_id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    now = datetime.now(UTC)
    if preview is None:
        raise PlanRollbackConflict("Rollback preview is invalid or expired", "preview_invalid_or_expired")
    if preview.applied_at is not None and preview.applied_response_json:
        return {**preview.applied_response_json, "status": "already_applied"}
    if preview.expires_at < now:
        raise PlanRollbackConflict("Rollback preview is invalid or expired", "preview_invalid_or_expired")
    plan = load_plan_for_rollback(db, user, preview.plan_id)
    preview = db.scalar(select(PlanRollbackPreview).where(PlanRollbackPreview.id == preview_id, PlanRollbackPreview.user_id == user.id).with_for_update().execution_options(populate_existing=True))
    if preview is None:
        raise PlanRollbackConflict("Rollback preview is invalid or expired", "preview_invalid_or_expired")
    if preview.applied_at is not None and preview.applied_response_json:
        return {**preview.applied_response_json, "status": "already_applied"}
    version = version_for_rollback(db, user, plan.id, preview.version_id)
    current = action_plan_snapshot(plan)
    if current != version.post_snapshot_json or snapshot_fingerprint(current) != preview.state_fingerprint:
        raise PlanRollbackConflict("Plan changed after the preview; create a new rollback preview", "rollback_conflict")
    validate_rollback_target(db, user, plan, version.pre_snapshot_json or {})
    changes = list(preview.preview_snapshot.get("changes") or [])
    restore_snapshot(db, plan, version.pre_snapshot_json or {})
    rollback_version = create_plan_version(
        db,
        user,
        plan,
        "compensating_rollback",
        f"Reversed plan version v{version.version_number}",
        pre_snapshot=current,
        rollback_of_version_id=version.id,
    )
    db.flush()
    audit = TrainingPlanRecommendationAudit(
        user_id=user.id,
        plan_id=plan.id,
        action="rollback_plan_version",
        status="applied",
        recommendations_snapshot={"version_id": version.id, "version_number": version.version_number, "rule_version": CONSTRAINT_RULE_VERSION},
        preview_changes={"preview_id": preview.id, "changes": changes},
        applied_changes={"rollback_version_id": rollback_version.id, "changes": changes},
    )
    db.add(audit)
    db.flush()
    event = record_coaching_event(
        db,
        user_id=user.id,
        event_type="plan_version_rolled_back",
        category="outcome",
        source="plan_rollback_preview",
        plan_id=plan.id,
        correlation_id=preview.id,
        payload={"version_id": version.id, "rollback_version_id": rollback_version.id, "rule_version": CONSTRAINT_RULE_VERSION, "changes": changes},
    )
    db.flush()
    audit_log = log_audit_event(db, user.id, "plan_version_rolled_back", "training_plan", plan.id, {"preview_id": preview.id, "version_id": version.id, "rollback_version_id": rollback_version.id, "recommendation_audit_id": audit.id, "coaching_event_id": event.id})
    db.flush()
    response = json_safe({
        "status": "applied",
        "preview_id": preview.id,
        "plan_id": plan.id,
        "version_id": version.id,
        "rollback_version_id": rollback_version.id,
        "rollback_version_number": rollback_version.version_number,
        "recommendation_audit_id": audit.id,
        "audit_log_id": audit_log.id,
        "coaching_event_id": event.id,
        "summary": preview.preview_snapshot["summary"],
    })
    preview.applied_at = now
    preview.rollback_version_id = rollback_version.id
    preview.recommendation_audit_id = audit.id
    preview.audit_log_id = audit_log.id
    preview.coaching_event_id = event.id
    preview.applied_response_json = response
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise PlanRollbackConflict("This plan version has already been rolled back", "already_rolled_back") from error
    return response
