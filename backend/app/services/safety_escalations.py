import hashlib
import json
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.models import AthleteProfile, DailyReadinessCheckIn, SafetyEscalation, SafetyEscalationEvent, User
from app.services.audit import log_audit_event


RULE_VERSION = "safety-escalation-v1"
ACTIVE_STATUSES = ("open", "acknowledged")
_COPY = {
    "red_flag_stop": {
        "title": "Остановитесь и оцените необходимость внешней помощи",
        "guidance": "Не начинайте тренировку. При тревожных или ухудшающихся симптомах обратитесь к квалифицированному специалисту или в местную экстренную службу.",
    },
    "pain_requires_rest": {
        "title": "Беговая нагрузка сегодня остановлена",
        "guidance": "Не начинайте бег и не пытайтесь компенсировать объём. Если боль сохраняется или усиливается, обратитесь к квалифицированному специалисту.",
    },
    "return_to_run_ambiguous": {
        "title": "Возврат к бегу требует внешнего решения",
        "guidance": "Текущие ограничения не позволяют рекомендовать возврат к нагрузке. Обновление check-in или acknowledgement не означает допуска к тренировкам.",
    },
}


class SafetyEscalationConflict(RuntimeError):
    pass


def _fingerprint(payload: dict[str, object]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def classify_escalation(
    profile: AthleteProfile,
    checkin: DailyReadinessCheckIn | None,
    recommendation: dict[str, object],
) -> dict[str, str] | None:
    rule_id = str(recommendation.get("rule_id") or "")
    if rule_id == "profile_injured" or profile.recovery_status == "injured":
        return {"trigger_kind": "return_to_run_ambiguous", "severity": "critical"}
    if rule_id == "pain_or_illness_stop":
        return {"trigger_kind": "red_flag_stop", "severity": "critical"}
    if rule_id == "rest_required" and checkin is not None and checkin.pain:
        return {"trigger_kind": "pain_requires_rest", "severity": "high"}
    return None


def escalation_response(escalation: SafetyEscalation | None) -> dict[str, object]:
    available = bool(get_settings().safety_escalation_enabled)
    if escalation is None:
        return {"available": available, "escalation": None}
    copy = _COPY[escalation.trigger_kind]
    return {
        "available": available,
        "escalation": {
            "id": escalation.id,
            "trigger_kind": escalation.trigger_kind,
            "severity": escalation.severity,
            "status": escalation.status,
            "rule_version": escalation.rule_version,
            "source_rule_id": escalation.source_rule_id,
            "local_date": escalation.local_date,
            "title": copy["title"],
            "guidance": copy["guidance"],
            "acknowledged_at": escalation.acknowledged_at,
            "created_at": escalation.created_at,
            "disclaimer": "Runforfan не является медицинским устройством, не обеспечивает наблюдение или экстренное реагирование и не подтверждает безопасность возврата к тренировкам.",
        },
    }


def _supersede(db: Session, escalation: SafetyEscalation, now: datetime) -> None:
    from app.services.safety_reviews import close_for_supersession

    close_for_supersession(db, escalation, now)
    escalation.status = "superseded"
    escalation.superseded_at = now
    db.add(SafetyEscalationEvent(
        escalation_id=escalation.id,
        user_id=escalation.user_id,
        event_type="superseded",
        actor_kind="system",
        rule_version=RULE_VERSION,
        metadata_json={"previous_status": "acknowledged" if escalation.acknowledged_at else "open"},
        occurred_at=now,
    ))
    log_audit_event(db, escalation.user_id, "safety_escalation.superseded", "safety_escalation", escalation.id, {"rule_version": RULE_VERSION})


def sync_escalation(
    db: Session,
    user: User,
    *,
    local_date: date,
    profile: AthleteProfile,
    checkin: DailyReadinessCheckIn | None,
    recommendation: dict[str, object],
) -> SafetyEscalation | None:
    if not get_settings().safety_escalation_enabled:
        return None
    db.scalar(select(User.id).where(User.id == user.id).with_for_update())
    active = db.scalar(
        select(SafetyEscalation)
        .where(SafetyEscalation.user_id == user.id, SafetyEscalation.status.in_(ACTIVE_STATUSES))
        .with_for_update()
    )
    classification = classify_escalation(profile, checkin, recommendation)
    now = datetime.now(UTC)
    if classification is None:
        if active is not None:
            _supersede(db, active, now)
        return None

    source_rule_version = str(recommendation.get("rule_version") or "unknown")
    source_rule_id = str(recommendation.get("rule_id") or "unknown")
    source_key = f"checkin:{checkin.id}" if checkin is not None else f"profile:{profile.id}"
    if (
        active is not None
        and active.source_key == source_key
        and active.source_rule_version == source_rule_version
        and active.source_rule_id == source_rule_id
        and active.trigger_kind == classification["trigger_kind"]
        and active.severity == classification["severity"]
    ):
        return active
    source_fingerprint = _fingerprint({
        "rule_version": RULE_VERSION,
        "source_rule_version": source_rule_version,
        "source_rule_id": source_rule_id,
        "source_key": source_key,
        "source_updated_at": checkin.updated_at if checkin is not None else profile.updated_at,
        "trigger_kind": classification["trigger_kind"],
    })
    if active is not None:
        _supersede(db, active, now)
        db.flush()

    existing = db.scalar(select(SafetyEscalation).where(SafetyEscalation.user_id == user.id, SafetyEscalation.source_fingerprint == source_fingerprint))
    if existing is not None:
        return existing if existing.status in ACTIVE_STATUSES else None
    escalation = SafetyEscalation(
        user_id=user.id,
        checkin_id=checkin.id if checkin is not None else None,
        local_date=local_date,
        trigger_kind=classification["trigger_kind"],
        severity=classification["severity"],
        status="open",
        rule_version=RULE_VERSION,
        source_rule_version=source_rule_version,
        source_rule_id=source_rule_id,
        source_key=source_key,
        source_fingerprint=source_fingerprint,
    )
    try:
        with db.begin_nested():
            db.add(escalation)
            db.flush()
    except IntegrityError:
        return db.scalar(select(SafetyEscalation).where(SafetyEscalation.user_id == user.id, SafetyEscalation.source_fingerprint == source_fingerprint))
    db.add(SafetyEscalationEvent(
        escalation_id=escalation.id,
        user_id=user.id,
        event_type="opened",
        actor_kind="system",
        rule_version=RULE_VERSION,
        metadata_json={"trigger_kind": escalation.trigger_kind, "source_rule_id": source_rule_id},
        occurred_at=now,
    ))
    log_audit_event(db, user.id, "safety_escalation.opened", "safety_escalation", escalation.id, {"trigger_kind": escalation.trigger_kind, "rule_version": RULE_VERSION})
    return escalation


def materialize_current_escalation(db: Session, user: User) -> dict[str, object]:
    if not get_settings().safety_escalation_enabled:
        return escalation_response(None)
    from app.services.readiness import daily_readiness_recommendation, recovery_summary_for_today, today_checkin, today_context

    db.scalar(select(User.id).where(User.id == user.id).with_for_update())
    local_date, profile, _workout = today_context(db, user)
    checkin = today_checkin(db, user, local_date)
    recommendation = daily_readiness_recommendation(checkin, profile, _workout, recovery_summary_for_today(db, user, local_date, checkin))
    escalation = sync_escalation(db, user, local_date=local_date, profile=profile, checkin=checkin, recommendation=recommendation)
    db.commit()
    if escalation is not None:
        db.refresh(escalation)
    return escalation_response(escalation)


def acknowledge_escalation(db: Session, user: User, escalation_id: int) -> dict[str, object]:
    if not get_settings().safety_escalation_enabled:
        raise SafetyEscalationConflict("Safety escalation is not available")
    from app.services.readiness import daily_readiness_recommendation, recovery_summary_for_today, today_checkin, today_context

    db.scalar(select(User.id).where(User.id == user.id).with_for_update())
    local_date, profile, _workout = today_context(db, user)
    checkin = today_checkin(db, user, local_date)
    recommendation = daily_readiness_recommendation(checkin, profile, _workout, recovery_summary_for_today(db, user, local_date, checkin))
    current = sync_escalation(db, user, local_date=local_date, profile=profile, checkin=checkin, recommendation=recommendation)
    if current is None or current.id != escalation_id:
        raise SafetyEscalationConflict("Safety escalation is no longer current")
    escalation = db.scalar(
        select(SafetyEscalation)
        .where(SafetyEscalation.id == escalation_id, SafetyEscalation.user_id == user.id)
        .with_for_update()
    )
    if escalation is None or escalation.status not in ACTIVE_STATUSES:
        raise SafetyEscalationConflict("Safety escalation is no longer current")
    if escalation.status == "acknowledged":
        return escalation_response(escalation)
    now = datetime.now(UTC)
    escalation.status = "acknowledged"
    escalation.acknowledgement_code = "understood_guidance"
    escalation.acknowledged_at = now
    db.add(SafetyEscalationEvent(
        escalation_id=escalation.id,
        user_id=user.id,
        event_type="acknowledged",
        actor_kind="athlete",
        rule_version=RULE_VERSION,
        metadata_json={"acknowledgement_code": "understood_guidance"},
        occurred_at=now,
    ))
    log_audit_event(db, user.id, "safety_escalation.acknowledged", "safety_escalation", escalation.id, {"acknowledgement_code": "understood_guidance", "rule_version": RULE_VERSION})
    db.commit()
    db.refresh(escalation)
    return escalation_response(escalation)
