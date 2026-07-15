import hashlib
import logging
import secrets
import time as time_module
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import String, exists, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.models import Activity, CoachDelivery, CoachDeliveryAttempt, CoachDeliveryPreference, CoachingEvent, TrainingPlanWorkout, User
from app.services.athlete_state import materialize_athlete_state
from app.services.audit import log_audit_event
from app.services.readiness import daily_readiness_for_today
from app.services.telegram_bot import TelegramDeliveryClient, TelegramDeliveryError, telegram_bot_start_url
from app.services.weekly_review import materialize_weekly_review


logger = logging.getLogger(__name__)
DAILY_BRIEF_RULE_VERSION = "coach-daily-brief-v1"
POST_WORKOUT_RULE_VERSION = "coach-post-workout-v1"
WEEKLY_REVIEW_DELIVERY_RULE_VERSION = "coach-weekly-review-v1"
_STALE_SENDING_AFTER = timedelta(minutes=10)
_POST_WORKOUT_GRACE = timedelta(minutes=10)
_POST_WORKOUT_FRESHNESS = timedelta(hours=24)
_TEMPLATES = {
    "checkin_required": "Доброе утро. Перед сегодняшней тренировкой заполните короткий check-in, чтобы проверить готовность к нагрузке.",
    "proceed": "Доброе утро. По сегодняшнему check-in тренировку можно выполнить по плану. Следите за самочувствием во время занятия.",
    "conservative": "Доброе утро. Сегодня выберите более консервативный вариант тренировки и не пытайтесь компенсировать объём позже.",
    "rest": "Доброе утро. Сегодня восстановление важнее плана. Откажитесь от беговой нагрузки; допустима только спокойная активность без боли и утомления.",
    "stop": "Доброе утро. Сегодня не начинайте тренировку. При ухудшении самочувствия обратитесь к квалифицированному специалисту.",
    "workout_completed": "Тренировка сохранена. Проверьте итог и добавьте короткую обратную связь в приложении: это поможет следующей детерминированной оценке, но не изменит план автоматически.",
    "workout_feedback_saved": "Тренировка и структурированная обратная связь сохранены. Следующая оценка плана остаётся только рекомендацией до отдельного подтверждения в приложении.",
    "activity_imported": "Новая активность импортирована. Проверьте привязку и детерминированную оценку в приложении; импорт сам по себе не меняет тренировочный план.",
    "historical_activity_imported": "Историческая активность импортирована. Она учтена как новый факт, но сообщение не интерпретирует её как только что завершённую тренировку и не меняет план.",
    "weekly_partial": "Недельный обзор готов, но историческое покрытие неполное. Пропуски данных не считаются признаком готовности к увеличению нагрузки.",
    "weekly_hold": "Недельный обзор готов. Детерминированная стратегия рекомендует сохранить нагрузку без попытки компенсировать пропущенный объём.",
    "weekly_deload": "Недельный обзор готов. Текущие safety- или recovery-сигналы поддерживают снижение нагрузки; изменение плана возможно только после отдельного preview и подтверждения.",
    "weekly_resume": "Недельный обзор готов. Возврат допускается только к прежнему безопасному уровню и требует отдельного preview и подтверждения.",
    "weekly_progression": "Недельный обзор готов. Доступна ограниченная консервативная прогрессия, но план не изменён и требует отдельного preview и подтверждения.",
}
_DISCLAIMER = "Это автоматическая тренировочная подсказка, а не медицинская рекомендация."


def _timezone(user: User) -> str:
    value = user.athlete_profile.timezone if user.athlete_profile and user.athlete_profile.timezone else "Europe/Moscow"
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError:
        return "Europe/Moscow"
    return value


def _local_schedule(local_date: date, local_time: time, timezone: str) -> datetime:
    zone = ZoneInfo(timezone)
    candidate = datetime.combine(local_date, local_time, zone)
    # Normalize a nonexistent DST wall time to the first valid local minute.
    # Ambiguous fold times deterministically use fold=0, Python's default.
    for _ in range(181):
        roundtrip = candidate.astimezone(UTC).astimezone(zone)
        if roundtrip.date() == candidate.date() and roundtrip.time().replace(tzinfo=None) == candidate.time().replace(tzinfo=None):
            return candidate.astimezone(UTC)
        candidate += timedelta(minutes=1)
    raise ValueError("Could not resolve local delivery time")


