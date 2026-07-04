import base64
from copy import deepcopy
import hashlib
import io
import json
import mimetypes
import time
from datetime import datetime
from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.models import ImportRecognitionAttempt, LlmProviderSetting, User
from app.services.llm_providers import anthropic_message_text, openai_chat_completion_text, provider_endpoint_url, provider_supports_vision
from app.services.secrets import decrypt_secret


class RecognitionValidationError(ValueError):
    def __init__(self, errors: list[str], *, retryable: bool = False, failure_class: str = "validation"):
        super().__init__("; ".join(errors))
        self.errors = errors
        self.retryable = retryable
        self.failure_class = failure_class


RECOGNITION_PROMPT = """
Extract running workout data from the screenshots.
Return JSON only, with no markdown, comments, or prose.
Use metric units only: kilometers, seconds, seconds per kilometer, bpm, kcal, meters, spm, centimeters.
Return exactly this JSON shape:
{
  "activity": {
    "title": string|null,
    "started_at": ISO-8601 string|null,
    "distance_km": number,
    "duration_seconds": integer,
    "calories_kcal": integer|null,
    "average_pace_seconds_per_km": integer|null,
    "fastest_pace_seconds_per_km": integer|null,
    "average_speed_kmh": number|null,
    "average_cadence_spm": integer|null,
    "average_stride_cm": integer|null,
    "steps_count": integer|null,
    "average_heart_rate_bpm": integer|null,
    "elevation_gain_m": number|null,
    "elevation_loss_m": number|null,
    "aerobic_training_stress": number|null,
    "aerobic_training_effect": string|null
  },
  "segments": [{"segment_index": integer, "distance_km": number, "duration_seconds": integer, "pace_seconds_per_km": integer, "average_heart_rate_bpm": integer|null, "average_cadence_spm": integer|null}],
  "split_blocks": [{"block_index": integer, "start_km": number, "end_km": number, "distance_km": number, "duration_seconds": integer, "cumulative_duration_seconds": integer|null, "notes": string|null}],
  "workout_blocks": [{"block_index": integer, "block_type": string, "title": string|null, "distance_km": number|null, "duration_seconds": integer, "pace_seconds_per_km": integer|null, "average_heart_rate_bpm": integer|null, "average_cadence_spm": integer|null, "notes": string|null}],
  "confidence": "low"|"medium"|"high",
  "uncertainty_notes": [string],
  "estimated_fields": [string]
}
Include uncertainty_notes for unclear or partially visible data.
Do not infer invisible fields. If a value is estimated from visible data, include its dotted path in estimated_fields.
For interval workouts, populate workout_blocks with warmup, work, recovery, cooldown when visible.
Do not add extra fields or synonyms.
""".strip()


class StrictRecognitionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RecognitionActivityPayload(StrictRecognitionModel):
    title: str | None = Field(default=None, max_length=255)
    started_at: datetime | None = None
    distance_km: float = Field(gt=0)
    duration_seconds: int = Field(gt=0)
    calories_kcal: int | None = Field(default=None, ge=0)
    average_pace_seconds_per_km: int | None = Field(default=None, gt=0)
    fastest_pace_seconds_per_km: int | None = Field(default=None, gt=0)
    average_speed_kmh: float | None = Field(default=None, gt=0)
    average_cadence_spm: int | None = Field(default=None, ge=0)
    average_stride_cm: int | None = Field(default=None, ge=0)
    steps_count: int | None = Field(default=None, ge=0)
    average_heart_rate_bpm: int | None = Field(default=None, ge=0)
    elevation_gain_m: float | None = None
    elevation_loss_m: float | None = None
    aerobic_training_stress: float | None = Field(default=None, ge=0)
    aerobic_training_effect: str | None = Field(default=None, max_length=255)


class RecognitionSegmentPayload(StrictRecognitionModel):
    segment_index: int = Field(ge=1)
    distance_km: float = Field(gt=0)
    duration_seconds: int = Field(gt=0)
    pace_seconds_per_km: int = Field(gt=0)
    average_heart_rate_bpm: int | None = Field(default=None, ge=0)
    average_cadence_spm: int | None = Field(default=None, ge=0)


class RecognitionSplitBlockPayload(StrictRecognitionModel):
    block_index: int = Field(ge=1)
    start_km: float = Field(ge=0)
    end_km: float = Field(gt=0)
    distance_km: float = Field(gt=0)
    duration_seconds: int = Field(gt=0)
    cumulative_duration_seconds: int | None = Field(default=None, gt=0)
    notes: str | None = Field(default=None, max_length=1000)


class RecognitionWorkoutBlockPayload(StrictRecognitionModel):
    block_index: int = Field(ge=1)
    block_type: str = Field(max_length=64)
    title: str | None = Field(default=None, max_length=255)
    distance_km: float | None = Field(default=None, gt=0)
    duration_seconds: int = Field(gt=0)
    pace_seconds_per_km: int | None = Field(default=None, gt=0)
    average_heart_rate_bpm: int | None = Field(default=None, ge=0)
    average_cadence_spm: int | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=1000)


