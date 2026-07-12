from datetime import UTC, date, datetime, time, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Activity, AthleteProfile, TrainingPlan, TrainingPlanWorkout, User
from app.services.constraint_engine import HardWorkoutPolicy, dates_within_days, is_hard_workout
from app.services.planning import workout_execution_score, workout_to_dict


HARD_WORKOUT_TYPES = {"interval", "tempo", "threshold", "race_pace", "hill", "long"}
HARD_INTENSITIES = {"interval", "tempo", "threshold", "race_pace", "hard"}
CALENDAR_HARD_POLICY = HardWorkoutPolicy(frozenset(HARD_WORKOUT_TYPES), frozenset(HARD_INTENSITIES))
MAX_CALENDAR_RANGE_DAYS = 42


def calendar_timezone(db: Session, user: User) -> tzinfo:
    timezone_name = db.scalar(select(AthleteProfile.timezone).where(AthleteProfile.user_id == user.id)) or "Europe/Moscow"
    try:
        return ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        return UTC


def calendar_activity_bounds(from_date: date, to_date: date, timezone: tzinfo) -> tuple[datetime, datetime]:
    start_local = datetime.combine(from_date, time.min, tzinfo=timezone)
    end_local = datetime.combine(to_date + timedelta(days=1), time.min, tzinfo=timezone)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def activity_calendar_date(activity: Activity, timezone: tzinfo) -> date | None:
    if not activity.started_at:
        return None
    started_at = activity.started_at
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone)
    return started_at.astimezone(timezone).date()


def hard_workout(workout: TrainingPlanWorkout) -> bool:
    return is_hard_workout(workout.workout_type, workout.intensity, policy=CALENDAR_HARD_POLICY)


def calendar_warnings(workouts: list[TrainingPlanWorkout]) -> list[dict[str, object]]:
    warnings: list[dict[str, object]] = []
    hard_workouts = sorted(
        [workout for workout in workouts if workout.scheduled_date and hard_workout(workout)],
        key=lambda workout: (workout.scheduled_date or date.max, workout.id),
    )
    for index, workout in enumerate(hard_workouts):
        for other in hard_workouts[index + 1:]:
            if not workout.scheduled_date or not other.scheduled_date:
                continue
            if not dates_within_days(workout.scheduled_date, other.scheduled_date, max_days=2):
                break
            title = "Hard workouts are close together"
            message = "Two hard sessions are scheduled within 48 hours. Keep the second one easier or reschedule if recovery is poor."
            if "long" in {workout.workout_type, other.workout_type}:
                title = "Long run is close to a hard workout"
                message = "Long run and quality work are close together; watch fatigue and avoid stacking intensity."
            warnings.append({
                "severity": "warning",
                "title": title,
                "message": message,
                "date": other.scheduled_date,
                "planned_workout_ids": [workout.id, other.id],
            })
            break
    return warnings[:8]


def planned_workout_event(workout: TrainingPlanWorkout) -> dict[str, object]:
    plan = workout.plan
    return {
        "id": f"planned_workout:{workout.id}",
        "kind": "planned_workout",
        "date": workout.scheduled_date,
        "title": workout.title,
        "status": workout.status,
        "planned_workout_id": workout.id,
        "linked_activity_id": workout.completed_activity_id,
        "plan_id": workout.plan_id,
        "plan_title": plan.title if plan else None,
        "workout_type": workout.workout_type,
        "distance_km": workout.distance_km,
        "duration_seconds": workout.duration_seconds,
        "execution_score": workout_execution_score(workout),
        "workout": workout_to_dict(workout),
        "activity": None,
    }


def activity_event(activity: Activity, linked_workout: TrainingPlanWorkout | None, timezone: tzinfo = UTC) -> dict[str, object]:
    return {
        "id": f"activity:{activity.id}",
        "kind": "activity",
        "date": activity_calendar_date(activity, timezone),
        "title": activity.title,
        "status": "linked" if linked_workout else "unlinked",
        "planned_workout_id": linked_workout.id if linked_workout else None,
        "linked_activity_id": activity.id,
        "plan_id": linked_workout.plan_id if linked_workout else None,
        "plan_title": linked_workout.plan.title if linked_workout and linked_workout.plan else None,
        "workout_type": activity.activity_type,
        "distance_km": activity.distance_km,
        "duration_seconds": activity.duration_seconds,
        "execution_score": workout_execution_score(linked_workout) if linked_workout else None,
        "workout": workout_to_dict(linked_workout) if linked_workout else None,
        "activity": activity,
    }


