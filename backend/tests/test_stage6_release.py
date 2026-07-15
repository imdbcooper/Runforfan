import json
import unittest
from unittest.mock import patch

try:
    from app.core.settings import Settings
    from app.services.stage6_release import EXPECTED_MANIFEST_FINGERPRINT, RELEASE_GATE_VERSION, REPLAY_VERSION, run_strategy_replay, software_release_gate
except ModuleNotFoundError as exc:
    if exc.name in {"pydantic", "sqlalchemy"}:
        raise unittest.SkipTest("Backend dependencies are required for Stage 6 release tests") from exc
    raise


class Stage6ReleaseTests(unittest.TestCase):
    def test_replay_covers_bounded_strategy_space_and_is_stable(self):
        first = run_strategy_replay()
        second = run_strategy_replay()
        self.assertEqual(first, second)
        self.assertEqual(first["replay_version"], REPLAY_VERSION)
        self.assertEqual(first["status"], "pass")
        self.assertEqual({item["actual_strategy"] for item in first["scenarios"]}, {"hold", "deload", "resume", "conservative_progression"})
        self.assertEqual(first["strategy_allowlist"], ["conservative_progression", "deload", "hold", "resume"])
        self.assertEqual(first["manifest_fingerprint"], EXPECTED_MANIFEST_FINGERPRINT)

    def test_safety_and_missing_evidence_scenarios_never_progress(self):
        report = run_strategy_replay()
        scenarios = {item["id"]: item for item in report["scenarios"]}
        self.assertEqual(scenarios["pain_deload"]["actual_strategy"], "deload")
        self.assertEqual(scenarios["partial_hold"]["actual_strategy"], "hold")
        self.assertEqual(scenarios["overdone_hold"]["actual_strategy"], "hold")
        self.assertEqual(scenarios["illness_deload"]["actual_strategy"], "deload")
        self.assertEqual(scenarios["profile_restriction_deload"]["actual_strategy"], "deload")
        self.assertEqual(scenarios["high_risk_feedback_deload"]["actual_strategy"], "deload")
        self.assertEqual(scenarios["severe_fatigue_deload"]["actual_strategy"], "deload")
        self.assertEqual(scenarios["reduced_readiness_hold"]["actual_strategy"], "hold")
        self.assertEqual(scenarios["unlinked_completion_hold"]["actual_strategy"], "hold")
        self.assertEqual(scenarios["low_adherence_hold"]["actual_strategy"], "hold")
        self.assertEqual(scenarios["missing_checkins_hold"]["actual_strategy"], "hold")
        self.assertEqual(scenarios["missing_workouts_hold"]["actual_strategy"], "hold")
        self.assertEqual(scenarios["wearable_anomaly_hold"]["actual_strategy"], "hold")
        self.assertEqual(scenarios["same_day_correction_deload"]["actual_strategy"], "deload")

    def test_golden_manifest_drift_blocks_executable_gate(self):
        with patch("app.services.stage6_release.EXPECTED_MANIFEST_FINGERPRINT", "0" * 64):
            replay = run_strategy_replay()
            report = software_release_gate(Settings())
        self.assertEqual(replay["status"], "block")
        self.assertEqual(report["gates"]["strategy_replay"], "block")
        self.assertEqual(report["status"], "block")

    def test_default_off_software_gate_passes_without_operational_overclaim(self):
        report = software_release_gate(Settings())
        self.assertEqual(report["release_gate_version"], RELEASE_GATE_VERSION)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["operational_staffed_review"], "blocked_pending_human_checklist")
        self.assertEqual(report["product_outcome_claims"], "insufficient_data_pending_retention_and_trust_measurement")
        self.assertIn("Software baseline only", report["disclaimer"])

    def test_any_open_rollout_blocks_software_gate(self):
        for field in ("coach_delivery_enabled", "coach_delivery_worker_enabled", "coach_post_workout_delivery_enabled", "coach_weekly_review_delivery_enabled", "safety_escalation_enabled", "safety_review_enabled", "safety_review_reviewer_api_enabled"):
            with self.subTest(field=field):
                report = software_release_gate(Settings(**{field: True}))
                self.assertEqual(report["status"], "block")
                self.assertFalse(report["closed_rollout_flags"][field])

    def test_release_report_has_no_context_or_identity_data(self):
        serialized = json.dumps(software_release_gate(Settings()), ensure_ascii=True, sort_keys=True).lower()
        for forbidden in ("user_id", "plan_id", "request_id", "display_name", "pain_level", "health_conditions", "injury_notes"):
            self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