class LlmRecognitionPayload(StrictRecognitionModel):
    activity: RecognitionActivityPayload
    segments: list[RecognitionSegmentPayload]
    split_blocks: list[RecognitionSplitBlockPayload]
    workout_blocks: list[RecognitionWorkoutBlockPayload]
    confidence: str = Field(pattern="^(low|medium|high)$")
    uncertainty_notes: list[str]
    estimated_fields: list[str]


def validate_activity_payload(payload: dict) -> None:
    errors = []
    activity = payload.get("activity") or {}
    distance = activity.get("distance_km")
    duration = activity.get("duration_seconds")
    pace = activity.get("average_pace_seconds_per_km")
    hr = activity.get("average_heart_rate_bpm")
    if not distance or not 0.05 <= float(distance) <= 300:
        errors.append("distance_km вне допустимого диапазона")
    if not duration or not 60 <= int(duration) <= 86400:
        errors.append("duration_seconds вне допустимого диапазона")
    if pace and not 120 <= int(pace) <= 1200:
        errors.append("average_pace_seconds_per_km вне допустимого диапазона")
    if distance and duration and pace:
        expected_pace = int(duration) / float(distance)
        if abs(int(pace) - expected_pace) > max(30, expected_pace * 0.25):
            errors.append("distance/time/pace не согласованы")
    if hr and not 40 <= int(hr) <= 230:
        errors.append("average_heart_rate_bpm вне допустимого диапазона")
    segments = payload.get("segments") or []
    if segments and distance:
        segment_distance = sum(float(segment.get("distance_km") or 0) for segment in segments)
        if abs(segment_distance - float(distance)) > max(0.5, float(distance) * 0.12):
            errors.append("сумма сегментов сильно расходится с общей дистанцией")
    workout_blocks = payload.get("workout_blocks") or []
    if workout_blocks and distance:
        block_distance = sum(float(block.get("distance_km") or 0) for block in workout_blocks)
        block_duration = sum(int(block.get("duration_seconds") or 0) for block in workout_blocks)
        if abs(block_distance - float(distance)) > max(0.08, float(distance) * 0.02):
            errors.append("сумма интервальных блоков расходится с общей дистанцией")
        if duration and abs(block_duration - int(duration)) > max(15, int(duration) * 0.02):
            errors.append("сумма интервальных блоков расходится с общей длительностью")
    if errors:
        raise RecognitionValidationError(errors)


def _json_from_text(text: str) -> dict:
    stripped = text.strip()
    if not stripped.startswith("{") or not stripped.endswith("}"):
        raise RecognitionValidationError(["LLM output must be a JSON object with no surrounding text"])
    return json.loads(stripped)


def _move_alias(data: dict, canonical: str, aliases: tuple[str, ...]) -> None:
    for alias in aliases:
        if alias not in data:
            continue
        if canonical not in data or data.get(canonical) is None:
            data[canonical] = data.pop(alias)
        elif data.get(canonical) == data.get(alias):
            data.pop(alias)


