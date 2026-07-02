from copy import deepcopy
import hashlib
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.db.session import get_db
from app.models import Activity, ActivityScreenshot, ActivitySegment, ActivitySplitBlock, ActivityWorkoutBlock, AthleteProfile, ImportBatch, ImportBatchSource, ImportRecognitionAttempt, ScreenshotSource, TrainingPlan, TrainingPlanWorkout, User
from app.schemas.common import CsvImportOut, ImportCandidatePatchIn
from app.services.audit import log_audit_event
from app.services.activity_metrics import sync_derived_activity_metrics
from app.services.auth import get_current_user
from app.services.csv_imports import activity_payload_from_csv_row, create_activity_from_csv_payload, iter_csv_rows
from app.services.planning import auto_match_activity_to_plan
from app.services.recognition import RecognitionValidationError, llm_or_template_recognize, validate_activity_payload
from app.services.training_load import sync_daily_training_loads_for_activities, sync_daily_training_loads_for_activity


router = APIRouter(prefix="/imports", tags=["imports"])
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_CSV_EXTENSIONS = {".csv", ".txt"}


def safe_filename(filename: str) -> str:
    return Path(filename or "screenshot.jpg").name.replace("/", "_").replace("\\", "_")[:120]


def save_upload_with_hash(upload: UploadFile, target: Path) -> str:
    digest = hashlib.sha256()
    with target.open("wb") as output:
        while chunk := upload.file.read(1024 * 1024):
            digest.update(chunk)
            output.write(chunk)
    return digest.hexdigest()


def file_content_hash(path: str | Path) -> str | None:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def backfill_user_screenshot_hashes(db: Session, user_id: int, limit: int = 500) -> int:
    sources = list(db.scalars(
        select(ScreenshotSource)
        .where(ScreenshotSource.user_id == user_id, ScreenshotSource.content_hash.is_(None))
        .order_by(ScreenshotSource.id.desc())
        .limit(limit)
    ))
    updated = 0
    for source in sources:
        content_hash = file_content_hash(source.file_path)
        if not content_hash:
            continue
        source.content_hash = content_hash
        updated += 1
    if updated:
        db.flush()
    return updated


def existing_activity_for_source_hashes(db: Session, user: User, content_hashes: list[str]) -> Activity | None:
    unique_hashes = {content_hash for content_hash in content_hashes if content_hash}
    if not unique_hashes:
        return None
    ordered_hashes = sorted(unique_hashes)
    candidate_ids = list(db.scalars(
        select(Activity.id)
        .join(ActivityScreenshot, ActivityScreenshot.activity_id == Activity.id)
        .join(ScreenshotSource, ScreenshotSource.id == ActivityScreenshot.source_id)
        .where(
            Activity.user_id == user.id,
            ScreenshotSource.content_hash.in_(ordered_hashes),
        )
        .group_by(Activity.id)
        .having(func.count(func.distinct(ScreenshotSource.content_hash)) == len(unique_hashes))
        .order_by(Activity.id.asc())
    ))
    for activity_id in candidate_ids:
        existing_hashes = set(db.scalars(
            select(ScreenshotSource.content_hash)
            .join(ActivityScreenshot, ActivityScreenshot.source_id == ScreenshotSource.id)
            .where(
                ActivityScreenshot.activity_id == activity_id,
                ScreenshotSource.content_hash.is_not(None),
            )
        ))
        if unique_hashes.issubset(existing_hashes):
            return db.get(Activity, activity_id)
    return None


def link_sources_to_activity(db: Session, activity: Activity, source_ids: list[int]) -> None:
    if not source_ids:
        return
    source_hashes = dict(db.execute(
        select(ScreenshotSource.id, ScreenshotSource.content_hash).where(ScreenshotSource.id.in_(source_ids))
    ).all())
    linked_hashes = set(db.scalars(
        select(ScreenshotSource.content_hash)
        .join(ActivityScreenshot, ActivityScreenshot.source_id == ScreenshotSource.id)
        .where(
            ActivityScreenshot.activity_id == activity.id,
            ScreenshotSource.content_hash.is_not(None),
        )
    ))
    linked_source_ids = set(db.scalars(
        select(ActivityScreenshot.source_id).where(
            ActivityScreenshot.activity_id == activity.id,
            ActivityScreenshot.source_id.in_(source_ids),
        )
    ))
    for source_id in source_ids:
        content_hash = source_hashes.get(source_id)
        if content_hash and content_hash in linked_hashes:
            continue
        if source_id not in linked_source_ids:
            db.add(ActivityScreenshot(activity_id=activity.id, source_id=source_id))
            if content_hash:
                linked_hashes.add(content_hash)


