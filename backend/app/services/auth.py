import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.db.session import get_db
from app.models import AuthSession, TelegramLoginCode, User


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
    return get_or_create_telegram_user_from_profile(
        db,
        telegram_id=int(payload["id"]),
        username=payload.get("username"),
        first_name=payload.get("first_name"),
        last_name=payload.get("last_name"),
    )


def clean_telegram_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def telegram_display_name(
    first_name: str | None,
    last_name: str | None,
    username: str | None,
    fallback: str = "Runner",
) -> str:
    name_parts = [part for part in (clean_telegram_text(first_name), clean_telegram_text(last_name)) if part]
    full_name = " ".join(name_parts).strip()
    if full_name:
        return full_name
    return clean_telegram_text(username) or fallback


def get_or_create_telegram_user_from_profile(
    db: Session,
    *,
    telegram_id: int,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
) -> User:
    username = clean_telegram_text(username)
    first_name = clean_telegram_text(first_name)
    last_name = clean_telegram_text(last_name)
    user = db.scalar(select(User).where(User.telegram_id == telegram_id))
    if user:
        user.username = username
        user.first_name = first_name
        user.last_name = last_name
        user.display_name = telegram_display_name(first_name, last_name, username, user.display_name)
        db.commit()
        db.refresh(user)
        return user
    user = User(
        telegram_id=telegram_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
        display_name=telegram_display_name(first_name, last_name, username),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_telegram_login_code(db: Session, user: User, telegram_id: int) -> str:
    settings = get_settings()
    code = secrets.token_urlsafe(32)
    login_code = TelegramLoginCode(
        user_id=user.id,
        telegram_id=telegram_id,
        code_hash=token_hash(code),
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=settings.telegram_login_code_ttl_seconds),
    )
    db.add(login_code)
    db.commit()
    return code


def consume_telegram_login_code(db: Session, code: str) -> User:
    current_time = datetime.now(timezone.utc)
    login_code = db.scalar(
        select(TelegramLoginCode)
        .where(TelegramLoginCode.code_hash == token_hash(code))
        .with_for_update()
    )
    if not login_code or login_code.used_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Telegram login code")
    expires_at = login_code.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < current_time:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Telegram login code expired")
    login_code.used_at = current_time
    db.commit()
    db.refresh(login_code.user)
    return login_code.user


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