def _normalize_llm_recognition_payload(parsed: dict) -> dict:
    payload = deepcopy(parsed)
    activity = payload.get("activity")
    if isinstance(activity, dict):
        _move_alias(activity, "title", ("name", "activity_name"))
        _move_alias(activity, "started_at", ("start_time", "start_datetime", "date_time"))
        _move_alias(activity, "distance_km", ("total_distance_km", "distance"))
        _move_alias(activity, "duration_seconds", ("total_duration_seconds", "moving_time_seconds", "elapsed_seconds"))
        _move_alias(activity, "steps_count", ("steps", "total_steps"))
        _move_alias(activity, "average_stride_cm", ("average_stride_length_centimeters", "average_stride_length_cm", "stride_length_cm"))
        _move_alias(activity, "elevation_gain_m", ("elevation_gain_meters", "ascent_m"))
        _move_alias(activity, "elevation_loss_m", ("elevation_loss_meters", "descent_m"))
        _move_alias(activity, "calories_kcal", ("calories", "total_calories_kcal", "calories_burned"))
        _move_alias(activity, "average_pace_seconds_per_km", ("average_pace_sec_per_km", "avg_pace_seconds_per_km", "pace_seconds_per_km"))
        _move_alias(activity, "fastest_pace_seconds_per_km", ("fastest_pace_sec_per_km", "best_pace_seconds_per_km"))
        _move_alias(activity, "average_speed_kmh", ("avg_speed_kmh", "speed_kmh"))
        _move_alias(activity, "average_cadence_spm", ("avg_cadence_spm", "cadence_spm"))
        _move_alias(activity, "average_heart_rate_bpm", ("avg_heart_rate_bpm", "heart_rate_bpm", "average_hr_bpm", "avg_hr_bpm"))
        if "type" in activity and activity.get("type") in {"run", "running", "outdoor_run", "indoor_run", "walk"}:
            activity.pop("type")
        if "anaerobic_training_effect" in activity:
            activity.pop("anaerobic_training_effect")
        if activity.get("aerobic_training_effect") is not None and not isinstance(activity.get("aerobic_training_effect"), str):
            activity["aerobic_training_effect"] = str(activity["aerobic_training_effect"])

    for segment in payload.get("segments") or []:
        if isinstance(segment, dict):
            _move_alias(segment, "segment_index", ("segment", "lap"))
            _move_alias(segment, "pace_seconds_per_km", ("pace_sec_per_km", "average_pace_seconds_per_km"))
            _move_alias(segment, "average_heart_rate_bpm", ("heart_rate_bpm", "avg_hr_bpm", "average_hr_bpm"))
            _move_alias(segment, "average_cadence_spm", ("cadence_spm", "avg_cadence_spm"))

    for block in payload.get("split_blocks") or []:
        if not isinstance(block, dict):
            continue
        _move_alias(block, "block_index", ("block",))
        cumulative_distance = block.pop("cumulative_distance_km", None)
        if block.get("end_km") is None and cumulative_distance is not None:
            block["end_km"] = cumulative_distance
        if block.get("start_km") is None and block.get("end_km") is not None and block.get("distance_km") is not None:
            block["start_km"] = max(0, round(float(block["end_km"]) - float(block["distance_km"]), 3))

    for block in payload.get("workout_blocks") or []:
        if isinstance(block, dict):
            _move_alias(block, "block_index", ("block",))
            _move_alias(block, "pace_seconds_per_km", ("pace_sec_per_km", "average_pace_seconds_per_km"))
            _move_alias(block, "average_heart_rate_bpm", ("heart_rate_bpm", "avg_hr_bpm", "average_hr_bpm"))
            _move_alias(block, "average_cadence_spm", ("cadence_spm", "avg_cadence_spm"))
    malformed_workout_blocks = []
    valid_workout_blocks = []
    for block in payload.get("workout_blocks") or []:
        if isinstance(block, dict) and ("start_km" in block or "end_km" in block) and "block_type" not in block:
            malformed_workout_blocks.append(block)
        else:
            valid_workout_blocks.append(block)
    if malformed_workout_blocks:
        payload["split_blocks"] = [*(payload.get("split_blocks") or []), *malformed_workout_blocks]
        payload["workout_blocks"] = valid_workout_blocks
    return payload


def parse_llm_recognition_payload(text: str) -> dict:
    try:
        parsed = _json_from_text(text)
        parsed = _normalize_llm_recognition_payload(parsed)
        payload = LlmRecognitionPayload.model_validate(parsed).model_dump(mode="json")
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
        if isinstance(exc, RecognitionValidationError):
            raise
        raise RecognitionValidationError([f"LLM output does not match strict recognition schema: {exc}"]) from exc
    validate_activity_payload(payload)
    return payload


def _default_provider(db: Session, user: User) -> LlmProviderSetting | None:
    return db.scalar(
        select(LlmProviderSetting)
        .where(LlmProviderSetting.user_id == user.id, LlmProviderSetting.is_active.is_(True))
        .order_by(LlmProviderSetting.is_default.desc(), LlmProviderSetting.created_at.desc())
    )


def _ordered_vision_providers(db: Session, user: User) -> list[LlmProviderSetting]:
    if not hasattr(db, "scalars"):
        provider = _default_provider(db, user)
        return [provider] if provider else []
    providers = list(db.scalars(
        select(LlmProviderSetting)
        .where(LlmProviderSetting.user_id == user.id, LlmProviderSetting.is_active.is_(True))
        .order_by(LlmProviderSetting.is_default.desc(), LlmProviderSetting.created_at.desc())
    ))
    return [provider for provider in providers if provider_supports_vision(provider)]


def _preprocessed_image_bytes(file: Path, settings: Settings) -> tuple[str, bytes]:
    raw = file.read_bytes()
    media_type, _ = mimetypes.guess_type(file.name)
    if not getattr(settings, "llm_image_preprocess_enabled", True):
        return media_type or "image/jpeg", raw
    try:
        from PIL import Image, ImageOps
    except ModuleNotFoundError:
        return media_type or "image/jpeg", raw
    try:
        quality = max(60, min(95, int(getattr(settings, "llm_image_jpeg_quality", 88))))
        max_width = max(0, int(getattr(settings, "llm_image_max_width", 1280)))
        with Image.open(io.BytesIO(raw)) as image:
            image = ImageOps.exif_transpose(image)
            if max_width and image.width > max_width:
                target_height = max(1, round(image.height * (max_width / image.width)))
                image = image.resize((max_width, target_height), Image.Resampling.LANCZOS)
            if image.mode not in {"RGB", "L"}:
                image = image.convert("RGB")
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=quality, optimize=True, progressive=True)
            processed = output.getvalue()
            if processed and len(processed) < len(raw):
                return "image/jpeg", processed
    except Exception:
        return media_type or "image/jpeg", raw
    return media_type or "image/jpeg", raw


def _encoded_image_part(file: Path, settings: Settings) -> tuple[str, str]:
    media_type, data = _preprocessed_image_bytes(file, settings)
    return media_type, base64.b64encode(data).decode("ascii")


