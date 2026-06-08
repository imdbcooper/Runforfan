from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

DEPENDENCY_SKIP_REASON = None

try:
    from app.api.routes import imports as imports_routes
    from app.models import ImportRecognitionAttempt, LlmProviderSetting, User
    from app.services.recognition import RECOGNITION_PROMPT, RecognitionValidationError, llm_or_template_recognize, parse_llm_recognition_payload
except ModuleNotFoundError as exc:
    if exc.name in {"fastapi", "httpx", "pydantic", "pydantic_core", "sqlalchemy", "starlette", "multipart"}:
        DEPENDENCY_SKIP_REASON = "Backend dependencies are required for recognition LLM tests"
    else:
        raise
except RuntimeError as exc:
    if "python-multipart" in str(exc):
        DEPENDENCY_SKIP_REASON = "python-multipart is required for import route tests"
    else:
        raise


class FakeDb:
    def __init__(self, provider: LlmProviderSetting | None):
        self.provider = provider
        self.added = []

    def scalar(self, query):
        return self.provider

    def add(self, item):
        self.added.append(item)

    def flush(self):
        return None


class NestedTransaction:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class ConfirmDb(FakeDb):
    def __init__(self):
        super().__init__(None)
        self.committed = False

    def begin_nested(self):
        return NestedTransaction()

    def commit(self):
        self.committed = True


def valid_llm_payload() -> dict:
    return {
        "activity": {
            "title": "Morning run",
            "started_at": "2026-06-08T07:00:00+00:00",
            "distance_km": 5.0,
            "duration_seconds": 1500,
            "calories_kcal": None,
            "average_pace_seconds_per_km": 300,
            "fastest_pace_seconds_per_km": None,
            "average_speed_kmh": 12.0,
            "average_cadence_spm": None,
            "average_stride_cm": None,
            "steps_count": None,
            "average_heart_rate_bpm": 145,
            "elevation_gain_m": None,
            "elevation_loss_m": None,
            "aerobic_training_stress": None,
            "aerobic_training_effect": None,
        },
        "segments": [],
        "split_blocks": [],
        "workout_blocks": [],
        "confidence": "medium",
        "uncertainty_notes": ["pace visible, calories hidden"],
        "estimated_fields": ["activity.average_speed_kmh"],
    }


