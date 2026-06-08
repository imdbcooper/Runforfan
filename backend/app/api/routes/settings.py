from time import perf_counter

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.db.session import get_db
from app.models import LlmProviderSetting, User
from app.schemas.common import LlmProviderCreate, LlmProviderOut, LlmProviderTestOut, LlmProviderUpdate
from app.services.auth import get_current_user
from app.services.llm_providers import provider_endpoint_url, provider_supports_vision
from app.services.secrets import decrypt_secret, encrypt_secret


router = APIRouter(prefix="/settings", tags=["settings"])


def provider_out(provider: LlmProviderSetting) -> LlmProviderOut:
    return LlmProviderOut(
        id=provider.id,
        provider=provider.provider,
        display_name=provider.display_name,
        base_url=provider.base_url,
        model=provider.model,
        is_default=provider.is_default,
        is_active=provider.is_active,
        has_api_key=bool(provider.encrypted_api_key),
        supports_vision=provider_supports_vision(provider),
        created_at=provider.created_at,
    )


def provider_for_user(db: Session, user: User, provider_id: int) -> LlmProviderSetting:
    provider = db.scalar(select(LlmProviderSetting).where(
        LlmProviderSetting.id == provider_id,
        LlmProviderSetting.user_id == user.id,
        LlmProviderSetting.is_active.is_(True),
    ))
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    return provider


def ensure_default_provider(db: Session, user_id: int, exclude_provider_id: int | None = None) -> LlmProviderSetting | None:
    providers = list(db.scalars(
        select(LlmProviderSetting)
        .where(LlmProviderSetting.user_id == user_id, LlmProviderSetting.is_active.is_(True))
        .order_by(LlmProviderSetting.created_at.desc())
    ))
    if not providers:
        return None
    current = next((provider for provider in providers if provider.is_default), None)
    if current:
        for provider in providers:
            provider.is_default = provider.id == current.id
        return current
    candidates = [provider for provider in providers if provider.id != exclude_provider_id] or providers
    selected = candidates[0]
    for provider in providers:
        provider.is_default = provider.id == selected.id
    return selected


def test_openai_provider(provider: LlmProviderSetting, endpoint: str, timeout: int) -> None:
    headers = {"Content-Type": "application/json"}
    api_key = decrypt_secret(provider.encrypted_api_key)
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    response = httpx.post(
        endpoint,
        headers=headers,
        timeout=timeout,
        json={
            "model": provider.model,
            "messages": [{"role": "user", "content": "Reply with exactly: ok"}],
            "max_tokens": 8,
            "temperature": 0,
        },
    )
    response.raise_for_status()


def test_anthropic_provider(provider: LlmProviderSetting, endpoint: str, timeout: int) -> None:
    api_key = decrypt_secret(provider.encrypted_api_key)
    headers = {"Content-Type": "application/json", "anthropic-version": "2023-06-01"}
    if api_key:
        headers["x-api-key"] = api_key
    response = httpx.post(
        endpoint,
        headers=headers,
        timeout=timeout,
        json={
            "model": provider.model,
            "max_tokens": 8,
            "temperature": 0,
            "messages": [{"role": "user", "content": "Reply with exactly: ok"}],
        },
    )
    response.raise_for_status()


def test_provider_connection(provider: LlmProviderSetting) -> LlmProviderTestOut:
    started = perf_counter()
    try:
        settings = get_settings()
        endpoint = provider_endpoint_url(provider, settings)
        if provider.provider == "openai":
            test_openai_provider(provider, endpoint, settings.llm_timeout)
        elif provider.provider == "anthropic":
            test_anthropic_provider(provider, endpoint, settings.llm_timeout)
        else:
            raise ValueError(f"Unsupported provider: {provider.provider}")
    except Exception as exc:
        return LlmProviderTestOut(
            ok=False,
            status="failed",
            provider=provider.provider,
            model=provider.model,
            response_ms=round((perf_counter() - started) * 1000),
            supports_vision=provider_supports_vision(provider),
            message=str(exc)[:500],
        )
    return LlmProviderTestOut(
        ok=True,
        status="ok",
        provider=provider.provider,
        model=provider.model,
        response_ms=round((perf_counter() - started) * 1000),
        supports_vision=provider_supports_vision(provider),
        message="Safe prompt completed successfully.",
    )


@router.get("/llm-providers", response_model=list[LlmProviderOut])
def list_llm_providers(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    providers = list(db.scalars(
        select(LlmProviderSetting)
        .where(LlmProviderSetting.user_id == user.id, LlmProviderSetting.is_active.is_(True))
        .order_by(LlmProviderSetting.is_default.desc(), LlmProviderSetting.created_at.desc())
    ))
    return [provider_out(provider) for provider in providers]


@router.post("/llm-providers", response_model=LlmProviderOut)
def create_llm_provider(payload: LlmProviderCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    has_active_provider = db.scalar(select(LlmProviderSetting.id).where(LlmProviderSetting.user_id == user.id, LlmProviderSetting.is_active.is_(True)).limit(1)) is not None
    is_default = bool(payload.is_default or not has_active_provider)
    if is_default:
        db.execute(update(LlmProviderSetting).where(LlmProviderSetting.user_id == user.id).values(is_default=False))
    provider = LlmProviderSetting(
        user_id=user.id,
        provider=payload.provider,
        display_name=payload.display_name,
        base_url=payload.base_url,
        model=payload.model,
        encrypted_api_key=encrypt_secret(payload.api_key),
        is_default=is_default,
    )
    db.add(provider)
    db.commit()
    db.refresh(provider)
    return provider_out(provider)


@router.post("/llm-providers/{provider_id}/default", response_model=LlmProviderOut)
def set_default_provider(provider_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    provider = provider_for_user(db, user, provider_id)
    db.execute(update(LlmProviderSetting).where(LlmProviderSetting.user_id == user.id).values(is_default=False))
    provider.is_default = True
    db.commit()
    db.refresh(provider)
    return provider_out(provider)


@router.patch("/llm-providers/{provider_id}", response_model=LlmProviderOut)
def update_llm_provider(provider_id: int, payload: LlmProviderUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    provider = provider_for_user(db, user, provider_id)
    updates = payload.model_dump(exclude_unset=True)
    if "display_name" in updates:
        if updates["display_name"] is not None:
            provider.display_name = updates["display_name"]
    if "base_url" in updates:
        provider.base_url = updates["base_url"] or None
    if "model" in updates and updates["model"]:
        provider.model = updates["model"]
    if "api_key" in updates:
        provider.encrypted_api_key = encrypt_secret(updates["api_key"])
    if updates.get("is_default") is True:
        db.execute(update(LlmProviderSetting).where(LlmProviderSetting.user_id == user.id).values(is_default=False))
        provider.is_default = True
    elif updates.get("is_default") is False:
        provider.is_default = False
        ensure_default_provider(db, user.id, exclude_provider_id=provider.id)
    db.commit()
    db.refresh(provider)
    return provider_out(provider)


@router.post("/llm-providers/{provider_id}/test", response_model=LlmProviderTestOut)
def test_llm_provider(provider_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    provider = provider_for_user(db, user, provider_id)
    return test_provider_connection(provider)


@router.delete("/llm-providers/{provider_id}")
def delete_llm_provider(provider_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    provider = provider_for_user(db, user, provider_id)
    provider.is_active = False
    provider.is_default = False
    ensure_default_provider(db, user.id, exclude_provider_id=provider.id)
    db.commit()
    return {"deleted": True, "id": provider_id}
