import unittest
from datetime import date, datetime, timedelta

DEPENDENCY_SKIP_REASON = None

try:
    from app.models import RunningGoal
    from app.services.goals import goal_milestones, goal_progress, normalize_goal_type, predicted_range_for_goal, validate_goal_data
except ModuleNotFoundError as exc:
    if exc.name in {"pydantic", "sqlalchemy"}:
        DEPENDENCY_SKIP_REASON = "Backend dependencies are required for goal service tests"
    else:
        raise


@unittest.skipIf(DEPENDENCY_SKIP_REASON is not None, DEPENDENCY_SKIP_REASON or "")
class GoalServiceTests(unittest.TestCase):
    def test_normalize_legacy_and_unknown_goal_types(self):
        self.assertEqual(normalize_goal_type("custom"), "custom_habit")
        self.assertEqual(normalize_goal_type("workout_count"), "weekly_consistency")
        self.assertEqual(normalize_goal_type("longest_run"), "long_run")
        self.assertEqual(normalize_goal_type("unknown_old_value"), "custom_habit")

    def test_race_goal_requires_distance_and_date(self):
        with self.assertRaises(ValueError):
            validate_goal_data({"title": "Race", "goal_type": "race", "target_date": date(2026, 9, 1)})
        with self.assertRaises(ValueError):
            validate_goal_data({"title": "Race", "goal_type": "race", "race_distance_km": 10.0})

    def test_predicted_range_matches_standard_race_distance(self):
        goal = RunningGoal(
            id=1,
            user_id=1,
            title="10K A race",
            goal_type="race",
            race_distance_km=10.0,
            target_date=date(2026, 9, 1),
            target_time_seconds=2700,
            status="active",
        )
        predictions = [{
            "target_distance_km": 10.0,
            "predicted_duration_seconds": 2650,
            "confidence": "medium",
            "source_result_name": "5K TT",
            "warnings": [],
        }]

        result = predicted_range_for_goal(goal, predictions)

        self.assertIsNotNone(result)
        self.assertEqual(result["predicted_duration_seconds"], 2650)
        self.assertEqual(result["target_delta_seconds"], -50)
        self.assertEqual(result["lower_seconds"], 2491)
        self.assertEqual(result["upper_seconds"], 2809)

    def test_race_progress_uses_plan_adherence_and_prediction_readiness(self):
        goal = RunningGoal(
            id=1,
            user_id=1,
            title="10K A race",
            goal_type="race",
            race_distance_km=10.0,
            target_date=date(2026, 9, 1),
            target_time_seconds=2700,
            status="active",
        )
        plan = {"adherence": {"completion_rate": 0.9}}
        prediction = {"lower_seconds": 2490, "upper_seconds": 2650, "predicted_duration_seconds": 2570}

        progress = goal_progress(goal, {}, plan, prediction)

        self.assertEqual(progress["percentage"], 0.9)
        self.assertEqual(progress["readiness"], "on_track")

    def test_monthly_distance_progress_uses_analytics_total_distance(self):
        goal = RunningGoal(id=2, user_id=1, title="June volume", goal_type="monthly_distance", target_value=100.0, unit="km", status="active")

        progress = goal_progress(goal, {"total_distance_km": 64.5}, None, None)

        self.assertEqual(progress["metric"], "distance_km")
        self.assertEqual(progress["percentage"], 0.65)

    def test_terminal_status_overrides_metric_readiness(self):
        goal = RunningGoal(id=4, user_id=1, title="Archived volume", goal_type="monthly_distance", target_value=100.0, unit="km", status="archived")

        progress = goal_progress(goal, {"total_distance_km": 100.0}, None, None)

        self.assertEqual(progress["readiness"], "archived")
        self.assertEqual(progress["percentage"], 0.0)

    def test_race_milestones_include_tuneup_threshold_and_long_run(self):
        target_date = date(2026, 9, 1)
        goal = RunningGoal(id=3, user_id=1, title="Half", goal_type="race", race_distance_km=21.1, target_date=target_date, status="active")

        milestones = goal_milestones(goal, {"longest_distance_km": 18.0}, target_date - timedelta(days=60))

        self.assertEqual([milestone["title"] for milestone in milestones], ["Tune-up race", "Threshold test", "Longest run"])
        self.assertEqual(milestones[2]["status"], "completed")


if __name__ == "__main__":
    unittest.main()
