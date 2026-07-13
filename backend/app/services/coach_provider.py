from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Callable

import httpx
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.models import CoachLlmAttempt, LlmProviderSetting, User
from app.schemas.coach import ProviderCoachOutput
from app.services.llm_providers import anthropic_message_text, openai_chat_completion_text, pinned_provider_request, provider_endpoint_url
from app.services.secrets import decrypt_secret


def active_providers(db: Session, user: User) -> list[LlmProviderSetting]:
    return list(db.scalars(select(LlmProviderSetting).where(LlmProviderSetting.user_id == user.id, LlmProviderSetting.is_active.is_(True)).order_by(LlmProviderSetting.is_default.desc(), LlmProviderSetting.created_at.desc(), LlmProviderSetting.id.desc())))


def _fingerprint(value: object) -> str:
    return hashlib.sha256(json.dumps(value, default=str, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _request(provider: LlmProviderSetting, prompt: dict[str, Any]) -> str:
    settings = get_settings()
    key = decrypt_secret(provider.encrypted_api_key)
    endpoint = provider_endpoint_url(provider, settings)
    if provider.provider == "anthropic":
        payload = {"model": provider.model, "max_tokens": settings.coach_llm_max_tokens, "temperature": 0, "system": prompt["system"], "messages": [{"role": "user", "content": prompt["user"]}]}
        headers = {"x-api-key": key or "", "anthropic-version": "2023-06-01"}
    else:
        payload = {"model": provider.model, "temperature": 0, "max_tokens": settings.coach_llm_max_tokens, "response_format": {"type": "json_object"}, "messages": [{"role": "system", "content": prompt["system"]}, {"role": "user", "content": prompt["user"]}]}
        headers = {"Authorization": f"Bearer {key or ''}"}
    response = pinned_provider_request(
        endpoint,
        allow_private=settings.allow_private_llm_base_urls,
        json=payload,
        headers=headers,
        timeout=settings.coach_llm_timeout,
    )
    response.raise_for_status()
    raw = response.json()
    return anthropic_message_text(raw) if provider.provider == "anthropic" else openai_chat_completion_text(raw)


def request_coach_output(db: Session, user: User, conversation_id: str, message_id: int, prompt: dict[str, Any], validator: Callable[[ProviderCoachOutput], bool] | None = None) -> tuple[ProviderCoachOutput | None, int, str | None, str | None]:
    attempts = 0
    for provider in active_providers(db, user):
        requests = [
            ("initial", prompt),
            ("repair", {**prompt, "user": prompt["user"] + "\nYour previous output was invalid. Return only a valid JSON object matching the contract."}),
        ]
        for phase, request_prompt in requests:
            started = datetime.now(UTC)
            raw: str | None = None
            errors: list[dict[str, str]] | None = None
            failure: str | None = None
            attempts += 1
            try:
                raw = _request(provider, request_prompt)
                output = ProviderCoachOutput.model_validate_json(raw)
                if validator is not None and not validator(output):
                    failure = "safety"
                    errors = [{"message": "Coach safety validation rejected output"}]
                else:
                    failure = None
            except ValidationError as exc:
                failure = "schema"
                errors = [{"message": str(item.get("msg", "invalid output"))} for item in exc.errors()]
            except ValueError:
                failure = "schema"
                errors = [{"message": "Provider JSON did not match the contract"}]
            except httpx.TimeoutException:
                failure = "timeout"
            except httpx.HTTPStatusError:
                failure = "http"
            except httpx.RequestError:
                failure = "request"
            except Exception:
                failure = "provider"
            completed = datetime.now(UTC)
            db.add(CoachLlmAttempt(
                user_id=user.id,
                conversation_id=conversation_id,
                message_id=message_id,
                provider=provider.provider,
                provider_id=provider.id,
                model=provider.model,
                attempt_number=attempts,
                request_phase=phase,
                status="failed" if failure else "success",
                failure_class=failure,
                started_at=started,
                completed_at=completed,
                duration_ms=int((completed - started).total_seconds() * 1000),
                request_fingerprint=_fingerprint(request_prompt),
                output_fingerprint=_fingerprint(raw) if raw else None,
                validation_errors=errors,
            ))
            db.commit()
            if failure is None:
                return output, attempts, provider.provider, provider.model
            if failure != "schema" or phase == "repair":
                break
    return None, attempts, None, None
