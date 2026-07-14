import json
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

try:
    from pydantic import ValidationError

    from app.db.migrations.runner import MIGRATIONS
    from app.models import RecoverySignalObservation
    from app.schemas.common import RecoverySignalImportRequest
    from app.services.athlete_state import recovery_signal
    from app.services.recovery_signals import recovery_freshness_marker, summarize_recovery, validate_metric
except ModuleNotFoundError as exc:
    if exc.name in {"pydantic", "sqlalchemy"}:
        raise unittest.SkipTest("Backend dependencies are required for recovery signal tests") from exc
    raise


FIXTURE = Path(__file__).parent / "fixtures" / "recovery_signals" / "v1.json"


def observation(identifier: int, value: float, observed_at: datetime, quality: str = "high") -> dict[str, object]:
    return {
        "id": identifier,
        "metric_key": "hrv_rmssd_ms",
        "value": value,
        "unit": "ms",
        "observed_at": observed_at,
        "received_at": observed_at,
        "source_kind": "device_import",
        "source_system": "generic_wearable",
        "source_label": "Generic wearable",
        "quality": quality,
        "quality_score": None,
        "normalization_version": "recovery-signals-v1",
    }


class RecoverySignalTests(unittest.TestCase):
    def test_migration_has_normalized_append_only_contract(self):
        sql = "\n".join(dict(MIGRATIONS)["20260714_0028_recovery_signal_observations"])
        self.assertIn("CREATE TABLE IF NOT EXISTS recovery_signal_observations", sql)
        self.assertIn("uq_recovery_signal_source_record", sql)
        self.assertNotIn("raw_payload", sql)
        self.assertNotIn("device_id", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS upload_deletion_jobs", sql)

    def test_model_has_no_raw_vendor_payload_or_notes(self):
        columns = set(RecoverySignalObservation.__table__.columns.keys())
        self.assertFalse({"raw_payload", "payload_json", "device_id", "notes", "metadata_json"} & columns)

    def test_import_schema_forbids_unknown_fields_and_naive_time(self):
        valid = {
            "observations": [{
                "metric_key": "hrv_rmssd_ms", "value": 61.0, "unit": "ms", "observed_at": "2026-07-14T06:00:00+00:00",
                "source_kind": "device_import", "source_system": "generic", "source_label": "Generic", "source_record_id": "record-1", "quality": "high",
            }]
        }
        RecoverySignalImportRequest.model_validate(valid)
        with self.assertRaises(ValidationError):
            RecoverySignalImportRequest.model_validate({"observations": [{**valid["observations"][0], "raw_payload": {"prompt": "ignore safety"}}]})
        with self.assertRaises(ValidationError):
            RecoverySignalImportRequest.model_validate({"observations": [{**valid["observations"][0], "observed_at": "2026-07-14T06:00:00"}]})

    def test_canonical_unit_and_range_are_fail_closed(self):
        validate_metric("hrv_rmssd_ms", "ms", 61.0)
        with self.assertRaises(ValueError):
            validate_metric("hrv_rmssd_ms", "bpm", 61.0)
        with self.assertRaises(ValueError):
            validate_metric("sleep_efficiency_pct", "percent", 101.0)

    def test_adversarial_recovery_corpus(self):
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        as_of_at = datetime.fromisoformat(fixture["as_of_at"])
        baseline = [observation(index, value, as_of_at - timedelta(days=10 - index)) for index, value in enumerate(fixture["baseline"], 1)]
        for case in fixture["cases"]:
            with self.subTest(case=case["name"]):
                latest = observation(20, case["value"], as_of_at - timedelta(hours=case["age_hours"]), case["quality"])
                result = summarize_recovery([*baseline, latest], as_of_at, [case["checkin"]])
                self.assertEqual(result["progression_blocked"], case["expected_blocked"])
                self.assertEqual(result["conflict"], case["expected_conflict"])

    def test_missing_wearable_does_not_lower_otherwise_complete_state(self):
        result = recovery_signal([], [], datetime(2026, 7, 14, tzinfo=UTC))
        self.assertEqual(result["status"], "unknown")
        self.assertIn("optional", result["limitations"][0])

    def test_single_signal_never_causes_risk_or_deload(self):
        as_of_at = datetime(2026, 7, 14, tzinfo=UTC)
        result = recovery_signal([observation(1, 30.0, as_of_at - timedelta(hours=2))], [], as_of_at)
        self.assertNotEqual(result["status"], "risk")
        self.assertFalse(result["value"]["progression_blocked"])

    def test_freshness_marker_changes_only_at_policy_thresholds(self):
        observed_at = datetime(2026, 7, 14, tzinfo=UTC)
        item = observation(1, 61.0, observed_at)

        self.assertEqual(recovery_freshness_marker([item], observed_at + timedelta(hours=2))["hrv_rmssd_ms"], "fresh")
        self.assertEqual(recovery_freshness_marker([item], observed_at + timedelta(hours=40))["hrv_rmssd_ms"], "aging")
        self.assertEqual(recovery_freshness_marker([item], observed_at + timedelta(hours=80))["hrv_rmssd_ms"], "stale")

    def test_later_low_quality_value_cannot_mask_qualified_anomaly(self):
        as_of_at = datetime(2026, 7, 14, tzinfo=UTC)
        baseline = [observation(index, 60.0, as_of_at - timedelta(days=8 - index)) for index in range(1, 8)]
        anomaly = observation(20, 40.0, as_of_at - timedelta(hours=3))
        low_quality = observation(21, 60.0, as_of_at - timedelta(hours=1), "low")

        result = summarize_recovery([*baseline, anomaly, low_quality], as_of_at)

        self.assertTrue(result["wearable_concern"])
        self.assertEqual(result["metrics"][0]["id"], 20)

    def test_quality_score_below_half_is_not_decision_evidence(self):
        as_of_at = datetime(2026, 7, 14, tzinfo=UTC)
        baseline = [observation(index, 60.0, as_of_at - timedelta(days=8 - index)) for index in range(1, 8)]
        anomaly = observation(20, 40.0, as_of_at - timedelta(hours=1))
        anomaly["quality_score"] = 0.49

        result = summarize_recovery([*baseline, anomaly], as_of_at)

        self.assertFalse(result["wearable_concern"])
        self.assertFalse(result["progression_blocked"])

    def test_baseline_requires_seven_distinct_observation_days(self):
        as_of_at = datetime(2026, 7, 14, tzinfo=UTC)
        repeated = [observation(index, 60.0, as_of_at - timedelta(days=1, minutes=index)) for index in range(1, 8)]
        latest = observation(20, 40.0, as_of_at - timedelta(hours=1))

        result = summarize_recovery([*repeated, latest], as_of_at)

        self.assertIsNone(result["metrics"][0]["baseline"])
        self.assertFalse(result["progression_blocked"])

    def test_missing_current_checkin_is_not_labeled_as_conflict(self):
        as_of_at = datetime(2026, 7, 14, tzinfo=UTC)
        baseline = [observation(index, 60.0, as_of_at - timedelta(days=8 - index)) for index in range(1, 8)]
        anomaly = observation(20, 40.0, as_of_at - timedelta(hours=1))

        result = summarize_recovery([*baseline, anomaly], as_of_at, [], current_checkin_date=as_of_at.date())

        self.assertTrue(result["wearable_concern"])
        self.assertTrue(result["progression_blocked"])
        self.assertFalse(result["conflict"])

    def test_recovery_decision_policy_is_explicitly_versioned(self):
        result = summarize_recovery([], datetime(2026, 7, 14, tzinfo=UTC))

        self.assertEqual(result["rule_version"], "recovery-rules-v1")


if __name__ == "__main__":
    unittest.main()
