import unittest
from datetime import UTC, date, datetime

try:
    from app.models import Activity, ActivitySegment, ActivityWorkoutBlock, AthleteProfile, TrainingPlanWorkout, TrainingPlanWorkoutFeedback
    from app.schemas.common import AthleteMeasurementCreate
    from app.api.routes.profile import apply_measurement_to_profile
    from app.services.zone_analytics import activity_efforts, classify_value, load_linked_workouts_with_feedback, planned_workout_zone, zone_distribution_from_data
    from app.services.zones import ZONE_INPUT_FIELDS, calculated_zones
except ModuleNotFoundError as exc:
    if exc.name in {"pydantic", "sqlalchemy"}:
        raise unittest.SkipTest("Backend dependencies are required for zone analytics tests") from exc
    raise


def make_activity(activity_id: int, started_at: datetime, distance_km: float | None = 5.0, duration_seconds: int = 1200) -> Activity:
    return Activity(
        id=activity_id,
        user_id=1,
        title=f"Activity {activity_id}",
        started_at=started_at,
        distance_km=distance_km,
        duration_seconds=duration_seconds,
        average_pace_seconds_per_km=round(duration_seconds / distance_km) if distance_km else None,
    )


def make_workout(workout_id: int, activity_id: int | None = None, intensity: str = "easy", duration_seconds: int = 1200, rpe: int | None = None) -> TrainingPlanWorkout:
    workout = TrainingPlanWorkout(
        id=workout_id,
        plan_id=1,
        scheduled_date=date(2026, 6, 1),
        status="done" if activity_id else "planned",
        completed_activity_id=activity_id,
        week_index=1,
        day_index=1,
        workout_type=intensity,
        title=f"{intensity} workout",
        distance_km=None,
        duration_seconds=duration_seconds,
        intensity=intensity,
    )
    if rpe is not None:
        workout.feedback = TrainingPlanWorkoutFeedback(id=workout_id, user_id=1, workout_id=workout_id, rpe=rpe, pain=False)
    return workout