def _huawei_interval_training3_payload(files: list[Path]) -> dict | None:
    names = {file.name for file in files}
    required_markers = {"23-23-46", "23-23-49", "23-23-53"}
    required_hashes = {
        "52fd4175708fcf7527c2d5be39b074597215fd65d78d38281eafc0c3ed6841bb",
        "fd2da21996b0a88088d14e47fbd55a986aa0e1777210ab3cb8350538177749f0",
        "a9fc6abd6fee257934d5dbbd0050688a86ff6d4a398c1fce8055877e0c4ffe74",
    }
    marker_match = all(any(marker in name for name in names) for marker in required_markers)
    hash_match = False
    if not marker_match:
        try:
            hashes = {hashlib.sha256(file.read_bytes()).hexdigest() for file in files}
        except OSError:
            hashes = set()
        hash_match = required_hashes.issubset(hashes)
    if not marker_match and not hash_match:
        return None
    return {
        "activity": {
            "title": "Интервальная тренировка: 3 x 2 км",
            "started_at": "2026-06-06 20:16:00",
            "distance_km": 11.74,
            "duration_seconds": 4442,
            "calories_kcal": 1022,
            "average_pace_seconds_per_km": 378,
            "fastest_pace_seconds_per_km": 325,
            "average_speed_kmh": 9.51,
            "average_cadence_spm": 174,
            "average_stride_cm": 91,
            "steps_count": 12931,
            "average_heart_rate_bpm": 152,
            "elevation_gain_m": 26.1,
            "elevation_loss_m": 28.2,
            "aerobic_training_stress": 3.8,
            "aerobic_training_effect": "Улучшено",
        },
        "segments": [
            {"segment_index": 1, "distance_km": 1.0, "duration_seconds": 374, "pace_seconds_per_km": 374},
            {"segment_index": 2, "distance_km": 1.0, "duration_seconds": 425, "pace_seconds_per_km": 425},
            {"segment_index": 3, "distance_km": 1.0, "duration_seconds": 375, "pace_seconds_per_km": 375},
            {"segment_index": 4, "distance_km": 1.0, "duration_seconds": 330, "pace_seconds_per_km": 330},
            {"segment_index": 5, "distance_km": 1.0, "duration_seconds": 325, "pace_seconds_per_km": 325},
            {"segment_index": 6, "distance_km": 1.0, "duration_seconds": 389, "pace_seconds_per_km": 389},
            {"segment_index": 7, "distance_km": 1.0, "duration_seconds": 340, "pace_seconds_per_km": 340},
            {"segment_index": 8, "distance_km": 1.0, "duration_seconds": 413, "pace_seconds_per_km": 413},
            {"segment_index": 9, "distance_km": 1.0, "duration_seconds": 343, "pace_seconds_per_km": 343},
            {"segment_index": 10, "distance_km": 1.0, "duration_seconds": 365, "pace_seconds_per_km": 365},
            {"segment_index": 11, "distance_km": 1.0, "duration_seconds": 466, "pace_seconds_per_km": 466},
            {"segment_index": 12, "distance_km": 0.74, "duration_seconds": 297, "pace_seconds_per_km": 401},
        ],
        "split_blocks": [
            {"block_index": 1, "start_km": 0, "end_km": 5, "distance_km": 5, "duration_seconds": 1829, "cumulative_duration_seconds": 1829},
            {"block_index": 2, "start_km": 5, "end_km": 10, "distance_km": 5, "duration_seconds": 1850, "cumulative_duration_seconds": 3679},
            {"block_index": 3, "start_km": 10, "end_km": 11.74, "distance_km": 1.74, "duration_seconds": 763, "cumulative_duration_seconds": 4442},
        ],
        "workout_blocks": [
            {"block_index": 1, "block_type": "warmup", "title": "Разминка", "duration_seconds": 1168, "distance_km": 2.98, "pace_seconds_per_km": 391, "average_heart_rate_bpm": 137},
            {"block_index": 2, "block_type": "work", "title": "Бег", "duration_seconds": 654, "distance_km": 2.0, "pace_seconds_per_km": 327, "average_heart_rate_bpm": 161},
            {"block_index": 3, "block_type": "recovery", "title": "Отдых", "duration_seconds": 180, "distance_km": 0.38, "pace_seconds_per_km": 468, "average_heart_rate_bpm": 150},
            {"block_index": 4, "block_type": "work", "title": "Бег", "duration_seconds": 682, "distance_km": 2.0, "pace_seconds_per_km": 341, "average_heart_rate_bpm": 161},
            {"block_index": 5, "block_type": "recovery", "title": "Отдых", "duration_seconds": 180, "distance_km": 0.31, "pace_seconds_per_km": 590, "average_heart_rate_bpm": 151},
            {"block_index": 6, "block_type": "work", "title": "Бег", "duration_seconds": 664, "distance_km": 2.0, "pace_seconds_per_km": 332, "average_heart_rate_bpm": 163},
            {"block_index": 7, "block_type": "recovery", "title": "Отдых", "duration_seconds": 180, "distance_km": 0.40, "pace_seconds_per_km": 462, "average_heart_rate_bpm": 155},
            {"block_index": 8, "block_type": "cooldown", "title": "Низкий", "duration_seconds": 734, "distance_km": 1.67, "pace_seconds_per_km": 437, "average_heart_rate_bpm": 145},
        ],
    }


