import hmac
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.services.auth import create_telegram_login_code, get_or_create_telegram_user_from_profile


_bot_username_cache: str | None = None


def validate_telegram_webhook_secret(received_secret: str | None) -> None:
    settings = get_settings()
    expected_secret = settings.telegram_webhook_secret
    if not expected_secret:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Telegram webhook secret is not configured")
    if not received_secret or not hmac.compare_digest(received_secret, expected_secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Telegram webhook secret")


def build_frontend_login_url(code: str) -> str:
    settings = get_settings()
    parts = urlsplit(settings.frontend_url)
    path = parts.path.rstrip("/") + "/"
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["telegram_login_code"] = code
    return urlunsplit((parts.scheme, parts.netloc, path, urlencode(query), parts.fragment))


def telegram_bot_start_url() -> str | None:
    if not get_settings().telegram_bot_token:
        return None
    username = _get_bot_username()
    if not username:
        return None
    return f"https://t.me/{username}?start=login"


def handle_telegram_webhook_update(db: Session, update: dict[str, Any]) -> None:
    message = update.get("message")
    if not isinstance(message, dict):
        return
    sender = message.get("from")
    chat = message.get("chat")
    if not isinstance(sender, dict) or not isinstance(chat, dict) or sender.get("is_bot"):
        return
    chat_id = chat.get("id")
    telegram_id = sender.get("id")
    if not chat_id or not telegram_id:
        return
    text = str(message.get("text") or "").strip()
    if not text.startswith("/start"):
        _send_message(chat_id, "Нажмите /start, чтобы зарегистрироваться в Runforfan.")
        return

    user = get_or_create_telegram_user_from_profile(
        db,
        telegram_id=int(telegram_id),
        username=sender.get("username"),
        first_name=sender.get("first_name"),
        last_name=sender.get("last_name"),
    )
    code = create_telegram_login_code(db, user, int(telegram_id))
    login_url = build_frontend_login_url(code)
    _send_message(
        chat_id,
        "Вы зарегистрированы в Runforfan. Нажмите кнопку ниже, чтобы открыть приложение. Ссылка действует 5 минут.",
        reply_markup={"inline_keyboard": [[{"text": "Открыть Runforfan", "url": login_url}]]},
    )


def _bot_api_url(method: str) -> str:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Telegram bot token is not configured")
    return f"https://api.telegram.org/bot{settings.telegram_bot_token}/{method}"


def _get_bot_username() -> str | None:
    global _bot_username_cache
    if _bot_username_cache:
        return _bot_username_cache
    try:
        response = httpx.post(_bot_api_url("getMe"), proxy=get_settings().telegram_bot_proxy_url, timeout=10)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Telegram Bot API request failed") from exc
    if not response.is_success:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Telegram Bot API request failed")
    payload = response.json()
    if not payload.get("ok"):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Telegram Bot API returned an error")
    username = payload.get("result", {}).get("username")
    if not username:
        return None
    _bot_username_cache = str(username)
    return _bot_username_cache


def _send_message(chat_id: int | str, text: str, reply_markup: dict[str, Any] | None = None) -> None:
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        response = httpx.post(_bot_api_url("sendMessage"), json=payload, proxy=get_settings().telegram_bot_proxy_url, timeout=10)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Telegram Bot API request failed") from exc
    if not response.is_success:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Telegram Bot API request failed")
    body = response.json()
    if not body.get("ok"):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Telegram Bot API returned an error")