def create_activity_from_payload(db: Session, user: User, payload: dict, source_ids: list[int]) -> Activity | None:
    activity_payload = payload.get("activity") or {}
    if not activity_payload:
        return None
    profile = db.scalar(select(AthleteProfile).where(AthleteProfile.user_id == user.id))
    started_at = datetime.fromisoformat(activity_payload["started_at"]) if activity_payload.get("started_at") else None
    source_hashes = [content_hash for content_hash in db.scalars(select(ScreenshotSource.content_hash).where(ScreenshotSource.id.in_(source_ids))) if content_hash]
    existing = existing_activity_for_source_hashes(db, user, source_hashes)
    if existing:
        link_sources_to_activity(db, existing, source_ids)
        sync_derived_activity_metrics(db, existing, profile)
        db.flush()
        return existing
    existing = None
    if started_at and activity_payload.get("distance_km") and activity_payload.get("duration_seconds"):
        existing = db.scalar(select(Activity).where(
            Activity.user_id == user.id,
            Activity.started_at == started_at,
            Activity.distance_km == activity_payload.get("distance_km"),
            Activity.duration_seconds == activity_payload.get("duration_seconds"),
        ))
    if existing:
        link_sources_to_activity(db, existing, source_ids)
        sync_derived_activity_metrics(db, existing, profile)
        db.flush()
        return existing
    activity = Activity(
        user_id=user.id,
        activity_type="outdoor_run",
        title=activity_payload.get("title") or "Бег на улице",
        started_at=started_at,
        distance_km=activity_payload.get("distance_km"),
        duration_seconds=activity_payload.get("duration_seconds"),
        calories_kcal=activity_payload.get("calories_kcal"),
        average_pace_seconds_per_km=activity_payload.get("average_pace_seconds_per_km"),
        fastest_pace_seconds_per_km=activity_payload.get("fastest_pace_seconds_per_km"),
        average_speed_kmh=activity_payload.get("average_speed_kmh"),
        average_cadence_spm=activity_payload.get("average_cadence_spm"),
        average_stride_cm=activity_payload.get("average_stride_cm"),
        steps_count=activity_payload.get("steps_count"),
        average_heart_rate_bpm=activity_payload.get("average_heart_rate_bpm"),
        elevation_gain_m=activity_payload.get("elevation_gain_m"),
        elevation_loss_m=activity_payload.get("elevation_loss_m"),
        aerobic_training_stress=activity_payload.get("aerobic_training_stress"),
        aerobic_training_effect=activity_payload.get("aerobic_training_effect"),
        source_note="Created from uploaded screenshots by recognition pipeline.",
    )
    db.add(activity)
    db.flush()
    for source_id in source_ids:
        db.add(ActivityScreenshot(activity_id=activity.id, source_id=source_id))
    for segment in payload.get("segments") or []:
        activity.segments.append(ActivitySegment(**segment))
    for block in payload.get("split_blocks") or []:
        activity.split_blocks.append(ActivitySplitBlock(**block))
    for block in payload.get("workout_blocks") or []:
        activity.workout_blocks.append(ActivityWorkoutBlock(
            block_index=block.get("block_index"),
            block_type=block.get("block_type") or "unknown",
            title=block.get("title") or block.get("block_type") or "Блок",
            distance_km=block.get("distance_km"),
            duration_seconds=block.get("duration_seconds"),
            pace_seconds_per_km=block.get("pace_seconds_per_km"),
            average_heart_rate_bpm=block.get("average_heart_rate_bpm"),
            average_cadence_spm=block.get("average_cadence_spm"),
            notes=block.get("notes"),
        ))
    db.flush()
    sync_derived_activity_metrics(db, activity, profile)
    return activity


def matched_workout_ids_for_activities(db: Session, user: User, activity_ids: list[int]) -> dict[int, int]:
    if not activity_ids:
        return {}
    rows = db.execute(
        select(TrainingPlanWorkout.completed_activity_id, TrainingPlanWorkout.id)
        .join(TrainingPlan)
        .where(TrainingPlan.user_id == user.id, TrainingPlanWorkout.completed_activity_id.in_(activity_ids))
        .order_by(TrainingPlanWorkout.id.asc())
    ).all()
    matched: dict[int, int] = {}
    for activity_id, workout_id in rows:
        if activity_id is not None and activity_id not in matched:
            matched[int(activity_id)] = int(workout_id)
    return matched


