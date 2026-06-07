import unittest
from datetime import date, timedelta

try:
    from pydantic import ValidationError

    from app.models import AthleteProfile
    from app.schemas.common import PlanGenerateRequest
    from app.services.planning import build_plan_preview_blueprint
    from app.services.profile import profile_completeness, safety_check
except ModuleNotFoundError as exc:
    if exc.name in {"pydantic", "sqlalchemy"}:
        raise unittest.SkipTest("Backend dependencies are required for plan builder preview tests") from exc
    raise


def make_profile(**kwargs) -> AthleteProfile:
    values = {
        "user_id": 1,
        "sex": "unspecified",
        "timezone": "Europe/Moscow",
        "locale": "ru-RU",
        "conservative_mode": False,
    }
    values.update(kwargs)
    return AthleteProfile(**values)


def make_context(**kwargs) -> dict[str, object]:
    values: dict[str, object] = {
        "activity_count": 12,
        "history_span_days": 70,
        "observed_weekly_volume_km": [18.0, 20.0, 22.0, 24.0, 26.0, 28.0],
        "current_weekly_volume_km": 25.0,
        "current_weekly_volume_source": "observed_median_4w",
        "recent_weekly_distance_km": 25.0,
        "recent_long_run_km": 14.0,
        "training_age_level": "intermediate",
        "confidence": "high",
    }
    values.update(kwargs)
    return values


class PlanBuilderPreviewTests(unittest.TestCase):
    def test_plan_request_rejects_invalid_race_distance(self):
        with self.assertRaises(ValidationError):
            PlanGenerateRequest(race_distance_km=0)
        with self.assertRaises(ValidationError):
            PlanGenerateRequest(race_distance_km=-5)

    def test_preview_builds_baseline_curve_and_workouts_without_persistence(self):
        start_date = date(2026, 6, 8)
        profile = make_profile(
            date_of_birth=date(1990, 1, 1),
            resting_heart_rate_bpm=48,
            max_heart_rate_bpm=188,
            lactate_threshold_pace_seconds_per_km=300,
            lactate_threshold_hr_bpm=170,
            weight_kg=72,
        )
        request = PlanGenerateRequest(
            title="10K builder",
            goal_type="10k",
            race_distance_km=10.0,
            target_date=start_date + timedelta(days=56),
            available_days_per_week=4,
        )

        preview = build_plan_preview_blueprint(
            request,
            profile,
            profile_completeness(profile),
            safety_check(profile),
            {"pace": [], "hr": [], "rpe": [], "metadata": {}},
            make_context(),
            start_date,
        )

        self.assertEqual(preview["weeks"], 8)
        self.assertEqual(preview["baseline"]["current_weekly_volume_source"], "observed_median_4w")
        self.assertEqual(preview["baseline"]["training_age_level"], "intermediate")
        self.assertEqual(len(preview["weekly_volume_curve"]), 8)
        self.assertEqual(len(preview["workouts"]), 32)
        self.assertEqual(preview["workouts"][0]["scheduled_date"], start_date)
        self.assertGreater(preview["peak_weekly_distance_km"], preview["current_weekly_distance_km"])
        self.assertNotIn("missing_recovery_after_hard", {flag["code"] for flag in preview["risk_flags"]})

    def test_preview_flags_target_too_close_before_plan_length_clamp(self):
        start_date = date(2026, 6, 8)
        profile = make_profile(
            date_of_birth=date(1990, 1, 1),
            resting_heart_rate_bpm=48,
            max_heart_rate_bpm=188,
            lactate_threshold_pace_seconds_per_km=300,
            lactate_threshold_hr_bpm=170,
            weight_kg=72,
        )
        request = PlanGenerateRequest(
            title="Tomorrow 5K",
            goal_type="5k",
            race_distance_km=5.0,
            target_date=start_date + timedelta(days=1),
            available_days_per_week=3,
            current_weekly_distance_km=20.0,
        )

        preview = build_plan_preview_blueprint(
            request,
            profile,
            profile_completeness(profile),
            safety_check(profile),
            {"pace": [], "hr": [], "rpe": [], "metadata": {}},
            make_context(),
            start_date,
        )

        target_flag = next(flag for flag in preview["risk_flags"] if flag["code"] == "target_too_close")
        self.assertEqual(preview["weeks"], 4)
        self.assertIn("available days: 1", target_flag["reasons"])

    def test_preview_reports_core_safety_risks(self):
        start_date = date(2026, 6, 8)
        profile = make_profile()
        request = PlanGenerateRequest(
            title="Risky marathon",
            goal_type="marathon",
            race_distance_km=42.2,
            target_date=start_date + timedelta(days=28),
            available_days_per_week=5,
            current_weekly_distance_km=12.0,
        )

        preview = build_plan_preview_blueprint(
            request,
            profile,
            profile_completeness(profile),
            safety_check(profile),
            {"pace": [], "hr": [], "rpe": [], "metadata": {}},
            make_context(activity_count=0, history_span_days=0, recent_long_run_km=None, training_age_level="beginner", confidence="low"),
            start_date,
        )

        codes = {flag["code"] for flag in preview["risk_flags"]}
        self.assertIn("target_too_close", codes)
        self.assertIn("marathon_low_volume", codes)
        self.assertIn("no_recent_long_run", codes)
        self.assertIn("missing_pace_zones", codes)
        self.assertIn("safety_gates", codes)


if __name__ == "__main__":
    unittest.main()