def preference_response(user: User, preference: CoachDeliveryPreference | None) -> dict[str, object]:
    settings = get_settings()
    available = bool(settings.coach_delivery_enabled)
    post_workout_available = available and bool(getattr(settings, "coach_post_workout_delivery_enabled", False))
    weekly_review_available = available and bool(getattr(settings, "coach_weekly_review_delivery_enabled", False))
    linked = bool(preference and preference.telegram_chat_id is not None and preference.telegram_chat_verified_at is not None)
    bot_url = None
    if available:
        try:
            bot_url = telegram_bot_start_url()
        except HTTPException:
            pass
    return {
        "available": available,
        "linked": linked,
        "enabled": bool(preference and preference.telegram_enabled),
        "post_workout_available": post_workout_available,
        "post_workout_enabled": bool(preference and preference.post_workout_enabled),
        "weekly_review_available": weekly_review_available,
        "weekly_review_enabled": bool(preference and preference.weekly_review_enabled),
        "daily_brief_local_time": preference.daily_brief_local_time if preference else time(8),
        "weekly_review_local_time": preference.weekly_review_local_time if preference else time(8),
        "timezone": _timezone(user),
        "bot_url": bot_url,
    }


def update_preference(
    db: Session,
    user: User,
    *,
    telegram_enabled: bool | None,
    daily_brief_local_time: object | None,
    post_workout_enabled: bool | None = None,
    weekly_review_enabled: bool | None = None,
    weekly_review_local_time: object | None = None,
) -> CoachDeliveryPreference:
    settings = get_settings()
    delivery_available = settings.coach_delivery_enabled
    has_schedule_update = daily_brief_local_time is not None or weekly_review_local_time is not None
    if not delivery_available and (has_schedule_update or any(value is not None and value is not False for value in (telegram_enabled, post_workout_enabled, weekly_review_enabled))):
        raise HTTPException(status_code=403, detail={"code": "coach_delivery_unavailable", "message": "Coach delivery is not available"})
    if post_workout_enabled is True and not getattr(settings, "coach_post_workout_delivery_enabled", False):
        raise HTTPException(status_code=403, detail={"code": "coach_post_workout_delivery_unavailable", "message": "Post-workout delivery is not available"})
    if (weekly_review_enabled is True or weekly_review_local_time is not None) and not getattr(settings, "coach_weekly_review_delivery_enabled", False):
        raise HTTPException(status_code=403, detail={"code": "coach_weekly_review_delivery_unavailable", "message": "Weekly Review delivery is not available"})
    preference = db.scalar(select(CoachDeliveryPreference).where(CoachDeliveryPreference.user_id == user.id).with_for_update())
    if preference is None:
        preference = CoachDeliveryPreference(user_id=user.id)
        db.add(preference)
        db.flush()
    if daily_brief_local_time is not None and delivery_available:
        preference.daily_brief_local_time = daily_brief_local_time
    if weekly_review_local_time is not None and delivery_available:
        preference.weekly_review_local_time = weekly_review_local_time
    if any(value is True for value in (telegram_enabled, post_workout_enabled, weekly_review_enabled)):
        if preference.telegram_chat_id is None or preference.telegram_chat_verified_at is None:
            raise HTTPException(status_code=409, detail={"code": "telegram_chat_not_verified", "message": "Start the bot in a private chat before enabling delivery"})
    now = datetime.now(UTC)
    if telegram_enabled is True:
        preference.telegram_enabled = True
        preference.enabled_at = now
        preference.disabled_at = None
        log_audit_event(db, user.id, "coach_delivery.enabled", "coach_delivery_preference", preference.id, {"channel": "telegram", "delivery_type": "daily_brief"})
    elif telegram_enabled is False:
        preference.telegram_enabled = False
        preference.disabled_at = now
        log_audit_event(db, user.id, "coach_delivery.disabled", "coach_delivery_preference", preference.id, {"channel": "telegram", "delivery_type": "daily_brief"})
    if post_workout_enabled is not None:
        was_post_workout_enabled = preference.post_workout_enabled
        preference.post_workout_enabled = post_workout_enabled
        if post_workout_enabled and not was_post_workout_enabled:
            preference.post_workout_enabled_at = now
        elif not post_workout_enabled:
            preference.post_workout_enabled_at = None
        log_audit_event(db, user.id, "coach_delivery.enabled" if post_workout_enabled else "coach_delivery.disabled", "coach_delivery_preference", preference.id, {"channel": "telegram", "delivery_type": "post_workout_debrief"})
    if weekly_review_enabled is not None:
        was_weekly_review_enabled = preference.weekly_review_enabled
        preference.weekly_review_enabled = weekly_review_enabled
        if weekly_review_enabled and not was_weekly_review_enabled:
            preference.weekly_review_enabled_at = now
        elif not weekly_review_enabled:
            preference.weekly_review_enabled_at = None
        log_audit_event(db, user.id, "coach_delivery.enabled" if weekly_review_enabled else "coach_delivery.disabled", "coach_delivery_preference", preference.id, {"channel": "telegram", "delivery_type": "weekly_review"})
    if has_schedule_update and delivery_available:
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
    existing = db.scalar(select(CoachDelivery.id).where(CoachDelivery.user_id == user.id, CoachDelivery.channel == "telegram", CoachDelivery.delivery_type == "daily_brief", CoachDelivery.local_date == local_date))
    if existing:
        return None
    timezone = _timezone(user)
    scheduled_for = _local_schedule(local_date, preference.daily_brief_local_time, timezone)
    fingerprint_input = "|".join((DAILY_BRIEF_RULE_VERSION, template_key, action, str(workout.get("id")), str(workout.get("title") or ""), str(state.get("input_fingerprint") or "")))
    delivery = CoachDelivery(id=secrets.token_urlsafe(24), user_id=user.id, local_date=local_date, timezone=timezone, rule_version=DAILY_BRIEF_RULE_VERSION, athlete_state_snapshot_id=state.get("snapshot_id"), readiness_checkin_id=(readiness.get("checkin") or {}).get("id") if isinstance(readiness.get("checkin"), dict) else None, workout_id=workout.get("id"), template_key=template_key, content_fingerprint=hashlib.sha256(fingerprint_input.encode()).hexdigest(), scheduled_for=scheduled_for, max_attempts=get_settings().coach_delivery_max_attempts)
    try:
        with db.begin_nested():
            db.add(delivery)
            db.flush()
    except IntegrityError:
        return None
    return delivery


