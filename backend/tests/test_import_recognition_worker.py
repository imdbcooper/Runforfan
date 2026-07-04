from __future__ import annotations

import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

DEPENDENCY_SKIP_REASON = None

try:
    from sqlalchemy import create_engine, select
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.ext.compiler import compiles
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.db.base import Base
    from app.models import AuditLog, ImportBatch, ImportBatchSource, ImportRecognitionAttempt, ScreenshotSource, User
    from app.services.import_recognition_worker import enqueue_recognition_batch, process_import_batch
    from app.services.recognition import RecognitionValidationError
except ModuleNotFoundError as exc:
    if exc.name in {"fastapi", "httpx", "pydantic", "pydantic_core", "sqlalchemy", "starlette", "multipart"}:
        DEPENDENCY_SKIP_REASON = "Backend dependencies are required for import recognition worker tests"
    else:
        raise


if DEPENDENCY_SKIP_REASON is None:
    @compiles(JSONB, "sqlite")
    def compile_jsonb_sqlite(element, compiler, **kw):
        return "JSON"


def valid_payload() -> dict:
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
        "uncertainty_notes": [],
        "estimated_fields": [],
    }


@unittest.skipIf(DEPENDENCY_SKIP_REASON is not None, DEPENDENCY_SKIP_REASON or "")
class ImportRecognitionWorkerTests(unittest.TestCase):
    def make_session(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine, tables=[
            User.__table__,
            ScreenshotSource.__table__,
            ImportBatch.__table__,
            ImportBatchSource.__table__,
            ImportRecognitionAttempt.__table__,
            AuditLog.__table__,
        ])
        return sessionmaker(bind=engine, expire_on_commit=False)

    def seed_batch(self, db, file_path: str, *, status="recognizing", attempt_count=1, max_attempts=3):
        user = User(id=1, display_name="Runner", is_demo=False)
        source = ScreenshotSource(user_id=1, file_path=file_path, content_hash="hash-a", screen_type="uploaded_screenshot")
        batch = ImportBatch(
            user_id=1,
            status=status,
            recognition_engine="queued",
            recognition_message="queued",
            recognition_attempt_count=attempt_count,
            recognition_max_attempts=max_attempts,
        )
        db.add_all([user, source, batch])
        db.flush()
        db.add(ImportBatchSource(batch_id=batch.id, source_id=source.id))
        db.commit()
        return batch.id

    def test_enqueue_sets_durable_queue_fields(self):
        SessionLocal = self.make_session()
        with SessionLocal() as db:
            batch = ImportBatch(user_id=1, status="uploaded", recognition_engine="pending", recognition_message="uploaded")
            enqueue_recognition_batch(db, batch, SimpleNamespace(import_recognition_max_attempts=4))

            self.assertEqual(batch.status, "queued")
            self.assertEqual(batch.recognition_engine, "queued")
            self.assertEqual(batch.recognition_attempt_count, 0)
            self.assertEqual(batch.recognition_max_attempts, 4)
            self.assertIsNotNone(batch.recognition_retry_at)

    def test_process_batch_stores_pending_confirmation_result(self):
        SessionLocal = self.make_session()
        with tempfile.NamedTemporaryFile(suffix=".jpg") as image:
            image.write(b"fake image")
            image.flush()
            with SessionLocal() as db:
                batch_id = self.seed_batch(db, image.name)

            recognition = {
                "status": "pending_confirmation",
                "engine": "openai:gpt-test",
                "message": "Подтвердите импорт",
                "payload": valid_payload(),
                "requires_confirmation": True,
            }
            with SessionLocal() as db, patch("app.services.import_recognition_worker.llm_or_template_recognize", return_value=recognition):
                processed = process_import_batch(db, batch_id, SimpleNamespace(llm_timeout=10))

                self.assertTrue(processed)
                batch = db.get(ImportBatch, batch_id)
                self.assertEqual(batch.status, "pending_confirmation")
                self.assertEqual(batch.recognition_engine, "openai:gpt-test")
                self.assertIsNone(batch.created_activity_id)
                self.assertIsNone(batch.recognition_retry_at)

    def test_retryable_error_schedules_retry_before_max_attempts(self):
        SessionLocal = self.make_session()
        with tempfile.NamedTemporaryFile(suffix=".jpg") as image:
            image.write(b"fake image")
            image.flush()
            with SessionLocal() as db:
                batch_id = self.seed_batch(db, image.name, attempt_count=1, max_attempts=3)

            error = RecognitionValidationError(["Provider timed out"], retryable=True, failure_class="timeout")
            settings = SimpleNamespace(llm_timeout=10, import_recognition_retry_delay_seconds=1)
            with SessionLocal() as db, patch("app.services.import_recognition_worker.llm_or_template_recognize", side_effect=error):
                processed = process_import_batch(db, batch_id, settings)

                self.assertTrue(processed)
                batch = db.get(ImportBatch, batch_id)
                self.assertEqual(batch.status, "retry_scheduled")
                self.assertIsNotNone(batch.recognition_retry_at)
                self.assertIn("Provider timed out", batch.recognition_last_error)

    def test_retryable_error_fails_after_max_attempts(self):
        SessionLocal = self.make_session()
        with tempfile.NamedTemporaryFile(suffix=".jpg") as image:
            image.write(b"fake image")
            image.flush()
            with SessionLocal() as db:
                batch_id = self.seed_batch(db, image.name, attempt_count=3, max_attempts=3)

            error = RecognitionValidationError(["Provider timed out"], retryable=True, failure_class="timeout")
            with SessionLocal() as db, patch("app.services.import_recognition_worker.llm_or_template_recognize", side_effect=error):
                processed = process_import_batch(db, batch_id, SimpleNamespace(llm_timeout=10))

                self.assertTrue(processed)
                batch = db.get(ImportBatch, batch_id)
                self.assertEqual(batch.status, "validation_failed")
                self.assertIsNone(batch.recognition_retry_at)


if __name__ == "__main__":
    unittest.main()