class ZoneAnalyticsTests(unittest.TestCase):
    def test_calculated_zones_prefer_thresholds_and_include_rpe(self):
        profile = AthleteProfile(user_id=1, lactate_threshold_hr_bpm=170, lactate_threshold_pace_seconds_per_km=300)

        zones = calculated_zones(profile)
        hr = [zone for zone in zones if zone["unit"] == "bpm"]
        pace = [zone for zone in zones if zone["unit"] == "seconds_per_km"]
        rpe = [zone for zone in zones if zone["unit"] == "rpe"]

        self.assertEqual(hr[0]["method"], "threshold_hr")
        self.assertEqual(pace[0]["method"], "threshold_pace")
        self.assertEqual(len(rpe), 5)
        self.assertIn("lactate_threshold_hr_bpm", ZONE_INPUT_FIELDS)
        self.assertEqual(classify_value(hr, 152)["zone_key"], "z3")

    def test_lactate_threshold_hr_measurement_invalidates_calculated_zones(self):
        profile = AthleteProfile(user_id=1)
        payload = AthleteMeasurementCreate(measurement_type="lactate_threshold", value_numeric=171, source="manual")

        changed = apply_measurement_to_profile(profile, payload)

        self.assertTrue(changed)
        self.assertEqual(profile.lactate_threshold_hr_bpm, 171)

    def test_calculated_zones_use_vdot_pace_when_threshold_pace_missing(self):
        profile = AthleteProfile(user_id=1, lactate_threshold_hr_bpm=170)

        zones = calculated_zones(profile, vdot_threshold_pace=305, vdot_confidence="medium")
        pace = [zone for zone in zones if zone["unit"] == "seconds_per_km"]

        self.assertTrue(pace)
        self.assertEqual(pace[0]["method"], "vdot_threshold_estimate")
        self.assertEqual(pace[0]["confidence"], "medium")

    def test_zone_distribution_combines_hr_pace_rpe_and_planned_distribution(self):
        profile = AthleteProfile(user_id=1, lactate_threshold_hr_bpm=170, lactate_threshold_pace_seconds_per_km=300)
        zones = {
            "hr": [{**zone, "zone_type": "hr", "id": None, "is_active": True} for zone in calculated_zones(profile) if zone["unit"] == "bpm"],
            "pace": [{**zone, "zone_type": "pace", "id": None, "is_active": True} for zone in calculated_zones(profile) if zone["unit"] == "seconds_per_km"],
            "rpe": [{**zone, "zone_type": "rpe", "id": None, "is_active": True} for zone in calculated_zones(profile) if zone["unit"] == "rpe"],
            "metadata": {},
        }
        segmented = make_activity(1, datetime(2026, 6, 1, 8, tzinfo=UTC), 4.0, 1200)
        segmented.segments = [
            ActivitySegment(id=1, activity_id=1, segment_index=1, distance_km=1.0, duration_seconds=600, pace_seconds_per_km=380, average_heart_rate_bpm=130),
            ActivitySegment(id=2, activity_id=1, segment_index=2, distance_km=1.0, duration_seconds=600, pace_seconds_per_km=330, average_heart_rate_bpm=162),
        ]
        rpe_only = make_activity(2, datetime(2026, 6, 2, 8, tzinfo=UTC), None, 1200)
        linked = [make_workout(1, activity_id=2, intensity="tempo", duration_seconds=1200, rpe=8)]
        planned = [make_workout(2, intensity="easy", duration_seconds=1800), make_workout(3, intensity="interval", duration_seconds=1200)]

        result = zone_distribution_from_data([segmented, rpe_only], linked, planned, zones, date(2026, 6, 1), date(2026, 6, 7), profile=profile)
        actual = {item["zone_key"]: item for item in result["actual_five_zone"]}
        seiler = {item["zone_key"]: item for item in result["seiler_three_zone"]}
        planned_rows = {item["zone_key"]: item for item in result["planned_five_zone"]}
        hr = {item["zone_key"]: item for item in result["actual_hr"]}
        rpe = {item["zone_key"]: item for item in result["actual_rpe"]}

        self.assertEqual(hr["z1"]["duration_seconds"], 600)
        self.assertEqual(hr["z4"]["duration_seconds"], 600)
        self.assertEqual(rpe["z4"]["duration_seconds"], 1200)
        self.assertEqual(actual["z4"]["duration_seconds"], 1800)
        self.assertEqual(seiler["high"]["duration_seconds"], 1800)
        self.assertEqual(planned_rows["z2"]["duration_seconds"], 1800)
        self.assertEqual(planned_rows["z4"]["duration_seconds"], 1200)
        self.assertEqual(result["metadata"]["classified_actual_duration_seconds"], 2400)
        self.assertEqual(len(result["time_buckets"]), 1)

    def test_activity_efforts_prefer_blocks_when_they_cover_activity_duration(self):
        activity = make_activity(1, datetime(2026, 6, 1, 8, tzinfo=UTC), 2.0, 900)
        activity.segments = [ActivitySegment(id=1, activity_id=1, segment_index=1, distance_km=1.0, duration_seconds=450, pace_seconds_per_km=450, average_heart_rate_bpm=130)]
        activity.workout_blocks = [ActivityWorkoutBlock(id=1, activity_id=1, block_index=1, block_type="work", title="400m rep", distance_km=0.4, duration_seconds=900, pace_seconds_per_km=225, average_heart_rate_bpm=178)]

        efforts = activity_efforts(activity)

        self.assertEqual(len(efforts), 1)
        self.assertEqual(efforts[0]["duration_seconds"], 900)
        self.assertEqual(efforts[0]["heart_rate_bpm"], 178)

    def test_activity_efforts_prefer_full_segments_over_partial_blocks(self):
        activity = make_activity(1, datetime(2026, 6, 1, 8, tzinfo=UTC), 2.0, 900)
        activity.segments = [ActivitySegment(id=1, activity_id=1, segment_index=1, distance_km=2.0, duration_seconds=900, pace_seconds_per_km=450, average_heart_rate_bpm=130)]
        activity.workout_blocks = [ActivityWorkoutBlock(id=1, activity_id=1, block_index=1, block_type="work", title="400m rep", distance_km=0.4, duration_seconds=90, pace_seconds_per_km=225, average_heart_rate_bpm=178)]

        efforts = activity_efforts(activity)

        self.assertEqual(len(efforts), 1)
        self.assertEqual(efforts[0]["duration_seconds"], 900)
        self.assertEqual(efforts[0]["heart_rate_bpm"], 130)

    def test_planned_workout_zone_does_not_treat_workout_title_as_interval(self):
        workout = TrainingPlanWorkout(
            id=10,
            plan_id=1,
            scheduled_date=date(2026, 6, 1),
            status="planned",
            week_index=1,
            day_index=1,
            workout_type="custom",
            title="Morning workout",
            intensity=None,
        )

        self.assertEqual(planned_workout_zone(workout), "z2")

        workout.title = "Morning interval workout"
        self.assertEqual(planned_workout_zone(workout), "z4")

    def test_zone_analytics_feedback_query_prefers_active_plans_without_dropping_history(self):
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
        load_linked_workouts_with_feedback(db, type("User", (), {"id": 1})(), [10, 11])

        self.assertIn("CASE", db.query_text)
        self.assertIn("completed_activity_id", db.query_text)


if __name__ == "__main__":
    unittest.main()
