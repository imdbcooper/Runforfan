from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import LlmProviderSetting, User
from app.schemas.common import LlmProviderCreate, LlmProviderOut
from app.services.auth import get_current_user
from app.services.secrets import encrypt_secret


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
        created_at=provider.created_at,
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
    if payload.is_default:
        db.execute(update(LlmProviderSetting).where(LlmProviderSetting.user_id == user.id).values(is_default=False))
    provider = LlmProviderSetting(
        user_id=user.id,
        provider=payload.provider,
        display_name=payload.display_name,
        base_url=payload.base_url,
        model=payload.model,
        encrypted_api_key=encrypt_secret(payload.api_key),
        is_default=payload.is_default,
    )
    db.add(provider)
    db.commit()
    db.refresh(provider)
    return provider_out(provider)


@router.post("/llm-providers/{provider_id}/default", response_model=LlmProviderOut)
def set_default_provider(provider_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    provider = db.scalar(select(LlmProviderSetting).where(LlmProviderSetting.id == provider_id, LlmProviderSetting.user_id == user.id))
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    db.execute(update(LlmProviderSetting).where(LlmProviderSetting.user_id == user.id).values(is_default=False))
    provider.is_default = True
    db.commit()
    db.refresh(provider)
    return provider_out(provider)


@router.delete("/llm-providers/{provider_id}")
def delete_llm_provider(provider_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    provider = db.scalar(select(LlmProviderSetting).where(LlmProviderSetting.id == provider_id, LlmProviderSetting.user_id == user.id))
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    provider.is_active = False
    db.commit()
    return {"deleted": True, "id": provider_id}
