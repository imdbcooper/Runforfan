import unittest
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

try:
    from app.models import Activity, AthleteProfile, DailyTrainingLoad, TrainingPlanWorkout, TrainingPlanWorkoutFeedback
    from app.services import training_load as training_load_service
    from app.services.training_load import load_warnings, load_planned_workouts_with_feedback, sync_daily_training_loads, training_load_from_data
except ModuleNotFoundError as exc:
    if exc.name in {"pydantic", "sqlalchemy"}:
        raise unittest.SkipTest("Backend dependencies are required for training load tests") from exc
    raise


def make_activity(activity_id: int, started_at: datetime, distance_km: float = 5.0, duration_seconds: int = 1800, stress: float | None = None) -> Activity:
    return Activity(
        id=activity_id,
        user_id=1,
        title=f"Activity {activity_id}",
        started_at=started_at,
        distance_km=distance_km,
        duration_seconds=duration_seconds,
        average_pace_seconds_per_km=round(duration_seconds / distance_km) if distance_km else None,
        aerobic_training_stress=stress,
    )


def make_workout(workout_id: int, activity_id: int, rpe: int | None = None, fatigue: int | None = None, workout_type: str = "easy") -> TrainingPlanWorkout:
    workout = TrainingPlanWorkout(
        id=workout_id,
        plan_id=1,
        scheduled_date=date(2026, 6, 1),
        status="done",
        completed_activity_id=activity_id,
        week_index=1,
        day_index=1,
        workout_type=workout_type,
        title=f"Workout {workout_id}",
        distance_km=5.0,
        duration_seconds=1800,
        intensity=workout_type,
    )
    workout.feedback = TrainingPlanWorkoutFeedback(id=workout_id, user_id=1, workout_id=workout_id, rpe=rpe, fatigue=fatigue, pain=False)
    return workout


