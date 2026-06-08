from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

DEPENDENCY_SKIP_REASON = None

try:
    from app.models import ImportRecognitionAttempt, LlmProviderSetting, User
    from app.services.recognition import RECOGNITION_PROMPT, RecognitionValidationError, llm_or_template_recognize, parse_llm_recognition_payload
except ModuleNotFoundError as exc:
    if exc.name in {"httpx", "pydantic", "sqlalchemy"}:
        DEPENDENCY_SKIP_REASON = "Backend dependencies are required for recognition LLM tests"
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


if __name__ == "__main__":
    unittest.main()
