import hashlib
import logging
import secrets
import time as time_module
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.models import CoachDelivery, CoachDeliveryAttempt, CoachDeliveryPreference, User
from app.services.athlete_state import materialize_athlete_state
from app.services.audit import log_audit_event
from app.services.readiness import daily_readiness_for_today
from app.services.telegram_bot import TelegramDeliveryClient, TelegramDeliveryError, telegram_bot_start_url


logger = logging.getLogger(__name__)
DAILY_BRIEF_RULE_VERSION = "coach-daily-brief-v1"
_STALE_SENDING_AFTER = timedelta(minutes=10)
_TEMPLATES = {
    "checkin_required": "Доброе утро. Перед сегодняшней тренировкой заполните короткий check-in, чтобы проверить готовность к нагрузке.",
    "proceed": "Доброе утро. По сегодняшнему check-in тренировку можно выполнить по плану. Следите за самочувствием во время занятия.",
    "conservative": "Доброе утро. Сегодня выберите более консервативный вариант тренировки и не пытайтесь компенсировать объём позже.",
    "rest": "Доброе утро. Сегодня восстановление важнее плана. Откажитесь от беговой нагрузки; допустима только спокойная активность без боли и утомления.",
    "stop": "Доброе утро. Сегодня не начинайте тренировку. При ухудшении самочувствия обратитесь к квалифицированному специалисту.",
}
_DISCLAIMER = "Это автоматическая тренировочная подсказка, а не медицинская рекомендация."


def _timezone(user: User) -> str:
    value = user.athlete_profile.timezone if user.athlete_profile and user.athlete_profile.timezone else "Europe/Moscow"
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError:
        return "Europe/Moscow"
    return value


def preference_response(user: User, preference: CoachDeliveryPreference | None) -> dict[str, object]:
    available = bool(get_settings().coach_delivery_enabled)
    linked = bool(preference and preference.telegram_chat_id is not None and preference.telegram_chat_verified_at is not None)
    bot_url = None
    if available:
        try:
            bot_url = telegram_bot_start_url()
        except HTTPException:
            pass
    return {"available": available, "linked": linked, "enabled": bool(preference and preference.telegram_enabled), "daily_brief_local_time": preference.daily_brief_local_time if preference else datetime.strptime("08:00", "%H:%M").time(), "timezone": _timezone(user), "bot_url": bot_url}


def update_preference(db: Session, user: User, *, telegram_enabled: bool | None, daily_brief_local_time: object | None) -> CoachDeliveryPreference:
    delivery_available = get_settings().coach_delivery_enabled
    if not delivery_available and telegram_enabled is not False:
        raise HTTPException(status_code=403, detail={"code": "coach_delivery_unavailable", "message": "Coach delivery is not available"})
    preference = db.scalar(select(CoachDeliveryPreference).where(CoachDeliveryPreference.user_id == user.id).with_for_update())
    if preference is None:
        preference = CoachDeliveryPreference(user_id=user.id)
        db.add(preference)
        db.flush()
    if daily_brief_local_time is not None and delivery_available:
        preference.daily_brief_local_time = daily_brief_local_time
    if telegram_enabled is True:
        if preference.telegram_chat_id is None or preference.telegram_chat_verified_at is None:
            raise HTTPException(status_code=409, detail={"code": "telegram_chat_not_verified", "message": "Start the bot in a private chat before enabling delivery"})
        preference.telegram_enabled = True
        preference.enabled_at = datetime.now(UTC)
        preference.disabled_at = None
        log_audit_event(db, user.id, "coach_delivery.enabled", "coach_delivery_preference", preference.id, {"channel": "telegram"})
    elif telegram_enabled is False:
        preference.telegram_enabled = False
        preference.disabled_at = datetime.now(UTC)
        log_audit_event(db, user.id, "coach_delivery.disabled", "coach_delivery_preference", preference.id, {"channel": "telegram"})
    elif daily_brief_local_time is not None and delivery_available:
        log_audit_event(db, user.id, "coach_delivery.schedule_updated", "coach_delivery_preference", preference.id, {"channel": "telegram"})
    db.commit()
    db.refresh(preference)
    return preference


def verify_private_telegram_chat(db: Session, user: User, chat_id: int, telegram_id: int) -> None:
    if chat_id != telegram_id or user.telegram_id != telegram_id:
        raise ValueError("Private Telegram destination does not match the authenticated sender")
    preference = db.scalar(select(CoachDeliveryPreference).where(CoachDeliveryPreference.user_id == user.id).with_for_update())
    if preference is None:
        preference = CoachDeliveryPreference(user_id=user.id)
        db.add(preference)
    preference.telegram_chat_id = chat_id
    preference.telegram_chat_verified_at = datetime.now(UTC)
    db.commit()


