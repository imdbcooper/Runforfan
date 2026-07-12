import unittest
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

try:
    from app.models import Activity, TrainingPlan, TrainingPlanWorkout, User
    from app.services.calendar import MAX_CALENDAR_RANGE_DAYS, calendar_activity_bounds, calendar_payload, calendar_warnings
except ModuleNotFoundError as exc:
    if exc.name == "sqlalchemy":
        raise unittest.SkipTest("SQLAlchemy is required for calendar tests") from exc
    raise


def make_user() -> User:
    return User(id=1, display_name="Test runner")


def make_activity(activity_id: int, started_at: datetime, distance_km: float = 5.0) -> Activity:
    return Activity(
        id=activity_id,
        user_id=1,
        title=f"Activity {activity_id}",
        started_at=started_at,
        distance_km=distance_km,
        duration_seconds=1800,
    )


def make_workout(
    workout_id: int,
    scheduled_date: date,
    *,
    status: str = "planned",
    workout_type: str = "easy",
    distance_km: float = 5.0,
    completed_activity: Activity | None = None,
    week_index: int = 1,
    day_index: int = 1,
) -> TrainingPlanWorkout:
    return TrainingPlanWorkout(
        id=workout_id,
        plan_id=10,
        scheduled_date=scheduled_date,
        status=status,
        completed_activity_id=completed_activity.id if completed_activity else None,
        completed_activity=completed_activity,
        week_index=week_index,
        day_index=day_index,
        workout_type=workout_type,
        title=f"Workout {workout_id}",
        distance_km=distance_km,
        duration_seconds=None,
        intensity="threshold" if workout_type in {"interval", "tempo"} else "easy",
        description=None,
    )


def make_plan(*workouts: TrainingPlanWorkout) -> TrainingPlan:
    return TrainingPlan(
        id=10,
        user_id=1,
        title="Active plan",
        goal_type="race",
        available_days_per_week=3,
        status="active",
        workouts=list(workouts),
    )


class CalendarTests(unittest.TestCase):
    def test_payload_returns_planned_and_activity_events_with_links(self):
        activity = make_activity(101, datetime(2026, 6, 3, 9, 0, tzinfo=UTC), distance_km=5.2)
        linked_workout = make_workout(1, date(2026, 6, 3), status="done", completed_activity=activity, distance_km=5.0)
        easy_workout = make_workout(2, date(2026, 6, 5), day_index=2, distance_km=6.0)
        make_plan(linked_workout, easy_workout)

        result = calendar_payload(
            date(2026, 6, 1),
            date(2026, 6, 7),
            [linked_workout, easy_workout],
            [activity],
            {activity.id: linked_workout},
        )

        self.assertEqual([event["id"] for event in result["events"]], ["planned_workout:1", "activity:101", "planned_workout:2"])
        activity_event = result["events"][1]
        self.assertEqual(activity_event["status"], "linked")
        self.assertEqual(activity_event["planned_workout_id"], 1)
        self.assertEqual(result["summary"]["planned_workouts"], 2)
        self.assertEqual(result["summary"]["done_workouts"], 1)
        self.assertEqual(result["summary"]["linked_activities"], 1)
        self.assertEqual(result["summary"]["unlinked_activities"], 0)

    def test_unlinked_activity_stays_visible(self):
        activity = make_activity(102, datetime(2026, 6, 4, 9, 0, tzinfo=UTC), distance_km=4.0)
        result = calendar_payload(date(2026, 6, 1), date(2026, 6, 7), [], [activity], {})

        self.assertEqual(result["events"][0]["kind"], "activity")
        self.assertEqual(result["events"][0]["status"], "unlinked")
        self.assertEqual(result["summary"]["unlinked_activities"], 1)

    def test_activity_events_use_user_local_calendar_date(self):
        timezone = ZoneInfo("Europe/Moscow")
        activity = make_activity(103, datetime(2026, 5, 31, 21, 30, tzinfo=UTC), distance_km=4.0)

        result = calendar_payload(date(2026, 6, 1), date(2026, 6, 1), [], [activity], {}, timezone)

        self.assertEqual(result["events"][0]["date"], date(2026, 6, 1))

    def test_activity_bounds_cover_user_local_calendar_day(self):
        timezone = ZoneInfo("Europe/Moscow")

        start_at, end_at = calendar_activity_bounds(date(2026, 6, 1), date(2026, 6, 1), timezone)

        self.assertEqual(start_at, datetime(2026, 5, 31, 21, 0, tzinfo=UTC))
        self.assertEqual(end_at, datetime(2026, 6, 1, 21, 0, tzinfo=UTC))
        self.assertEqual(MAX_CALENDAR_RANGE_DAYS, 42)

    def test_hard_sessions_within_two_days_raise_warning(self):
        first = make_workout(1, date(2026, 6, 3), workout_type="interval")
        second = make_workout(2, date(2026, 6, 5), workout_type="tempo", day_index=2)
        make_plan(first, second)

        warnings = calendar_warnings([first, second])

        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["planned_workout_ids"], [1, 2])

    def test_hard_sessions_three_days_apart_do_not_raise_warning(self):
        first = make_workout(1, date(2026, 6, 3), workout_type="interval")
        second = make_workout(2, date(2026, 6, 6), workout_type="tempo", day_index=2)
        make_plan(first, second)

        self.assertEqual(calendar_warnings([first, second]), [])


if __name__ == "__main__":
    unittest.main()