def calendar_summary(events: list[dict[str, object]]) -> dict[str, object]:
    planned = [event for event in events if event["kind"] == "planned_workout"]
    activities = [event for event in events if event["kind"] == "activity"]
    return {
        "planned_workouts": len(planned),
        "done_workouts": len([event for event in planned if event.get("status") == "done"]),
        "missed_workouts": len([event for event in planned if event.get("status") == "missed"]),
        "skipped_workouts": len([event for event in planned if event.get("status") == "skipped"]),
        "activities": len(activities),
        "linked_activities": len([event for event in activities if event.get("status") == "linked"]),
        "unlinked_activities": len([event for event in activities if event.get("status") == "unlinked"]),
        "planned_distance_km": round(sum(float(event.get("distance_km") or 0) for event in planned), 1),
        "activity_distance_km": round(sum(float(event.get("distance_km") or 0) for event in activities), 1),
    }


def calendar_payload(
    from_date: date,
    to_date: date,
    workouts: list[TrainingPlanWorkout],
    activities: list[Activity],
    linked_by_activity: dict[int, TrainingPlanWorkout] | None = None,
    timezone: tzinfo = UTC,
) -> dict[str, object]:
    linked = linked_by_activity or {}
    events: list[dict[str, object]] = [planned_workout_event(workout) for workout in workouts if workout.scheduled_date]
    events.extend(activity_event(activity, linked.get(activity.id), timezone) for activity in activities if activity.started_at)
    events.sort(key=lambda event: (event["date"], 0 if event["kind"] == "planned_workout" else 1, str(event["id"])))
    return {
        "from_date": from_date,
        "to_date": to_date,
        "events": events,
        "warnings": calendar_warnings(workouts),
        "summary": calendar_summary(events),
    }


def calendar_range(db: Session, user: User, from_date: date, to_date: date) -> dict[str, object]:
    timezone = calendar_timezone(db, user)
    start_at, end_at = calendar_activity_bounds(from_date, to_date, timezone)
    workouts = list(db.scalars(
        select(TrainingPlanWorkout)
        .join(TrainingPlan)
        .where(
            TrainingPlan.user_id == user.id,
            TrainingPlan.status == "active",
            TrainingPlanWorkout.scheduled_date >= from_date,
            TrainingPlanWorkout.scheduled_date <= to_date,
        )
        .options(
            selectinload(TrainingPlanWorkout.plan),
            selectinload(TrainingPlanWorkout.completed_activity),
            selectinload(TrainingPlanWorkout.feedback),
            selectinload(TrainingPlanWorkout.blocks),
        )
        .order_by(TrainingPlanWorkout.scheduled_date.asc(), TrainingPlanWorkout.id.asc())
    ))
    activities = list(db.scalars(
        select(Activity)
        .where(
            Activity.user_id == user.id,
            Activity.started_at.is_not(None),
            Activity.started_at >= start_at,
            Activity.started_at < end_at,
        )
        .options(selectinload(Activity.segments), selectinload(Activity.split_blocks), selectinload(Activity.workout_blocks), selectinload(Activity.derived_metrics))
        .order_by(Activity.started_at.asc(), Activity.id.asc())
    ))
    activity_ids = [activity.id for activity in activities]
    linked_by_activity: dict[int, TrainingPlanWorkout] = {}
    if activity_ids:
        linked_workouts = list(db.scalars(
            select(TrainingPlanWorkout)
            .join(TrainingPlan)
            .where(TrainingPlan.user_id == user.id, TrainingPlanWorkout.completed_activity_id.in_(activity_ids))
            .options(selectinload(TrainingPlanWorkout.plan), selectinload(TrainingPlanWorkout.completed_activity), selectinload(TrainingPlanWorkout.feedback), selectinload(TrainingPlanWorkout.blocks))
            .order_by(TrainingPlanWorkout.id.asc())
        ))
        linked_by_activity = {workout.completed_activity_id: workout for workout in linked_workouts if workout.completed_activity_id is not None}
    return calendar_payload(from_date, to_date, workouts, activities, linked_by_activity, timezone)