def _post_workout_template(event: CoachingEvent, activity: Activity, workout: TrainingPlanWorkout | None, now: datetime) -> str:
    if event.event_type == "activity_imported":
        occurred_at = event.occurred_at if event.occurred_at.tzinfo else event.occurred_at.replace(tzinfo=UTC)
        return "historical_activity_imported" if now - occurred_at.astimezone(UTC) > _POST_WORKOUT_FRESHNESS else "activity_imported"
    if workout and workout.feedback:
        return "workout_feedback_saved"
    return "workout_completed"


def compose_post_workout_delivery(db: Session, user: User, preference: CoachDeliveryPreference, event: CoachingEvent, now: datetime) -> CoachDelivery | None:
    if event.activity_id is None:
        return None
    activity = db.scalar(select(Activity).where(Activity.id == event.activity_id, Activity.user_id == user.id))
    if activity is None:
        return None
    # Imports and completion events can describe the same activity. The stable
    # activity key permits one debrief, with an import event taking precedence.
    canonical_event = db.scalar(
        select(CoachingEvent)
        .where(CoachingEvent.user_id == user.id, CoachingEvent.activity_id == activity.id, CoachingEvent.event_type == "activity_imported")
        .order_by(CoachingEvent.id.asc())
        .limit(1)
    ) or event
    if event.id != canonical_event.id:
        return None
    if preference.post_workout_enabled_at and canonical_event.created_at < preference.post_workout_enabled_at:
        return None
    occurred_at = canonical_event.occurred_at if canonical_event.occurred_at.tzinfo else canonical_event.occurred_at.replace(tzinfo=UTC)
    if canonical_event.event_type == "workout_completed" and now - occurred_at.astimezone(UTC) > _POST_WORKOUT_FRESHNESS:
        return None
    if canonical_event.event_type == "workout_completed":
        invalidated = db.scalar(
            select(CoachingEvent.id).where(
                CoachingEvent.user_id == user.id,
                CoachingEvent.activity_id == activity.id,
                CoachingEvent.event_type == "workout_completion_removed",
                CoachingEvent.created_at >= canonical_event.created_at,
            ).limit(1)
        )
        if invalidated:
            return None
    workout = db.get(TrainingPlanWorkout, canonical_event.workout_id) if canonical_event.workout_id else None
    if workout and workout.plan.user_id != user.id:
        return None
    template_key = _post_workout_template(canonical_event, activity, workout, now)
    timezone = _timezone(user)
    local_date = occurred_at.astimezone(ZoneInfo(timezone)).date()
    source_key = f"activity:{activity.id}"
    fingerprint_input = "|".join((POST_WORKOUT_RULE_VERSION, source_key, template_key, str(canonical_event.id), str(workout.id if workout else ""), str(activity.distance_km or ""), str(activity.duration_seconds)))
    delivery = CoachDelivery(
        id=secrets.token_urlsafe(24),
        user_id=user.id,
        delivery_type="post_workout_debrief",
        local_date=local_date,
        timezone=timezone,
        rule_version=POST_WORKOUT_RULE_VERSION,
        workout_id=workout.id if workout else None,
        source_key=source_key,
        source_event_id=canonical_event.id,
        activity_id=activity.id,
        template_key=template_key,
        content_fingerprint=hashlib.sha256(fingerprint_input.encode()).hexdigest(),
        scheduled_for=max(now, canonical_event.created_at + _POST_WORKOUT_GRACE),
        max_attempts=get_settings().coach_delivery_max_attempts,
    )
    try:
        with db.begin_nested():
            db.add(delivery)
            db.flush()
    except IntegrityError:
        return None
    return delivery


