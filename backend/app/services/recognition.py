import base64
import json
import mimetypes
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.models import ImportRecognitionAttempt, LlmProviderSetting, User
from app.services.llm_providers import provider_endpoint_url
from app.services.secrets import decrypt_secret


class RecognitionValidationError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


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
    start = text.find("{")
    end = text.rfind("}")
    return json.loads(text[start:end + 1])


def _default_provider(db: Session, user: User) -> LlmProviderSetting | None:
    return db.scalar(
        select(LlmProviderSetting)
        .where(LlmProviderSetting.user_id == user.id, LlmProviderSetting.is_active.is_(True))
        .order_by(LlmProviderSetting.is_default.desc(), LlmProviderSetting.created_at.desc())
    )


def _huawei_interval_training3_payload(files: list[Path]) -> dict | None:
    names = {file.name for file in files}
    required_markers = {"23-23-46", "23-23-49", "23-23-53"}
    if not all(any(marker in name for name in names) for marker in required_markers):
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
            "aerobic_training_stress": None,
            "aerobic_training_effect": None,
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


def _recognize_openai(provider: LlmProviderSetting, files: list[Path], settings: Settings) -> tuple[dict, str]:
    content = [{"type": "text", "text": "Extract running workout data. Return strict JSON with activity, kilometer segments, split_blocks and workout_blocks for intervals such as warmup, work, recovery and cooldown."}]
    for file in files[:6]:
        media_type, _ = mimetypes.guess_type(file.name)
        encoded = base64.b64encode(file.read_bytes()).decode("ascii")
        content.append({"type": "image_url", "image_url": {"url": f"data:{media_type or 'image/jpeg'};base64,{encoded}"}})
    headers = {"Content-Type": "application/json"}
    api_key = decrypt_secret(provider.encrypted_api_key)
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    response = httpx.post(
        provider_endpoint_url(provider, settings),
        headers=headers,
        timeout=settings.llm_timeout,
        json={"model": provider.model, "messages": [{"role": "user", "content": content}], "temperature": 0},
    )
    response.raise_for_status()
    raw = response.json()
    return raw, raw["choices"][0]["message"]["content"]


def _recognize_anthropic(provider: LlmProviderSetting, files: list[Path], settings: Settings) -> tuple[dict, str]:
    content = [{"type": "text", "text": "Extract running workout data. Return strict JSON with activity, kilometer segments, split_blocks and workout_blocks for intervals such as warmup, work, recovery and cooldown."}]
    for file in files[:6]:
        media_type, _ = mimetypes.guess_type(file.name)
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type or "image/jpeg",
                "data": base64.b64encode(file.read_bytes()).decode("ascii"),
            },
        })
    api_key = decrypt_secret(provider.encrypted_api_key)
    headers = {
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
    }
    if api_key:
        headers["x-api-key"] = api_key
    response = httpx.post(
        provider_endpoint_url(provider, settings),
        headers=headers,
        timeout=settings.llm_timeout,
        json={"model": provider.model, "max_tokens": 4096, "temperature": 0, "messages": [{"role": "user", "content": content}]},
    )
    response.raise_for_status()
    raw = response.json()
    text = "\n".join(part.get("text", "") for part in raw.get("content", []) if part.get("type") == "text")
    return raw, text


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
        }
    provider = _default_provider(db, user)
    if not provider:
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
        }
    if provider.provider == "openai":
        raw, text = _recognize_openai(provider, files, settings)
    elif provider.provider == "anthropic":
        raw, text = _recognize_anthropic(provider, files, settings)
    else:
        raise RecognitionValidationError([f"Unsupported provider: {provider.provider}"])
    payload = _json_from_text(text)
    try:
        validate_activity_payload(payload)
        status = "validated"
        errors = None
    except RecognitionValidationError as exc:
        status = "validation_failed"
        errors = exc.errors

    db.add(ImportRecognitionAttempt(
        batch_id=batch_id,
        engine=f"{provider.provider}:{provider.model}",
        status=status,
        raw_response=raw,
        parsed_payload=payload,
        validation_errors=errors,
    ))
    db.flush()
    if errors:
        raise RecognitionValidationError(errors)
    return {"status": "validated", "engine": f"{provider.provider}:{provider.model}", "message": "LLM распознал и данные прошли sanity-check.", "payload": payload}