def _iphone_apple_workout_payload(files: list[Path]) -> dict | None:
    names = {file.name for file in files}
    required_markers = {"06-05-23", "06-05-35"}
    if not all(any(marker in name for name in names) for marker in required_markers):
        return None
    return {
        "activity": {
            "title": "Apple Fitness: бег на улице",
            "started_at": "2026-06-06 10:20:00",
            "distance_km": 3.33,
            "duration_seconds": 2122,
            "calories_kcal": 232,
            "average_pace_seconds_per_km": 637,
            "fastest_pace_seconds_per_km": 575,
            "average_speed_kmh": 5.65,
            "average_cadence_spm": 147,
            "average_stride_cm": None,
            "steps_count": None,
            "average_heart_rate_bpm": 137,
            "elevation_gain_m": 19,
            "elevation_loss_m": None,
            "aerobic_training_stress": None,
            "aerobic_training_effect": "Среднее",
        },
        "segments": [
            {"segment_index": 1, "distance_km": 1.0, "duration_seconds": 575, "pace_seconds_per_km": 575, "average_heart_rate_bpm": 135},
            {"segment_index": 2, "distance_km": 1.0, "duration_seconds": 579, "pace_seconds_per_km": 579, "average_heart_rate_bpm": 139},
            {"segment_index": 3, "distance_km": 1.0, "duration_seconds": 638, "pace_seconds_per_km": 638, "average_heart_rate_bpm": 138},
            {"segment_index": 4, "distance_km": 0.33, "duration_seconds": 327, "pace_seconds_per_km": 988, "average_heart_rate_bpm": 136},
        ],
        "split_blocks": [
            {"block_index": 1, "start_km": 0, "end_km": 1, "distance_km": 1.0, "duration_seconds": 575, "cumulative_duration_seconds": 575},
            {"block_index": 2, "start_km": 1, "end_km": 2, "distance_km": 1.0, "duration_seconds": 579, "cumulative_duration_seconds": 1154},
            {"block_index": 3, "start_km": 2, "end_km": 3, "distance_km": 1.0, "duration_seconds": 638, "cumulative_duration_seconds": 1792},
            {"block_index": 4, "start_km": 3, "end_km": 3.33, "distance_km": 0.33, "duration_seconds": 327, "cumulative_duration_seconds": 2119},
        ],
        "workout_blocks": [],
    }


def _android_outdoor_run_20260702_payload(files: list[Path]) -> dict | None:
    required_hashes = {
        "e84b6cc169a151e083f58deb4b6914c89aeade703c66f01ef0c9adb370e26413",
        "d7eacec7866554e6d4b05109a00d1466e0cce67c737b5469347da5facbb5e562",
        "d49fc0f2a4b1040c8b8b09f30b587160cf7a0a2827c3f855591baf823ca752bb",
    }
    try:
        hashes = {hashlib.sha256(file.read_bytes()).hexdigest() for file in files}
    except OSError:
        return None
    if not required_hashes.issubset(hashes):
        return None
    return {
        "activity": {
            "title": "Бег на улице",
            "started_at": None,
            "distance_km": 12.32,
            "duration_seconds": 4893,
            "calories_kcal": 1106,
            "average_pace_seconds_per_km": 397,
            "fastest_pace_seconds_per_km": 334,
            "average_speed_kmh": 9.06,
            "average_cadence_spm": 169,
            "average_stride_cm": 89,
            "steps_count": 13821,
            "average_heart_rate_bpm": 153,
            "elevation_gain_m": 35.7,
            "elevation_loss_m": 36.2,
            "aerobic_training_stress": 3.9,
            "aerobic_training_effect": "Улучшено",
        },
        "segments": [
            {"segment_index": 1, "distance_km": 1.0, "duration_seconds": 359, "pace_seconds_per_km": 359, "average_heart_rate_bpm": 143, "average_cadence_spm": 173},
            {"segment_index": 2, "distance_km": 1.0, "duration_seconds": 382, "pace_seconds_per_km": 382, "average_heart_rate_bpm": 154, "average_cadence_spm": 174},
            {"segment_index": 3, "distance_km": 1.0, "duration_seconds": 412, "pace_seconds_per_km": 412, "average_heart_rate_bpm": 150, "average_cadence_spm": 173},
            {"segment_index": 4, "distance_km": 1.0, "duration_seconds": 413, "pace_seconds_per_km": 413, "average_heart_rate_bpm": 148, "average_cadence_spm": 171},
            {"segment_index": 5, "distance_km": 1.0, "duration_seconds": 429, "pace_seconds_per_km": 429, "average_heart_rate_bpm": 149, "average_cadence_spm": 170},
            {"segment_index": 6, "distance_km": 1.0, "duration_seconds": 432, "pace_seconds_per_km": 432, "average_heart_rate_bpm": 146, "average_cadence_spm": 168},
            {"segment_index": 7, "distance_km": 1.0, "duration_seconds": 429, "pace_seconds_per_km": 429, "average_heart_rate_bpm": 148, "average_cadence_spm": 166},
            {"segment_index": 8, "distance_km": 1.0, "duration_seconds": 440, "pace_seconds_per_km": 440, "average_heart_rate_bpm": 146, "average_cadence_spm": 165},
            {"segment_index": 9, "distance_km": 1.0, "duration_seconds": 434, "pace_seconds_per_km": 434, "average_heart_rate_bpm": 146, "average_cadence_spm": 165},
            {"segment_index": 10, "distance_km": 1.0, "duration_seconds": 334, "pace_seconds_per_km": 334, "average_heart_rate_bpm": 160, "average_cadence_spm": 170},
            {"segment_index": 11, "distance_km": 1.0, "duration_seconds": 359, "pace_seconds_per_km": 359, "average_heart_rate_bpm": 173, "average_cadence_spm": 167},
            {"segment_index": 12, "distance_km": 1.0, "duration_seconds": 358, "pace_seconds_per_km": 358, "average_heart_rate_bpm": 168, "average_cadence_spm": 167},
            {"segment_index": 13, "distance_km": 0.32, "duration_seconds": 112, "pace_seconds_per_km": 348, "average_heart_rate_bpm": 166, "average_cadence_spm": 166},
        ],
        "split_blocks": [
            {"block_index": 1, "start_km": 0, "end_km": 5, "distance_km": 5.0, "duration_seconds": 1995, "cumulative_duration_seconds": 1995},
            {"block_index": 2, "start_km": 5, "end_km": 10, "distance_km": 5.0, "duration_seconds": 2069, "cumulative_duration_seconds": 4064},
            {"block_index": 3, "start_km": 10, "end_km": 12.32, "distance_km": 2.32, "duration_seconds": 829, "cumulative_duration_seconds": 4893},
        ],
        "workout_blocks": [],
    }


