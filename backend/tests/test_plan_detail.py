import unittest
from datetime import date

try:
    from app.models import Activity, TrainingPlan, TrainingPlanWorkout
    from app.services.planning import plan_to_dict, plan_week_summaries
except ModuleNotFoundError as exc:
    if exc.name in {"pydantic", "sqlalchemy"}:
        raise unittest.SkipTest("Backend dependencies are required for plan detail tests") from exc
    raise


def make_workout(
    workout_id: int,
    *,
    week_index: int,
    day_index: int,
    workout_type: str,
    distance_km: float | None,
    duration_seconds: int | None = None,
    status: str = "planned",
    linked_distance_km: float | None = None,
    linked_duration_seconds: int = 1800,
) -> TrainingPlanWorkout:
    activity = None
    if linked_distance_km is not None:
        activity = Activity(
            id=100 + workout_id,
            user_id=1,
            title=f"Activity {workout_id}",
            distance_km=linked_distance_km,
            duration_seconds=linked_duration_seconds,
        )
    return TrainingPlanWorkout(
        id=workout_id,
        plan_id=10,
        scheduled_date=date(2026, 6, workout_id),
        status=status,
        completed_activity_id=activity.id if activity else None,
        completed_activity=activity,
        week_index=week_index,
        day_index=day_index,
        workout_type=workout_type,
        title=f"Workout {workout_id}",
        distance_km=distance_km,
        duration_seconds=duration_seconds,
        intensity="threshold" if workout_type == "interval" else "easy",
        description="Structured workout",
    )


def make_plan() -> TrainingPlan:
    return TrainingPlan(
        id=10,
        user_id=1,
        title="Detail plan",
        goal_type="10k",
        race_distance_km=10.0,
        target_date=date(2026, 8, 1),
        target_time_seconds=2400,
        available_days_per_week=3,
        status="active",
        explanation="Safety gates: no active safety gates",
        workouts=[
            make_workout(1, week_index=1, day_index=1, workout_type="easy", distance_km=6.0, duration_seconds=2100, status="done", linked_distance_km=5.5),
            make_workout(2, week_index=1, day_index=2, workout_type="interval", distance_km=8.0),
            make_workout(3, week_index=1, day_index=3, workout_type="long", distance_km=12.0),
            make_workout(8, week_index=2, day_index=1, workout_type="easy", distance_km=5.0),
            make_workout(9, week_index=2, day_index=2, workout_type="long", distance_km=9.0),
        ],
    )


class PlanDetailTests(unittest.TestCase):
    def test_plan_week_summaries_include_detail_metrics(self):
        summaries = plan_week_summaries(make_plan())

        self.assertEqual(len(summaries), 2)
        self.assertEqual(summaries[0]["planned_distance_km"], 26.0)
        self.assertEqual(summaries[0]["planned_duration_seconds"], 8100)
        self.assertEqual(summaries[0]["completed_distance_km"], 5.5)
        self.assertEqual(summaries[0]["completed_duration_seconds"], 1800)
        self.assertEqual(summaries[0]["hard_sessions"], 1)
        self.assertEqual(summaries[0]["long_run_km"], 12.0)
        self.assertFalse(summaries[0]["deload"])
        self.assertTrue(summaries[1]["deload"])
        self.assertEqual([workout["id"] for workout in summaries[0]["workouts"]], [1, 2, 3])

    def test_plan_to_dict_exposes_target_time_and_timestamps(self):
        plan = make_plan()

        result = plan_to_dict(plan)

        self.assertEqual(result["target_time_seconds"], 2400)
        self.assertIn("created_at", result)
        self.assertIn("updated_at", result)

    def test_plan_adherence_estimates_duration_for_legacy_running_workouts(self):
        run = make_workout(
            1,
            week_index=1,
            day_index=1,
            workout_type="easy",
            distance_km=5.0,
            duration_seconds=None,
            status="done",
            linked_distance_km=5.0,
            linked_duration_seconds=1800,
        )
        plan = TrainingPlan(
            id=13,
            user_id=1,
            title="Legacy duration plan",
            goal_type="10k",
            available_days_per_week=3,
            status="active",
            workouts=[run],
        )

        adherence = plan_to_dict(plan)["adherence"]

        self.assertEqual(adherence["planned_duration_seconds"], 2100)
        self.assertEqual(adherence["duration_completion_rate"], 0.86)

    def test_duration_only_support_workout_contributes_time_not_distance(self):
        strength = make_workout(
            4,
            week_index=1,
            day_index=4,
            workout_type="strength",
            distance_km=None,
            duration_seconds=1800,
            status="done",
            linked_distance_km=None,
            linked_duration_seconds=1700,
        )
        strength.completed_activity = Activity(id=104, user_id=1, title="Strength", activity_type="manual_strength", duration_seconds=1700)
        strength.completed_activity_id = 104
        plan = TrainingPlan(
            id=11,
            user_id=1,
            title="Support plan",
            goal_type="base_building",
            available_days_per_week=3,
            status="active",
            workouts=[strength],
        )

        summary = plan_week_summaries(plan)[0]
        adherence = plan_to_dict(plan)["adherence"]

        self.assertEqual(summary["planned_distance_km"], 0)
        self.assertEqual(summary["planned_duration_seconds"], 1800)
        self.assertEqual(summary["support_workouts"], 1)
        self.assertEqual(summary["completed_duration_seconds"], 1700)
        self.assertEqual(adherence["support_workouts"], 1)
        self.assertEqual(adherence["duration_completion_rate"], 0.94)

    def test_mixed_plan_warns_when_support_duration_is_short(self):
        run = make_workout(
            1,
            week_index=1,
            day_index=1,
            workout_type="easy",
            distance_km=5.0,
            duration_seconds=1800,
            status="done",
            linked_distance_km=5.0,
            linked_duration_seconds=1800,
        )
        strength = make_workout(
            2,
            week_index=1,
            day_index=2,
            workout_type="strength",
            distance_km=None,
            duration_seconds=1800,
            status="done",
        )
        strength.completed_activity = Activity(id=102, user_id=1, title="Strength", activity_type="manual_strength", duration_seconds=600)
        strength.completed_activity_id = 102
        plan = TrainingPlan(
            id=12,
            user_id=1,
            title="Mixed support plan",
            goal_type="10k",
            available_days_per_week=3,
            status="active",
            workouts=[run, strength],
        )

        warnings = plan_to_dict(plan)["adherence"]["warnings"]

        self.assertIn("ОФП/support длительность заметно ниже плана", warnings)


if __name__ == "__main__":
    unittest.main()
