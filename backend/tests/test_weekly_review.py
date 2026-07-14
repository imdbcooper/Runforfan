import hashlib
import json
import unittest
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from app.db.migrations.runner import MIGRATIONS
    from app.services.historical_state import apply_plan_events, local_week_bounds, utc_week_interval
    from app.services.weekly_review import cap_target_duration, compute_weekly_review, weekly_review_input_fingerprint
except ModuleNotFoundError as exc:
    if exc.name in {"pydantic", "sqlalchemy"}:
        raise unittest.SkipTest("Backend dependencies are required for Weekly Review tests") from exc
    raise


FIXTURE = Path(__file__).parent / "fixtures" / "coach_replay" / "weekly_review_healthy.json"


class Profile:
    timezone = "Europe/Moscow"


class WeeklyReviewTests(unittest.TestCase):
    def fixture(self):
        return json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_local_week_uses_athlete_timezone_and_completed_week(self):
        week_start, week_end, timezone_name, _timezone = local_week_bounds(Profile(), datetime(2026, 7, 12, 22, 30, tzinfo=UTC))

        self.assertEqual(week_start, date(2026, 7, 6))
        self.assertEqual(week_end, date(2026, 7, 12))
        self.assertEqual(timezone_name, "Europe/Moscow")

    def test_dst_week_intervals_use_local_calendar_boundaries(self):
        timezone = ZoneInfo("America/New_York")
        spring_start, spring_end = utc_week_interval(date(2026, 3, 2), date(2026, 3, 8), timezone)
        fall_start, fall_end = utc_week_interval(date(2026, 10, 26), date(2026, 11, 1), timezone)

        self.assertEqual((spring_end - spring_start).total_seconds() / 3600, 167)
        self.assertEqual((fall_end - fall_start).total_seconds() / 3600, 169)
        self.assertEqual(spring_start, datetime(2026, 3, 2, 5, tzinfo=UTC))
        self.assertEqual(spring_end, datetime(2026, 3, 9, 4, tzinfo=UTC))

    def test_duration_cap_scales_top_level_and_blocks_consistently(self):
        target = {
            "distance_km": 12.0,
            "duration_seconds": 5400,
            "blocks": [
                {"target_distance_km": 4.0, "target_duration_seconds": 1800},
                {"target_distance_km": None, "target_duration_seconds": 3600},
            ],
        }

        capped = cap_target_duration(target, 3600)

        self.assertEqual(capped["duration_seconds"], 3600)
        self.assertEqual(capped["distance_km"], 8.0)
        self.assertEqual(capped["blocks"][0]["target_duration_seconds"], 1200)
        self.assertEqual(capped["blocks"][0]["target_distance_km"], 2.67)
        self.assertEqual(capped["blocks"][1]["target_duration_seconds"], 2400)

    def test_event_overlay_reconstructs_outcome_and_feedback(self):
        workouts = [{"id": 1, "scheduled_date": "2026-07-07", "status": "planned", "distance_km": 8.0}]
        events = [
            {"id": 2, "event_type": "workout_feedback_saved", "workout_id": 1, "payload": {"feedback": {"rpe": 5}, "execution_score": {"score": 1.0}}},
            {"id": 1, "event_type": "workout_completed", "workout_id": 1, "activity_id": 9, "payload": {"actual_distance_km": 8.2, "actual_duration_seconds": 3000}},
        ]

        result = apply_plan_events(workouts, events)

        self.assertEqual(result[0]["status"], "done")
        self.assertEqual(result[0]["actual"]["activity_id"], 9)
        self.assertEqual(result[0]["feedback"]["rpe"], 5)

    def test_healthy_complete_week_selects_conservative_progression(self):
        review = compute_weekly_review(self.fixture())

        self.assertEqual(review["recommended_strategy"], "conservative_progression")
        self.assertEqual(review["coverage"]["confidence"], "high")
        self.assertEqual(review["metrics"]["session_adherence"], 1.0)
        self.assertEqual(review["metrics"]["hard_sessions"], 1)

    def test_missing_or_partial_data_never_selects_progression(self):
        fixture = self.fixture()
        fixture["resolution"]["status"] = "partial_legacy"
        fixture["resolution"]["limitations"] = ["legacy gap"]

        review = compute_weekly_review(fixture)

        self.assertEqual(review["recommended_strategy"], "hold")
        self.assertIn("legacy gap", review["limitations"])

    def test_pain_overrides_positive_week(self):
        fixture = self.fixture()
        fixture["events"].append({"id": 900, "event_type": "pain_reported", "occurred_at": "2026-07-12T10:00:00+00:00", "payload": {"pain_level_0_10": 4}})

        review = compute_weekly_review(fixture)

        self.assertEqual(review["recommended_strategy"], "deload")
        self.assertIn({"model": "coaching_events", "id": 900}, review["evidence"])

    def test_profile_health_restrictions_override_positive_week(self):
        for field in ("injury_notes", "health_conditions"):
            with self.subTest(field=field):
                fixture = self.fixture()
                fixture["profile"][field] = "Current restriction"

                review = compute_weekly_review(fixture)

                self.assertEqual(review["recommended_strategy"], "deload")

    def test_recovery_trends_block_progression_without_pain(self):
        for signals, expected in (
            ({"sleep_quality_0_10": 5, "fatigue_0_10": 9, "soreness_0_10": 2, "stress_0_10": 2, "pain": False, "illness_symptoms": False}, "deload"),
            ({"sleep_quality_0_10": 4, "fatigue_0_10": 4, "soreness_0_10": 7, "stress_0_10": 2, "pain": False, "illness_symptoms": False}, "hold"),
            ({"sleep_quality_0_10": 7, "fatigue_0_10": 3, "soreness_0_10": 2, "stress_0_10": 8, "pain": False, "illness_symptoms": False}, "hold"),
        ):
            with self.subTest(signals=signals, expected=expected):
                fixture = self.fixture()
                for event in fixture["events"]:
                    if event["event_type"] == "readiness_checkin_saved":
                        event["payload"]["signals"] = signals

                review = compute_weekly_review(fixture)

                self.assertEqual(review["recommended_strategy"], expected)

    def test_single_calibrated_wearable_anomaly_only_holds_progression(self):
        fixture = self.fixture()
        as_of_at = datetime.fromisoformat(fixture["as_of_at"])
        fixture["recovery_observations"] = [
            {
                "id": index,
                "metric_key": "hrv_rmssd_ms",
                "value": 60.0 if index < 8 else 40.0,
                "unit": "ms",
                "observed_at": (as_of_at - timedelta(days=8 - index) if index < 8 else as_of_at - timedelta(hours=1)).isoformat(),
                "received_at": as_of_at.isoformat(),
                "source_kind": "device_import",
                "source_system": "generic",
                "source_label": "Generic",
                "quality": "high",
                "quality_score": 0.9,
                "normalization_version": "recovery-signals-v1",
            }
            for index in range(1, 9)
        ]

        review = compute_weekly_review(fixture)

        self.assertEqual(review["recommended_strategy"], "hold")
        self.assertNotEqual(review["recommended_strategy"], "deload")

    def test_same_day_checkin_correction_uses_latest_event(self):
        fixture = self.fixture()
        original = next(event for event in fixture["events"] if event["event_type"] == "readiness_checkin_saved")
        corrected = json.loads(json.dumps(original))
        corrected["id"] = 999
        corrected["occurred_at"] = "2026-07-12T20:00:00+00:00"
        corrected["payload"]["signals"]["fatigue_0_10"] = 9
        fixture["events"].append(corrected)

        review = compute_weekly_review(fixture)

        self.assertEqual(review["recommended_strategy"], "deload")

    def test_prior_deload_selects_resume_without_current_risk(self):
        fixture = self.fixture()
        fixture["events"].append({
            "id": 901,
            "event_type": "weekly_strategy_applied",
            "occurred_at": "2026-07-06T04:00:00+00:00",
            "payload": {
                "strategy": "deload",
                "changes": [
                    {"field": "distance_km", "before": 14.0, "after": 11.0},
                    {"field": "duration_seconds", "before": 5400, "after": 4300}
                ]
            }
        })

        review = compute_weekly_review(fixture)

        self.assertEqual(review["recommended_strategy"], "resume")
        self.assertEqual(review["metrics"]["prior_safe_baseline"]["planned_distance_km"], 14.0)

    def test_replay_is_order_independent_and_byte_stable(self):
        fixture = self.fixture()
        first = json.dumps(compute_weekly_review(fixture), ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        fixture["events"] = list(reversed(fixture["events"]))
        fixture["review_workouts"] = list(reversed(fixture["review_workouts"]))
        second = json.dumps(compute_weekly_review(fixture), ensure_ascii=True, sort_keys=True, separators=(",", ":"))

        self.assertEqual(first, second)
        self.assertEqual(hashlib.sha256(first.encode("utf-8")).hexdigest(), "95ce8d571dd71efd850ff7b067453388f22d833703acfef16796db6e7ab513d8")

    def test_fingerprint_ignores_collection_clock_but_not_evidence(self):
        first = self.fixture()
        second = self.fixture()
        second["as_of_at"] = "2026-07-13T09:00:00+00:00"

        self.assertEqual(weekly_review_input_fingerprint(first), weekly_review_input_fingerprint(second))
        second["events"].append({"id": 999, "event_type": "workout_missed", "occurred_at": "2026-07-10T10:00:00+00:00", "payload": {}})
        self.assertNotEqual(weekly_review_input_fingerprint(first), weekly_review_input_fingerprint(second))

    def test_migration_adds_weekly_review_contracts(self):
        migration = next(statements for version, statements in MIGRATIONS if version == "20260713_0026_weekly_reviews")
        sql = "\n".join(migration)

        self.assertIn("CREATE TABLE IF NOT EXISTS weekly_reviews", sql)
        self.assertIn("uq_weekly_review_input", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS weekly_strategy_previews", sql)


if __name__ == "__main__":
    unittest.main()
