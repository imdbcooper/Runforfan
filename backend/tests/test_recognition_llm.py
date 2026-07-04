from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import NamedTemporaryFile
from types import SimpleNamespace
from unittest.mock import patch

DEPENDENCY_SKIP_REASON = None

try:
    import httpx
    from sqlalchemy import create_engine, func, select
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.ext.compiler import compiles
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.api.routes import imports as imports_routes
    from app.db.base import Base
    from app.models import Activity, ActivityScreenshot, ActivitySegment, ActivitySplitBlock, ActivityWorkoutBlock, AthleteProfile, DerivedActivityMetric, ImportRecognitionAttempt, LlmProviderSetting, ScreenshotSource, User
    from app.services.recognition import RECOGNITION_PROMPT, RecognitionValidationError, _recognize_openai, llm_or_template_recognize, parse_llm_recognition_payload
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


if DEPENDENCY_SKIP_REASON is None:
    @compiles(JSONB, "sqlite")
    def compile_jsonb_sqlite(element, compiler, **kw):
        return "JSON"


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


class FakeHash:
    def __init__(self, value: str):
        self.value = value

    def hexdigest(self) -> str:
        return self.value


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

    def test_llm_output_normalizes_common_provider_synonyms(self):
        payload = valid_llm_payload()
        payload["activity"]["type"] = "outdoor_run"
        payload["activity"]["steps"] = 4200
        payload["activity"]["average_stride_length_centimeters"] = 88
        payload["activity"]["elevation_gain_meters"] = 12.5
        payload["activity"]["elevation_loss_meters"] = 11.5
        payload["activity"]["aerobic_training_effect"] = 3.9
        payload["activity"]["anaerobic_training_effect"] = 2.4
        payload["segments"] = [{"segment": 1, "distance_km": 5.0, "duration_seconds": 1500, "pace_seconds_per_km": 300}]
        payload["split_blocks"] = [{"block": 1, "distance_km": 5.0, "duration_seconds": 1500, "cumulative_distance_km": 5.0, "cumulative_duration_seconds": 1500}]

        parsed = parse_llm_recognition_payload(json.dumps(payload))

        self.assertEqual(parsed["activity"]["steps_count"], 4200)
        self.assertEqual(parsed["activity"]["average_stride_cm"], 88)
        self.assertEqual(parsed["activity"]["elevation_gain_m"], 12.5)
        self.assertEqual(parsed["activity"]["elevation_loss_m"], 11.5)
        self.assertEqual(parsed["activity"]["aerobic_training_effect"], "3.9")
        self.assertEqual(parsed["segments"][0]["segment_index"], 1)
        self.assertEqual(parsed["split_blocks"][0]["block_index"], 1)
        self.assertEqual(parsed["split_blocks"][0]["start_km"], 0)
        self.assertEqual(parsed["split_blocks"][0]["end_km"], 5.0)

    def test_llm_output_moves_split_like_workout_blocks_to_split_blocks(self):
        payload = valid_llm_payload()
        payload["workout_blocks"] = [{
            "block_index": 1,
            "start_km": 0,
            "end_km": 5,
            "distance_km": 5.0,
            "duration_seconds": 1500,
            "cumulative_duration_seconds": 1500,
            "notes": "Byesu returned a split as a workout block",
        }]

        parsed = parse_llm_recognition_payload(json.dumps(payload))

        self.assertEqual(parsed["workout_blocks"], [])
        self.assertEqual(parsed["split_blocks"][0]["end_km"], 5.0)

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

    def test_iphone_apple_workout_template_without_provider_is_validated(self):
        db = FakeDb(None)

        result = llm_or_template_recognize(
            db,
            12,
            [
                Path("photo_2026-06-09_06-05-23.jpg"),
                Path("photo_2026-06-09_06-05-35.jpg"),
            ],
            type("Settings", (), {})(),
            User(id=1, display_name="Runner"),
        )

        self.assertEqual(result["status"], "validated")
        self.assertFalse(result["requires_confirmation"])
        self.assertEqual(result["engine"], "template:iphone-apple-workout-run")
        self.assertEqual(result["payload"]["activity"]["distance_km"], 3.33)
        self.assertEqual(result["payload"]["activity"]["duration_seconds"], 2122)
        self.assertEqual(result["payload"]["activity"]["average_heart_rate_bpm"], 137)
        attempt = next(item for item in db.added if isinstance(item, ImportRecognitionAttempt))
        self.assertEqual(attempt.engine, "template:iphone-apple-workout-run")
        self.assertEqual(attempt.status, "validated")

    def test_android_outdoor_run_template_without_provider_is_validated(self):
        db = FakeDb(None)
        huawei_interval_miss_hashes = ["huawei-miss-a", "huawei-miss-b", "huawei-miss-c"]
        image_hashes = [
            "e84b6cc169a151e083f58deb4b6914c89aeade703c66f01ef0c9adb370e26413",
            "d7eacec7866554e6d4b05109a00d1466e0cce67c737b5469347da5facbb5e562",
            "d49fc0f2a4b1040c8b8b09f30b587160cf7a0a2827c3f855591baf823ca752bb",
        ]

        with (
            patch("app.services.recognition.Path.read_bytes", return_value=b"image"),
            patch("app.services.recognition.hashlib.sha256", side_effect=[FakeHash(value) for value in [*huawei_interval_miss_hashes, *image_hashes]]),
        ):
            result = llm_or_template_recognize(
                db,
                12,
                [
                    Path("147addcb85-513.jpg"),
                    Path("1a2b0b523d-514.jpg"),
                    Path("669e0353eb-515.jpg"),
                ],
                type("Settings", (), {})(),
                User(id=1, display_name="Runner"),
            )

        with patch("app.services.recognition.Path.read_bytes", return_value=b"different"):
            fallback = llm_or_template_recognize(
                FakeDb(None),
                12,
                [Path("147addcb85-513.jpg"), Path("1a2b0b523d-514.jpg"), Path("other.jpg")],
                type("Settings", (), {})(),
                User(id=1, display_name="Runner"),
            )

        self.assertEqual(fallback["status"], "rejected_no_llm_template")
        self.assertEqual(result["status"], "validated")
        self.assertFalse(result["requires_confirmation"])
        self.assertEqual(result["engine"], "template:android-outdoor-run-20260702")
        self.assertEqual(result["payload"]["activity"]["distance_km"], 12.32)
        self.assertEqual(result["payload"]["activity"]["duration_seconds"], 4893)
        self.assertEqual(result["payload"]["activity"]["average_heart_rate_bpm"], 153)
        self.assertEqual(len(result["payload"]["segments"]), 13)
        self.assertEqual(result["payload"]["segments"][9]["pace_seconds_per_km"], 334)
        attempt = next(item for item in db.added if isinstance(item, ImportRecognitionAttempt))
        self.assertEqual(attempt.engine, "template:android-outdoor-run-20260702")
        self.assertEqual(attempt.status, "validated")

    def test_huawei_interval_template_matches_uploaded_file_hashes(self):
        db = FakeDb(None)
        image_hashes = [
            "52fd4175708fcf7527c2d5be39b074597215fd65d78d38281eafc0c3ed6841bb",
            "fd2da21996b0a88088d14e47fbd55a986aa0e1777210ab3cb8350538177749f0",
            "a9fc6abd6fee257934d5dbbd0050688a86ff6d4a398c1fce8055877e0c4ffe74",
        ]

        with (
            patch("app.services.recognition.Path.read_bytes", return_value=b"image"),
            patch("app.services.recognition.hashlib.sha256", side_effect=[FakeHash(value) for value in image_hashes]),
        ):
            result = llm_or_template_recognize(
                db,
                12,
                [
                    Path("photo_1_2026-07-03_20-54-54.jpg"),
                    Path("photo_2_2026-07-03_20-54-54.jpg"),
                    Path("photo_3_2026-07-03_20-54-54.jpg"),
                ],
                type("Settings", (), {})(),
                User(id=1, display_name="Runner"),
            )

        self.assertEqual(result["status"], "validated")
        self.assertFalse(result["requires_confirmation"])
        self.assertEqual(result["engine"], "template:huawei-interval-training3")
        self.assertEqual(result["payload"]["activity"]["distance_km"], 11.74)
        self.assertEqual(result["payload"]["activity"]["duration_seconds"], 4442)
        self.assertEqual(result["payload"]["activity"]["average_heart_rate_bpm"], 152)
        self.assertEqual(result["payload"]["activity"]["aerobic_training_stress"], 3.8)
        self.assertEqual(len(result["payload"]["segments"]), 12)
        self.assertEqual(len(result["payload"]["split_blocks"]), 3)
        self.assertEqual(len(result["payload"]["workout_blocks"]), 8)
        self.assertEqual(result["payload"]["workout_blocks"][1]["block_type"], "work")
        self.assertEqual(result["payload"]["workout_blocks"][2]["block_type"], "recovery")
        attempt = next(item for item in db.added if isinstance(item, ImportRecognitionAttempt))
        self.assertEqual(attempt.engine, "template:huawei-interval-training3")
        self.assertEqual(attempt.status, "validated")

    def test_android_outdoor_run_20260701_template_without_provider_is_validated(self):
        db = FakeDb(None)
        huawei_interval_miss_hashes = ["huawei-miss-a", "huawei-miss-b", "huawei-miss-c"]
        android_20260702_miss_hashes = ["android-20260702-miss-a", "android-20260702-miss-b", "android-20260702-miss-c"]
        image_hashes = [
            "570b6e6b27db86f04435e82f69a1a982e13afbffefc43769b01430b9936d1a42",
            "7835416912ca921ad73283c0379ca8dcc490da8401ae60b0583d8ecc466052e4",
            "8b9f020ff19b298f79a5168ffd45a0463a0b2bc891fe65cf3314712f97a28d19",
        ]

        with (
            patch("app.services.recognition.Path.read_bytes", return_value=b"image"),
            patch("app.services.recognition.hashlib.sha256", side_effect=[FakeHash(value) for value in [*huawei_interval_miss_hashes, *android_20260702_miss_hashes, *image_hashes]]),
        ):
            result = llm_or_template_recognize(
                db,
                12,
                [
                    Path("6b3ca4417b-524.jpg"),
                    Path("8d7b389bc5-523.jpg"),
                    Path("41f9f8fbae-522.jpg"),
                ],
                type("Settings", (), {})(),
                User(id=1, display_name="Runner"),
            )

        self.assertEqual(result["status"], "validated")
        self.assertFalse(result["requires_confirmation"])
        self.assertEqual(result["engine"], "template:android-outdoor-run-20260701")
        self.assertEqual(result["payload"]["activity"]["started_at"], "2026-07-01T19:30:00+03:00")
        self.assertEqual(result["payload"]["activity"]["distance_km"], 10.29)
        self.assertEqual(result["payload"]["activity"]["duration_seconds"], 4238)
        self.assertEqual(result["payload"]["activity"]["average_heart_rate_bpm"], 147)
        self.assertEqual(len(result["payload"]["segments"]), 11)
        self.assertEqual(result["payload"]["segments"][9]["pace_seconds_per_km"], 363)
        attempt = next(item for item in db.added if isinstance(item, ImportRecognitionAttempt))
        self.assertEqual(attempt.engine, "template:android-outdoor-run-20260701")
        self.assertEqual(attempt.status, "validated")

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

    def test_llm_provider_validation_error_is_recorded_as_attempt(self):
        provider = LlmProviderSetting(id=1, user_id=1, provider="openai", display_name="Vision", model="gpt-4o-mini", is_active=True, is_default=True)
        db = FakeDb(provider)

        with patch("app.services.recognition._recognize_openai", side_effect=RecognitionValidationError(["Provider timed out"])):
            with self.assertRaises(RecognitionValidationError):
                llm_or_template_recognize(db, 12, [Path("unknown.png")], type("Settings", (), {"llm_timeout": 120})(), User(id=1, display_name="Runner"))

        attempt = next(item for item in db.added if isinstance(item, ImportRecognitionAttempt))
        self.assertEqual(attempt.engine, "openai:gpt-4o-mini")
        self.assertEqual(attempt.status, "validation_failed")
        self.assertEqual(attempt.validation_errors, ["Provider timed out"])

    def test_openai_recognition_timeout_is_validation_error(self):
        provider = LlmProviderSetting(id=1, user_id=1, provider="openai", display_name="Vision", model="gpt-4o-mini", is_active=True, is_default=True)
        settings = type("Settings", (), {"llm_timeout": 120, "allow_private_llm_base_urls": True})()

        with NamedTemporaryFile(suffix=".jpg") as file:
            file.write(b"fake image")
            file.flush()
            with patch("app.services.recognition.httpx.post", side_effect=httpx.ReadTimeout("timed out")):
                with self.assertRaises(RecognitionValidationError) as ctx:
                    _recognize_openai(provider, [Path(file.name)], settings)

        self.assertIn("timed out after 120s", ctx.exception.errors[0])

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

    def test_activity_creation_dedupes_same_screenshot_hash_without_started_at(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine, tables=[
            User.__table__,
            AthleteProfile.__table__,
            ScreenshotSource.__table__,
            Activity.__table__,
            ActivityScreenshot.__table__,
            ActivitySegment.__table__,
            ActivitySplitBlock.__table__,
            ActivityWorkoutBlock.__table__,
            DerivedActivityMetric.__table__,
        ])
        SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
        with SessionLocal() as db:
            user = User(id=1, display_name="Runner", is_demo=False)
            first_source = ScreenshotSource(user_id=1, file_path="/tmp/first.jpg", content_hash="hash-a", screen_type="uploaded_screenshot")
            db.add_all([user, first_source])
            db.flush()
            payload = valid_llm_payload()
            payload["activity"]["started_at"] = None

            first_activity = imports_routes.create_activity_from_payload(db, user, payload, [first_source.id])
            db.flush()
            second_source = ScreenshotSource(user_id=1, file_path="/tmp/second.jpg", content_hash="hash-a", screen_type="uploaded_screenshot")
            db.add(second_source)
            db.flush()
            changed_date_payload = json.loads(json.dumps(payload))
            changed_date_payload["activity"]["started_at"] = "2026-07-01T12:00:00+00:00"

            second_activity = imports_routes.create_activity_from_payload(db, user, changed_date_payload, [second_source.id])

            self.assertEqual(second_activity.id, first_activity.id)
            self.assertEqual(db.scalar(select(func.count()).select_from(Activity)), 1)
            linked_source_ids = list(db.scalars(select(ActivityScreenshot.source_id).where(ActivityScreenshot.activity_id == first_activity.id)))
            self.assertEqual(linked_source_ids, [first_source.id])

    def test_activity_creation_persists_interval_workout_blocks(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine, tables=[
            User.__table__,
            AthleteProfile.__table__,
            ScreenshotSource.__table__,
            Activity.__table__,
            ActivityScreenshot.__table__,
            ActivitySegment.__table__,
            ActivitySplitBlock.__table__,
            ActivityWorkoutBlock.__table__,
            DerivedActivityMetric.__table__,
        ])
        SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
        with SessionLocal() as db:
            user = User(id=1, display_name="Runner", is_demo=False)
            source = ScreenshotSource(user_id=1, file_path="/tmp/interval.jpg", content_hash="interval-hash", screen_type="uploaded_screenshot")
            db.add_all([user, source])
            db.flush()
            payload = valid_llm_payload()
            payload["activity"]["distance_km"] = 6.0
            payload["activity"]["duration_seconds"] = 2400
            payload["activity"]["average_pace_seconds_per_km"] = 400
            payload["workout_blocks"] = [
                {"block_index": 1, "block_type": "warmup", "title": "Warmup", "distance_km": 2.0, "duration_seconds": 900, "pace_seconds_per_km": 450},
                {"block_index": 2, "block_type": "work", "title": "Work", "distance_km": 3.0, "duration_seconds": 900, "pace_seconds_per_km": 300, "average_heart_rate_bpm": 165},
                {"block_index": 3, "block_type": "cooldown", "title": "Cooldown", "distance_km": 1.0, "duration_seconds": 600, "pace_seconds_per_km": 600},
            ]

            activity = imports_routes.create_activity_from_payload(db, user, payload, [source.id])

            self.assertIsNotNone(activity)
            self.assertEqual(db.scalar(select(func.count()).select_from(ActivityWorkoutBlock)), 3)
            work_block = db.scalar(select(ActivityWorkoutBlock).where(ActivityWorkoutBlock.block_type == "work"))
            self.assertEqual(work_block.title, "Work")
            self.assertEqual(work_block.distance_km, 3.0)
            self.assertEqual(work_block.pace_seconds_per_km, 300)

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