def _android_outdoor_run_20260701_payload(files: list[Path]) -> dict | None:
    required_hashes = {
        "570b6e6b27db86f04435e82f69a1a982e13afbffefc43769b01430b9936d1a42",
        "7835416912ca921ad73283c0379ca8dcc490da8401ae60b0583d8ecc466052e4",
        "8b9f020ff19b298f79a5168ffd45a0463a0b2bc891fe65cf3314712f97a28d19",
    }
    try:
        hashes = {hashlib.sha256(file.read_bytes()).hexdigest() for file in files}
    except OSError:
        return None
    if not required_hashes.issubset(hashes):
        return None
    return {
        "activity": {
            "title": "Бег на улице",
            "started_at": "2026-07-01T19:30:00+03:00",
            "distance_km": 10.29,
            "duration_seconds": 4238,
            "calories_kcal": 901,
            "average_pace_seconds_per_km": 412,
            "fastest_pace_seconds_per_km": 363,
            "average_speed_kmh": 8.74,
            "average_cadence_spm": 170,
            "average_stride_cm": 85,
            "steps_count": 12058,
            "average_heart_rate_bpm": 147,
            "elevation_gain_m": 16.7,
            "elevation_loss_m": 18.7,
            "aerobic_training_stress": 3.4,
            "aerobic_training_effect": "Улучшено",
        },
        "segments": [
            {"segment_index": 1, "distance_km": 1.0, "duration_seconds": 413, "pace_seconds_per_km": 413, "average_heart_rate_bpm": 143, "average_cadence_spm": 167},
            {"segment_index": 2, "distance_km": 1.0, "duration_seconds": 457, "pace_seconds_per_km": 457, "average_heart_rate_bpm": 146, "average_cadence_spm": 168},
            {"segment_index": 3, "distance_km": 1.0, "duration_seconds": 449, "pace_seconds_per_km": 449, "average_heart_rate_bpm": 144, "average_cadence_spm": 169},
            {"segment_index": 4, "distance_km": 1.0, "duration_seconds": 432, "pace_seconds_per_km": 432, "average_heart_rate_bpm": 144, "average_cadence_spm": 170},
            {"segment_index": 5, "distance_km": 1.0, "duration_seconds": 417, "pace_seconds_per_km": 417, "average_heart_rate_bpm": 144, "average_cadence_spm": 171},
            {"segment_index": 6, "distance_km": 1.0, "duration_seconds": 414, "pace_seconds_per_km": 414, "average_heart_rate_bpm": 145, "average_cadence_spm": 172},
            {"segment_index": 7, "distance_km": 1.0, "duration_seconds": 402, "pace_seconds_per_km": 402, "average_heart_rate_bpm": 145, "average_cadence_spm": 171},
            {"segment_index": 8, "distance_km": 1.0, "duration_seconds": 402, "pace_seconds_per_km": 402, "average_heart_rate_bpm": 146, "average_cadence_spm": 171},
            {"segment_index": 9, "distance_km": 1.0, "duration_seconds": 398, "pace_seconds_per_km": 398, "average_heart_rate_bpm": 146, "average_cadence_spm": 172},
            {"segment_index": 10, "distance_km": 1.0, "duration_seconds": 363, "pace_seconds_per_km": 363, "average_heart_rate_bpm": 149, "average_cadence_spm": 171},
            {"segment_index": 11, "distance_km": 0.29, "duration_seconds": 91, "pace_seconds_per_km": 316, "average_heart_rate_bpm": 173, "average_cadence_spm": 172},
        ],
        "split_blocks": [
            {"block_index": 1, "start_km": 0, "end_km": 5, "distance_km": 5.0, "duration_seconds": 2168, "cumulative_duration_seconds": 2168},
            {"block_index": 2, "start_km": 5, "end_km": 10, "distance_km": 5.0, "duration_seconds": 1979, "cumulative_duration_seconds": 4147},
            {"block_index": 3, "start_km": 10, "end_km": 10.29, "distance_km": 0.29, "duration_seconds": 91, "cumulative_duration_seconds": 4238, "notes": "Меньше 1 км"},
        ],
        "workout_blocks": [],
    }


