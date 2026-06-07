import unittest
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

try:
    from app.models import Activity, ActivitySegment, AthleteMeasurement, TrainingPlan, TrainingPlanWorkout
    from app.services.analytics import activity_local_date, analytics_summary_from_data, best_efforts, insights_from_summary, measurement_local_date, timeseries_from_activities
except ModuleNotFoundError as exc:
    if exc.name in {"pydantic", "sqlalchemy"}:
        raise unittest.SkipTest("Backend dependencies are required for analytics tests") from exc
    raise


def make_activity(activity_id: int, started_at: datetime, distance_km: float, duration_seconds: int, hr: int | None = None) -> Activity:
    return Activity(
        id=activity_id,
        user_id=1,
        title=f"Activity {activity_id}",
        started_at=started_at,
        distance_km=distance_km,
        duration_seconds=duration_seconds,
        average_pace_seconds_per_km=round(duration_seconds / distance_km),
        average_heart_rate_bpm=hr,
    )


def make_workout(workout_id: int, scheduled_date: date, status: str = "planned") -> TrainingPlanWorkout:
    workout = TrainingPlanWorkout(
        id=workout_id,
        plan_id=10,
        scheduled_date=scheduled_date,
        status=status,
        week_index=1,
        day_index=1,
        workout_type="easy",
        title=f"Workout {workout_id}",
        distance_km=5.0,
        duration_seconds=1800,
        intensity="easy",
        description=None,
    )
    TrainingPlan(id=10, user_id=1, title="Plan", goal_type="10k", available_days_per_week=3, status="active", workouts=[workout])
    return workout


