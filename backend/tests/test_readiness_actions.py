import unittest
from datetime import UTC, date, datetime, timedelta

try:
    from app.models import AthleteProfile, DailyReadinessActionPreview, DailyReadinessCheckIn, TrainingPlanWorkout, TrainingPlanWorkoutBlock, User
    from app.services.readiness import ReadinessActionConflict, action_state_fingerprint, action_target, apply_daily_readiness_action_preview, daily_readiness_recommendation
except ModuleNotFoundError as exc:
    if exc.name in {"pydantic", "sqlalchemy"}:
        raise unittest.SkipTest("Backend dependencies are required for readiness action tests") from exc
    raise


TODAY = date(2026, 7, 12)


def make_profile() -> AthleteProfile:
    return AthleteProfile(id=1, user_id=1, sex="unspecified", timezone="Europe/Moscow", locale="ru-RU", unit_system="metric", recovery_status="normal", conservative_mode=False)


def make_checkin(**values) -> DailyReadinessCheckIn:
    data = {
        "id": 2,
        "user_id": 1,
        "checkin_date": TODAY,
        "sleep_quality_0_10": 8,
        "fatigue_0_10": 3,
        "soreness_0_10": 2,
        "stress_0_10": 3,
        "pain": False,
        "illness_symptoms": False,
    }
    data.update(values)
    return DailyReadinessCheckIn(**data)


def make_workout(*, hard: bool = False, duration_seconds: int | None = 3600, distance_km: float | None = 10.0) -> TrainingPlanWorkout:
    workout = TrainingPlanWorkout(
        id=3,
        plan_id=4,
        scheduled_date=TODAY,
        status="planned",
        week_index=1,
        day_index=1,
        workout_type="interval" if hard else "easy",
        title="Intervals" if hard else "Easy run",
        distance_km=distance_km,
        duration_seconds=duration_seconds,
        intensity="threshold" if hard else "easy",
        description="Original workout",
    )
    workout.blocks = [TrainingPlanWorkoutBlock(
        id=5,
        workout_id=3,
        block_index=1,
        block_type="work",
        repeat_count=1,
        target_distance_km=distance_km,
        target_duration_seconds=duration_seconds,
        target_rpe_min=6 if hard else 2,
        target_rpe_max=8 if hard else 4,
    )]
    return workout


class ReadinessActionTests(unittest.TestCase):
    def test_shorten_target_scales_easy_workout_and_blocks(self):
        workout = make_workout()
        recommendation = daily_readiness_recommendation(make_checkin(fatigue_0_10=6), make_profile(), workout)

        target = action_target(workout, recommendation)

        self.assertEqual(target["distance_km"], 7.0)
        self.assertEqual(target["duration_seconds"], 2520)
        self.assertEqual(target["blocks"][0]["target_distance_km"], 7.0)
        self.assertEqual(target["blocks"][0]["target_duration_seconds"], 2520)
        self.assertIn("Readiness adjustment:", target["description"])

    def test_easy_replacement_removes_quality_targets(self):
        workout = make_workout(hard=True)
        recommendation = daily_readiness_recommendation(make_checkin(fatigue_0_10=7), make_profile(), workout)

        target = action_target(workout, recommendation)

        self.assertEqual(target["workout_type"], "easy")
        self.assertEqual(target["intensity"], "easy")
        self.assertIsNone(target["distance_km"])
        self.assertEqual(target["duration_seconds"], 2160)
        self.assertEqual(target["blocks"][0]["target_rpe_max"], 3)

    def test_non_applicable_recommendation_is_rejected(self):
        workout = make_workout()
        recommendation = daily_readiness_recommendation(make_checkin(), make_profile(), workout)

        with self.assertRaisesRegex(ReadinessActionConflict, "cannot be applied"):
            action_target(workout, recommendation)

    def test_shorten_without_measurable_target_is_rejected(self):
        workout = make_workout(duration_seconds=None, distance_km=None)
        recommendation = daily_readiness_recommendation(make_checkin(fatigue_0_10=6), make_profile(), workout)

        with self.assertRaises(ReadinessActionConflict) as context:
            action_target(workout, recommendation)

        self.assertEqual(context.exception.reason, "safety_blocks_action")

    def test_fingerprint_is_stable_for_dictionary_key_order(self):
        self.assertEqual(action_state_fingerprint({"b": 2, "a": 1}), action_state_fingerprint({"a": 1, "b": 2}))

    def test_applied_preview_remains_idempotent_after_expiry(self):
        response = {
            "status": "applied",
            "preview_id": "token",
            "action": "shorten_easy",
            "date": TODAY.isoformat(),
            "workout": {"id": 3},
            "plan_version_id": 6,
            "plan_version_number": 2,
            "recommendation_audit_id": 7,
            "audit_log_id": 8,
            "summary": "Applied",
        }
        preview = DailyReadinessActionPreview(
            id="token",
            user_id=1,
            plan_id=4,
            workout_id=3,
            checkin_id=2,
            checkin_date=TODAY,
            action="shorten_easy",
            rule_version="daily-readiness-v1",
            recommendation_snapshot={},
            preview_snapshot={},
            state_fingerprint="fingerprint",
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
            applied_at=datetime.now(UTC) - timedelta(minutes=2),
            applied_response_json=response,
        )

        class Db:
            def __init__(self):
                self.calls = 0

            def scalar(self, _query):
                self.calls += 1
                return User(id=1, display_name="Runner") if self.calls == 1 else preview

        result = apply_daily_readiness_action_preview(Db(), User(id=1, display_name="Runner"), "token")

        self.assertEqual(result["status"], "already_applied")
        self.assertEqual(result["plan_version_id"], 6)


if __name__ == "__main__":
    unittest.main()