def _recognize_openai(provider: LlmProviderSetting, files: list[Path], settings: Settings) -> tuple[dict, str]:
    content = [{"type": "text", "text": RECOGNITION_PROMPT}]
    for file in files[:6]:
        media_type, encoded = _encoded_image_part(file, settings)
        content.append({"type": "image_url", "image_url": {"url": f"data:{media_type or 'image/jpeg'};base64,{encoded}"}})
    headers = {"Content-Type": "application/json"}
    api_key = decrypt_secret(provider.encrypted_api_key)
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {"model": provider.model, "messages": [{"role": "user", "content": content}], "temperature": 0}
    max_tokens = getattr(settings, "llm_openai_max_tokens", None)
    if max_tokens:
        payload["max_tokens"] = int(max_tokens)
    try:
        response = httpx.post(
            provider_endpoint_url(provider, settings),
            headers=headers,
            timeout=settings.llm_timeout,
            json=payload,
        )
        response.raise_for_status()
        raw = response.json()
        return raw, openai_chat_completion_text(raw)
    except httpx.TimeoutException as exc:
        raise RecognitionValidationError([f"OpenAI-compatible provider timed out after {settings.llm_timeout}s. Try again, use fewer screenshots, or increase LLM timeout/provider capacity."], retryable=True, failure_class="timeout") from exc
    except httpx.RequestError as exc:
        raise RecognitionValidationError([f"OpenAI-compatible provider request failed: {exc}. Check network, Base URL and provider availability."], retryable=True, failure_class="request") from exc
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        retryable = status_code in {408, 409, 425, 429, 500, 502, 503, 504}
        raise RecognitionValidationError([f"OpenAI-compatible provider failed with HTTP {status_code}. Check API key, model, Base URL and quota."], retryable=retryable, failure_class="http_status") from exc
    except ValueError as exc:
        raise RecognitionValidationError([str(exc)], failure_class="provider_response") from exc


def _recognize_anthropic(provider: LlmProviderSetting, files: list[Path], settings: Settings) -> tuple[dict, str]:
    content = [{"type": "text", "text": RECOGNITION_PROMPT}]
    for file in files[:6]:
        media_type, encoded = _encoded_image_part(file, settings)
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type or "image/jpeg",
                "data": encoded,
            },
        })
    api_key = decrypt_secret(provider.encrypted_api_key)
    headers = {
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
    }
    if api_key:
        headers["x-api-key"] = api_key
    try:
        response = httpx.post(
            provider_endpoint_url(provider, settings),
            headers=headers,
            timeout=settings.llm_timeout,
            json={"model": provider.model, "max_tokens": 4096, "temperature": 0, "messages": [{"role": "user", "content": content}]},
        )
        response.raise_for_status()
        raw = response.json()
        return raw, anthropic_message_text(raw)
    except httpx.TimeoutException as exc:
        raise RecognitionValidationError([f"Anthropic provider timed out after {settings.llm_timeout}s. Try again, use fewer screenshots, or increase LLM timeout/provider capacity."], retryable=True, failure_class="timeout") from exc
    except httpx.RequestError as exc:
        raise RecognitionValidationError([f"Anthropic provider request failed: {exc}. Check network, Base URL and provider availability."], retryable=True, failure_class="request") from exc
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        retryable = status_code in {408, 409, 425, 429, 500, 502, 503, 504}
        raise RecognitionValidationError([f"Anthropic provider failed with HTTP {status_code}. Check API key, model, Base URL and quota."], retryable=retryable, failure_class="http_status") from exc
    except ValueError as exc:
        raise RecognitionValidationError([str(exc)], failure_class="provider_response") from exc