def matched_workout_id_for_activity(db: Session, user: User, activity_id: int | None) -> int | None:
    if activity_id is None:
        return None
    return matched_workout_ids_for_activities(db, user, [activity_id]).get(activity_id)


def latest_recognition_attempt(db: Session, batch_id: int) -> ImportRecognitionAttempt | None:
    return db.scalar(
        select(ImportRecognitionAttempt)
        .where(ImportRecognitionAttempt.batch_id == batch_id)
        .order_by(ImportRecognitionAttempt.created_at.desc(), ImportRecognitionAttempt.id.desc())
        .limit(1)
    )


def candidate_from_payload(payload: dict | None) -> dict[str, object] | None:
    if not payload:
        return None
    activity = payload.get("activity") or {}
    return {
        "activity": {
            "title": activity.get("title"),
            "started_at": activity.get("started_at"),
            "distance_km": activity.get("distance_km"),
            "duration_seconds": activity.get("duration_seconds"),
            "average_pace_seconds_per_km": activity.get("average_pace_seconds_per_km"),
            "average_heart_rate_bpm": activity.get("average_heart_rate_bpm"),
        },
        "confidence": payload.get("confidence"),
        "uncertainty_notes": payload.get("uncertainty_notes") or [],
        "estimated_fields": payload.get("estimated_fields") or [],
        "segments_count": len(payload.get("segments") or []),
        "workout_blocks_count": len(payload.get("workout_blocks") or []),
    }


def import_result(db: Session, user: User, batch: ImportBatch, matched_workout=None, include_candidate: bool = False) -> dict[str, object]:
    matched_workout_id = matched_workout.id if matched_workout else matched_workout_id_for_activity(db, user, batch.created_activity_id)
    match_status = "auto_matched" if matched_workout else "already_matched" if matched_workout_id else "unmatched"
    attempt = latest_recognition_attempt(db, batch.id) if include_candidate or batch.status == "pending_confirmation" else None
    candidate = candidate_from_payload(attempt.parsed_payload if attempt else None)
    return {
        "id": batch.id,
        "status": batch.status,
        "source_app": batch.source_app,
        "recognition_engine": batch.recognition_engine,
        "recognition_message": batch.recognition_message,
        "created_activity_id": batch.created_activity_id,
        "matched_workout_id": matched_workout_id,
        "match_status": match_status,
        "auto_matched": bool(matched_workout),
        "requires_confirmation": batch.status == "pending_confirmation",
        "candidate": candidate,
        "created_at": batch.created_at,
    }


def import_batch_for_user(db: Session, user: User, batch_id: int, for_update: bool = False) -> ImportBatch:
    query = select(ImportBatch).where(ImportBatch.id == batch_id, ImportBatch.user_id == user.id)
    if for_update:
        query = query.with_for_update()
    batch = db.scalar(query)
    if not batch:
        raise HTTPException(status_code=404, detail="Import batch not found")
    return batch


def candidate_field_changed(current: object, value: object, field: str) -> bool:
    if field == "started_at" and current and value:
        try:
            current_dt = datetime.fromisoformat(str(current).replace("Z", "+00:00"))
            value_dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return current_dt != value_dt
        except ValueError:
            return current != value
    return current != value


def sync_candidate_dependent_fields(payload: dict, changed_fields: set[str]) -> None:
    if not ({"distance_km", "duration_seconds"} & changed_fields):
        return
    activity = payload.get("activity") or {}
    distance = activity.get("distance_km")
    duration = activity.get("duration_seconds")
    if distance and duration:
        activity["average_speed_kmh"] = round(float(distance) * 3600 / int(duration), 2)
        if "average_pace_seconds_per_km" not in changed_fields:
            activity["average_pace_seconds_per_km"] = round(int(duration) / float(distance))
        estimated_fields = set(payload.get("estimated_fields") or [])
        estimated_fields.add("activity.average_speed_kmh")
        if "average_pace_seconds_per_km" not in changed_fields:
            estimated_fields.add("activity.average_pace_seconds_per_km")
        payload["estimated_fields"] = sorted(estimated_fields)


