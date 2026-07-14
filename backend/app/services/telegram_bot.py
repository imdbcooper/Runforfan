import hmac
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.db.session import SessionLocal
from app.services.auth import create_telegram_login_code, get_or_create_telegram_user_from_profile


logger = logging.getLogger(__name__)
_bot_username_cache: str | None = None
_polling_thread: threading.Thread | None = None
_polling_stop_event = threading.Event()


@dataclass(frozen=True)
class TelegramDeliveryResult:
    http_status: int


class TelegramDeliveryError(Exception):
    def __init__(self, failure_class: str, http_status: int | None = None, retry_after: int | None = None):
        self.failure_class = failure_class
        self.http_status = http_status
        self.retry_after = retry_after
        super().__init__(failure_class)


class TelegramDeliveryClient:
    def send(self, chat_id: int, text: str) -> TelegramDeliveryResult:
        payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True, "reply_markup": {"inline_keyboard": [[{"text": "Открыть Runforfan", "url": get_settings().frontend_url}]]}}
        try:
            url = _bot_api_url("sendMessage")
        except HTTPException as exc:
            raise TelegramDeliveryError("configuration") from exc
        try:
            response = httpx.post(url, json=payload, proxy=get_settings().telegram_bot_proxy_url, timeout=10)
        except httpx.TimeoutException as exc:
            raise TelegramDeliveryError("timeout") from exc
        except httpx.NetworkError as exc:
            raise TelegramDeliveryError("network") from exc
        except httpx.HTTPError as exc:
            raise TelegramDeliveryError("upstream") from exc
        retry_after = None
        try:
            body = response.json()
            parameters = body.get("parameters") if isinstance(body, dict) else None
            if isinstance(parameters, dict) and isinstance(parameters.get("retry_after"), int):
                retry_after = parameters["retry_after"]
        except ValueError:
            body = {}
        if response.status_code == 429:
            raise TelegramDeliveryError("rate_limited", 429, retry_after)
        if response.status_code == 403:
            raise TelegramDeliveryError("forbidden", 403)
        if response.status_code == 400:
            raise TelegramDeliveryError("bad_request", 400)
        if response.status_code >= 500 or not response.is_success or not isinstance(body, dict) or not body.get("ok"):
            raise TelegramDeliveryError("upstream", response.status_code)
        return TelegramDeliveryResult(response.status_code)


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
    try:
        username = _get_bot_username()
    except HTTPException:
        logger.warning("Telegram Bot API getMe failed while building start URL")
        return None
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
    is_private_chat = chat.get("type") == "private"
    if not text.startswith("/start"):
        if is_private_chat:
            _send_message(chat_id, "Нажмите /start, чтобы зарегистрироваться в Runforfan.")
        return

    if not is_private_chat:
        return

    # Telegram private chats use the sender's numeric id as their chat id.
    # Reject malformed updates before provisioning any local account state.
    if int(chat_id) != int(telegram_id):
        logger.warning("Ignoring Telegram private chat with mismatched sender and chat IDs")
        return

    user = get_or_create_telegram_user_from_profile(
        db,
        telegram_id=int(telegram_id),
        username=sender.get("username"),
        first_name=sender.get("first_name"),
        last_name=sender.get("last_name"),
    )
    # Authentication remains available during a closed delivery rollout, but
    # destination metadata is collected only when delivery itself is available.
    if get_settings().coach_delivery_enabled:
        from app.services.coach_delivery import verify_private_telegram_chat
        verify_private_telegram_chat(db, user, int(chat_id), int(telegram_id))
    code = create_telegram_login_code(db, user, int(telegram_id))
    login_url = build_frontend_login_url(code)
    _send_message(
        chat_id,
        "Вы зарегистрированы в Runforfan. Нажмите кнопку ниже, чтобы открыть приложение. Ссылка действует 5 минут.",
        reply_markup={"inline_keyboard": [[{"text": "Открыть Runforfan", "url": login_url}]]},
    )


def start_telegram_polling() -> None:
    settings = get_settings()
    if not settings.telegram_polling_enabled or not settings.telegram_bot_token:
        return
    global _polling_thread
    if _polling_thread and _polling_thread.is_alive():
        return
    _polling_stop_event.clear()
    _polling_thread = threading.Thread(target=_poll_telegram_updates, name="telegram-bot-polling", daemon=True)
    _polling_thread.start()
    logger.info("Telegram Bot API polling started")


def stop_telegram_polling() -> None:
    _polling_stop_event.set()
    if _polling_thread and _polling_thread.is_alive():
        _polling_thread.join(timeout=5)


def _bot_api_url(method: str) -> str:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Telegram bot token is not configured")
    return f"https://api.telegram.org/bot{settings.telegram_bot_token}/{method}"


def _bot_api_post(method: str, payload: dict[str, Any] | None = None, timeout: float = 10) -> dict[str, Any]:
    try:
        response = httpx.post(_bot_api_url(method), json=payload, proxy=get_settings().telegram_bot_proxy_url, timeout=timeout)
    except httpx.HTTPError as exc:
        logger.warning("Telegram Bot API request failed: method=%s error=%s", method, exc.__class__.__name__)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Telegram Bot API request failed") from exc
    try:
        body = response.json()
    except ValueError as exc:
        logger.warning("Telegram Bot API returned non-JSON response: method=%s status=%s", method, response.status_code)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Telegram Bot API request failed") from exc
    if not response.is_success or not body.get("ok"):
        logger.warning(
            "Telegram Bot API returned an error: method=%s status=%s description=%s",
            method,
            response.status_code,
            body.get("description"),
        )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Telegram Bot API returned an error")
    return body


def _get_bot_username() -> str | None:
    global _bot_username_cache
    if _bot_username_cache:
        return _bot_username_cache
    payload = _bot_api_post("getMe")
    username = payload.get("result", {}).get("username")
    if not username:
        return None
    _bot_username_cache = str(username)
    return _bot_username_cache


def _send_message(chat_id: int | str, text: str, reply_markup: dict[str, Any] | None = None) -> None:
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    _bot_api_post("sendMessage", payload)


def _poll_telegram_updates() -> None:
    offset: int | None = None
    try:
        _bot_api_post("deleteWebhook", {"drop_pending_updates": False})
    except HTTPException:
        logger.exception("Telegram polling could not delete webhook before getUpdates")
    while not _polling_stop_event.is_set():
        try:
            for update in _get_updates(offset):
                update_id = update.get("update_id")
                try:
                    with SessionLocal() as db:
                        handle_telegram_webhook_update(db, update)
                except Exception:
                    logger.exception("Telegram polling failed to process update")
                if isinstance(update_id, int):
                    offset = update_id + 1
        except Exception:
            logger.exception("Telegram polling iteration failed")
            time.sleep(get_settings().telegram_polling_error_delay_seconds)


def _get_updates(offset: int | None) -> list[dict[str, Any]]:
    settings = get_settings()
    payload: dict[str, Any] = {"timeout": settings.telegram_polling_timeout_seconds, "allowed_updates": ["message"]}
    if offset is not None:
        payload["offset"] = offset
    response = _bot_api_post("getUpdates", payload, timeout=settings.telegram_polling_timeout_seconds + 10)
    updates = response.get("result")
    if not isinstance(updates, list):
        return []
    return [update for update in updates if isinstance(update, dict)]