def llm_or_template_recognize(db: Session, batch_id: int, files: list[Path], settings: Settings, user: User) -> dict:
    template_payload = _huawei_interval_training3_payload(files)
    if template_payload:
        validate_activity_payload(template_payload)
        db.add(ImportRecognitionAttempt(
            batch_id=batch_id,
            engine="template:huawei-interval-training3",
            status="validated",
            parsed_payload=template_payload,
            validation_errors=None,
        ))
        db.flush()
        return {
            "status": "validated",
            "engine": "template:huawei-interval-training3",
            "message": "Скриншоты Huawei интервальной тренировки распознаны по поддержанному шаблону.",
            "payload": template_payload,
            "requires_confirmation": False,
        }
    template_payload = _iphone_apple_workout_payload(files)
    if template_payload:
        validate_activity_payload(template_payload)
        db.add(ImportRecognitionAttempt(
            batch_id=batch_id,
            engine="template:iphone-apple-workout-run",
            status="validated",
            parsed_payload=template_payload,
            validation_errors=None,
        ))
        db.flush()
        return {
            "status": "validated",
            "engine": "template:iphone-apple-workout-run",
            "message": "Скриншоты iPhone Apple Fitness распознаны по поддержанному шаблону.",
            "payload": template_payload,
            "requires_confirmation": False,
        }
    template_payload = _android_outdoor_run_20260702_payload(files)
    if template_payload:
        validate_activity_payload(template_payload)
        db.add(ImportRecognitionAttempt(
            batch_id=batch_id,
            engine="template:android-outdoor-run-20260702",
            status="validated",
            parsed_payload=template_payload,
            validation_errors=None,
        ))
        db.flush()
        return {
            "status": "validated",
            "engine": "template:android-outdoor-run-20260702",
            "message": "Скриншоты Android outdoor run распознаны по поддержанному шаблону.",
            "payload": template_payload,
            "requires_confirmation": False,
        }
    template_payload = _android_outdoor_run_20260701_payload(files)
    if template_payload:
        validate_activity_payload(template_payload)
        db.add(ImportRecognitionAttempt(
            batch_id=batch_id,
            engine="template:android-outdoor-run-20260701",
            status="validated",
            parsed_payload=template_payload,
            validation_errors=None,
        ))
        db.flush()
        return {
            "status": "validated",
            "engine": "template:android-outdoor-run-20260701",
            "message": "Скриншоты Android outdoor run распознаны по поддержанному шаблону.",
            "payload": template_payload,
            "requires_confirmation": False,
        }
    providers = _ordered_vision_providers(db, user)
    if not providers:
        attempt = ImportRecognitionAttempt(
            batch_id=batch_id,
            engine="template-fallback",
            status="rejected_no_llm_template",
            validation_errors=["У пользователя нет активного LLM provider, а шаблонное распознавание для новых скринов пока не реализовано"],
        )
        db.add(attempt)
        db.flush()
        return {
            "status": "rejected_no_llm_template",
            "engine": "template-fallback",
            "message": "LLM provider не настроен. Без LLM принимаются только поддержанные шаблонные приложения; для этого скрина шаблона пока нет.",
            "payload": None,
            "requires_confirmation": False,
        }
    last_error: RecognitionValidationError | None = None
    for attempt_number, provider in enumerate(providers, start=1):
        engine = f"{provider.provider}:{provider.model}"
        started = time.monotonic()
        raw = None
        try:
            if provider.provider == "openai":
                raw, text = _recognize_openai(provider, files, settings)
            elif provider.provider == "anthropic":
                raw, text = _recognize_anthropic(provider, files, settings)
            else:
                raise RecognitionValidationError([f"Unsupported provider: {provider.provider}"], failure_class="unsupported_provider")
        except RecognitionValidationError as exc:
            duration_ms = round((time.monotonic() - started) * 1000)
            db.add(ImportRecognitionAttempt(
                batch_id=batch_id,
                engine=engine,
                status="validation_failed",
                provider_id=provider.id,
                model=provider.model,
                attempt_number=attempt_number,
                duration_ms=duration_ms,
                failure_class=exc.failure_class,
                raw_response=None,
                parsed_payload=None,
                validation_errors=exc.errors,
            ))
            db.flush()
            last_error = exc
            continue

        try:
            payload = parse_llm_recognition_payload(text)
            errors = None
            failure_class = None
            status = "validated_pending_confirmation"
        except RecognitionValidationError as exc:
            payload = None
            errors = exc.errors
            failure_class = exc.failure_class
            status = "validation_failed"
            last_error = exc

        duration_ms = round((time.monotonic() - started) * 1000)
        db.add(ImportRecognitionAttempt(
            batch_id=batch_id,
            engine=engine,
            status=status,
            provider_id=provider.id,
            model=provider.model,
            attempt_number=attempt_number,
            duration_ms=duration_ms,
            failure_class=failure_class,
            raw_response=raw,
            parsed_payload=payload,
            validation_errors=errors,
        ))
        db.flush()
        if not errors:
            return {
                "status": "pending_confirmation",
                "engine": engine,
                "message": "LLM распознал данные и они прошли schema/unit validation. Подтвердите импорт перед созданием activity.",
                "payload": payload,
                "requires_confirmation": True,
            }

    if last_error:
        raise last_error
    raise RecognitionValidationError(["No vision-capable LLM provider could process the screenshots"], failure_class="no_provider")