def stale_candidate_structure_keys(payload: dict) -> list[str]:
    activity = payload.get("activity") or {}
    distance = activity.get("distance_km")
    duration = activity.get("duration_seconds")

    def distance_mismatch(rows: list[dict], tolerance_km: float, tolerance_fraction: float) -> bool:
        if not rows or not distance:
            return False
        total = sum(float(row.get("distance_km") or 0) for row in rows)
        return abs(total - float(distance)) > max(tolerance_km, float(distance) * tolerance_fraction)

    def duration_mismatch(rows: list[dict], tolerance_seconds: int, tolerance_fraction: float) -> bool:
        if not rows or not duration:
            return False
        total = sum(int(row.get("duration_seconds") or 0) for row in rows)
        return abs(total - int(duration)) > max(tolerance_seconds, int(duration) * tolerance_fraction)

    stale = []
    checks = [
        ("segments", 0.5, 0.12, 10, 0.01),
        ("split_blocks", 0.05, 0.01, 10, 0.01),
        ("workout_blocks", 0.08, 0.02, 15, 0.02),
    ]
    for key, distance_tolerance, distance_fraction, duration_tolerance, duration_fraction in checks:
        rows = payload.get(key) or []
        if distance_mismatch(rows, distance_tolerance, distance_fraction) or duration_mismatch(rows, duration_tolerance, duration_fraction):
            stale.append(key)
    return stale


def clear_stale_candidate_structure(payload: dict, changed_fields: set[str]) -> list[str]:
    if not ({"distance_km", "duration_seconds"} & changed_fields):
        return []
    stale_keys = set(stale_candidate_structure_keys(payload))
    cleared = []
    for key in ("segments", "split_blocks", "workout_blocks"):
        if key in stale_keys and payload.get(key):
            payload[key] = []
            cleared.append(key)
    return cleared


def update_candidate_payload(payload: dict, patch: ImportCandidatePatchIn) -> tuple[dict, list[str]]:
    updated = deepcopy(payload)
    activity = updated.setdefault("activity", {})
    patch_values = patch.model_dump(exclude_unset=True, mode="json")
    changed = {}
    for key, value in patch_values.items():
        if candidate_field_changed(activity.get(key), value, key):
            changed[key] = value
            activity[key] = value
    if changed:
        sync_candidate_dependent_fields(updated, set(changed))
        cleared_structure = clear_stale_candidate_structure(updated, set(changed))
        estimated_fields = set(updated.get("estimated_fields") or [])
        for key in changed:
            estimated_fields.discard(f"activity.{key}")
        updated["estimated_fields"] = sorted(estimated_fields)
        notes = list(updated.get("uncertainty_notes") or [])
        note = f"Manually corrected: {', '.join(sorted(changed))}"
        if note not in notes:
            notes.append(note)
        if cleared_structure:
            structure_note = f"Cleared stale structured data after correction: {', '.join(cleared_structure)}"
            if structure_note not in notes:
                notes.append(structure_note)
        updated["uncertainty_notes"] = notes
    validate_activity_payload(updated)
    return updated, sorted(changed)