def _weekly_template(review: dict[str, object]) -> str:
    if review.get("resolution_status") != "complete":
        return "weekly_partial"
    return {
        "hold": "weekly_hold",
        "deload": "weekly_deload",
        "resume": "weekly_resume",
        "conservative_progression": "weekly_progression",
    }.get(str(review.get("recommended_strategy")), "weekly_hold")


def compose_weekly_review_delivery(db: Session, user: User, preference: CoachDeliveryPreference, week_start: date, scheduled_for: datetime, now: datetime) -> CoachDelivery | None:
    try:
        review = materialize_weekly_review(db, user, week_start=week_start, as_of_at=now)
    except (ValueError, RuntimeError) as exc:
        logger.warning("Skipping weekly coach delivery: user_id=%s error_type=%s", user.id, type(exc).__name__)
        return None
    template_key = _weekly_template(review)
    source_key = f"week:{week_start.isoformat()}"
    fingerprint_input = "|".join((WEEKLY_REVIEW_DELIVERY_RULE_VERSION, source_key, template_key, str(review.get("review_id")), str(review.get("input_fingerprint") or "")))
    delivery = CoachDelivery(
        id=secrets.token_urlsafe(24),
        user_id=user.id,
        delivery_type="weekly_review",
        local_date=week_start,
        timezone=_timezone(user),
        rule_version=WEEKLY_REVIEW_DELIVERY_RULE_VERSION,
        source_key=source_key,
        weekly_review_id=int(review["review_id"]),
        template_key=template_key,
        content_fingerprint=hashlib.sha256(fingerprint_input.encode()).hexdigest(),
        scheduled_for=scheduled_for,
        max_attempts=get_settings().coach_delivery_max_attempts,
    )
    try:
        with db.begin_nested():
            db.add(delivery)
            db.flush()
    except IntegrityError:
        return None
    return delivery


def enqueue_due_deliveries(db: Session, now: datetime | None = None) -> int:
    settings = get_settings()
    if not settings.coach_delivery_enabled:
        return 0
    now = now or datetime.now(UTC)
    preferences = list(db.scalars(select(CoachDeliveryPreference).join(User).where(
        or_(CoachDeliveryPreference.telegram_enabled.is_(True), CoachDeliveryPreference.post_workout_enabled.is_(True), CoachDeliveryPreference.weekly_review_enabled.is_(True)),
        CoachDeliveryPreference.telegram_chat_id.is_not(None),
        CoachDeliveryPreference.telegram_chat_verified_at.is_not(None),
    )))
    count = 0
    for preference in preferences:
        timezone = _timezone(preference.user)
        local_now = now.astimezone(ZoneInfo(timezone))
        if preference.telegram_enabled and local_now.time().replace(tzinfo=None) >= preference.daily_brief_local_time:
            if compose_delivery(db, preference.user, preference, now):
                count += 1
        if getattr(settings, "coach_post_workout_delivery_enabled", False) and preference.post_workout_enabled and preference.post_workout_enabled_at:
            delivered_activity = exists().where(
                CoachDelivery.user_id == preference.user_id,
                CoachDelivery.delivery_type == "post_workout_debrief",
                CoachDelivery.source_key == "activity:" + CoachingEvent.activity_id.cast(String),
            )
            events = list(db.scalars(
                select(CoachingEvent).where(
                    CoachingEvent.user_id == preference.user_id,
                    CoachingEvent.event_type.in_(("workout_completed", "activity_imported")),
                    CoachingEvent.activity_id.is_not(None),
                    CoachingEvent.created_at >= preference.post_workout_enabled_at,
                    CoachingEvent.created_at <= now - _POST_WORKOUT_GRACE,
                    ~delivered_activity,
                ).order_by(CoachingEvent.created_at, CoachingEvent.id).limit(settings.coach_delivery_batch_size * 4)
            ))
            for event in events:
                if compose_post_workout_delivery(db, preference.user, preference, event, now):
                    count += 1
        if getattr(settings, "coach_weekly_review_delivery_enabled", False) and preference.weekly_review_enabled and preference.weekly_review_enabled_at:
            current_week_start = local_now.date() - timedelta(days=local_now.weekday())
            week_start = current_week_start - timedelta(days=7)
            scheduled_for = _local_schedule(current_week_start, preference.weekly_review_local_time, timezone)
            if now >= scheduled_for and scheduled_for >= preference.weekly_review_enabled_at:
                if compose_weekly_review_delivery(db, preference.user, preference, week_start, scheduled_for, now):
                    count += 1
    db.commit()
    return count


