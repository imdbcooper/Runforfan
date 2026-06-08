import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.db.session import get_db
from app.models import AuthSession, User


TELEGRAM_LOGIN_MAX_AGE_SECONDS = 86400
TELEGRAM_LOGIN_FUTURE_SKEW_SECONDS = 300


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(48)
    session = AuthSession(
        user_id=user.id,
        token_hash=token_hash(token),
        expires_at=datetime.now(timezone.utc) + timedelta(days=90),
    )
    db.add(session)
    db.commit()
    return token


def get_or_create_demo_user(db: Session) -> User:
    user = db.scalar(select(User).where(User.is_demo.is_(True)))
    if user:
        return user
    user = User(display_name="Demo Runner", username="demo", is_demo=True, is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def validate_telegram_login(payload: dict[str, str], now: datetime | None = None) -> bool:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise HTTPException(status_code=400, detail="RUNFORFAN_TELEGRAM_BOT_TOKEN is not configured")
    received_hash = payload.get("hash")
    if not received_hash:
        return False
    try:
        auth_time = datetime.fromtimestamp(int(payload.get("auth_date", "")), timezone.utc)
    except (TypeError, ValueError, OSError):
        return False
    current_time = now or datetime.now(timezone.utc)
    if auth_time > current_time + timedelta(seconds=TELEGRAM_LOGIN_FUTURE_SKEW_SECONDS):
        return False
    if current_time - auth_time > timedelta(seconds=TELEGRAM_LOGIN_MAX_AGE_SECONDS):
        return False
    data_check = "\n".join(f"{key}={value}" for key, value in sorted(payload.items()) if key != "hash")
    secret = hashlib.sha256(settings.telegram_bot_token.encode("utf-8")).digest()
    calculated = hmac.new(secret, data_check.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(calculated, received_hash)


def get_or_create_telegram_user(db: Session, payload: dict[str, str]) -> User:
    telegram_id = int(payload["id"])
    user = db.scalar(select(User).where(User.telegram_id == telegram_id))
    if user:
        user.username = payload.get("username")
        user.first_name = payload.get("first_name")
        user.last_name = payload.get("last_name")
        user.display_name = payload.get("first_name") or payload.get("username") or user.display_name
        db.commit()
        db.refresh(user)
        return user
    user = User(
        telegram_id=telegram_id,
        username=payload.get("username"),
        first_name=payload.get("first_name"),
        last_name=payload.get("last_name"),
        display_name=payload.get("first_name") or payload.get("username") or "Runner",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required")
    token = authorization.split(" ", 1)[1].strip()
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash(token)))
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    expires_at = session.expires_at
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at and expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    return session.user
