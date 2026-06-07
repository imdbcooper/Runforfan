import shutil
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.db.session import get_db
from app.models import Activity, ActivityScreenshot, ActivitySegment, ActivitySplitBlock, ActivityWorkoutBlock, ImportBatch, ImportBatchSource, ScreenshotSource, User
from app.services.auth import get_current_user
from app.services.planning import auto_match_activity_to_plan
from app.services.recognition import RecognitionValidationError, llm_or_template_recognize


router = APIRouter(prefix="/imports", tags=["imports"])
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


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


@router.get("")
def list_imports(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    batches = list(db.scalars(select(ImportBatch).where(ImportBatch.user_id == user.id).order_by(ImportBatch.created_at.desc())))
    return [{
        "id": batch.id,
        "status": batch.status,
        "source_app": batch.source_app,
        "recognition_engine": batch.recognition_engine,
        "recognition_message": batch.recognition_message,
        "created_activity_id": batch.created_activity_id,
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

    try:
        recognition = llm_or_template_recognize(db, batch.id, files, settings, user)
        activity = create_activity_from_payload(db, user, recognition["payload"], source_ids) if recognition.get("payload") else None
        if activity:
            auto_match_activity_to_plan(db, user, activity)
        batch.status = "recognized" if activity else recognition["status"]
        batch.recognition_engine = recognition["engine"]
        batch.recognition_message = recognition["message"]
        batch.created_activity_id = activity.id if activity else None
    except RecognitionValidationError as exc:
        batch.status = "validation_failed"
        batch.recognition_engine = "llm"
        batch.recognition_message = "; ".join(exc.errors)

    db.commit()
    return {
        "id": batch.id,
        "status": batch.status,
        "recognition_engine": batch.recognition_engine,
        "recognition_message": batch.recognition_message,
        "created_activity_id": batch.created_activity_id,
    }
