import shutil
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.db.session import get_db
from app.models import Activity, ActivityScreenshot, ActivitySegment, ActivitySplitBlock, ActivityWorkoutBlock, ImportBatch, ImportBatchSource, ScreenshotSource, TrainingPlan, TrainingPlanWorkout, User
from app.schemas.common import CsvImportOut
from app.services.audit import log_audit_event
from app.services.auth import get_current_user
from app.services.csv_imports import activity_payload_from_csv_row, create_activity_from_csv_payload, iter_csv_rows
from app.services.planning import auto_match_activity_to_plan
from app.services.recognition import RecognitionValidationError, llm_or_template_recognize


router = APIRouter(prefix="/imports", tags=["imports"])
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_CSV_EXTENSIONS = {".csv", ".txt"}


def safe_filename(filename: str) -> str:
    return Path(filename or "screenshot.jpg").name.replace("/", "_").replace("\\", "_")[:120]


def create_activity_from_payload(db: Session, user: User, payload: dict, source_ids: list[int]) -> Activity | None:
    activity_payload = payload.get("activity") or {}
    if not activity_payload:
        return None
    started_at = datetime.fromisoformat(activity_payload["started_at"]) if activity_payload.get("started_at") else None
    existing = None
    if started_at and activity_payload.get("distance_km") and activity_payload.get("duration_seconds"):
        existing = db.scalar(select(Activity).where(
            Activity.user_id == user.id,
            Activity.started_at == started_at,
            Activity.distance_km == activity_payload.get("distance_km"),
            Activity.duration_seconds == activity_payload.get("duration_seconds"),
        ))
    if existing:
        for source_id in source_ids:
            db.add(ActivityScreenshot(activity_id=existing.id, source_id=source_id))
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
        db.add(ActivitySegment(activity_id=activity.id, **segment))
    for block in payload.get("split_blocks") or []:
        db.add(ActivitySplitBlock(activity_id=activity.id, **block))
    for block in payload.get("workout_blocks") or []:
        db.add(ActivityWorkoutBlock(
            activity_id=activity.id,
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


@router.get("")
def list_imports(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    batches = list(db.scalars(select(ImportBatch).where(ImportBatch.user_id == user.id).order_by(ImportBatch.created_at.desc())))
    matched_by_activity = matched_workout_ids_for_activities(db, user, [batch.created_activity_id for batch in batches if batch.created_activity_id is not None])
    return [{
        "id": batch.id,
        "status": batch.status,
        "source_app": batch.source_app,
        "recognition_engine": batch.recognition_engine,
        "recognition_message": batch.recognition_message,
        "created_activity_id": batch.created_activity_id,
        "matched_workout_id": matched_by_activity.get(batch.created_activity_id),
        "match_status": "matched" if matched_by_activity.get(batch.created_activity_id) else "unmatched",
        "auto_matched": False,
        "created_at": batch.created_at,
    } for batch in batches]


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
    for screenshot in screenshots[:6]:
        filename = safe_filename(screenshot.filename or "screenshot.jpg")
        if Path(filename).suffix.lower() not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {filename}")
        target = target_dir / f"{uuid.uuid4().hex[:10]}-{filename}"
        with target.open("wb") as output:
            shutil.copyfileobj(screenshot.file, output)
        source = ScreenshotSource(
            user_id=user.id,
            file_path=str(target),
            screen_type="uploaded_screenshot",
            notes=f"Uploaded screenshot {filename}",
        )
        db.add(source)
        db.flush()
        db.add(ImportBatchSource(batch_id=batch.id, source_id=source.id))
        files.append(target)
        source_ids.append(source.id)

    matched_workout = None
    try:
        recognition = llm_or_template_recognize(db, batch.id, files, settings, user)
        activity = create_activity_from_payload(db, user, recognition["payload"], source_ids) if recognition.get("payload") else None
        if activity:
            matched_workout = auto_match_activity_to_plan(db, user, activity)
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
    matched_workout_id = matched_workout.id if matched_workout else matched_workout_id_for_activity(db, user, batch.created_activity_id)
    match_status = "auto_matched" if matched_workout else "already_matched" if matched_workout_id else "unmatched"
    return {
        "id": batch.id,
        "status": batch.status,
        "recognition_engine": batch.recognition_engine,
        "recognition_message": batch.recognition_message,
        "created_activity_id": batch.created_activity_id,
        "matched_workout_id": matched_workout_id,
        "match_status": match_status,
        "auto_matched": bool(matched_workout),
    }


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
        if created_activity_id is not None:
            created_ids.append(created_activity_id)
            if matched:
                matched_workouts += 1
        elif duplicate:
            skipped_duplicates += 1

    batch.created_activity_id = created_ids[0] if len(created_ids) == 1 else None
    batch.status = "failed" if not created_ids and not skipped_duplicates else "partial_failed" if errors else "imported"
    batch.recognition_message = f"CSV import: {len(created_ids)} created, {skipped_duplicates} duplicates, {len(errors)} failed, {matched_workouts} matched."
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
