import unittest
from datetime import date, timedelta

try:
    from pydantic import ValidationError

    from app.models import AthleteProfile, TrainingPlan, User
    from app.schemas.common import PlanGenerateRequest
    from app.services.planning import apply_generated_plan_status, build_plan_preview_blueprint
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

    def test_preferred_weekdays_drive_schedule(self):
        start_date = date(2026, 6, 8)  # Monday
        profile = make_profile(
            date_of_birth=date(1990, 1, 1),
            resting_heart_rate_bpm=48,
            max_heart_rate_bpm=188,
            lactate_threshold_pace_seconds_per_km=300,
            lactate_threshold_hr_bpm=170,
            weight_kg=72,
        )
        request = PlanGenerateRequest(
            title="Preferred days",
            goal_type="10k",
            race_distance_km=10.0,
            available_days_per_week=3,
            preferred_weekdays=[2, 4, 6],
            current_weekly_distance_km=25.0,
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

        first_week_dates = [workout["scheduled_date"] for workout in preview["workouts"] if workout["week_index"] == 1]
        self.assertEqual([day.isoweekday() for day in first_week_dates], [2, 4, 6])

    def test_profile_preferences_drive_schedule_when_request_omits_them(self):
        start_date = date(2026, 6, 8)  # Monday
        profile = make_profile(
            date_of_birth=date(1990, 1, 1),
            resting_heart_rate_bpm=48,
            max_heart_rate_bpm=188,
            lactate_threshold_pace_seconds_per_km=300,
            lactate_threshold_hr_bpm=170,
            weight_kg=72,
            preferred_weekdays=[1, 3, 6],
            long_run_weekday=6,
            max_run_duration_minutes=45,
        )
        request = PlanGenerateRequest(
            title="Profile schedule",
            goal_type="10k",
            race_distance_km=10.0,
            available_days_per_week=3,
            current_weekly_distance_km=25.0,
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

        first_week = [workout for workout in preview["workouts"] if workout["week_index"] == 1]
        long_run = next(workout for workout in first_week if workout["workout_type"] == "long")
        self.assertEqual(preview["preferred_weekdays"], [1, 3, 6])
        self.assertEqual([workout["scheduled_date"].isoweekday() for workout in first_week], [1, 3, 6])
        self.assertEqual(long_run["scheduled_date"].isoweekday(), 6)
        self.assertLessEqual(long_run["duration_seconds"], 45 * 60)
        self.assertEqual(preview["constraints"]["max_long_run_duration_minutes"], 45)

    def test_no_hard_constraint_removes_hard_workouts_and_caps_long_run(self):
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
            title="Constraint plan",
            goal_type="half_marathon",
            race_distance_km=21.1,
            available_days_per_week=4,
            current_weekly_distance_km=30.0,
            no_hard_workouts=True,
            max_long_run_km=8.0,
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

        workout_types = {workout["workout_type"] for workout in preview["workouts"]}
        self.assertNotIn("interval", workout_types)
        self.assertNotIn("tempo", workout_types)
        self.assertLessEqual(max(week["long_run_km"] for week in preview["weekly_volume_curve"]), 8.0)
        self.assertTrue(preview["constraints"]["no_hard_workouts"])

    def test_hr_mode_uses_hr_zones_without_pace_or_hrr(self):
        start_date = date(2026, 6, 8)
        profile = make_profile(date_of_birth=date(1990, 1, 1), max_heart_rate_bpm=188)
        request = PlanGenerateRequest(
            title="HR plan",
            goal_type="10k",
            race_distance_km=10.0,
            available_days_per_week=4,
            current_weekly_distance_km=25.0,
            intensity_mode="hr",
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

        workout_types = {workout["workout_type"] for workout in preview["workouts"]}
        self.assertIn("interval", workout_types)
        self.assertIn("tempo", workout_types)
        self.assertNotIn("missing_pace_zones", {flag["code"] for flag in preview["risk_flags"]})

    def test_preview_adds_duration_only_strength_and_mobility_support(self):
        start_date = date(2026, 6, 8)
        profile = make_profile(date_of_birth=date(1990, 1, 1), lactate_threshold_pace_seconds_per_km=300)
        request = PlanGenerateRequest(
            title="Mixed plan",
            goal_type="10k",
            race_distance_km=10.0,
            available_days_per_week=4,
            current_weekly_distance_km=25.0,
            include_strength=True,
            strength_sessions_per_week=1,
            include_mobility=True,
            mobility_sessions_per_week=1,
            strength_equipment="bands",
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

        support = [workout for workout in preview["workouts"] if workout["workout_type"] in {"strength", "mobility"}]
        self.assertEqual(len(support), preview["weeks"] * 2)
        self.assertTrue(all(workout["distance_km"] is None for workout in support))
        self.assertTrue(all(workout["duration_seconds"] > 0 for workout in support))
        self.assertEqual(preview["weekly_volume_curve"][0]["support_sessions"], 2)
        self.assertEqual(preview["constraints"]["strength_sessions_per_week"], 1)
        self.assertIn("bands", support[0]["description"])
        self.assertGreater(preview["intensity_split"]["strength"], 0)
        self.assertGreater(preview["intensity_split"]["mobility"], 0)
        total_duration = sum(int(workout.get("duration_seconds") or 0) for workout in preview["workouts"])
        strength_duration = sum(int(workout.get("duration_seconds") or 0) for workout in preview["workouts"] if workout["workout_type"] == "strength")
        mobility_duration = sum(int(workout.get("duration_seconds") or 0) for workout in preview["workouts"] if workout["workout_type"] == "mobility")
        self.assertEqual(preview["intensity_split"]["strength"], round(strength_duration / total_duration, 3))
        self.assertEqual(preview["intensity_split"]["mobility"], round(mobility_duration / total_duration, 3))

    def test_target_time_recent_race_and_terrain_affect_preview(self):
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
            title="Ambitious race",
            goal_type="10k",
            race_distance_km=10.0,
            target_time_seconds=2400,
            priority="a",
            available_days_per_week=4,
            current_weekly_distance_km=25.0,
            recent_race_distance_km=10.0,
            recent_race_time_seconds=3000,
            terrain="trail",
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

        self.assertIn("ambitious_target_time", {flag["code"] for flag in preview["risk_flags"]})
        self.assertIn("Terrain constraint: trail", preview["workouts"][0]["description"])
        self.assertEqual(preview["priority"], "a")

    def test_base_building_does_not_default_to_marathon_distance(self):
        start_date = date(2026, 6, 8)
        profile = make_profile()
        request = PlanGenerateRequest(goal_type="base_building", race_distance_km=42.2, available_days_per_week=3, current_weekly_distance_km=20.0)

        preview = build_plan_preview_blueprint(
            request,
            profile,
            profile_completeness(profile),
            safety_check(profile),
            {"pace": [], "hr": [], "rpe": [], "metadata": {}},
            make_context(),
            start_date,
        )

        self.assertEqual(preview["race_distance_km"], 10.0)
        self.assertNotIn("marathon_low_volume", {flag["code"] for flag in preview["risk_flags"]})

    def test_duration_constraints_use_estimated_pace(self):
        start_date = date(2026, 6, 8)
        profile = make_profile()
        request = PlanGenerateRequest(
            goal_type="10k",
            race_distance_km=10.0,
            available_days_per_week=3,
            current_weekly_distance_km=30.0,
            target_time_seconds=2400,
            max_long_run_duration_minutes=45,
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

        self.assertEqual(preview["constraints"]["estimated_easy_pace_seconds_per_km"], 300)
        self.assertLessEqual(max(week["long_run_km"] for week in preview["weekly_volume_curve"]), 9.0)

    def test_manual_zero_volume_is_preserved_as_manual_source(self):
        start_date = date(2026, 6, 8)
        profile = make_profile()
        request = PlanGenerateRequest(goal_type="5k", race_distance_km=5.0, available_days_per_week=3, current_weekly_distance_km=0.0)

        preview = build_plan_preview_blueprint(
            request,
            profile,
            profile_completeness(profile),
            safety_check(profile),
            {"pace": [], "hr": [], "rpe": [], "metadata": {}},
            make_context(current_weekly_volume_km=40.0),
            start_date,
        )

        self.assertEqual(preview["baseline"]["current_weekly_volume_source"], "manual_override")
        self.assertEqual(preview["current_weekly_distance_km"], 3.0)

    def test_time_budget_and_long_run_cap_bound_weekly_curve(self):
        start_date = date(2026, 6, 8)
        profile = make_profile()
        request = PlanGenerateRequest(
            goal_type="10k",
            race_distance_km=10.0,
            available_days_per_week=7,
            current_weekly_distance_km=40.0,
            time_budget_minutes_per_week=70,
            max_long_run_km=1.0,
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

        max_week = max(week["planned_distance_km"] for week in preview["weekly_volume_curve"])
        self.assertLessEqual(max_week, 10.0)
        self.assertEqual(preview["peak_weekly_distance_km"], max_week)
        self.assertLessEqual(max(week["long_run_km"] for week in preview["weekly_volume_curve"]), 1.0)

    def test_time_budget_limits_support_sessions_before_running_volume(self):
        start_date = date(2026, 6, 8)
        profile = make_profile()
        request = PlanGenerateRequest(
            goal_type="10k",
            race_distance_km=10.0,
            available_days_per_week=4,
            current_weekly_distance_km=25.0,
            time_budget_minutes_per_week=30,
            include_strength=True,
            strength_sessions_per_week=1,
            include_mobility=True,
            mobility_sessions_per_week=1,
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
        first_week = [workout for workout in preview["workouts"] if workout["week_index"] == 1]
        first_week_duration = sum(int(workout.get("duration_seconds") or 0) for workout in first_week)

        self.assertLessEqual(first_week_duration, 30 * 60)
        self.assertEqual(preview["constraints"]["strength_sessions_per_week"], 0)
        self.assertEqual(preview["constraints"]["mobility_sessions_per_week"], 1)
        self.assertTrue(preview["constraints"]["support_limited_by_time_budget"])
        self.assertIn("support_limited_by_time_budget", {flag["code"] for flag in preview["risk_flags"]})

    def test_tight_time_budget_flags_running_floor_instead_of_shrinking_below_floor(self):
        start_date = date(2026, 6, 8)
        profile = make_profile()
        request = PlanGenerateRequest(
            goal_type="10k",
            race_distance_km=10.0,
            available_days_per_week=4,
            current_weekly_distance_km=25.0,
            target_time_seconds=172800,
            time_budget_minutes_per_week=30,
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

        self.assertGreaterEqual(preview["weekly_volume_curve"][0]["planned_distance_km"], 1.0)
        self.assertIn("time_budget_below_running_floor", {flag["code"] for flag in preview["risk_flags"]})

    def test_generated_plan_activation_archives_existing_active_plan(self):
        existing_active = TrainingPlan(id=1, user_id=1, title="Old", goal_type="10k", status="active", available_days_per_week=3)
        new_plan = TrainingPlan(id=2, user_id=1, title="New", goal_type="10k", status="draft", available_days_per_week=3)

        class FakeDb:
            def __init__(self):
                self.added = []

            def scalars(self, _query):
                return [existing_active]

            def flush(self):
                return None

            def scalar(self, _query):
                return None

            def add(self, item):
                self.added.append(item)

        fake_db = FakeDb()

        apply_generated_plan_status(fake_db, User(id=1, display_name="Runner"), new_plan, activate=True)

        self.assertEqual(existing_active.status, "archived")
        self.assertEqual(new_plan.status, "active")
        self.assertEqual(len(fake_db.added), 1)
        self.assertEqual(fake_db.added[0].reason, "manual_edit")


if __name__ == "__main__":
    unittest.main()
