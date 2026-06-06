import base64
import json
import mimetypes
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.models import ImportRecognitionAttempt, LlmProviderSetting, User
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


def _recognize_openai(provider: LlmProviderSetting, files: list[Path], settings: Settings) -> tuple[dict, str]:
    content = [{"type": "text", "text": "Extract running workout data. Return strict JSON with activity, segments and split_blocks."}]
    for file in files[:6]:
        media_type, _ = mimetypes.guess_type(file.name)
        encoded = base64.b64encode(file.read_bytes()).decode("ascii")
        content.append({"type": "image_url", "image_url": {"url": f"data:{media_type or 'image/jpeg'};base64,{encoded}"}})
    headers = {"Content-Type": "application/json"}
    api_key = decrypt_secret(provider.encrypted_api_key)
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    response = httpx.post(
        provider.base_url or "https://api.openai.com/v1/chat/completions",
        headers=headers,
        timeout=settings.llm_timeout,
        json={"model": provider.model, "messages": [{"role": "user", "content": content}], "temperature": 0},
    )
    response.raise_for_status()
    raw = response.json()
    return raw, raw["choices"][0]["message"]["content"]


def _recognize_anthropic(provider: LlmProviderSetting, files: list[Path], settings: Settings) -> tuple[dict, str]:
    content = [{"type": "text", "text": "Extract running workout data. Return strict JSON with activity, segments and split_blocks."}]
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
        provider.base_url or "https://api.anthropic.com/v1/messages",
        headers=headers,
        timeout=settings.llm_timeout,
        json={"model": provider.model, "max_tokens": 4096, "temperature": 0, "messages": [{"role": "user", "content": content}]},
    )
    response.raise_for_status()
    raw = response.json()
    text = "\n".join(part.get("text", "") for part in raw.get("content", []) if part.get("type") == "text")
    return raw, text


def llm_or_template_recognize(db: Session, batch_id: int, files: list[Path], settings: Settings, user: User) -> dict:
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
