from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import AthleteProfile, CoachingEvent, RecoverySignalObservation, TrainingPlan, TrainingPlanVersion, TrainingPlanWorkout, User
from app.services.athlete_state import resolved_timezone
from app.services.plan_versions import json_safe, plan_snapshot
from app.services.recovery_signals import RECOVERY_RULE_VERSION, observation_input


HISTORICAL_RESOLVER_VERSION = "historical-state-v2"


class HistoricalStateConflict(ValueError):
    def __init__(self, message: str, reason: str):
        super().__init__(message)
        self.reason = reason


def utc_value(value: datetime) -> datetime:
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).astimezone(UTC)


def local_week_bounds(profile: AthleteProfile | None, as_of_at: datetime, requested_week_start: date | None = None) -> tuple[date, date, str, ZoneInfo]:
    timezone_name, timezone = resolved_timezone(profile)
    current_local_date = utc_value(as_of_at).astimezone(timezone).date()
    current_week_start = current_local_date - timedelta(days=current_local_date.weekday())
    week_start = requested_week_start or current_week_start - timedelta(days=7)
    if week_start.weekday() != 0:
        raise ValueError("week_start must be a Monday")
    if week_start >= current_week_start:
        raise ValueError("Weekly Review is available only for completed local weeks")
    return week_start, week_start + timedelta(days=6), timezone_name, timezone