@router.get("")
def list_imports(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    batches = list(db.scalars(select(ImportBatch).where(ImportBatch.user_id == user.id).order_by(ImportBatch.created_at.desc())))
    matched_by_activity = matched_workout_ids_for_activities(db, user, [batch.created_activity_id for batch in batches if batch.created_activity_id is not None])
    results = []
    for batch in batches:
        result = import_result(db, user, batch, include_candidate=batch.status == "pending_confirmation")
        matched_id = matched_by_activity.get(batch.created_activity_id)
        result["matched_workout_id"] = matched_id
        result["match_status"] = "matched" if matched_id else "unmatched"
        result["auto_matched"] = False
        results.append(result)
    return results


@router.post("/screenshots")
def upload_screenshots(
    screenshots: list[UploadFile] = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not screenshots:
        raise HTTPException(status_code=400, detail="At least one screenshot is required")
    settings = get_settings()
    target_dir = settings.upload_dir / str(user.id) / datetime.now().strftime("%Y%m%d_%H%M%S")
    target_dir.mkdir(parents=True, exist_ok=True)

    batch = ImportBatch(user_id=user.id, status="uploaded", recognition_engine="pending", recognition_message="Screenshots uploaded")
    db.add(batch)
    db.flush()

    files: list[Path] = []
    source_ids: list[int] = []
    content_hashes: list[str] = []
    for screenshot in screenshots[:6]:
        filename = safe_filename(screenshot.filename or "screenshot.jpg")
        if Path(filename).suffix.lower() not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {filename}")
        target = target_dir / f"{uuid.uuid4().hex[:10]}-{filename}"
        content_hash = save_upload_with_hash(screenshot, target)
        source = ScreenshotSource(
            user_id=user.id,
            file_path=str(target),
            content_hash=content_hash,
            screen_type="uploaded_screenshot",
            notes=f"Uploaded screenshot {filename}",
        )
        db.add(source)
        db.flush()
        db.add(ImportBatchSource(batch_id=batch.id, source_id=source.id))
        files.append(target)
        source_ids.append(source.id)
        content_hashes.append(content_hash)

    backfill_user_screenshot_hashes(db, user.id)
    duplicate_activity = existing_activity_for_source_hashes(db, user, content_hashes)
    if duplicate_activity:
        profile = db.scalar(select(AthleteProfile).where(AthleteProfile.user_id == user.id))
        link_sources_to_activity(db, duplicate_activity, source_ids)
        sync_derived_activity_metrics(db, duplicate_activity, profile)
        batch.status = "duplicate"
        batch.recognition_engine = "duplicate:screenshot-hash"
        batch.recognition_message = f"Эти скриншоты уже импортированы как activity #{duplicate_activity.id}; новая тренировка не создана."
        batch.created_activity_id = duplicate_activity.id
        log_audit_event(db, user.id, "import.screenshots.duplicate", "import_batch", batch.id, {
            "created_activity_id": batch.created_activity_id,
            "hash_count": len(set(content_hashes)),
        })
        db.commit()
        return import_result(db, user, batch, include_candidate=True)

    matched_workout = None
    try:
        recognition = llm_or_template_recognize(db, batch.id, files, settings, user)
        activity = None
        if recognition.get("payload") and not recognition.get("requires_confirmation"):
            activity = create_activity_from_payload(db, user, recognition["payload"], source_ids)
        if activity:
            matched_workout = auto_match_activity_to_plan(db, user, activity)
            sync_daily_training_loads_for_activity(db, user, activity)
        batch.status = "recognized" if activity else recognition["status"]
        batch.recognition_engine = recognition["engine"]
        batch.recognition_message = recognition["message"]
        batch.created_activity_id = activity.id if activity else None
    except RecognitionValidationError as exc:
        batch.status = "validation_failed"
        batch.recognition_engine = "llm"
        batch.recognition_message = "; ".join(exc.errors)
    except Exception:
        batch.status = "recognition_failed"
        batch.recognition_engine = "unknown"
        batch.recognition_message = "Recognition failed unexpectedly. Check provider settings or uploaded screenshots."

    log_audit_event(db, user.id, "import.screenshots", "import_batch", batch.id, {
        "status": batch.status,
        "created_activity_id": batch.created_activity_id,
        "recognition_engine": batch.recognition_engine,
    })
    db.commit()
    return import_result(db, user, batch, matched_workout, include_candidate=True)


@router.post("/{batch_id}/confirm")
def confirm_import(batch_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    batch = import_batch_for_user(db, user, batch_id, for_update=True)
    if batch.status != "pending_confirmation":
        if batch.created_activity_id is not None:
            return import_result(db, user, batch, include_candidate=True)
        raise HTTPException(status_code=409, detail="Import batch is not pending confirmation")
    attempt = latest_recognition_attempt(db, batch.id)
    if not attempt or not attempt.parsed_payload:
        raise HTTPException(status_code=409, detail="Import candidate payload is missing")
    source_ids = [link.source_id for link in batch.sources]
    batch.status = "confirming"
    db.flush()
    try:
        with db.begin_nested():
            activity = create_activity_from_payload(db, user, attempt.parsed_payload, source_ids)
    except Exception as exc:
        batch.status = "validation_failed"
        batch.recognition_message = f"Could not create activity from confirmed candidate: {exc}"
        db.commit()
        raise HTTPException(status_code=400, detail=batch.recognition_message) from exc
    matched_workout = None
    if activity:
        matched_workout = auto_match_activity_to_plan(db, user, activity)
        sync_daily_training_loads_for_activity(db, user, activity)
        batch.created_activity_id = activity.id
    batch.status = "recognized" if activity else "validation_failed"
    batch.recognition_message = "Import candidate confirmed by user and activity was created." if activity else "Confirmed candidate did not contain activity data."
    log_audit_event(db, user.id, "import.confirmed", "import_batch", batch.id, {
        "created_activity_id": batch.created_activity_id,
        "recognition_engine": batch.recognition_engine,
    })
    db.commit()
    return import_result(db, user, batch, matched_workout, include_candidate=True)


@router.patch("/{batch_id}/candidate")
def patch_import_candidate(batch_id: int, patch: ImportCandidatePatchIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    batch = import_batch_for_user(db, user, batch_id, for_update=True)
    if batch.status != "pending_confirmation":
        raise HTTPException(status_code=409, detail="Import batch is not pending confirmation")
    attempt = latest_recognition_attempt(db, batch.id)
    if not attempt or not attempt.parsed_payload:
        raise HTTPException(status_code=409, detail="Import candidate payload is missing")
    try:
        updated_payload, changed_fields = update_candidate_payload(attempt.parsed_payload, patch)
    except RecognitionValidationError as exc:
        raise HTTPException(status_code=400, detail="; ".join(exc.errors)) from exc
    if not changed_fields:
        db.commit()
        return import_result(db, user, batch, include_candidate=True)
    attempt.parsed_payload = updated_payload
    batch.recognition_message = "Import candidate manually corrected; review and confirm to create activity." if changed_fields else batch.recognition_message
    log_audit_event(db, user.id, "import.candidate_corrected", "import_batch", batch.id, {"fields": changed_fields})
    db.commit()
    return import_result(db, user, batch, include_candidate=True)


@router.post("/{batch_id}/reject")
def reject_import(batch_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    batch = import_batch_for_user(db, user, batch_id, for_update=True)
    if batch.status != "pending_confirmation":
        raise HTTPException(status_code=409, detail="Import batch is not pending confirmation")
    batch.status = "rejected_by_user"
    batch.recognition_message = "Import candidate rejected by user; no activity was created."
    log_audit_event(db, user.id, "import.rejected", "import_batch", batch.id, {"recognition_engine": batch.recognition_engine})
    db.commit()
    return import_result(db, user, batch, include_candidate=True)


@router.post("/csv", response_model=CsvImportOut)
def upload_csv(
    csv_file: UploadFile = File(...),
    source_app: str = Form(default="csv"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    filename = safe_filename(csv_file.filename or "activities.csv")
    if Path(filename).suffix.lower() not in ALLOWED_CSV_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {filename}")
    raw = csv_file.file.read(5 * 1024 * 1024 + 1)
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="CSV file is too large; limit is 5 MB")
    try:
        rows = iter_csv_rows(raw)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not parse CSV: {exc}") from exc
    if not rows:
        raise HTTPException(status_code=400, detail="CSV file has no data rows")

    source_label = (source_app or "csv")[:100]
    batch = ImportBatch(user_id=user.id, status="processing", source_app=source_label, recognition_engine="csv")
    db.add(batch)
    db.flush()

    created_ids: list[int] = []
    touched_activities: list[Activity] = []
    skipped_duplicates = 0
    matched_workouts = 0
    errors: list[str] = []
    for row_number, row in enumerate(rows, start=2):
        try:
            payload = activity_payload_from_csv_row(row, row_number, filename)
        except Exception as exc:
            errors.append(str(exc)[:250])
            continue
        created_activity_id = None
        duplicate = False
        matched = False
        activity = None
        try:
            with db.begin_nested():
                activity, created = create_activity_from_csv_payload(db, user, payload)
                if created:
                    matched = bool(auto_match_activity_to_plan(db, user, activity))
                    created_activity_id = activity.id
                else:
                    duplicate = True
        except Exception as exc:
            errors.append(str(exc)[:250])
            continue
        if activity is not None:
            touched_activities.append(activity)
        if created_activity_id is not None:
            created_ids.append(created_activity_id)
            if matched:
                matched_workouts += 1
        elif duplicate:
            skipped_duplicates += 1

    batch.created_activity_id = created_ids[0] if len(created_ids) == 1 else None
    batch.status = "failed" if not created_ids and not skipped_duplicates else "partial_failed" if errors else "imported"
    batch.recognition_message = f"CSV import: {len(created_ids)} created, {skipped_duplicates} duplicates, {len(errors)} failed, {matched_workouts} matched."
    sync_daily_training_loads_for_activities(db, user, touched_activities)
    log_audit_event(db, user.id, "import.csv", "import_batch", batch.id, {
        "source_app": source_label,
        "created_activities": len(created_ids),
        "skipped_duplicates": skipped_duplicates,
        "failed_rows": len(errors),
        "matched_workouts": matched_workouts,
    })
    db.commit()
    return CsvImportOut(
        id=batch.id,
        status=batch.status,
        source_app=source_label,
        created_activities=len(created_ids),
        skipped_duplicates=skipped_duplicates,
        failed_rows=len(errors),
        matched_workouts=matched_workouts,
        created_activity_ids=created_ids,
        errors=errors[:50],
        recognition_message=batch.recognition_message,
    )