class TrainingLoadTests(unittest.TestCase):
    def test_workout_query_uses_activity_ids_not_scheduled_date_window(self):
        class FakeScalarResult:
            def __iter__(self):
                return iter([])

        class FakeDb:
            def __init__(self):
                self.query_text = ""

            def scalars(self, query):
                self.query_text = str(query)
                return FakeScalarResult()

        db = FakeDb()
        load_planned_workouts_with_feedback(db, type("User", (), {"id": 1})(), [10, 11])

        self.assertIn("completed_activity_id", db.query_text)
        self.assertNotIn("scheduled_date >=", db.query_text)

    def test_training_load_prefers_activity_stress_over_srpe_fallback(self):
        activity = make_activity(1, datetime(2026, 6, 1, 8, tzinfo=UTC), duration_seconds=3600, stress=42)
        workout = make_workout(1, activity.id, rpe=9)

        result = training_load_from_data([activity], [workout], None, date(2026, 6, 1), date(2026, 6, 1))
        point = result["daily"]["points"][0]

        self.assertEqual(point["load"], 42)
        self.assertEqual(point["load_method"], "aerobic_training_stress")
        self.assertEqual(point["duration_minutes"], 60.0)
        self.assertEqual(point["activity_ids"], [1])
        self.assertIsNotNone(point["ctl"])
        self.assertIsNotNone(point["atl"])
        self.assertIsNotNone(point["tsb"])
        self.assertEqual(point["srpe_count"], 0)

    def test_training_load_uses_srpe_when_stress_missing(self):
        activity = make_activity(1, datetime(2026, 6, 1, 8, tzinfo=UTC), duration_seconds=3600, stress=None)
        workout = make_workout(1, activity.id, rpe=5)

        result = training_load_from_data([activity], [workout], None, date(2026, 6, 1), date(2026, 6, 1))
        point = result["daily"]["points"][0]

        self.assertEqual(point["load"], 300)
        self.assertEqual(point["load_method"], "session_rpe")
        self.assertEqual(point["srpe_count"], 1)

    def test_training_load_buckets_activities_by_profile_timezone(self):
        timezone = ZoneInfo("Europe/Moscow")
        activity = make_activity(1, datetime(2026, 6, 1, 22, 30, tzinfo=UTC), stress=30)

        result = training_load_from_data([activity], [], None, date(2026, 6, 2), date(2026, 6, 2), timezone)
        point = result["daily"]["points"][0]

        self.assertEqual(point["date"], date(2026, 6, 2))
        self.assertEqual(point["load"], 30)

    def test_training_load_fitness_points_and_weekly_monotony(self):
        activities = [
            make_activity(1, datetime(2026, 6, 1, 8, tzinfo=UTC), stress=50),
            make_activity(2, datetime(2026, 6, 3, 8, tzinfo=UTC), stress=80),
            make_activity(3, datetime(2026, 6, 5, 8, tzinfo=UTC), stress=20),
        ]

        result = training_load_from_data(activities, [], None, date(2026, 6, 1), date(2026, 6, 7))

        self.assertEqual(len(result["fitness_fatigue"]["points"]), 7)
        self.assertIn("ctl", result["fitness_fatigue"]["current"])
        self.assertIsNotNone(result["weekly"]["points"][0]["monotony"])
        self.assertIsNotNone(result["daily"]["points"][-1]["monotony_window_value"])
        self.assertIsNotNone(result["daily"]["points"][-1]["strain_window_value"])

    def test_load_warnings_include_close_hard_sessions_and_intensity_share(self):
        activities = [
            make_activity(1, datetime(2026, 6, 1, 8, tzinfo=UTC), stress=90),
            make_activity(2, datetime(2026, 6, 2, 8, tzinfo=UTC), stress=95),
        ]
        result = training_load_from_data(activities, [], None, date(2026, 6, 1), date(2026, 6, 7))
        titles = {warning["title"] for warning in load_warnings(result["daily"]["points"], result["weekly"]["points"], result["fitness_fatigue"]["points"])}

        self.assertIn("Hard sessions too close", titles)
        self.assertIn("Too much intensity", titles)

    def test_hard_spacing_warning_uses_entire_selected_period(self):
        activities = [
            make_activity(1, datetime(2026, 6, 1, 8, tzinfo=UTC), stress=90),
            make_activity(2, datetime(2026, 6, 2, 8, tzinfo=UTC), stress=95),
            make_activity(3, datetime(2026, 6, 20, 8, tzinfo=UTC), stress=20),
        ]
        result = training_load_from_data(activities, [], None, date(2026, 6, 1), date(2026, 6, 28))
        titles = {warning["title"] for warning in load_warnings(result["daily"]["points"], result["weekly"]["points"], result["fitness_fatigue"]["points"])}

        self.assertIn("Hard sessions too close", titles)

    def test_hr_profile_enables_hr_trimp_fallback(self):
        profile = AthleteProfile(user_id=1, resting_heart_rate_bpm=50, max_heart_rate_bpm=190, lactate_threshold_pace_seconds_per_km=300)
        activity = make_activity(1, datetime(2026, 6, 1, 8, tzinfo=UTC), duration_seconds=3600, stress=None)
        activity.average_heart_rate_bpm = 160

        result = training_load_from_data([activity], [], profile, date(2026, 6, 1), date(2026, 6, 1))
        point = result["daily"]["points"][0]

        self.assertEqual(point["load_method"], "hr_trimp")
        self.assertGreater(point["load"], 0)

    def test_support_activity_uses_duration_fallback_without_distance(self):
        activity = make_activity(1, datetime(2026, 6, 1, 8, tzinfo=UTC), distance_km=None, duration_seconds=1800, stress=None)
        activity.activity_type = "manual_strength"

        result = training_load_from_data([activity], [], None, date(2026, 6, 1), date(2026, 6, 1))
        point = result["daily"]["points"][0]

        self.assertEqual(point["load_method"], "support_duration_fallback")
        self.assertEqual(point["load"], 22.5)

    def test_sync_daily_training_loads_upserts_materialized_rows(self):
        class FakeScalarResult:
            def __iter__(self):
                return iter([])

        class FakeDb:
            def __init__(self):
                self.added = []
                self.flushed = False

            def add(self, item):
                self.added.append(item)

            def flush(self):
                self.flushed = True

            def scalar(self, _query):
                return None

            def scalars(self, _query):
                return FakeScalarResult()

        activity = make_activity(1, datetime(2026, 6, 1, 8, tzinfo=UTC), duration_seconds=3600, stress=42)
        db = FakeDb()
        original_timezone = training_load_service.profile_timezone
        original_activities = training_load_service.load_activities
        original_workouts = training_load_service.load_planned_workouts_with_feedback
        try:
            training_load_service.profile_timezone = lambda _db, _user: ZoneInfo("UTC")
            training_load_service.load_activities = lambda _db, _user, _from_date, _to_date, _timezone: [activity]
            training_load_service.load_planned_workouts_with_feedback = lambda _db, _user, _activity_ids: []

            synced = sync_daily_training_loads(db, type("User", (), {"id": 1})(), date(2026, 6, 1), date(2026, 6, 1))
        finally:
            training_load_service.profile_timezone = original_timezone
            training_load_service.load_activities = original_activities
            training_load_service.load_planned_workouts_with_feedback = original_workouts

        self.assertTrue(db.flushed)
        self.assertEqual(synced, 1)
        self.assertEqual(len(db.added), 1)
        row = db.added[0]
        self.assertIsInstance(row, DailyTrainingLoad)
        self.assertEqual(row.load_value, 42)
        self.assertEqual(row.method, "manual")
        self.assertEqual(row.duration_minutes, 60.0)
        self.assertEqual(row.activity_ids, [1])


if __name__ == "__main__":
    unittest.main()
