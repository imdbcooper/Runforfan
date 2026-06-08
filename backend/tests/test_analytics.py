import unittest
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

try:
    from app.models import Activity, ActivitySegment, AthleteMeasurement, TrainingPlan, TrainingPlanWorkout, TrainingPlanWorkoutFeedback
    from app.services.analytics import activity_local_date, analytics_summary_from_data, best_efforts, insights_from_data, insights_from_summary, measurement_local_date, timeseries_from_activities
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
        activity_type="outdoor_run",
        distance_km=distance_km,
        duration_seconds=duration_seconds,
        average_pace_seconds_per_km=round(duration_seconds / distance_km),
        average_heart_rate_bpm=hr,
    )


def make_workout(workout_id: int, scheduled_date: date, status: str = "planned", *, activity_id: int | None = None, workout_type: str = "easy", intensity: str = "easy") -> TrainingPlanWorkout:
    workout = TrainingPlanWorkout(
        id=workout_id,
        plan_id=10,
        scheduled_date=scheduled_date,
        status=status,
        completed_activity_id=activity_id,
        week_index=1,
        day_index=1,
        workout_type=workout_type,
        title=f"Workout {workout_id}",
        distance_km=5.0,
        duration_seconds=1800,
        intensity=intensity,
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

    def test_insights_include_evidence_and_confidence(self):
        activity = make_activity(1, datetime(2026, 6, 1, 8, tzinfo=UTC), 5.0, 1500, 145)
        summary = analytics_summary_from_data([activity], [], date(2026, 6, 1), date(2026, 6, 7))

        insights = insights_from_data(summary, [activity], [])

        self.assertTrue(insights)
        self.assertTrue(all(insight["evidence"] for insight in insights))
        self.assertTrue(all(insight["confidence"] in {"low", "medium", "high"} for insight in insights))

    def test_insights_detect_too_much_intensity(self):
        activities = [
            make_activity(1, datetime(2026, 6, 1, 8, tzinfo=UTC), 5.0, 1500, 150),
            make_activity(2, datetime(2026, 6, 2, 8, tzinfo=UTC), 5.0, 1450, 155),
            make_activity(3, datetime(2026, 6, 3, 8, tzinfo=UTC), 5.0, 1800, 140),
        ]
        workouts = [
            make_workout(1, date(2026, 6, 1), "done", activity_id=1, workout_type="interval", intensity="threshold"),
            make_workout(2, date(2026, 6, 2), "done", activity_id=2, workout_type="tempo", intensity="threshold"),
            make_workout(3, date(2026, 6, 3), "done", activity_id=3, workout_type="easy", intensity="easy"),
        ]
        summary = analytics_summary_from_data(activities, workouts, date(2026, 6, 1), date(2026, 6, 7))

        insights = insights_from_data(summary, activities, workouts)

        insight = next(item for item in insights if item["title"] == "Слишком много интенсивности")
        self.assertEqual(insight["severity"], "warning")
        self.assertTrue(any(item["metric"] == "hard_session_share" for item in insight["evidence"]))

    def test_insights_detect_easy_pace_improvement_with_stable_hr(self):
        activities = [
            make_activity(1, datetime(2026, 6, 1, 8, tzinfo=UTC), 5.0, 1800, 145),
            make_activity(2, datetime(2026, 6, 3, 8, tzinfo=UTC), 5.0, 1780, 145),
            make_activity(3, datetime(2026, 6, 8, 8, tzinfo=UTC), 5.0, 1680, 146),
            make_activity(4, datetime(2026, 6, 10, 8, tzinfo=UTC), 5.0, 1660, 146),
        ]
        workouts = [make_workout(index, activity_local_date(activity, ZoneInfo("UTC")) or date(2026, 6, 1), "done", activity_id=activity.id) for index, activity in enumerate(activities, start=1)]
        summary = analytics_summary_from_data(activities, workouts, date(2026, 6, 1), date(2026, 6, 14))

        insights = insights_from_data(summary, activities, workouts)

        self.assertTrue(any(item["title"] == "Темп на easy runs улучшился" for item in insights))

    def test_easy_pace_insight_excludes_non_run_linked_to_easy_workout(self):
        activities = [
            make_activity(1, datetime(2026, 6, 1, 8, tzinfo=UTC), 5.0, 1800, 145),
            make_activity(2, datetime(2026, 6, 3, 8, tzinfo=UTC), 5.0, 1780, 145),
            make_activity(3, datetime(2026, 6, 8, 8, tzinfo=UTC), 5.0, 1500, 146),
            make_activity(4, datetime(2026, 6, 10, 8, tzinfo=UTC), 5.0, 1480, 146),
        ]
        for activity in activities[2:]:
            activity.activity_type = "ride"
        workouts = [make_workout(index, activity_local_date(activity, ZoneInfo("UTC")) or date(2026, 6, 1), "done", activity_id=activity.id) for index, activity in enumerate(activities, start=1)]
        summary = analytics_summary_from_data(activities, workouts, date(2026, 6, 1), date(2026, 6, 14))

        insights = insights_from_data(summary, activities, workouts)

        self.assertFalse(any(item["title"] == "Темп на easy runs улучшился" for item in insights))

    def test_easy_pace_insight_excludes_unlinked_hard_runs(self):
        activities = [
            make_activity(1, datetime(2026, 6, 1, 8, tzinfo=UTC), 5.0, 1800, 145),
            make_activity(2, datetime(2026, 6, 3, 8, tzinfo=UTC), 5.0, 1780, 145),
            make_activity(3, datetime(2026, 6, 8, 8, tzinfo=UTC), 5.0, 1500, 146),
            make_activity(4, datetime(2026, 6, 10, 8, tzinfo=UTC), 5.0, 1480, 146),
        ]
        activities[2].title = "Tempo run"
        activities[3].title = "5K race"
        summary = analytics_summary_from_data(activities, [], date(2026, 6, 1), date(2026, 6, 14))

        insights = insights_from_data(summary, activities, [])

        self.assertFalse(any(item["title"] == "Темп на easy runs улучшился" for item in insights))

    def test_stable_volume_insight_requires_no_zero_week_gap(self):
        activities = [
            make_activity(1, datetime(2026, 6, 1, 8, tzinfo=UTC), 10.0, 3600),
            make_activity(2, datetime(2026, 6, 15, 8, tzinfo=UTC), 11.0, 3900),
            make_activity(3, datetime(2026, 6, 22, 8, tzinfo=UTC), 12.0, 4200),
        ]
        summary = analytics_summary_from_data(activities, [], date(2026, 6, 1), date(2026, 6, 28))

        insights = insights_from_data(summary, activities, [])

        self.assertFalse(any(item["title"] == "Объем растет стабильно" for item in insights))

    def test_stable_volume_insight_requires_consecutive_weeks_for_all_time(self):
        activities = [
            make_activity(1, datetime(2026, 1, 5, 8, tzinfo=UTC), 10.0, 3600),
            make_activity(2, datetime(2026, 3, 2, 8, tzinfo=UTC), 11.0, 3900),
            make_activity(3, datetime(2026, 6, 1, 8, tzinfo=UTC), 12.0, 4200),
        ]
        summary = analytics_summary_from_data(activities, [], None, None)

        insights = insights_from_data(summary, activities, [])

        self.assertFalse(any(item["title"] == "Объем растет стабильно" for item in insights))

    def test_insights_detect_fatigue_without_medical_advice(self):
        activity = make_activity(1, datetime(2026, 6, 1, 8, tzinfo=UTC), 5.0, 1500, 155)
        workout = make_workout(1, date(2026, 6, 1), "done", activity_id=1)
        workout.feedback = TrainingPlanWorkoutFeedback(id=1, user_id=1, workout_id=1, fatigue=9, pain=False)
        summary = analytics_summary_from_data([activity], [workout], date(2026, 6, 1), date(2026, 6, 7))

        insights = insights_from_data(summary, [activity], [workout])
        fatigue = next(item for item in insights if item["title"] == "Возможная усталость")

        self.assertEqual(fatigue["severity"], "warning")
        self.assertNotIn("doctor", fatigue["message"].lower())
        self.assertNotIn("medical", fatigue["message"].lower())

    def test_fatigue_insight_ignores_stale_feedback_in_long_period(self):
        activity = make_activity(1, datetime(2026, 6, 1, 8, tzinfo=UTC), 5.0, 1500, 155)
        workout = make_workout(1, date(2026, 3, 1), "done", activity_id=1)
        workout.feedback = TrainingPlanWorkoutFeedback(id=1, user_id=1, workout_id=1, fatigue=9, pain=False)
        summary = analytics_summary_from_data([activity], [workout], date(2026, 3, 1), date(2026, 6, 8))

        insights = insights_from_data(summary, [activity], [workout])

        self.assertFalse(any(item["title"] == "Возможная усталость" for item in insights))

    def test_warning_insights_are_prioritized_before_cap(self):
        activities = [
            make_activity(1, datetime(2026, 6, 1, 8, tzinfo=UTC), 5.0, 1200, 175),
            make_activity(2, datetime(2026, 6, 2, 8, tzinfo=UTC), 5.0, 1500, 155),
            make_activity(3, datetime(2026, 6, 8, 8, tzinfo=UTC), 6.0, 1800, 156),
            make_activity(4, datetime(2026, 6, 9, 8, tzinfo=UTC), 5.0, 1700, 145),
            make_activity(5, datetime(2026, 6, 15, 8, tzinfo=UTC), 6.0, 2000, 145),
            make_activity(6, datetime(2026, 6, 16, 8, tzinfo=UTC), 6.0, 1980, 145),
        ]
        activities[0].title = "5K race"
        workouts = [
            make_workout(1, date(2026, 6, 1), "done", activity_id=1, workout_type="race", intensity="threshold"),
            make_workout(2, date(2026, 6, 2), "done", activity_id=2, workout_type="tempo", intensity="threshold"),
            make_workout(3, date(2026, 6, 8), "done", activity_id=3, workout_type="interval", intensity="threshold"),
            make_workout(4, date(2026, 6, 9), "done", activity_id=4),
            make_workout(5, date(2026, 6, 15), "done", activity_id=5),
            make_workout(6, date(2026, 6, 16), "done", activity_id=6),
            make_workout(7, date(2026, 6, 17), "missed"),
        ]
        workouts[5].feedback = TrainingPlanWorkoutFeedback(id=1, user_id=1, workout_id=6, rpe=9, pain=False)
        summary = analytics_summary_from_data(activities, workouts, date(2026, 6, 1), date(2026, 6, 21))

        insights = insights_from_data(summary, activities, workouts)
        titles = [item["title"] for item in insights]

        self.assertLessEqual(len(insights), 8)
        self.assertIn("Слишком много интенсивности", titles)
        self.assertIn("Возможная усталость", titles)

    def test_load_spike_uses_chronological_recent_activities(self):
        activities = [
            make_activity(4, datetime(2026, 6, 4, 8, tzinfo=UTC), 5.0, 1500, 155),
            make_activity(3, datetime(2026, 6, 3, 8, tzinfo=UTC), 5.0, 1500, 155),
            make_activity(2, datetime(2026, 6, 2, 8, tzinfo=UTC), 5.0, 1500, 145),
            make_activity(1, datetime(2026, 6, 1, 8, tzinfo=UTC), 5.0, 1500, 145),
        ]
        for activity, load in zip(activities, [90, 80, 20, 20]):
            activity.aerobic_training_stress = load
        summary = analytics_summary_from_data(activities, [], date(2026, 6, 1), date(2026, 6, 4))

        insights = insights_from_data(summary, activities, [])
        fatigue = next(item for item in insights if item["title"] == "Возможная усталость")

        self.assertTrue(any(item["metric"] == "recent_load_spike_ratio" for item in fatigue["evidence"]))

    def test_load_spike_ignores_stale_loaded_sessions_when_recent_load_missing(self):
        activities = [
            make_activity(6, datetime(2026, 6, 6, 8, tzinfo=UTC), 5.0, 1500, 145),
            make_activity(5, datetime(2026, 6, 5, 8, tzinfo=UTC), 5.0, 1500, 145),
            make_activity(4, datetime(2026, 6, 4, 8, tzinfo=UTC), 5.0, 1500, 155),
            make_activity(3, datetime(2026, 6, 3, 8, tzinfo=UTC), 5.0, 1500, 155),
            make_activity(2, datetime(2026, 6, 2, 8, tzinfo=UTC), 5.0, 1500, 145),
            make_activity(1, datetime(2026, 6, 1, 8, tzinfo=UTC), 5.0, 1500, 145),
        ]
        for activity, load in zip(activities[2:], [90, 80, 20, 20]):
            activity.aerobic_training_stress = load
        summary = analytics_summary_from_data(activities, [], date(2026, 6, 1), date(2026, 6, 6))

        insights = insights_from_data(summary, activities, [])

        self.assertFalse(any(item["title"] == "Возможная усталость" for item in insights))


if __name__ == "__main__":
    unittest.main()