class AnalyticsTests(unittest.TestCase):
    def test_summary_returns_zero_state_for_empty_period(self):
        summary = analytics_summary_from_data([], [], date(2026, 6, 1), date(2026, 6, 7))

        self.assertEqual(summary["activity_count"], 0)
        self.assertEqual(summary["total_distance_km"], 0)
        self.assertIsNone(summary["weighted_average_pace_seconds_per_km"])
        self.assertEqual(summary["best_efforts"], [])

    def test_summary_uses_weighted_pace_and_duration_weighted_hr(self):
        activities = [
            make_activity(1, datetime(2026, 6, 1, 8, tzinfo=UTC), 5.0, 1500, 140),
            make_activity(2, datetime(2026, 6, 3, 8, tzinfo=UTC), 10.0, 3600, 160),
        ]
        workouts = [make_workout(1, date(2026, 6, 2), "missed")]

        summary = analytics_summary_from_data(activities, workouts, date(2026, 6, 1), date(2026, 6, 7))

        self.assertEqual(summary["activity_count"], 2)
        self.assertEqual(summary["total_distance_km"], 15.0)
        self.assertEqual(summary["weighted_average_pace_seconds_per_km"], 340)
        self.assertEqual(summary["average_heart_rate_bpm"], 154)
        self.assertEqual(summary["adherence"]["missed_workouts"], 1)
        self.assertEqual(summary["consistency"]["training_days"], 2)

    def test_adherence_estimates_duration_for_legacy_running_workouts(self):
        workout = make_workout(1, date(2026, 6, 2), "done")
        workout.duration_seconds = None
        workout.completed_activity = make_activity(10, datetime(2026, 6, 2, 8, tzinfo=UTC), 5.0, 1800)
        workout.completed_activity_id = 10

        summary = analytics_summary_from_data([], [workout], date(2026, 6, 1), date(2026, 6, 7))

        self.assertEqual(summary["adherence"]["planned_duration_seconds"], 2100)
        self.assertEqual(summary["adherence"]["duration_completion_rate"], 0.86)

    def test_weighted_pace_ignores_duration_only_activities(self):
        distance_activity = make_activity(1, datetime(2026, 6, 1, 8, tzinfo=UTC), 5.0, 1500, 140)
        duration_only = Activity(id=2, user_id=1, title="Strength", started_at=datetime(2026, 6, 2, 8, tzinfo=UTC), distance_km=None, duration_seconds=3600)

        summary = analytics_summary_from_data([distance_activity, duration_only], [], date(2026, 6, 1), date(2026, 6, 7))

        self.assertEqual(summary["total_duration_seconds"], 5100)
        self.assertEqual(summary["weighted_average_pace_seconds_per_km"], 300)

    def test_best_efforts_and_vdot_are_derived_from_eligible_efforts(self):
        activity = make_activity(1, datetime(2026, 6, 1, 8, tzinfo=UTC), 5.0, 1200, 175)
        activity.title = "5K race"
        activity.segments = [ActivitySegment(id=1, activity_id=1, segment_index=1, distance_km=1.0, duration_seconds=210, pace_seconds_per_km=210)]

        summary = analytics_summary_from_data([activity], [], date(2026, 6, 1), date(2026, 6, 7))

        self.assertEqual([effort["target_distance_km"] for effort in summary["best_efforts"]], [1.0, 5.0])
        self.assertIsNotNone(summary["estimated_vdot"])
        self.assertEqual(summary["estimated_vdot_activity_id"], 1)

    def test_ordinary_exact_distance_run_does_not_drive_vdot_estimate(self):
        activity = make_activity(1, datetime(2026, 6, 1, 8, tzinfo=UTC), 5.0, 1500, 145)
        activity.title = "Scott easy run"

        summary = analytics_summary_from_data([activity], [], date(2026, 6, 1), date(2026, 6, 7))

        self.assertEqual(summary["best_efforts"][0]["confidence"], "low")
        self.assertIsNone(summary["estimated_vdot"])

    def test_best_efforts_do_not_scale_long_activity_to_short_target(self):
        activity = make_activity(1, datetime(2026, 6, 1, 8, tzinfo=UTC), 13.0, 4200, 155)

        efforts = best_efforts([activity])

        self.assertEqual(efforts, [])

    def test_best_efforts_do_not_project_short_split_to_one_km(self):
        activity = make_activity(1, datetime(2026, 6, 1, 8, tzinfo=UTC), 5.0, 1500, 155)
        activity.segments = [ActivitySegment(id=1, activity_id=1, segment_index=1, distance_km=0.8, duration_seconds=150, pace_seconds_per_km=188)]

        efforts = best_efforts([activity])

        self.assertEqual([effort["target_distance_km"] for effort in efforts], [5.0])

    def test_timeseries_groups_by_week(self):
        activities = [
            make_activity(1, datetime(2026, 6, 1, 8, tzinfo=UTC), 5.0, 1500),
            make_activity(2, datetime(2026, 6, 7, 8, tzinfo=UTC), 7.0, 2100),
        ]

        series = timeseries_from_activities(activities, "distance", "week")

        self.assertEqual(len(series["points"]), 1)
        self.assertEqual(series["points"][0]["distance_km"], 12.0)
        self.assertEqual(series["points"][0]["value"], 12.0)

    def test_naive_activity_and_measurement_dates_use_profile_timezone(self):
        timezone = ZoneInfo("Europe/Moscow")
        activity = Activity(id=1, user_id=1, title="Late run", started_at=datetime(2026, 6, 1, 23, 30), distance_km=5.0, duration_seconds=1500)
        measurement = AthleteMeasurement(id=1, user_id=1, measurement_type="vo2max", measured_at=datetime(2026, 6, 1, 23, 30), value_numeric=50, source="lab")

        self.assertEqual(activity_local_date(activity, timezone), date(2026, 6, 1))
        self.assertEqual(measurement_local_date(measurement, timezone), date(2026, 6, 1))

    def test_insights_include_vdot_note_when_available(self):
        activity = make_activity(1, datetime(2026, 6, 1, 8, tzinfo=UTC), 5.0, 1200, 175)
        activity.title = "5K race"
        summary = analytics_summary_from_data([activity], [], date(2026, 6, 1), date(2026, 6, 7))

        insights = insights_from_summary(summary)

        self.assertTrue(any("VO2max" in insight["title"] for insight in insights))


if __name__ == "__main__":
    unittest.main()
