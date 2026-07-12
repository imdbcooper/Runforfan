import unittest
from datetime import date

try:
    from pydantic import ValidationError

    from app.models import AthleteProfile, DailyReadinessCheckIn, TrainingPlanWorkout
    from app.schemas.common import DailyReadinessCheckInUpsert
    from app.services.readiness import daily_readiness_recommendation, readiness_to_dict, today_checkin
except ModuleNotFoundError as exc:
    if exc.name in {"pydantic", "sqlalchemy"}:
        raise unittest.SkipTest("Backend dependencies are required for readiness tests") from exc
    raise


TODAY = date(2026, 7, 12)


def make_profile(*, recovery_status: str = "normal", conservative_mode: bool = False) -> AthleteProfile:
    return AthleteProfile(
        id=1,
        user_id=1,
        sex="unspecified",
        timezone="Europe/Moscow",
        locale="ru-RU",
        unit_system="metric",
        recovery_status=recovery_status,
        conservative_mode=conservative_mode,
    )


def make_workout(*, workout_type: str = "easy", intensity: str = "easy", duration_seconds: int = 3600) -> TrainingPlanWorkout:
    return TrainingPlanWorkout(
        id=10,
        plan_id=20,
        scheduled_date=TODAY,
        status="planned",
        week_index=1,
        day_index=1,
        workout_type=workout_type,
        title="Today's workout",
        distance_km=10.0,
        duration_seconds=duration_seconds,
        intensity=intensity,
    )


def make_checkin(**values) -> DailyReadinessCheckIn:
    defaults = {
        "id": 30,
        "user_id": 1,
        "checkin_date": TODAY,
        "sleep_quality_0_10": 8,
        "fatigue_0_10": 3,
        "soreness_0_10": 2,
        "stress_0_10": 3,
        "pain": False,
        "pain_level_0_10": None,
        "illness_symptoms": False,
    }
    defaults.update(values)
    return DailyReadinessCheckIn(**defaults)


class DailyReadinessTests(unittest.TestCase):
    def test_checkin_is_required_before_workout_guidance(self):
        result = daily_readiness_recommendation(None, make_profile(), make_workout())

        self.assertEqual(result["status"], "checkin_required")
        self.assertEqual(result["action"], "checkin_required")

    def test_illness_has_priority_over_good_signals(self):
        checkin = make_checkin(illness_symptoms=True, sleep_quality_0_10=10, fatigue_0_10=0)

        result = daily_readiness_recommendation(checkin, make_profile(), make_workout())

        self.assertEqual(result["status"], "stop")
        self.assertEqual(result["action"], "rest_and_seek_guidance")

    def test_pain_level_four_stops_hard_workout(self):
        checkin = make_checkin(pain=True, pain_level_0_10=4)

        result = daily_readiness_recommendation(checkin, make_profile(), make_workout(workout_type="interval", intensity="threshold"))

        self.assertEqual(result["rule_id"], "pain_or_illness_stop")
        self.assertIsNone(result["prescribed_workout"])

    def test_any_reported_pain_never_prescribes_running(self):
        checkin = make_checkin(pain=True, pain_level_0_10=1)

        result = daily_readiness_recommendation(checkin, make_profile(), make_workout())

        self.assertEqual(result["action"], "rest_or_gentle_mobility")
        self.assertIsNone(result["prescribed_workout"])

    def test_high_fatigue_replaces_hard_workout_with_shorter_easy_run(self):
        workout = make_workout(workout_type="interval", intensity="threshold", duration_seconds=3600)
        checkin = make_checkin(fatigue_0_10=7)

        result = daily_readiness_recommendation(checkin, make_profile(), workout)

        self.assertEqual(result["action"], "easy_replacement")
        self.assertEqual(result["prescribed_workout"]["intensity"], "easy")
        self.assertEqual(result["prescribed_workout"]["duration_seconds"], 2160)
        self.assertLess(result["prescribed_workout"]["duration_seconds"], workout.duration_seconds)

    def test_moderate_fatigue_shortens_easy_workout(self):
        workout = make_workout(duration_seconds=3000)
        checkin = make_checkin(fatigue_0_10=6)

        result = daily_readiness_recommendation(checkin, make_profile(), workout)

        self.assertEqual(result["action"], "shorten_easy")
        self.assertEqual(result["prescribed_workout"]["duration_seconds"], 2100)
        self.assertEqual(result["prescribed_workout"]["distance_km"], 7.0)

    def test_good_checkin_does_not_add_unplanned_training(self):
        result = daily_readiness_recommendation(make_checkin(), make_profile(), None)

        self.assertEqual(result["action"], "optional_easy_movement")
        self.assertIsNone(result["prescribed_workout"])

    def test_profile_injury_has_priority_before_checkin(self):
        result = daily_readiness_recommendation(None, make_profile(recovery_status="injured"), make_workout())

        self.assertEqual(result["rule_id"], "profile_injured")
        self.assertEqual(result["status"], "stop")

    def test_payload_rejects_pain_level_without_pain(self):
        with self.assertRaises(ValidationError):
            DailyReadinessCheckInUpsert(sleep_quality_0_10=8, fatigue_0_10=3, soreness_0_10=2, stress_0_10=3, pain=False, pain_level_0_10=4)

    def test_payload_rejects_fractional_score(self):
        with self.assertRaises(ValidationError):
            DailyReadinessCheckInUpsert(sleep_quality_0_10=8, fatigue_0_10=4.5, soreness_0_10=2, stress_0_10=3)

    def test_payload_requires_all_four_readiness_scores(self):
        with self.assertRaises(ValidationError):
            DailyReadinessCheckInUpsert(sleep_quality_0_10=8, fatigue_0_10=3, soreness_0_10=2)

    def test_response_keeps_saved_recommendation_separate_from_current_evaluation(self):
        checkin = make_checkin()
        checkin.recommendation_snapshot = {"rule_version": "daily-readiness-v1", "action": "proceed_as_planned"}
        current = {"rule_version": "daily-readiness-v1", "action": "rest_or_gentle_mobility"}

        result = readiness_to_dict(TODAY, checkin, make_workout(), current)

        self.assertEqual(result["recommendation"], current)
        self.assertEqual(result["saved_recommendation"], checkin.recommendation_snapshot)

    def test_locked_checkin_query_uses_row_lock_and_user_scope(self):
        class CapturingDb:
            def __init__(self):
                self.query = None

            def scalar(self, query):
                self.query = query
                return None

        db = CapturingDb()

        today_checkin(db, type("UserStub", (), {"id": 42})(), TODAY, lock=True)

        sql = str(db.query.compile(compile_kwargs={"literal_binds": True}))
        self.assertIn("daily_readiness_checkins.user_id = 42", sql)
        self.assertIn("FOR UPDATE", sql)


if __name__ == "__main__":
    unittest.main()
