import unittest
from datetime import date
from unittest.mock import patch

try:
    from app.models import Activity, TrainingPlan, TrainingPlanWorkout, User
    from app.services.dashboard import current_week_for_plan, readiness_from_signals, week_bounds
except ModuleNotFoundError as exc:
    if exc.name == "sqlalchemy":
        raise unittest.SkipTest("SQLAlchemy is required for dashboard tests") from exc
    raise


TODAY = date(2026, 6, 7)


def make_user() -> User:
    return User(id=1, display_name="Test runner")


def make_activity(activity_id: int, distance_km: float) -> Activity:
    return Activity(id=activity_id, user_id=1, title=f"Activity {activity_id}", distance_km=distance_km, duration_seconds=1800)


def make_workout(
    workout_id: int,
    scheduled_date: date | None,
    *,
    status: str = "planned",
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
        completed_activity=completed_activity,
        week_index=week_index,
        day_index=day_index,
        workout_type="easy",
        title=f"Workout {workout_id}",
        distance_km=distance_km,
        duration_seconds=None,
        intensity="easy",
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


class DashboardTests(unittest.TestCase):
    def test_week_bounds_uses_monday_to_sunday(self):
        self.assertEqual(week_bounds(TODAY), (date(2026, 6, 1), date(2026, 6, 7)))

    def test_current_week_returns_active_calendar_window(self):
        plan = make_plan(
            make_workout(1, date(2026, 6, 1), status="done", completed_activity=make_activity(101, 5.0), day_index=1),
            make_workout(2, TODAY, day_index=2),
            make_workout(3, date(2026, 6, 8), day_index=3, week_index=2),
        )

        with patch("app.services.dashboard.today_for_user", return_value=TODAY):
            result = current_week_for_plan(object(), make_user(), plan)

        self.assertEqual(result["status"], "active")
        self.assertEqual(result["week_start"], date(2026, 6, 1))
        self.assertEqual(result["week_end"], date(2026, 6, 7))
        self.assertEqual([workout["id"] for workout in result["workouts"]], [1, 2])
        self.assertEqual(result["today_workout"]["id"], 2)
        self.assertEqual(result["next_workout"]["id"], 2)
        self.assertEqual(result["adherence"]["total_workouts"], 2)
        self.assertEqual(result["adherence"]["done_workouts"], 1)

    def test_current_week_handles_missing_active_plan(self):
        with patch("app.services.dashboard.today_for_user", return_value=TODAY):
            result = current_week_for_plan(object(), make_user(), None)

        self.assertEqual(result["status"], "no_plan")
        self.assertEqual(result["workouts"], [])
        self.assertIsNone(result["next_workout"])

    def test_readiness_raises_risk_for_multiple_missed_workouts(self):
        readiness = readiness_from_signals(
            {"adherence": {"missed_workouts": 1, "skipped_workouts": 1}, "workouts": []},
            {"conservative_mode": False, "warnings": []},
            None,
        )

        self.assertEqual(readiness["status"], "risk")
        self.assertIn("2 missed or skipped workouts this week", readiness["factors"])


if __name__ == "__main__":
    unittest.main()