def claim_due_deliveries(db: Session, worker_id: str, now: datetime | None = None) -> list[CoachDelivery]:
    settings = get_settings()
    if not settings.coach_delivery_enabled:
        return []
    now = now or datetime.now(UTC)
    # A stale send may already have reached Telegram before the worker died.
    # Fail closed instead of retrying an ambiguous external side effect.
    db.query(CoachDelivery).filter(CoachDelivery.status == "sending", CoachDelivery.locked_at < now - _STALE_SENDING_AFTER).update({"status": "permanent_failure", "retry_at": None, "locked_at": None, "locked_by": None}, synchronize_session=False)
    enabled_types = ["daily_brief"]
    if getattr(settings, "coach_post_workout_delivery_enabled", False):
        enabled_types.append("post_workout_debrief")
    if getattr(settings, "coach_weekly_review_delivery_enabled", False):
        enabled_types.append("weekly_review")
    query = select(CoachDelivery).where(
        CoachDelivery.delivery_type.in_(enabled_types),
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
    settings = get_settings()
    type_available = delivery.delivery_type == "daily_brief" or (delivery.delivery_type == "post_workout_debrief" and getattr(settings, "coach_post_workout_delivery_enabled", False)) or (delivery.delivery_type == "weekly_review" and getattr(settings, "coach_weekly_review_delivery_enabled", False))
    if not settings.coach_delivery_enabled or not settings.coach_delivery_worker_enabled or not type_available:
        delivery.status, delivery.locked_at, delivery.locked_by = "pending", None, None
        db.commit()
        return
    # Serialize sends with consent changes. An opt-out is acknowledged only
    # after an already-authorized in-flight send has completed.
    preference = db.scalar(select(CoachDeliveryPreference).where(CoachDeliveryPreference.user_id == delivery.user_id).with_for_update())
    consent = bool(preference and (
        (delivery.delivery_type == "daily_brief" and preference.telegram_enabled)
        or (delivery.delivery_type == "post_workout_debrief" and preference.post_workout_enabled)
        or (delivery.delivery_type == "weekly_review" and preference.weekly_review_enabled)
    ))
    if not preference or not consent or preference.telegram_chat_id is None:
        delivery.status, delivery.locked_at, delivery.locked_by = "cancelled", None, None
        db.commit()
        return
    if delivery.delivery_type == "post_workout_debrief" and delivery.source_event_id:
        source_event = db.get(CoachingEvent, delivery.source_event_id)
        source_activity = db.get(Activity, delivery.activity_id) if delivery.activity_id else None
        if source_event is None or source_activity is None or source_activity.user_id != delivery.user_id:
            delivery.status, delivery.locked_at, delivery.locked_by = "cancelled", None, None
            db.commit()
            return
        if source_event and source_event.event_type == "workout_completed":
            invalidated = db.scalar(
                select(CoachingEvent.id).where(
                    CoachingEvent.user_id == delivery.user_id,
                    CoachingEvent.activity_id == delivery.activity_id,
                    CoachingEvent.event_type == "workout_completion_removed",
                    CoachingEvent.created_at >= source_event.created_at,
                ).limit(1)
            )
            if invalidated:
                delivery.status, delivery.locked_at, delivery.locked_by = "cancelled", None, None
                db.commit()
                return
    if delivery.delivery_type == "weekly_review" and delivery.weekly_review_id is None:
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
            preference.telegram_enabled, preference.post_workout_enabled, preference.weekly_review_enabled = False, False, False
            preference.disabled_at, preference.post_workout_enabled_at, preference.weekly_review_enabled_at = datetime.now(UTC), None, None
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
