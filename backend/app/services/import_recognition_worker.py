from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.settings import Settings, get_settings
from app.db.session import SessionLocal
from app.models import AthleteProfile, ImportBatch, User
from app.services.activity_metrics import sync_derived_activity_metrics
from app.services.audit import log_audit_event
from app.services.planning import auto_match_activity_to_plan
from app.services.recognition import RecognitionValidationError, llm_or_template_recognize
from app.services.training_load import sync_daily_training_loads_for_activity


logger = logging.getLogger(__name__)
PROVIDER_FAILURE_CLASSES = {"timeout", "request", "http_status", "provider_response", "unsupported_provider"}

ACTIVE_RECOGNITION_STATUSES = {"queued", "retry_scheduled", "recognizing"}
TERMINAL_RECOGNITION_STATUSES = {
    "recognized",
    "duplicate",
    "pending_confirmation",
    "validation_failed",
    "recognition_failed",
    "rejected_no_llm_template",
    "rejected_by_user",
}

_worker_thread: threading.Thread | None = None
_stop_event = threading.Event()
_worker_id = f"import-recognition-{uuid.uuid4().hex[:8]}"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def enqueue_recognition_batch(db: Session, batch: ImportBatch, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    now = utcnow()
    batch.status = "queued"
    batch.recognition_engine = "queued"
    batch.recognition_message = "Скриншоты загружены и поставлены в очередь распознавания."
    batch.queued_at = now
    batch.recognition_retry_at = now
    batch.recognition_started_at = None
    batch.recognition_finished_at = None
    batch.recognition_attempt_count = 0
    batch.recognition_max_attempts = max(1, int(getattr(settings, "import_recognition_max_attempts", 3)))
    batch.recognition_locked_at = None
    batch.recognition_locked_by = None
    batch.recognition_last_error = None


def recognition_is_active(status: str | None) -> bool:
    return status in ACTIVE_RECOGNITION_STATUSES


def _retry_delay(settings: Settings, attempt_count: int) -> timedelta:
    base_seconds = max(1, int(getattr(settings, "import_recognition_retry_delay_seconds", 45)))
    seconds = min(base_seconds * (2 ** max(0, attempt_count - 1)), 15 * 60)
    return timedelta(seconds=seconds)


def _unlock(batch: ImportBatch) -> None:
    batch.recognition_locked_at = None
    batch.recognition_locked_by = None


def _schedule_retry(batch: ImportBatch, settings: Settings, message: str) -> None:
    now = utcnow()
    batch.status = "retry_scheduled"
    batch.recognition_engine = batch.recognition_engine or "llm"
    batch.recognition_message = message
    batch.recognition_retry_at = now + _retry_delay(settings, batch.recognition_attempt_count or 1)
    batch.recognition_last_error = message
    batch.recognition_finished_at = now
    _unlock(batch)


def _finish_failure(batch: ImportBatch, status: str, engine: str, message: str) -> None:
    batch.status = status
    batch.recognition_engine = engine
    batch.recognition_message = message
    batch.recognition_last_error = message
    batch.recognition_finished_at = utcnow()
    batch.recognition_retry_at = None
    _unlock(batch)


def _finish_success(batch: ImportBatch, status: str, engine: str, message: str, created_activity_id: int | None) -> None:
    batch.status = status
    batch.recognition_engine = engine
    batch.recognition_message = message
    batch.created_activity_id = created_activity_id
    batch.recognition_last_error = None
    batch.recognition_finished_at = utcnow()
    batch.recognition_retry_at = None
    _unlock(batch)


def _batch_files(batch: ImportBatch) -> list[Path]:
    return [Path(link.source.file_path) for link in batch.sources if link.source and link.source.file_path]


def _claim_next_batch(db: Session, settings: Settings, worker_id: str) -> int | None:
    now = utcnow()
    stale_after = now - timedelta(seconds=max(int(getattr(settings, "llm_timeout", 120)) * 2, 10 * 60))
    query = (
        select(ImportBatch)
        .where(
            or_(
                and_(
                    ImportBatch.status.in_(["queued", "retry_scheduled"]),
                    or_(ImportBatch.recognition_retry_at.is_(None), ImportBatch.recognition_retry_at <= now),
                ),
                and_(
                    ImportBatch.status == "recognizing",
                    ImportBatch.recognition_locked_at.is_not(None),
                    ImportBatch.recognition_locked_at < stale_after,
                ),
            )
        )
        .order_by(ImportBatch.queued_at.asc(), ImportBatch.id.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    batch = db.scalar(query)
    if not batch:
        return None
    batch.status = "recognizing"
    batch.recognition_engine = "llm/template"
    batch.recognition_message = "Распознавание скриншотов выполняется."
    batch.recognition_started_at = now
    batch.recognition_finished_at = None
    batch.recognition_locked_at = now
    batch.recognition_locked_by = worker_id
    batch.recognition_attempt_count = int(batch.recognition_attempt_count or 0) + 1
    db.commit()
    return batch.id


def process_import_batch(db: Session, batch_id: int, settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    batch = db.get(ImportBatch, batch_id)
    if not batch or batch.status not in ACTIVE_RECOGNITION_STATUSES:
        return False
    user = db.get(User, batch.user_id)
    if not user:
        _finish_failure(batch, "recognition_failed", "unknown", "Import batch user is missing.")
        db.commit()
        return True
    files = _batch_files(batch)
    if not files:
        _finish_failure(batch, "recognition_failed", "unknown", "Import batch has no screenshot files.")
        db.commit()
        return True
    missing_files = [str(file) for file in files if not file.exists()]
    if missing_files:
        _finish_failure(batch, "recognition_failed", "unknown", f"Screenshot files are missing: {', '.join(missing_files[:3])}")
        db.commit()
        return True
    source_ids = [link.source_id for link in batch.sources]
    matched_workout = None
    try:
        recognition = llm_or_template_recognize(db, batch.id, files, settings, user)
        activity = None
        if recognition.get("payload") and not recognition.get("requires_confirmation"):
            from app.api.routes.imports import create_activity_from_payload

            activity = create_activity_from_payload(db, user, recognition["payload"], source_ids)
        if activity:
            matched_workout = auto_match_activity_to_plan(db, user, activity)
            sync_daily_training_loads_for_activity(db, user, activity)
            profile = db.scalar(select(AthleteProfile).where(AthleteProfile.user_id == user.id))
            sync_derived_activity_metrics(db, activity, profile)
        final_status = "recognized" if activity else recognition["status"]
        _finish_success(batch, final_status, recognition["engine"], recognition["message"], activity.id if activity else None)
        log_audit_event(db, user.id, "import.recognition.completed", "import_batch", batch.id, {
            "status": batch.status,
            "created_activity_id": batch.created_activity_id,
            "recognition_engine": batch.recognition_engine,
            "matched_workout_id": matched_workout.id if matched_workout else None,
        })
        db.commit()
        return True
    except RecognitionValidationError as exc:
        message = "; ".join(exc.errors)
        can_retry = exc.retryable and int(batch.recognition_attempt_count or 0) < int(batch.recognition_max_attempts or 1)
        if can_retry:
            _schedule_retry(batch, settings, f"{message} Повтор будет выполнен автоматически.")
        else:
            if exc.failure_class == "no_provider":
                status = "rejected_no_llm_template"
            elif exc.failure_class in PROVIDER_FAILURE_CLASSES:
                status = "recognition_failed"
            else:
                status = "validation_failed"
            _finish_failure(batch, status, "llm", message)
        log_audit_event(db, user.id, "import.recognition.failed", "import_batch", batch.id, {
            "status": batch.status,
            "attempt_count": batch.recognition_attempt_count,
            "failure_class": exc.failure_class,
            "retryable": exc.retryable,
        })
        db.commit()
        return True
    except Exception as exc:
        logger.exception("Unexpected import recognition failure for batch %s", batch_id)
        db.rollback()
        batch = db.get(ImportBatch, batch_id)
        user = db.get(User, batch.user_id) if batch else None
        if not batch or not user:
            return False
        message = "Recognition failed unexpectedly. Check provider settings or uploaded screenshots."
        _finish_failure(batch, "recognition_failed", "unknown", message)
        log_audit_event(db, user.id, "import.recognition.error", "import_batch", batch.id, {
            "status": batch.status,
            "attempt_count": batch.recognition_attempt_count,
            "error": str(exc)[:250],
        })
        db.commit()
        return True


def run_import_recognition_once(settings: Settings | None = None, worker_id: str | None = None) -> bool:
    settings = settings or get_settings()
    worker_id = worker_id or _worker_id
    with SessionLocal() as db:
        batch_id = _claim_next_batch(db, settings, worker_id)
    if batch_id is None:
        return False
    with SessionLocal() as db:
        return process_import_batch(db, batch_id, settings=settings)


def _run_loop(settings: Settings) -> None:
    poll_seconds = max(1.0, float(getattr(settings, "import_recognition_worker_poll_seconds", 5.0)))
    while not _stop_event.is_set():
        try:
            processed = run_import_recognition_once(settings=settings, worker_id=_worker_id)
        except Exception:
            logger.exception("Import recognition worker iteration failed")
            processed = False
        if not processed:
            _stop_event.wait(poll_seconds)


def start_import_recognition_worker() -> None:
    global _worker_thread
    settings = get_settings()
    if not getattr(settings, "import_recognition_worker_enabled", True):
        return
    if _worker_thread and _worker_thread.is_alive():
        return
    _stop_event.clear()
    _worker_thread = threading.Thread(target=_run_loop, args=(settings,), name="import-recognition-worker", daemon=True)
    _worker_thread.start()


def stop_import_recognition_worker() -> None:
    _stop_event.set()
    if _worker_thread and _worker_thread.is_alive():
        _worker_thread.join(timeout=5)