def _template_key(action: str) -> str | None:
    return {
        "checkin_required": "checkin_required",
        "proceed_as_planned": "proceed",
        "proceed_conservatively": "conservative",
        "easy_replacement": "conservative",
        "rest_or_gentle_mobility": "rest",
        "rest_and_seek_guidance": "stop",
    }.get(action)


def compose_delivery(db: Session, user: User, preference: CoachDeliveryPreference, now: datetime) -> CoachDelivery | None:
    readiness = daily_readiness_for_today(db, user)
    workout = readiness.get("today_workout")
    if not isinstance(workout, dict) or workout.get("status") not in {"planned", "rescheduled"}:
        return None
    state = materialize_athlete_state(db, user)
    recommendation = readiness.get("recommendation") if isinstance(readiness.get("recommendation"), dict) else {}
    action = str(recommendation.get("action") or "checkin_required")
    template_key = _template_key(action)
    if template_key is None:
        logger.warning("Skipping coach delivery with unsupported readiness action: user_id=%s action=%s", user.id, action)
        return None
    local_date = readiness["date"]
    existing = db.scalar(select(CoachDelivery.id).where(CoachDelivery.user_id == user.id, CoachDelivery.channel == "telegram", CoachDelivery.delivery_type == "daily_brief", CoachDelivery.local_date == local_date, CoachDelivery.rule_version == DAILY_BRIEF_RULE_VERSION))
    if existing:
        return None
    timezone = _timezone(user)
    scheduled_for = datetime.combine(local_date, preference.daily_brief_local_time, ZoneInfo(timezone)).astimezone(UTC)
    fingerprint_input = "|".join((DAILY_BRIEF_RULE_VERSION, template_key, action, str(workout.get("id")), str(workout.get("title") or ""), str(state.get("input_fingerprint") or "")))
    delivery = CoachDelivery(id=secrets.token_urlsafe(24), user_id=user.id, local_date=local_date, timezone=timezone, rule_version=DAILY_BRIEF_RULE_VERSION, athlete_state_snapshot_id=state.get("snapshot_id"), readiness_checkin_id=(readiness.get("checkin") or {}).get("id") if isinstance(readiness.get("checkin"), dict) else None, workout_id=workout.get("id"), template_key=template_key, content_fingerprint=hashlib.sha256(fingerprint_input.encode()).hexdigest(), scheduled_for=scheduled_for, max_attempts=get_settings().coach_delivery_max_attempts)
    try:
        with db.begin_nested():
            db.add(delivery)
            db.flush()
    except IntegrityError:
        return None
    return delivery


def enqueue_due_deliveries(db: Session, now: datetime | None = None) -> int:
    if not get_settings().coach_delivery_enabled:
        return 0
    now = now or datetime.now(UTC)
    preferences = list(db.scalars(select(CoachDeliveryPreference).join(User).where(CoachDeliveryPreference.telegram_enabled.is_(True), CoachDeliveryPreference.telegram_chat_id.is_not(None), CoachDeliveryPreference.telegram_chat_verified_at.is_not(None))))
    count = 0
    for preference in preferences:
        timezone = _timezone(preference.user)
        local_now = now.astimezone(ZoneInfo(timezone))
        if local_now.time().replace(tzinfo=None) >= preference.daily_brief_local_time:
            if compose_delivery(db, preference.user, preference, now):
                count += 1
    db.commit()
    return count


def claim_due_deliveries(db: Session, worker_id: str, now: datetime | None = None) -> list[CoachDelivery]:
    if not get_settings().coach_delivery_enabled:
        return []
    now = now or datetime.now(UTC)
    # A stale send may already have reached Telegram before the worker died.
    # Fail closed instead of retrying an ambiguous external side effect.
    db.query(CoachDelivery).filter(CoachDelivery.status == "sending", CoachDelivery.locked_at < now - _STALE_SENDING_AFTER).update({"status": "permanent_failure", "retry_at": None, "locked_at": None, "locked_by": None}, synchronize_session=False)
    query = select(CoachDelivery).where(
        CoachDelivery.status.in_(("pending", "retry_scheduled")),
        CoachDelivery.scheduled_for <= now,
        or_(CoachDelivery.status == "pending", CoachDelivery.retry_at <= now),
        CoachDelivery.attempt_count < CoachDelivery.max_attempts,
    ).order_by(CoachDelivery.scheduled_for, CoachDelivery.id).limit(get_settings().coach_delivery_batch_size).with_for_update(skip_locked=True)
    rows = list(db.scalars(query))
    for row in rows:
        row.status, row.retry_at, row.locked_at, row.locked_by = "sending", None, now, worker_id
    db.commit()
    return rows