def utc_week_interval(week_start: date, week_end: date, timezone: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(week_start, time.min, tzinfo=timezone).astimezone(UTC)
    end = datetime.combine(week_end + timedelta(days=1), time.min, tzinfo=timezone).astimezone(UTC)
    return start, end


def latest_historical_plan_snapshot(db: Session, user: User, cutoff: datetime, *, inclusive: bool = True) -> tuple[dict[str, object] | None, dict[str, object]]:
    version_boundary = TrainingPlanVersion.created_at <= cutoff if inclusive else TrainingPlanVersion.created_at < cutoff
    versions = list(db.scalars(
        select(TrainingPlanVersion)
        .where(TrainingPlanVersion.user_id == user.id, version_boundary)
        .order_by(TrainingPlanVersion.created_at.desc(), TrainingPlanVersion.id.desc())
    ))
    latest_by_plan: dict[int, TrainingPlanVersion] = {}
    for version in versions:
        latest_by_plan.setdefault(version.plan_id, version)
    for version in sorted(latest_by_plan.values(), key=lambda item: (item.created_at, item.id), reverse=True):
        snapshot = version.snapshot_json
        if isinstance(snapshot, dict) and snapshot.get("status") == "active" and isinstance(snapshot.get("workouts"), list):
            return json_safe(snapshot), {
                "status": "complete",
                "plan_id": version.plan_id,
                "plan_version_id": version.id,
                "plan_version_number": version.version_number,
                "resolved_from": "plan_version",
                "limitations": [],
            }

    plan = db.scalar(
        select(TrainingPlan)
        .where(TrainingPlan.user_id == user.id, TrainingPlan.status == "active", TrainingPlan.created_at <= cutoff)
        .options(selectinload(TrainingPlan.workouts).selectinload(TrainingPlanWorkout.blocks))
        .order_by(TrainingPlan.created_at.desc(), TrainingPlan.id.desc())
        .limit(1)
    )
    if plan is None:
        return None, {
            "status": "partial_legacy",
            "plan_id": None,
            "plan_version_id": None,
            "plan_version_number": None,
            "resolved_from": "none",
            "limitations": ["No immutable active-plan snapshot was available at the historical cutoff."],
        }
    return plan_snapshot(plan), {
        "status": "partial_legacy",
        "plan_id": plan.id,
        "plan_version_id": None,
        "plan_version_number": None,
        "resolved_from": "current_plan_fallback",
        "limitations": ["The plan predates complete version-ledger coverage; current mutable values are shown as partial legacy evidence."],
    }


def apply_plan_events(workouts: list[dict[str, object]], events: list[dict[str, object]]) -> list[dict[str, object]]:
    by_id = {item.get("id"): dict(item) for item in workouts if isinstance(item.get("id"), int)}
    for event in events:
        workout = by_id.get(event.get("workout_id"))
        if workout is None:
            continue
        event_type = event.get("event_type")
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if event_type == "workout_completed":
            workout["status"] = "done"
            workout["completed_activity_id"] = event.get("activity_id")
            workout["actual"] = {
                "activity_id": event.get("activity_id"),
                "distance_km": payload.get("actual_distance_km"),
                "duration_seconds": payload.get("actual_duration_seconds"),
            }
        elif event_type == "workout_missed":
            workout["status"] = "missed"
        elif event_type == "workout_completion_removed":
            workout["status"] = str(payload.get("status") or "planned")
            workout["completed_activity_id"] = None
            workout["actual"] = None
        elif event_type == "coach_action_applied":
            for change in payload.get("changes") or []:
                if isinstance(change, dict) and change.get("field") in {"scheduled_date", "status"}:
                    workout[str(change["field"])] = change.get("after")
        elif event_type == "workout_feedback_saved":
            workout["feedback"] = payload.get("feedback") if isinstance(payload.get("feedback"), dict) else None
            workout["execution"] = payload.get("execution_score") if isinstance(payload.get("execution_score"), dict) else None
    return sorted(by_id.values(), key=lambda item: (str(item.get("scheduled_date") or ""), int(item.get("id") or 0)))


def plan_changes(before: list[dict[str, object]], after: list[dict[str, object]]) -> list[dict[str, object]]:
    before_by_id = {item.get("id"): item for item in before if isinstance(item.get("id"), int)}
    after_by_id = {item.get("id"): item for item in after if isinstance(item.get("id"), int)}
    changes = []
    for workout_id in sorted(before_by_id.keys() | after_by_id.keys()):
        first = before_by_id.get(workout_id) or {}
        last = after_by_id.get(workout_id) or {}
        for field in ("scheduled_date", "status", "workout_type", "distance_km", "duration_seconds", "intensity"):
            if first.get(field) != last.get(field):
                changes.append({"workout_id": workout_id, "field": field, "before": first.get(field), "after": last.get(field)})
    return changes


def resolve_historical_week(
    db: Session,
    user: User,
    *,
    as_of_at: datetime,
    requested_week_start: date | None = None,
) -> dict[str, object]:
    cutoff = utc_value(as_of_at)
    profile = db.scalar(
        select(AthleteProfile)
        .where(AthleteProfile.user_id == user.id, AthleteProfile.created_at <= cutoff)
        .order_by(AthleteProfile.id.desc())
        .limit(1)
    )
    profile_at_cutoff = profile if profile is None or profile.updated_at is None or utc_value(profile.updated_at) <= cutoff else None
    week_start, week_end, timezone_name, timezone = local_week_bounds(profile_at_cutoff, cutoff, requested_week_start)
    interval_start, interval_end = utc_week_interval(week_start, week_end, timezone)
    if profile_at_cutoff is not None and profile_at_cutoff.updated_at and utc_value(profile_at_cutoff.updated_at) > interval_start:
        raise HistoricalStateConflict(
            "Historical athlete timezone and safety profile cannot be reconstructed because the profile changed after the reviewed week began",
            "historical_profile_unreconstructable",
        )
    end_snapshot, end_resolution = latest_historical_plan_snapshot(db, user, min(cutoff, interval_end), inclusive=cutoff < interval_end)
    start_snapshot, start_resolution = latest_historical_plan_snapshot(db, user, min(cutoff, interval_start))
    if end_snapshot is None:
        end_snapshot = start_snapshot
        end_resolution = start_resolution
    if start_snapshot is None or (end_snapshot and start_snapshot.get("id") != end_snapshot.get("id")):
        start_snapshot = end_snapshot
        start_resolution = {
            **end_resolution,
            "status": "partial_legacy",
            "limitations": [
                *(end_resolution.get("limitations") or []),
                "The active plan at the beginning of the reviewed week could not be reconstructed exactly.",
            ],
        }

    raw_events = list(db.scalars(
        select(CoachingEvent)
        .where(
            CoachingEvent.user_id == user.id,
            CoachingEvent.created_at <= cutoff,
        )
        .order_by(CoachingEvent.occurred_at.asc(), CoachingEvent.id.asc())
    ))
    events = [
        json_safe({
            "id": event.id,
            "event_type": event.event_type,
            "source": event.source,
            "occurred_at": event.occurred_at,
            "recorded_at": event.created_at,
            "plan_id": event.plan_id,
            "workout_id": event.workout_id,
            "activity_id": event.activity_id,
            "checkin_id": event.checkin_id,
            "feedback_id": event.feedback_id,
            "payload": event.payload_json or {},
        })
        for event in raw_events
    ]
    plan_id = end_resolution.get("plan_id")
    plan_events = [
        event for event in events
        if (plan_id is None or event.get("plan_id") in {None, plan_id})
        and utc_value(datetime.fromisoformat(str(event["occurred_at"]))) <= cutoff
    ]
    start_workouts = list(start_snapshot.get("workouts") or []) if start_snapshot else []
    end_workouts = list(end_snapshot.get("workouts") or []) if end_snapshot else []
    planned_review_workouts = [
        item for item in start_workouts
        if isinstance(item.get("scheduled_date"), str) and week_start <= date.fromisoformat(str(item["scheduled_date"])) <= week_end
    ]
    effective_review_workouts = [
        item for item in end_workouts
        if isinstance(item.get("scheduled_date"), str) and week_start <= date.fromisoformat(str(item["scheduled_date"])) <= week_end
    ]
    review_candidates = {int(item["id"]): item for item in [*planned_review_workouts, *effective_review_workouts] if isinstance(item.get("id"), int)}
    overlay_events = [
        event for event in plan_events
        if utc_value(datetime.fromisoformat(str(event["occurred_at"]))) < interval_end
        or (
            event.get("workout_id") in review_candidates
            and event.get("event_type") in {"workout_completion_removed", "workout_feedback_saved", "workout_missed", "pain_reported", "illness_reported"}
        )
    ]
    overlaid_review_workouts = apply_plan_events(list(review_candidates.values()), overlay_events)
    review_workouts = [
        item for item in overlaid_review_workouts
        if item.get("status") in {"done", "missed", "skipped"}
        or (isinstance(item.get("scheduled_date"), str) and week_start <= date.fromisoformat(str(item["scheduled_date"])) <= week_end)
    ]
    target_week_start = week_end + timedelta(days=1)
    target_week_end = target_week_start + timedelta(days=6)
    target_workouts = [
        item for item in (list(end_snapshot.get("workouts") or []) if end_snapshot else [])
        if isinstance(item.get("scheduled_date"), str) and target_week_start <= date.fromisoformat(str(item["scheduled_date"])) <= target_week_end
    ]
    in_week_checkin_ids = set()
    for event in events:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        checkin_date = payload.get("checkin_date") if event.get("event_type") == "readiness_checkin_saved" else None
        if not isinstance(checkin_date, str):
            continue
        try:
            if week_start <= date.fromisoformat(checkin_date) <= week_end:
                if isinstance(event.get("checkin_id"), int):
                    in_week_checkin_ids.add(event["checkin_id"])
        except ValueError:
            continue
    user_level_event_types = {"readiness_checkin_saved", "pain_reported", "illness_reported"}
    workout_event_types = {"workout_completed", "workout_completion_removed", "workout_feedback_saved", "workout_missed"}
    week_events = []
    for event in events:
        occurred_at = utc_value(datetime.fromisoformat(str(event["occurred_at"])))
        if occurred_at > cutoff:
            continue
        event_type = event.get("event_type")
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        checkin_date = payload.get("checkin_date") if event_type == "readiness_checkin_saved" else None
        checkin_in_week = False
        if isinstance(checkin_date, str):
            try:
                checkin_in_week = week_start <= date.fromisoformat(checkin_date) <= week_end
            except ValueError:
                checkin_in_week = False
        linked_late_fact = (
            event.get("workout_id") in review_candidates
            and event_type in {"workout_completion_removed", "workout_feedback_saved", "workout_missed", "pain_reported", "illness_reported"}
        )
        linked_checkin_safety = event_type in {"pain_reported", "illness_reported"} and event.get("checkin_id") in in_week_checkin_ids
        occurred_in_week = interval_start <= occurred_at < interval_end
        plan_relevant = (
            event_type in user_level_event_types
            or (event_type in workout_event_types and event.get("workout_id") in review_candidates)
            or (event_type == "weekly_strategy_applied" and event.get("plan_id") == plan_id)
        )
        if plan_relevant and (checkin_in_week or linked_checkin_safety or (event_type != "readiness_checkin_saved" and (occurred_in_week or linked_late_fact))):
            week_events.append(event)

    recovery_observations = list(db.scalars(
        select(RecoverySignalObservation)
        .where(
            RecoverySignalObservation.user_id == user.id,
            RecoverySignalObservation.observed_at >= interval_start - timedelta(days=28),
            RecoverySignalObservation.observed_at < interval_end,
            RecoverySignalObservation.received_at <= cutoff,
        )
        .order_by(RecoverySignalObservation.observed_at.asc(), RecoverySignalObservation.id.asc())
    ))

    resolution_status = "complete" if start_resolution.get("status") == "complete" and end_resolution.get("status") == "complete" else "partial_legacy"
    limitations = [*(start_resolution.get("limitations") or []), *(end_resolution.get("limitations") or [])]
    profile_input = None
    if profile_at_cutoff is None:
        resolution_status = "partial_legacy"
        limitations.append("No immutable athlete profile state was available at the cutoff; missing safety data and timezone history are not treated as favorable.")
    else:
        profile_input = json_safe({
            "id": profile.id,
            "timezone": profile.timezone,
            "recovery_status": profile.recovery_status,
            "conservative_mode": profile.conservative_mode,
            "injury_notes": profile.injury_notes,
            "health_conditions": profile.health_conditions,
            "max_run_duration_minutes": profile.max_run_duration_minutes,
            "updated_at": profile.updated_at,
        })

    return json_safe({
        "resolver_version": HISTORICAL_RESOLVER_VERSION,
        "recovery_rule_version": RECOVERY_RULE_VERSION,
        "as_of_at": cutoff,
        "timezone": timezone_name,
        "week_start": week_start,
        "week_end": week_end,
        "target_week_start": target_week_start,
        "target_week_end": target_week_end,
        "recovery_as_of_at": min(cutoff, interval_end),
        "resolution": {
            "status": resolution_status,
            "resolver_version": HISTORICAL_RESOLVER_VERSION,
            "plan_id": plan_id,
            "week_start_plan_version_id": start_resolution.get("plan_version_id"),
            "week_end_plan_version_id": end_resolution.get("plan_version_id"),
            "resolved_from": "plan_version_ledger" if resolution_status == "complete" else "partial_legacy",
            "limitations": sorted(set(limitations)),
        },
        "profile": profile_input,
        "plan": {key: end_snapshot.get(key) for key in ("id", "title", "goal_type", "status", "target_date") if end_snapshot and key in end_snapshot} if end_snapshot else None,
        "review_workouts": review_workouts,
        "planned_review_workouts": sorted(planned_review_workouts, key=lambda item: (str(item.get("scheduled_date") or ""), int(item.get("id") or 0))),
        "plan_changes": plan_changes(start_workouts, end_workouts),
        "target_workouts": target_workouts,
        "events": week_events,
        "recovery_observations": [observation_input(item) for item in recovery_observations],
    })
