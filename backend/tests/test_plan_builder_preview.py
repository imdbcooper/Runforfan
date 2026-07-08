import unittest
from datetime import date, timedelta

try:
    from pydantic import ValidationError

    from app.models import Activity, ActivityWorkoutBlock, AthleteProfile, TrainingPlan, User
    from app.schemas.common import PlanGenerateRequest
    from app.services.planning import activity_is_quality_session, apply_generated_plan_status, build_plan_preview_blueprint, classify_training_age_level, estimated_volume_from_sparse_history
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
        "consistent_weeks": 10,
        "quality_sessions_8w": 1,
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
        self.assertEqual(preview["baseline"]["detected_training_age_level"], "intermediate")
        self.assertEqual(preview["baseline"]["consistent_weeks"], 10)
        self.assertEqual(len(preview["weekly_volume_curve"]), 8)
        self.assertEqual(len(preview["workouts"]), 32)
        self.assertEqual(preview["workouts"][0]["scheduled_date"], start_date)
        self.assertTrue(preview["workouts"][0]["blocks"])
        self.assertGreater(preview["peak_weekly_distance_km"], preview["current_weekly_distance_km"])
        self.assertNotIn("missing_recovery_after_hard", {flag["code"] for flag in preview["risk_flags"]})

    def test_plan_length_weeks_drives_preview_without_target_date(self):
        start_date = date(2026, 6, 8)
        profile = make_profile(lactate_threshold_pace_seconds_per_km=300)
        request = PlanGenerateRequest(
            title="12 week 10K",
            goal_type="10k",
            race_distance_km=10.0,
            plan_length_weeks=12,
            available_days_per_week=3,
            current_weekly_distance_km=24.0,
            longest_recent_run_km=9.0,
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

        self.assertEqual(preview["weeks"], 12)
        self.assertIsNone(preview["target_date"])
        self.assertEqual(preview["constraints"]["plan_length_weeks"], 12)
        self.assertEqual(len([workout for workout in preview["workouts"] if workout["distance_km"] is not None]), 36)

    def test_training_age_classification_uses_spec_inputs(self):
        self.assertEqual(classify_training_age_level(14.9, 12.0, 8, 4), "beginner")
        self.assertEqual(classify_training_age_level(30.0, 5.9, 8, 4), "beginner")
        self.assertEqual(classify_training_age_level(30.0, 10.0, 8, 0), "intermediate")
        self.assertEqual(classify_training_age_level(50.0, 20.0, 16, 0), "intermediate")
        self.assertEqual(classify_training_age_level(50.0, 20.0, 16, 2), "advanced")

    def test_quality_session_detection_ignores_generic_single_work_block(self):
        easy = Activity(id=1, user_id=1, activity_type="outdoor_run", title="Easy run", duration_seconds=3600)
        easy.workout_blocks = [ActivityWorkoutBlock(block_index=1, block_type="work", title="Continuous running", duration_seconds=3600)]
        imported_easy = Activity(id=4, user_id=1, activity_type="outdoor_run", title="Easy run", source_note="intervals.csv", duration_seconds=3600)
        tempo = Activity(id=2, user_id=1, activity_type="outdoor_run", title="Easy run", duration_seconds=3600)
        tempo.workout_blocks = [ActivityWorkoutBlock(block_index=1, block_type="work", title="Threshold segment", duration_seconds=1200)]
        intervals = Activity(id=3, user_id=1, activity_type="outdoor_run", title="Structured run", duration_seconds=3600)
        intervals.workout_blocks = [
            ActivityWorkoutBlock(block_index=1, block_type="work", title="Fast repeat", duration_seconds=300),
            ActivityWorkoutBlock(block_index=2, block_type="recovery", title="Jog", duration_seconds=180),
            ActivityWorkoutBlock(block_index=3, block_type="work", title="Fast repeat", duration_seconds=300),
        ]

        self.assertFalse(activity_is_quality_session(easy))
        self.assertFalse(activity_is_quality_session(imported_easy))
        self.assertTrue(activity_is_quality_session(tempo))
        self.assertTrue(activity_is_quality_session(intervals))

    def test_sparse_history_estimates_volume_from_real_runs(self):
        volume, source = estimated_volume_from_sparse_history([10.2, 11.0, 9.8], [], requested_days=4)

        self.assertEqual(source, "estimated_from_recent_runs")
        self.assertGreaterEqual(volume, 29.0)

    def test_recent_quality_history_can_schedule_first_week_interval(self):
        start_date = date(2026, 6, 8)
        profile = make_profile(lactate_threshold_pace_seconds_per_km=300)
        request = PlanGenerateRequest(goal_type="10k", race_distance_km=10.0, plan_length_weeks=8, available_days_per_week=4)

        preview = build_plan_preview_blueprint(
            request,
            profile,
            profile_completeness(profile),
            safety_check(profile),
            {"pace": [], "hr": [], "rpe": [], "metadata": {}},
            make_context(current_weekly_volume_km=30.0, recent_weekly_distance_km=30.0, recent_long_run_km=11.0, quality_sessions_8w=1, recent_run_count_4w=3, recent_run_distance_median_km=10.0),
            start_date,
        )

        first_week = [workout for workout in preview["workouts"] if workout["week_index"] == 1]
        self.assertIn("interval", {workout["workout_type"] for workout in first_week})
        self.assertGreaterEqual(max(float(workout["distance_km"] or 0) for workout in first_week), 9.0)

    def test_recent_typical_run_protects_primary_workouts_from_tiny_distances(self):
        start_date = date(2026, 6, 8)
        profile = make_profile(lactate_threshold_pace_seconds_per_km=300)
        request = PlanGenerateRequest(goal_type="10k", race_distance_km=10.0, plan_length_weeks=8, available_days_per_week=4)

        preview = build_plan_preview_blueprint(
            request,
            profile,
            profile_completeness(profile),
            safety_check(profile),
            {"pace": [], "hr": [], "rpe": [], "metadata": {}},
            make_context(current_weekly_volume_km=30.0, recent_weekly_distance_km=30.0, recent_long_run_km=11.0, quality_sessions_8w=1, recent_run_count_4w=3, recent_run_distance_median_km=10.0),
            start_date,
        )

        first_week = [workout for workout in preview["workouts"] if workout["week_index"] == 1]
        primary_runs = [workout for workout in first_week if workout["workout_type"] not in {"long", "recovery"}]
        recovery = next(workout for workout in first_week if workout["workout_type"] == "recovery")
        self.assertTrue(primary_runs)
        self.assertTrue(all(float(workout["distance_km"] or 0) >= 7.0 for workout in primary_runs))
        self.assertGreaterEqual(float(recovery["distance_km"] or 0), 4.5)
        self.assertNotIn("short_runs_vs_recent_pattern", {flag["code"] for flag in preview["risk_flags"]})

    def test_running_days_reduce_when_recent_pattern_would_create_tiny_runs(self):
        start_date = date(2026, 6, 8)
        profile = make_profile(lactate_threshold_pace_seconds_per_km=300)
        request = PlanGenerateRequest(goal_type="10k", race_distance_km=10.0, plan_length_weeks=8, available_days_per_week=4)

        preview = build_plan_preview_blueprint(
            request,
            profile,
            profile_completeness(profile),
            safety_check(profile),
            {"pace": [], "hr": [], "rpe": [], "metadata": {}},
            make_context(current_weekly_volume_km=20.0, recent_weekly_distance_km=20.0, recent_long_run_km=10.0, quality_sessions_8w=1, recent_run_count_4w=2, recent_run_distance_median_km=10.0),
            start_date,
        )

        first_week = [workout for workout in preview["workouts"] if workout["week_index"] == 1 and workout["distance_km"] is not None]
        primary_runs = [workout for workout in first_week if workout["workout_type"] not in {"long", "recovery"}]
        self.assertEqual(preview["available_days_per_week"], 3)
        self.assertTrue(preview["constraints"]["running_days_capped_by_recent_pattern"])
        self.assertIn("running_days_capped_by_recent_pattern", {flag["code"] for flag in preview["risk_flags"]})
        self.assertTrue(all(float(workout["distance_km"] or 0) >= 5.5 for workout in primary_runs))

    def test_ready_mixed_mode_can_use_rpe_intervals_without_pace_zones(self):
        start_date = date(2026, 6, 8)
        profile = make_profile()
        request = PlanGenerateRequest(goal_type="10k", race_distance_km=10.0, plan_length_weeks=8, available_days_per_week=3, intensity_mode="mixed")

        preview = build_plan_preview_blueprint(
            request,
            profile,
            profile_completeness(profile),
            safety_check(profile),
            {"pace": [], "hr": [], "rpe": [], "metadata": {}},
            make_context(current_weekly_volume_km=28.0, recent_weekly_distance_km=28.0, recent_long_run_km=10.0, quality_sessions_8w=0, recent_run_count_4w=3, recent_run_distance_median_km=9.0, consistent_weeks=6),
            start_date,
        )

        first_week_types = {workout["workout_type"] for workout in preview["workouts"] if workout["week_index"] == 1}
        self.assertIn("interval", first_week_types)
        self.assertNotIn("safety_gates", {flag["code"] for flag in preview["risk_flags"]})

    def test_two_day_marathon_keeps_long_run_primary_and_adds_quality(self):
        start_date = date(2026, 7, 8)
        profile = make_profile(lactate_threshold_pace_seconds_per_km=300, lactate_threshold_hr_bpm=160)
        request = PlanGenerateRequest(
            goal_type="marathon",
            race_distance_km=42.2,
            plan_length_weeks=16,
            available_days_per_week=2,
            current_weekly_distance_km=22.0,
            longest_recent_run_km=11.7,
        )

        preview = build_plan_preview_blueprint(
            request,
            profile,
            profile_completeness(profile),
            safety_check(profile),
            {"pace": [], "hr": [], "rpe": [], "metadata": {}},
            make_context(
                activity_count=5,
                current_weekly_volume_km=22.0,
                recent_weekly_distance_km=22.0,
                recent_long_run_km=11.7,
                recent_run_count_4w=3,
                recent_run_distance_median_km=10.3,
                consistent_weeks=2,
                quality_sessions_8w=1,
            ),
            start_date,
        )

        first_week = [workout for workout in preview["workouts"] if workout["week_index"] == 1 and workout["distance_km"] is not None]
        interval = next(workout for workout in first_week if workout["workout_type"] == "interval")
        long = next(workout for workout in first_week if workout["workout_type"] == "long")
        block_types = {block["block_type"] for block in interval["blocks"]}

        self.assertEqual(preview["available_days_per_week"], 2)
        self.assertGreater(float(long["distance_km"] or 0), float(interval["distance_km"] or 0))
        self.assertGreaterEqual(float(long["distance_km"] or 0), preview["weekly_volume_curve"][0]["planned_distance_km"] * 0.5)
        self.assertIn("work", block_types)
        self.assertIn("recovery", block_types)
        self.assertIn("marathon_low_frequency", {flag["code"] for flag in preview["risk_flags"]})

    def test_aggressiveness_override_only_lowers_detected_level(self):
        start_date = date(2026, 6, 8)
        profile = make_profile(lactate_threshold_pace_seconds_per_km=300)
        advanced_context = make_context(
            history_span_days=140,
            observed_weekly_volume_km=[48.0, 50.0, 52.0, 54.0, 56.0, 58.0],
            current_weekly_volume_km=54.0,
            recent_weekly_distance_km=54.0,
            recent_long_run_km=22.0,
            consistent_weeks=16,
            quality_sessions_8w=3,
            training_age_level="advanced",
        )
        lowered_request = PlanGenerateRequest(goal_type="10k", race_distance_km=10.0, aggressiveness="beginner", available_days_per_week=4)

        lowered = build_plan_preview_blueprint(
            lowered_request,
            profile,
            profile_completeness(profile),
            safety_check(profile),
            {"pace": [], "hr": [], "rpe": [], "metadata": {}},
            advanced_context,
            start_date,
        )

        self.assertEqual(lowered["baseline"]["detected_training_age_level"], "advanced")
        self.assertEqual(lowered["baseline"]["training_age_level"], "beginner")
        self.assertFalse(lowered["constraints"]["aggressiveness_capped"])

        beginner_context = make_context(
            history_span_days=12,
            observed_weekly_volume_km=[0.0, 0.0, 0.0, 0.0, 8.0, 10.0],
            current_weekly_volume_km=10.0,
            recent_weekly_distance_km=10.0,
            recent_long_run_km=4.0,
            consistent_weeks=2,
            quality_sessions_8w=0,
            training_age_level="beginner",
        )
        upgrade_request = PlanGenerateRequest(goal_type="10k", race_distance_km=10.0, aggressiveness="advanced", available_days_per_week=4)

        capped = build_plan_preview_blueprint(
            upgrade_request,
            profile,
            profile_completeness(profile),
            safety_check(profile),
            {"pace": [], "hr": [], "rpe": [], "metadata": {}},
            beginner_context,
            start_date,
        )

        self.assertEqual(capped["baseline"]["detected_training_age_level"], "beginner")
        self.assertEqual(capped["baseline"]["training_age_level"], "beginner")
        self.assertTrue(capped["constraints"]["aggressiveness_capped"])

    def test_zero_consistent_weeks_is_not_recomputed_from_observed_buckets(self):
        start_date = date(2026, 6, 8)
        profile = make_profile(lactate_threshold_pace_seconds_per_km=300)
        request = PlanGenerateRequest(goal_type="marathon", race_distance_km=42.2, available_days_per_week=5, current_weekly_distance_km=60.0, longest_recent_run_km=24.0)

        preview = build_plan_preview_blueprint(
            request,
            profile,
            profile_completeness(profile),
            safety_check(profile),
            {"pace": [], "hr": [], "rpe": [], "metadata": {}},
            make_context(
                history_span_days=180,
                observed_weekly_volume_km=[50.0, 55.0, 60.0, 62.0, 64.0, 66.0],
                current_weekly_volume_km=60.0,
                recent_weekly_distance_km=60.0,
                recent_long_run_km=24.0,
                consistent_weeks=0,
                quality_sessions_8w=3,
                training_age_level="beginner",
            ),
            start_date,
        )

        self.assertEqual(preview["baseline"]["consistent_weeks"], 0)
        self.assertEqual(preview["baseline"]["detected_training_age_level"], "beginner")
        self.assertEqual(preview["constraints"]["max_weekly_growth"], 0.05)

    def test_four_day_composition_has_one_quality_and_recovery_day(self):
        start_date = date(2026, 6, 8)
        profile = make_profile(lactate_threshold_pace_seconds_per_km=300)
        request = PlanGenerateRequest(goal_type="10k", race_distance_km=10.0, available_days_per_week=4, current_weekly_distance_km=28.0, longest_recent_run_km=10.0)

        preview = build_plan_preview_blueprint(
            request,
            profile,
            profile_completeness(profile),
            safety_check(profile),
            {"pace": [], "hr": [], "rpe": [], "metadata": {}},
            make_context(),
            start_date,
        )
        build_week_index = next(week["week_index"] for week in preview["weekly_volume_curve"] if week["phase"] == "build")
        build_week = [workout for workout in preview["workouts"] if workout["week_index"] == build_week_index and workout["distance_km"] is not None]
        hard = [workout for workout in build_week if workout["workout_type"] in {"interval", "tempo", "threshold", "hill", "race_pace"}]

        self.assertEqual(len(build_week), 4)
        self.assertEqual(len(hard), 1)
        self.assertIn("recovery", {workout["workout_type"] for workout in build_week})

    def test_beginner_rpe_without_threshold_zones_avoids_hard_workouts(self):
        start_date = date(2026, 6, 8)
        profile = make_profile()
        request = PlanGenerateRequest(
            goal_type="10k",
            race_distance_km=10.0,
            available_days_per_week=4,
            current_weekly_distance_km=12.0,
            longest_recent_run_km=5.0,
            intensity_mode="rpe",
        )

        preview = build_plan_preview_blueprint(
            request,
            profile,
            profile_completeness(profile),
            safety_check(profile),
            {"pace": [], "hr": [], "rpe": [], "metadata": {}},
            make_context(
                current_weekly_volume_km=12.0,
                recent_weekly_distance_km=12.0,
                recent_long_run_km=5.0,
                consistent_weeks=2,
                quality_sessions_8w=0,
                training_age_level="beginner",
            ),
            start_date,
        )

        workout_types = {workout["workout_type"] for workout in preview["workouts"]}
        self.assertNotIn("interval", workout_types)
        self.assertNotIn("tempo", workout_types)
        self.assertNotIn("hill", workout_types)
        self.assertIn("steady", workout_types)

    def test_beginner_seven_day_request_is_capped_by_experience(self):
        start_date = date(2026, 6, 8)
        profile = make_profile(lactate_threshold_pace_seconds_per_km=300)
        request = PlanGenerateRequest(goal_type="10k", race_distance_km=10.0, available_days_per_week=7, current_weekly_distance_km=12.0, longest_recent_run_km=5.0)

        preview = build_plan_preview_blueprint(
            request,
            profile,
            profile_completeness(profile),
            safety_check(profile),
            {"pace": [], "hr": [], "rpe": [], "metadata": {}},
            make_context(
                current_weekly_volume_km=12.0,
                recent_weekly_distance_km=12.0,
                recent_long_run_km=5.0,
                consistent_weeks=2,
                quality_sessions_8w=0,
                training_age_level="beginner",
            ),
            start_date,
        )

        first_week = [workout for workout in preview["workouts"] if workout["week_index"] == 1 and workout["distance_km"] is not None]
        self.assertEqual(preview["available_days_per_week"], 5)
        self.assertEqual(len(first_week), 5)
        self.assertTrue(preview["constraints"]["running_days_capped_by_experience"])
        self.assertIn("running_days_capped_by_experience", {flag["code"] for flag in preview["risk_flags"]})

    def test_10k_periodization_exposes_phases_and_one_week_taper(self):
        start_date = date(2026, 6, 8)
        profile = make_profile(lactate_threshold_pace_seconds_per_km=300)
        request = PlanGenerateRequest(
            goal_type="10k",
            race_distance_km=10.0,
            target_time_seconds=2400,
            plan_length_weeks=8,
            available_days_per_week=4,
            current_weekly_distance_km=25.0,
            longest_recent_run_km=10.0,
            include_mobility=True,
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
        phases = [week["phase"] for week in preview["weekly_volume_curve"]]
        first_week_types = {workout["workout_type"] for workout in preview["workouts"] if workout["week_index"] == 1}
        final_week = preview["weekly_volume_curve"][-1]
        previous_week = preview["weekly_volume_curve"][-2]
        taper_workouts = [workout for workout in preview["workouts"] if workout["week_index"] == final_week["week_index"]]

        self.assertEqual(preview["constraints"]["taper_weeks"], 1)
        self.assertEqual(phases[-1], "taper")
        self.assertIn("base", phases)
        self.assertIn("build", phases)
        self.assertIn("specific", phases)
        self.assertTrue(final_week["is_taper"])
        self.assertLess(final_week["planned_distance_km"], previous_week["planned_distance_km"])
        self.assertIn("interval", first_week_types)
        self.assertNotIn("tempo", first_week_types)
        self.assertIn("race_pace", {workout["workout_type"] for workout in taper_workouts})
        self.assertTrue(all(workout["phase"] == "taper" for workout in taper_workouts))
        self.assertTrue(any(workout["workout_type"] == "mobility" and workout["phase"] == "taper" for workout in taper_workouts))

    def test_half_and_marathon_taper_defaults_are_distance_specific(self):
        start_date = date(2026, 6, 8)
        profile = make_profile(lactate_threshold_pace_seconds_per_km=300)
        half = build_plan_preview_blueprint(
            PlanGenerateRequest(goal_type="half_marathon", race_distance_km=21.1, plan_length_weeks=12, available_days_per_week=4, current_weekly_distance_km=35.0, longest_recent_run_km=14.0),
            profile,
            profile_completeness(profile),
            safety_check(profile),
            {"pace": [], "hr": [], "rpe": [], "metadata": {}},
            make_context(current_weekly_volume_km=35.0, recent_weekly_distance_km=35.0, recent_long_run_km=14.0),
            start_date,
        )
        marathon = build_plan_preview_blueprint(
            PlanGenerateRequest(goal_type="marathon", race_distance_km=42.2, plan_length_weeks=18, available_days_per_week=5, current_weekly_distance_km=60.0, longest_recent_run_km=24.0),
            profile,
            profile_completeness(profile),
            safety_check(profile),
            {"pace": [], "hr": [], "rpe": [], "metadata": {}},
            make_context(current_weekly_volume_km=60.0, recent_weekly_distance_km=60.0, recent_long_run_km=24.0, consistent_weeks=18, quality_sessions_8w=3, training_age_level="advanced"),
            start_date,
        )

        self.assertEqual(half["constraints"]["taper_weeks"], 2)
        self.assertEqual([week["phase"] for week in half["weekly_volume_curve"][-2:]], ["taper", "taper"])
        self.assertGreater(half["weekly_volume_curve"][-2]["planned_distance_km"], half["weekly_volume_curve"][-1]["planned_distance_km"])
        self.assertNotIn("race_pace", {workout["workout_type"] for workout in half["workouts"]})
        self.assertEqual(marathon["constraints"]["taper_weeks"], 3)
        self.assertEqual([week["phase"] for week in marathon["weekly_volume_curve"][-3:]], ["taper", "taper", "taper"])
        taper_distances = [week["planned_distance_km"] for week in marathon["weekly_volume_curve"][-3:]]
        self.assertEqual(taper_distances, sorted(taper_distances, reverse=True))

    def test_beginner_weekly_growth_and_long_run_share_are_capped(self):
        start_date = date(2026, 6, 8)
        profile = make_profile(lactate_threshold_pace_seconds_per_km=300)
        request = PlanGenerateRequest(
            title="Safe 10K",
            goal_type="10k",
            race_distance_km=10.0,
            plan_length_weeks=10,
            available_days_per_week=3,
            current_weekly_distance_km=10.0,
            longest_recent_run_km=5.0,
        )

        preview = build_plan_preview_blueprint(
            request,
            profile,
            profile_completeness(profile),
            safety_check(profile),
            {"pace": [], "hr": [], "rpe": [], "metadata": {}},
            make_context(
                history_span_days=18,
                observed_weekly_volume_km=[0.0, 0.0, 0.0, 10.0, 10.0, 10.0],
                current_weekly_volume_km=10.0,
                recent_weekly_distance_km=10.0,
                recent_long_run_km=5.0,
                consistent_weeks=2,
                quality_sessions_8w=0,
                training_age_level="beginner",
            ),
            start_date,
        )

        previous_build_volume = preview["current_weekly_distance_km"]
        for week in preview["weekly_volume_curve"]:
            planned = week["planned_distance_km"]
            if week["week_index"] % 4 == 0:
                self.assertLessEqual(planned, round(previous_build_volume * 0.85, 1))
            else:
                self.assertLessEqual(planned, round(previous_build_volume * 1.05, 1) + 0.1)
                previous_build_volume = planned
            self.assertLessEqual(week["long_run_km"], round(planned * 0.30, 1) + 0.1)
        self.assertEqual(preview["constraints"]["max_weekly_growth"], 0.05)
        self.assertEqual(preview["constraints"]["long_run_share"], 0.30)

    def test_time_budget_growth_cap_uses_actual_planned_distance(self):
        start_date = date(2026, 6, 8)
        profile = make_profile(lactate_threshold_pace_seconds_per_km=300)
        request = PlanGenerateRequest(
            title="Budget capped",
            goal_type="10k",
            race_distance_km=10.0,
            plan_length_weeks=8,
            available_days_per_week=7,
            current_weekly_distance_km=60.0,
            longest_recent_run_km=20.0,
            time_budget_minutes_per_week=70,
        )

        preview = build_plan_preview_blueprint(
            request,
            profile,
            profile_completeness(profile),
            safety_check(profile),
            {"pace": [], "hr": [], "rpe": [], "metadata": {}},
            make_context(
                history_span_days=140,
                observed_weekly_volume_km=[55.0, 56.0, 57.0, 58.0, 59.0, 60.0],
                current_weekly_volume_km=60.0,
                recent_weekly_distance_km=60.0,
                recent_long_run_km=20.0,
                consistent_weeks=16,
                quality_sessions_8w=2,
                training_age_level="advanced",
            ),
            start_date,
        )

        previous_build_volume = preview["weekly_volume_curve"][0]["planned_distance_km"]
        for week in preview["weekly_volume_curve"][1:]:
            planned = week["planned_distance_km"]
            if week["week_index"] % 4 != 0:
                self.assertLessEqual(planned, round(previous_build_volume * 1.10, 1) + 0.1)
                previous_build_volume = planned

    def test_marathon_defaults_cap_long_run_distance_and_duration(self):
        start_date = date(2026, 6, 8)
        profile = make_profile(max_run_duration_minutes=240)
        request = PlanGenerateRequest(
            title="Advanced marathon",
            goal_type="marathon",
            race_distance_km=42.2,
            plan_length_weeks=18,
            available_days_per_week=5,
            current_weekly_distance_km=80.0,
            longest_recent_run_km=28.0,
            max_long_run_km=40.0,
            max_long_run_duration_minutes=240,
        )
        zones = {
            "pace": [{"zone_key": "easy", "lower_value": 300, "upper_value": 420}],
            "hr": [],
            "rpe": [],
            "metadata": {},
        }

        preview = build_plan_preview_blueprint(
            request,
            profile,
            profile_completeness(profile),
            safety_check(profile),
            zones,
            make_context(
                history_span_days=180,
                observed_weekly_volume_km=[70.0, 75.0, 80.0, 82.0, 84.0, 86.0],
                current_weekly_volume_km=82.0,
                recent_weekly_distance_km=82.0,
                recent_long_run_km=28.0,
                consistent_weeks=18,
                quality_sessions_8w=3,
                training_age_level="advanced",
            ),
            start_date,
        )

        max_long_run = max(week["long_run_km"] for week in preview["weekly_volume_curve"])
        long_runs = [workout for workout in preview["workouts"] if workout["workout_type"] == "long"]

        self.assertEqual(preview["baseline"]["training_age_level"], "advanced")
        self.assertEqual(preview["constraints"]["default_max_long_run_km"], 32.0)
        self.assertEqual(preview["constraints"]["default_max_long_run_duration_minutes"], 180)
        self.assertEqual(preview["constraints"]["max_long_run_km"], 32.0)
        self.assertEqual(preview["constraints"]["max_long_run_duration_minutes"], 180)
        self.assertLessEqual(max_long_run, 32.0)
        self.assertLessEqual(max(workout["duration_seconds"] for workout in long_runs), 180 * 60)

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
            available_days_per_week=5,
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
        self.assertNotIn("strides", workout_types)
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

        build_week_index = next(week["week_index"] for week in preview["weekly_volume_curve"] if week["phase"] == "build")
        build_week = [workout for workout in preview["workouts"] if workout["week_index"] == build_week_index and workout["distance_km"] is not None]
        workout_types = {workout["workout_type"] for workout in build_week}
        hard = [workout for workout in build_week if workout["workout_type"] in {"interval", "tempo", "threshold", "hill", "race_pace"}]
        self.assertIn("interval", workout_types)
        self.assertEqual(len(hard), 1)
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
        self.assertEqual(preview["constraints"]["taper_weeks"], 0)
        self.assertNotIn("taper", {week["phase"] for week in preview["weekly_volume_curve"]})
        self.assertNotIn("specific", {week["phase"] for week in preview["weekly_volume_curve"]})

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
