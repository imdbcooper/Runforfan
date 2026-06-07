import unittest
from datetime import date
from unittest.mock import patch

try:
    from app.models import Activity, TrainingPlan, TrainingPlanWorkout, User
    from app.services.planning import plan_adjustment_recommendations
except ModuleNotFoundError as exc:
    if exc.name == "sqlalchemy":
        raise unittest.SkipTest("SQLAlchemy is required for planning recommendation tests") from exc
    raise


TODAY = date(2026, 6, 7)


def make_user() -> User:
    return User(id=1, display_name="Test runner")


def make_plan(*workouts: TrainingPlanWorkout, status: str = "active", explanation: str | None = None) -> TrainingPlan:
    return TrainingPlan(
        id=10,
        user_id=1,
        title="Test plan",
        goal_type="race",
        available_days_per_week=3,
        status=status,
        explanation=explanation,
        workouts=list(workouts),
    )


def make_workout(
    workout_id: int,
    scheduled_date: date | None,
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
        completed_activity=completed_activity,
        week_index=week_index,
        day_index=day_index,
        workout_type=workout_type,
        title=f"Workout {workout_id}",
        distance_km=distance_km,
        duration_seconds=None,
        intensity="easy",
        description=None,
    )


def make_activity(activity_id: int, distance_km: float) -> Activity:
    return Activity(
        id=activity_id,
        user_id=1,
        title=f"Activity {activity_id}",
        distance_km=distance_km,
        duration_seconds=1800,
    )


class PlanAdjustmentRecommendationTests(unittest.TestCase):
    def recommendations(self, plan: TrainingPlan) -> dict[str, object]:
        with patch("app.services.planning.today_for_user", return_value=TODAY):
            return plan_adjustment_recommendations(object(), make_user(), plan)

    def recommendation_types(self, result: dict[str, object]) -> list[str]:
        return [item["type"] for item in result["recommendations"]]

    def test_inactive_plan_recommends_activation(self):
        plan = make_plan(
            make_workout(1, TODAY),
            status="draft",
        )

        result = self.recommendations(plan)

        self.assertEqual(result["status"], "watch")
        self.assertIn("resume_plan", self.recommendation_types(result))
        self.assertEqual(result["recommendations"][0]["severity"], "warning")
        self.assertEqual(result["metrics"]["planned_distance_km"], 5.0)

    def test_missed_recent_key_workouts_trigger_hold_and_move(self):
        plan = make_plan(
            make_workout(1, date(2026, 6, 2), status="missed", workout_type="easy"),
            make_workout(2, date(2026, 6, 5), status="skipped", workout_type="long", day_index=2),
        )

        result = self.recommendations(plan)

        self.assertEqual(result["status"], "watch")
        self.assertEqual(result["metrics"]["missed_recent_workouts"], 2)
        self.assertIn("hold_volume", self.recommendation_types(result))
        self.assertIn("move_workout", self.recommendation_types(result))

    def test_done_workout_without_activity_recommends_linking(self):
        plan = make_plan(
            make_workout(1, TODAY, status="done", distance_km=6.0),
        )

        result = self.recommendations(plan)

        self.assertEqual(result["status"], "watch")
        self.assertEqual(result["metrics"]["unlinked_done_workouts"], 1)
        self.assertIn("link_activity", self.recommendation_types(result))

    def test_low_linked_distance_reduces_volume_and_ignores_unscheduled(self):
        plan = make_plan(
            make_workout(
                1,
                TODAY,
                status="done",
                distance_km=10.0,
                completed_activity=make_activity(101, 5.0),
            ),
            make_workout(2, None, distance_km=100.0, day_index=2),
        )

        result = self.recommendations(plan)

        self.assertEqual(result["status"], "watch")
        self.assertEqual(result["metrics"]["planned_distance_km"], 10.0)
        self.assertEqual(result["metrics"]["completed_distance_km"], 5.0)
        self.assertIn("reduce_volume", self.recommendation_types(result))
        self.assertIn("schedule_workouts", self.recommendation_types(result))

    def test_upcoming_jump_from_recent_linked_volume_triggers_hold(self):
        plan = make_plan(
            make_workout(
                1,
                TODAY,
                status="done",
                distance_km=4.0,
                completed_activity=make_activity(101, 4.0),
            ),
            make_workout(2, date(2026, 6, 9), distance_km=8.0, day_index=2),
        )

        result = self.recommendations(plan)

        self.assertEqual(result["metrics"]["recent_completed_distance_km"], 4.0)
        self.assertEqual(result["metrics"]["upcoming_planned_distance_km"], 8.0)
        self.assertIn("hold_volume", self.recommendation_types(result))

    def test_safety_gate_recommends_zone_review(self):
        plan = make_plan(
            make_workout(1, TODAY, status="done", completed_activity=make_activity(101, 5.0)),
            explanation="Safety gates: no threshold pace zones",
        )

        result = self.recommendations(plan)

        self.assertIn("review_zones", self.recommendation_types(result))


if __name__ == "__main__":
    unittest.main()