def _message(delivery: CoachDelivery) -> str:
    return f"{_TEMPLATES[delivery.template_key]}\n\n{_DISCLAIMER}"


def process_delivery(db: Session, delivery_id: str) -> None:
    delivery = db.scalar(select(CoachDelivery).where(CoachDelivery.id == delivery_id).with_for_update())
    if not delivery or delivery.status != "sending":
        return
    if not get_settings().coach_delivery_enabled:
        delivery.status, delivery.locked_at, delivery.locked_by = "pending", None, None
        db.commit()
        return
    # Serialize sends with consent changes. An opt-out is acknowledged only
    # after an already-authorized in-flight send has completed.
    preference = db.scalar(select(CoachDeliveryPreference).where(CoachDeliveryPreference.user_id == delivery.user_id).with_for_update())
    if not preference or not preference.telegram_enabled or preference.telegram_chat_id is None:
        delivery.status, delivery.locked_at, delivery.locked_by = "cancelled", None, None
        db.commit()
        return
    started = datetime.now(UTC)
    delivery.attempt_count += 1
    try:
        result = TelegramDeliveryClient().send(preference.telegram_chat_id, _message(delivery))
        delivery.status, delivery.sent_at, delivery.locked_at, delivery.locked_by = "sent", datetime.now(UTC), None, None
        db.add(CoachDeliveryAttempt(delivery_id=delivery.id, attempt_number=delivery.attempt_count, status="success", http_status=result.http_status, started_at=started, completed_at=datetime.now(UTC)))
        log_audit_event(db, delivery.user_id, "coach_delivery.sent", "coach_delivery", None, {"delivery_type": delivery.delivery_type, "template_key": delivery.template_key, "attempt": delivery.attempt_count})
    except TelegramDeliveryError as exc:
        # Only Telegram's explicit rate limit is known not to have accepted the
        # message. Network/timeouts/upstream responses are ambiguous and must
        # not be retried because sendMessage has no idempotency key.
        permanent = exc.failure_class != "rate_limited" or delivery.attempt_count >= delivery.max_attempts
        delivery.status, delivery.locked_at, delivery.locked_by = ("permanent_failure" if permanent else "retry_scheduled"), None, None
        delivery.retry_at = None if permanent else datetime.now(UTC) + timedelta(seconds=max(exc.retry_after or 0, get_settings().coach_delivery_retry_base_seconds * (2 ** (delivery.attempt_count - 1))))
        db.add(CoachDeliveryAttempt(delivery_id=delivery.id, attempt_number=delivery.attempt_count, status="permanent_failure" if permanent else "retryable_failure", failure_class=exc.failure_class, http_status=exc.http_status, started_at=started, completed_at=datetime.now(UTC)))
        if exc.failure_class == "forbidden":
            preference.telegram_enabled, preference.disabled_at = False, datetime.now(UTC)
        log_audit_event(db, delivery.user_id, "coach_delivery.failed", "coach_delivery", None, {"failure_class": exc.failure_class, "permanent": permanent, "attempt": delivery.attempt_count})
    except Exception as exc:
        logger.error("Coach delivery transport failed closed: delivery_id=%s error_type=%s", delivery.id, type(exc).__name__)
        delivery.status, delivery.retry_at, delivery.locked_at, delivery.locked_by = "permanent_failure", None, None, None
        db.add(CoachDeliveryAttempt(delivery_id=delivery.id, attempt_number=delivery.attempt_count, status="permanent_failure", failure_class="internal", started_at=started, completed_at=datetime.now(UTC)))
        log_audit_event(db, delivery.user_id, "coach_delivery.failed", "coach_delivery", None, {"failure_class": "internal", "permanent": True, "attempt": delivery.attempt_count})
    db.commit()


def run_once(worker_id: str = "coach-delivery-worker") -> int:
    settings = get_settings()
    if not settings.coach_delivery_enabled or not settings.coach_delivery_worker_enabled:
        return 0
    from app.db.session import SessionLocal
    with SessionLocal() as db:
        enqueue_due_deliveries(db)
        deliveries = claim_due_deliveries(db, worker_id)
        for delivery in deliveries:
            process_delivery(db, delivery.id)
        return len(deliveries)


def run_loop() -> None:
    while True:
        if get_settings().coach_delivery_worker_enabled:
            try:
                run_once()
            except Exception:
                logger.exception("Coach delivery worker iteration failed")
        time_module.sleep(get_settings().coach_delivery_poll_seconds)