@unittest.skipIf(DEPENDENCY_SKIP_REASON is not None, DEPENDENCY_SKIP_REASON or "")
class RecognitionLlmTests(unittest.TestCase):
    def test_prompt_contains_strict_section_12_contract(self):
        prompt = RECOGNITION_PROMPT.lower()

        self.assertIn("return json only", prompt)
        self.assertIn("confidence", prompt)
        self.assertIn("uncertainty_notes", prompt)
        self.assertIn("estimated_fields", prompt)
        self.assertIn("do not infer invisible fields", prompt)

    def test_llm_output_requires_confidence_uncertainty_and_estimated_fields(self):
        payload = valid_llm_payload()
        del payload["confidence"]

        with self.assertRaises(RecognitionValidationError) as ctx:
            parse_llm_recognition_payload(json.dumps(payload))

        self.assertIn("strict recognition schema", ctx.exception.errors[0])

    def test_llm_output_rejects_extra_unstructured_fields(self):
        payload = valid_llm_payload()
        payload["activity"]["raw_visible_text"] = "freeform"

        with self.assertRaises(RecognitionValidationError):
            parse_llm_recognition_payload(json.dumps(payload))

    def test_llm_output_rejects_invalid_started_at_before_pending_confirmation(self):
        payload = valid_llm_payload()
        payload["activity"]["started_at"] = "not a date"

        with self.assertRaises(RecognitionValidationError):
            parse_llm_recognition_payload(json.dumps(payload))

    def test_llm_output_rejects_inconsistent_distance_duration_and_pace(self):
        payload = valid_llm_payload()
        payload["activity"]["average_pace_seconds_per_km"] = 420

        with self.assertRaises(RecognitionValidationError) as ctx:
            parse_llm_recognition_payload(json.dumps(payload))

        self.assertIn("distance/time/pace", ctx.exception.errors[0])

    def test_llm_output_allows_moving_pace_vs_elapsed_duration_tolerance(self):
        payload = valid_llm_payload()
        payload["activity"]["average_pace_seconds_per_km"] = 240

        parsed = parse_llm_recognition_payload(json.dumps(payload))

        self.assertEqual(parsed["activity"]["average_pace_seconds_per_km"], 240)

    def test_llm_output_must_be_json_only_without_surrounding_text(self):
        with self.assertRaises(RecognitionValidationError) as ctx:
            parse_llm_recognition_payload(f"Here is the JSON:\n{json.dumps(valid_llm_payload())}")

        self.assertIn("no surrounding text", ctx.exception.errors[0])

    def test_unknown_screenshot_without_provider_is_rejected(self):
        db = FakeDb(None)

        result = llm_or_template_recognize(db, 12, [Path("unknown.png")], type("Settings", (), {})(), User(id=1, display_name="Runner"))

        self.assertEqual(result["status"], "rejected_no_llm_template")
        self.assertIsNone(result["payload"])
        attempt = next(item for item in db.added if isinstance(item, ImportRecognitionAttempt))
        self.assertEqual(attempt.status, "rejected_no_llm_template")

    def test_valid_llm_recognition_returns_pending_confirmation(self):
        provider = LlmProviderSetting(id=1, user_id=1, provider="openai", display_name="Vision", model="gpt-4o-mini", is_active=True, is_default=True)
        db = FakeDb(provider)

        with patch("app.services.recognition._recognize_openai", return_value=({"id": "resp"}, json.dumps(valid_llm_payload()))):
            result = llm_or_template_recognize(db, 12, [Path("unknown.png")], type("Settings", (), {"llm_timeout": 10})(), User(id=1, display_name="Runner"))

        self.assertEqual(result["status"], "pending_confirmation")
        self.assertTrue(result["requires_confirmation"])
        self.assertEqual(result["payload"]["confidence"], "medium")
        attempt = next(item for item in db.added if isinstance(item, ImportRecognitionAttempt))
        self.assertEqual(attempt.status, "validated_pending_confirmation")
        self.assertEqual(attempt.parsed_payload["uncertainty_notes"], ["pace visible, calories hidden"])

    def test_candidate_preview_exposes_only_safe_llm_candidate_fields(self):
        payload = valid_llm_payload()
        payload["segments"] = [{"segment_index": 1, "distance_km": 5.0, "duration_seconds": 1500, "pace_seconds_per_km": 300}]
        payload["workout_blocks"] = [{"block_index": 1, "block_type": "easy", "duration_seconds": 1500, "distance_km": 5.0}]

        candidate = imports_routes.candidate_from_payload(payload)

        self.assertEqual(candidate["activity"], {
            "title": "Morning run",
            "started_at": "2026-06-08T07:00:00+00:00",
            "distance_km": 5.0,
            "duration_seconds": 1500,
            "average_pace_seconds_per_km": 300,
            "average_heart_rate_bpm": 145,
        })
        self.assertEqual(candidate["confidence"], "medium")
        self.assertEqual(candidate["uncertainty_notes"], ["pace visible, calories hidden"])
        self.assertEqual(candidate["estimated_fields"], ["activity.average_speed_kmh"])
        self.assertEqual(candidate["segments_count"], 1)
        self.assertEqual(candidate["workout_blocks_count"], 1)
        self.assertNotIn("calories_kcal", candidate["activity"])
        self.assertNotIn("average_speed_kmh", candidate["activity"])
        self.assertNotIn("segments", candidate)
        self.assertNotIn("workout_blocks", candidate)

    def test_import_result_includes_pending_candidate_without_created_activity(self):
        batch = SimpleNamespace(
            id=12,
            status="pending_confirmation",
            source_app=None,
            recognition_engine="llm:gpt-4o-mini",
            recognition_message="Подтвердите импорт",
            created_activity_id=None,
            created_at=None,
        )
        attempt = SimpleNamespace(parsed_payload=valid_llm_payload())

        with patch.object(imports_routes, "latest_recognition_attempt", return_value=attempt), patch.object(imports_routes, "matched_workout_id_for_activity", return_value=None):
            result = imports_routes.import_result(object(), SimpleNamespace(id=1), batch)

        self.assertTrue(result["requires_confirmation"])
        self.assertIsNone(result["created_activity_id"])
        self.assertEqual(result["candidate"]["confidence"], "medium")
        self.assertEqual(result["match_status"], "unmatched")

    def test_confirm_import_creates_activity_only_from_pending_candidate(self):
        db = ConfirmDb()
        user = SimpleNamespace(id=1)
        batch = SimpleNamespace(
            id=12,
            status="pending_confirmation",
            source_app=None,
            recognition_engine="llm:gpt-4o-mini",
            recognition_message="Подтвердите импорт",
            created_activity_id=None,
            created_at=None,
            sources=[SimpleNamespace(source_id=101)],
        )
        attempt = SimpleNamespace(parsed_payload=valid_llm_payload())
        activity = SimpleNamespace(id=55)

        with (
            patch.object(imports_routes, "import_batch_for_user", return_value=batch),
            patch.object(imports_routes, "latest_recognition_attempt", return_value=attempt),
            patch.object(imports_routes, "create_activity_from_payload", return_value=activity) as create_activity,
            patch.object(imports_routes, "auto_match_activity_to_plan", return_value=None),
            patch.object(imports_routes, "sync_daily_training_loads_for_activity") as sync_load,
            patch.object(imports_routes, "log_audit_event") as audit,
            patch.object(imports_routes, "matched_workout_id_for_activity", return_value=None),
        ):
            result = imports_routes.confirm_import(12, user=user, db=db)

        create_activity.assert_called_once_with(db, user, attempt.parsed_payload, [101])
        sync_load.assert_called_once_with(db, user, activity)
        audit.assert_called_once()
        self.assertTrue(db.committed)
        self.assertEqual(batch.status, "recognized")
        self.assertEqual(batch.created_activity_id, 55)
        self.assertEqual(result["created_activity_id"], 55)
        self.assertEqual(result["candidate"]["confidence"], "medium")

    def test_candidate_patch_updates_safe_fields_and_clears_estimated_flags(self):
        payload = valid_llm_payload()
        payload["estimated_fields"] = ["activity.distance_km", "activity.average_pace_seconds_per_km", "activity.average_speed_kmh"]
        patch = imports_routes.ImportCandidatePatchIn(distance_km=6.0, duration_seconds=2400, average_pace_seconds_per_km=400)

        updated, changed_fields = imports_routes.update_candidate_payload(payload, patch)

        self.assertEqual(changed_fields, ["average_pace_seconds_per_km", "distance_km", "duration_seconds"])
        self.assertEqual(updated["activity"]["distance_km"], 6.0)
        self.assertEqual(updated["activity"]["duration_seconds"], 2400)
        self.assertEqual(updated["activity"]["average_speed_kmh"], 9.0)
        self.assertEqual(updated["estimated_fields"], ["activity.average_speed_kmh"])
        self.assertIn("Manually corrected: average_pace_seconds_per_km, distance_km, duration_seconds", updated["uncertainty_notes"])
        self.assertEqual(payload["activity"]["distance_km"], 5.0)

    def test_candidate_patch_recomputes_stale_pace_when_distance_or_duration_changes(self):
        patch = imports_routes.ImportCandidatePatchIn(distance_km=6.0, average_pace_seconds_per_km=300)

        updated, changed_fields = imports_routes.update_candidate_payload(valid_llm_payload(), patch)

        self.assertEqual(changed_fields, ["distance_km"])
        self.assertEqual(updated["activity"]["average_pace_seconds_per_km"], 250)
        self.assertEqual(updated["activity"]["average_speed_kmh"], 14.4)
        self.assertIn("activity.average_pace_seconds_per_km", updated["estimated_fields"])

    def test_candidate_patch_revalidates_corrected_payload(self):
        patch = imports_routes.ImportCandidatePatchIn(average_pace_seconds_per_km=600)

        with self.assertRaises(RecognitionValidationError):
            imports_routes.update_candidate_payload(valid_llm_payload(), patch)

    def test_candidate_patch_can_clear_nullable_review_fields(self):
        patch = imports_routes.ImportCandidatePatchIn(title=None, started_at=None, average_heart_rate_bpm=None)

        updated, changed_fields = imports_routes.update_candidate_payload(valid_llm_payload(), patch)

        self.assertEqual(changed_fields, ["average_heart_rate_bpm", "started_at", "title"])
        self.assertIsNone(updated["activity"]["title"])
        self.assertIsNone(updated["activity"]["started_at"])
        self.assertIsNone(updated["activity"]["average_heart_rate_bpm"])

    def test_candidate_patch_clears_stale_nested_structure_after_top_level_correction(self):
        payload = valid_llm_payload()
        payload["segments"] = [{"segment_index": 1, "distance_km": 5.0, "duration_seconds": 1500, "pace_seconds_per_km": 300}]
        payload["split_blocks"] = [{"block_index": 1, "start_km": 0, "end_km": 5, "distance_km": 5.0, "duration_seconds": 1500}]
        payload["workout_blocks"] = [{"block_index": 1, "block_type": "easy", "duration_seconds": 1500, "distance_km": 5.0}]
        patch = imports_routes.ImportCandidatePatchIn(distance_km=6.0, duration_seconds=2400, average_pace_seconds_per_km=400)

        updated, _changed_fields = imports_routes.update_candidate_payload(payload, patch)

        self.assertEqual(updated["segments"], [])
        self.assertEqual(updated["split_blocks"], [])
        self.assertEqual(updated["workout_blocks"], [])
        self.assertIn("Cleared stale structured data after correction: segments, split_blocks, workout_blocks", updated["uncertainty_notes"])

    def test_candidate_patch_clears_only_stale_nested_structure(self):
        payload = valid_llm_payload()
        payload["activity"]["distance_km"] = 6.0
        payload["activity"]["duration_seconds"] = 2400
        payload["segments"] = [{"segment_index": 1, "distance_km": 5.0, "duration_seconds": 1500, "pace_seconds_per_km": 300}]
        payload["split_blocks"] = [{"block_index": 1, "start_km": 0, "end_km": 6, "distance_km": 6.0, "duration_seconds": 2400}]
        payload["workout_blocks"] = [{"block_index": 1, "block_type": "easy", "duration_seconds": 2400, "distance_km": 6.0}]

        cleared = imports_routes.clear_stale_candidate_structure(payload, {"distance_km"})

        self.assertEqual(cleared, ["segments"])
        self.assertEqual(payload["segments"], [])
        self.assertEqual(len(payload["split_blocks"]), 1)
        self.assertEqual(len(payload["workout_blocks"]), 1)


if __name__ == "__main__":
    unittest.main()
