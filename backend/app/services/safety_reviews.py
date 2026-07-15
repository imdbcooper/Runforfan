from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.models import SafetyEscalation, SafetyReviewConsent, SafetyReviewEvent, SafetyReviewerGrant, SafetyReviewRequest, User
from app.services.audit import log_audit_event


POLICY_VERSION = "safety-review-consent-v1"
ACTIVE_CASE_STATUSES = ("open", "acknowledged")
ACTIVE_REQUEST_STATUSES = ("requested", "claimed")
DISCLAIMER = "Human review is asynchronous, is not emergency support or continuous monitoring, has no guaranteed response time, and cannot provide medical clearance or change your training plan."


class SafetyReviewConflict(RuntimeError):
    pass


def athlete_review_available() -> bool:
    settings = get_settings()
    return bool(settings.safety_escalation_enabled and settings.safety_review_enabled and settings.safety_review_reviewer_api_enabled)


def reviewer_api_available() -> bool:
    settings = get_settings()
    return bool(settings.safety_escalation_enabled and settings.safety_review_enabled and settings.safety_review_reviewer_api_enabled)


def require_active_reviewer(db: Session, user: User, *, lock: bool = False) -> SafetyReviewerGrant:
    if not reviewer_api_available():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Safety review API is unavailable")
    if not user.is_active or user.is_demo:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Active provisioned reviewer required")
    query = select(SafetyReviewerGrant).where(SafetyReviewerGrant.user_id == user.id, SafetyReviewerGrant.status == "active")
    if lock:
        query = query.with_for_update()
    grant = db.scalar(query)
    if grant is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Active provisioned reviewer required")
    return grant


def release_reviewer_claims(db: Session, reviewer_user_id: int, now: datetime | None = None) -> int:
    occurred_at = now or datetime.now(UTC)
    request_refs = list(db.execute(
        select(SafetyReviewRequest.id, SafetyReviewRequest.user_id, SafetyReviewRequest.escalation_id)
        .where(SafetyReviewRequest.reviewer_user_id == reviewer_user_id, SafetyReviewRequest.status == "claimed")
        .order_by(SafetyReviewRequest.user_id.asc(), SafetyReviewRequest.id.asc())
    ))
    requests: list[SafetyReviewRequest] = []
    for request_id, user_id, escalation_id in request_refs:
        db.scalar(select(User.id).where(User.id == user_id).with_for_update())
        db.scalar(select(SafetyEscalation.id).where(SafetyEscalation.id == escalation_id, SafetyEscalation.user_id == user_id).with_for_update())
        _consent(db, escalation_id, user_id, lock=True)
        request = db.scalar(
            select(SafetyReviewRequest)
            .where(
                SafetyReviewRequest.id == request_id,
                SafetyReviewRequest.reviewer_user_id == reviewer_user_id,
                SafetyReviewRequest.status == "claimed",
            )
            .with_for_update()
        )
        if request is not None:
            requests.append(request)
    for request in requests:
        db.add(SafetyReviewEvent(request_id=request.id, user_id=request.user_id, actor_user_id=reviewer_user_id, event_type="released", actor_kind="reviewer", occurred_at=occurred_at))
    db.flush()
    for request in requests:
        request.status = "requested"
        request.reviewer_user_id = None
        request.claimed_at = None
    db.flush()
    return len(requests)


def provision_reviewer(db: Session, user_id: int) -> SafetyReviewerGrant:
    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None or not user.is_active or user.is_demo:
        raise SafetyReviewConflict("Reviewer must be an existing active non-demo user")
    grant = db.scalar(select(SafetyReviewerGrant).where(SafetyReviewerGrant.user_id == user_id).with_for_update())
    if grant is not None:
        if grant.status != "active":
            raise SafetyReviewConflict("Revoked reviewer grant is terminal; create a new controlled identity")
        return grant
    grant = SafetyReviewerGrant(user_id=user_id, status="active")
    db.add(grant)
    db.flush()
    log_audit_event(db, user_id, "safety_reviewer.granted", "safety_reviewer_grant", grant.id, {})
    db.commit()
    db.refresh(grant)
    return grant


def revoke_reviewer(db: Session, user_id: int) -> tuple[SafetyReviewerGrant, int]:
    grant = db.scalar(select(SafetyReviewerGrant).where(SafetyReviewerGrant.user_id == user_id).with_for_update())
    if grant is None:
        raise SafetyReviewConflict("Reviewer grant not found")
    if grant.status == "revoked":
        return grant, 0
    now = datetime.now(UTC)
    released = release_reviewer_claims(db, user_id, now)
    grant.status = "revoked"
    grant.revoked_at = now
    log_audit_event(db, user_id, "safety_reviewer.revoked", "safety_reviewer_grant", grant.id, {"released_claims": released})
    db.commit()
    db.refresh(grant)
    return grant, released


def _owned_active_case(db: Session, user_id: int, escalation_id: int, *, lock: bool = False) -> SafetyEscalation:
    query = select(SafetyEscalation).where(
        SafetyEscalation.id == escalation_id,
        SafetyEscalation.user_id == user_id,
        SafetyEscalation.status.in_(ACTIVE_CASE_STATUSES),
    )
    if lock:
        query = query.with_for_update()
    escalation = db.scalar(query)
    if escalation is None:
        raise SafetyReviewConflict("Safety escalation is no longer current")
    return escalation


def _consent(db: Session, escalation_id: int, user_id: int, *, lock: bool = False) -> SafetyReviewConsent | None:
    query = select(SafetyReviewConsent).where(SafetyReviewConsent.escalation_id == escalation_id, SafetyReviewConsent.user_id == user_id)
    if lock:
        query = query.with_for_update()
    return db.scalar(query)


def _request(db: Session, escalation_id: int, user_id: int, *, lock: bool = False) -> SafetyReviewRequest | None:
    query = select(SafetyReviewRequest).where(SafetyReviewRequest.escalation_id == escalation_id, SafetyReviewRequest.user_id == user_id)
    if lock:
        query = query.with_for_update()
    return db.scalar(query)


def review_state(db: Session, user_id: int, escalation_id: int) -> dict[str, object]:
    if not athlete_review_available():
        return {"available": False, "policy_version": POLICY_VERSION, "consent_status": None, "request_status": None, "disposition_code": None, "requested_at": None, "completed_at": None, "disclaimer": DISCLAIMER}
    _owned_active_case(db, user_id, escalation_id)
    consent = _consent(db, escalation_id, user_id)
    request = _request(db, escalation_id, user_id)
    return {
        "available": True,
        "policy_version": POLICY_VERSION,
        "consent_status": consent.status if consent is not None else None,
        "request_status": request.status if request is not None else None,
        "disposition_code": request.disposition_code if request is not None else None,
        "requested_at": request.requested_at if request is not None else None,
        "completed_at": request.completed_at if request is not None else None,
        "disclaimer": DISCLAIMER,
    }


def grant_consent(db: Session, user: User, escalation_id: int) -> dict[str, object]:
    if not athlete_review_available():
        raise SafetyReviewConflict("Human review is unavailable")
    db.scalar(select(User.id).where(User.id == user.id).with_for_update())
    escalation = _owned_active_case(db, user.id, escalation_id, lock=True)
    existing = _consent(db, escalation.id, user.id, lock=True)
    if existing is not None:
        if existing.status != "active":
            raise SafetyReviewConflict("Consent for this safety case was withdrawn and cannot be reopened")
        return review_state(db, user.id, escalation.id)
    consent = SafetyReviewConsent(escalation_id=escalation.id, user_id=user.id, policy_version=POLICY_VERSION, status="active")
    db.add(consent)
    log_audit_event(db, user.id, "safety_review.consent_granted", "safety_escalation", escalation.id, {"policy_version": POLICY_VERSION})
    db.commit()
    return review_state(db, user.id, escalation.id)


def request_review(db: Session, user: User, escalation_id: int) -> dict[str, object]:
    if not athlete_review_available():
        raise SafetyReviewConflict("Human review is unavailable")
    enrolled_reviewer = db.scalar(
        select(SafetyReviewerGrant.id)
        .join(User, User.id == SafetyReviewerGrant.user_id)
        .where(SafetyReviewerGrant.status == "active", SafetyReviewerGrant.user_id != user.id, User.is_active.is_(True), User.is_demo.is_(False))
        .order_by(SafetyReviewerGrant.user_id.asc())
        .with_for_update(of=SafetyReviewerGrant)
        .limit(1)
    )
    if enrolled_reviewer is None:
        raise SafetyReviewConflict("No reviewer is currently provisioned; no review request was created")
    db.scalar(select(User.id).where(User.id == user.id).with_for_update())
    escalation = _owned_active_case(db, user.id, escalation_id, lock=True)
    consent = _consent(db, escalation.id, user.id, lock=True)
    if consent is None or consent.status != "active":
        raise SafetyReviewConflict("Active review consent is required")
    existing = _request(db, escalation.id, user.id, lock=True)
    if existing is not None:
        return review_state(db, user.id, escalation.id)
    request = SafetyReviewRequest(escalation_id=escalation.id, consent_id=consent.id, user_id=user.id, status="requested")
    db.add(request)
    db.flush()
    db.add(SafetyReviewEvent(request_id=request.id, user_id=user.id, actor_user_id=user.id, event_type="requested", actor_kind="athlete"))
    log_audit_event(db, user.id, "safety_review.requested", "safety_review_request", request.id, {"policy_version": POLICY_VERSION})
    db.commit()
    return review_state(db, user.id, escalation.id)


def withdraw_consent(db: Session, user: User, escalation_id: int) -> dict[str, object]:
    if not athlete_review_available():
        raise SafetyReviewConflict("Human review is unavailable")
    db.scalar(select(User.id).where(User.id == user.id).with_for_update())
    escalation = _owned_active_case(db, user.id, escalation_id, lock=True)
    consent = _consent(db, escalation.id, user.id, lock=True)
    if consent is None:
        raise SafetyReviewConflict("Review consent was not granted")
    if consent.status != "active":
        return review_state(db, user.id, escalation.id)
    now = datetime.now(UTC)
    request = _request(db, escalation.id, user.id, lock=True)
    if request is not None and request.status in ACTIVE_REQUEST_STATUSES:
        request.status = "withdrawn"
        request.closed_at = now
        db.flush()
        db.add(SafetyReviewEvent(request_id=request.id, user_id=user.id, actor_user_id=user.id, event_type="withdrawn", actor_kind="athlete", occurred_at=now))
    consent.status = "withdrawn"
    consent.closed_at = now
    log_audit_event(db, user.id, "safety_review.consent_withdrawn", "safety_escalation", escalation.id, {"policy_version": POLICY_VERSION})
    db.commit()
    return review_state(db, user.id, escalation.id)


def close_for_supersession(db: Session, escalation: SafetyEscalation, now: datetime) -> None:
    consent = _consent(db, escalation.id, escalation.user_id, lock=True)
    if consent is None or consent.status != "active":
        return
    request = _request(db, escalation.id, escalation.user_id, lock=True)
    if request is not None and request.status in ACTIVE_REQUEST_STATUSES:
        request.status = "cancelled_case_superseded"
        request.closed_at = now
        db.flush()
        db.add(SafetyReviewEvent(request_id=request.id, user_id=escalation.user_id, actor_user_id=None, event_type="case_superseded", actor_kind="system", occurred_at=now))
    consent.status = "case_superseded"
    consent.closed_at = now
    log_audit_event(db, escalation.user_id, "safety_review.case_superseded", "safety_escalation", escalation.id, {"policy_version": POLICY_VERSION})


def reviewer_queue(db: Session, reviewer: User, limit: int, offset: int) -> list[dict[str, object]]:
    require_active_reviewer(db, reviewer)
    requests = list(db.scalars(
        select(SafetyReviewRequest)
        .where(
            ((SafetyReviewRequest.status == "requested") & (SafetyReviewRequest.user_id != reviewer.id))
            | ((SafetyReviewRequest.status == "claimed") & (SafetyReviewRequest.reviewer_user_id == reviewer.id))
        )
        .order_by(SafetyReviewRequest.requested_at.asc(), SafetyReviewRequest.id.asc())
        .offset(offset)
        .limit(limit)
    ))
    return [{"id": item.id, "status": item.status, "requested_at": item.requested_at, "claimed_at": item.claimed_at} for item in requests]


def claim_request(db: Session, reviewer: User, request_id: int) -> dict[str, object]:
    require_active_reviewer(db, reviewer, lock=True)
    request_owner = db.execute(select(SafetyReviewRequest.user_id, SafetyReviewRequest.escalation_id).where(SafetyReviewRequest.id == request_id)).one_or_none()
    if request_owner is None:
        raise SafetyReviewConflict("Review request not found")
    user_id, escalation_id = request_owner
    db.scalar(select(User.id).where(User.id == user_id).with_for_update())
    escalation = db.scalar(select(SafetyEscalation).where(SafetyEscalation.id == escalation_id, SafetyEscalation.user_id == user_id).with_for_update())
    consent = _consent(db, escalation_id, user_id, lock=True)
    request = db.scalar(select(SafetyReviewRequest).where(SafetyReviewRequest.id == request_id, SafetyReviewRequest.user_id == user_id).with_for_update())
    if request is None:
        raise SafetyReviewConflict("Review request not found")
    if request.status == "claimed" and request.reviewer_user_id == reviewer.id:
        return _record_context_view(db, reviewer, request, escalation, consent)
    if request.status != "requested":
        raise SafetyReviewConflict("Review request is no longer claimable")
    if request.user_id == reviewer.id:
        raise SafetyReviewConflict("Reviewers cannot claim their own request")
    if consent is None or consent.status != "active" or escalation is None or escalation.status not in ACTIVE_CASE_STATUSES:
        raise SafetyReviewConflict("Review request is no longer authorized")
    now = datetime.now(UTC)
    request.status = "claimed"
    request.reviewer_user_id = reviewer.id
    request.claimed_at = now
    db.flush()
    db.add(SafetyReviewEvent(request_id=request.id, user_id=request.user_id, actor_user_id=reviewer.id, event_type="claimed", actor_kind="reviewer", occurred_at=now))
    db.add(SafetyReviewEvent(request_id=request.id, user_id=request.user_id, actor_user_id=reviewer.id, event_type="viewed", actor_kind="reviewer", occurred_at=now))
    response = _context_response(request, escalation)
    db.commit()
    return response


def reviewer_context(db: Session, reviewer: User, request_id: int) -> dict[str, object]:
    require_active_reviewer(db, reviewer, lock=True)
    request_owner = db.execute(select(SafetyReviewRequest.user_id, SafetyReviewRequest.escalation_id).where(SafetyReviewRequest.id == request_id)).one_or_none()
    if request_owner is None:
        raise SafetyReviewConflict("Claimed review request not found")
    user_id, escalation_id = request_owner
    db.scalar(select(User.id).where(User.id == user_id).with_for_update())
    escalation = db.scalar(select(SafetyEscalation).where(SafetyEscalation.id == escalation_id, SafetyEscalation.user_id == user_id).with_for_update())
    consent = _consent(db, escalation_id, user_id, lock=True)
    request = db.scalar(select(SafetyReviewRequest).where(SafetyReviewRequest.id == request_id, SafetyReviewRequest.user_id == user_id).with_for_update())
    if request is None or request.status != "claimed" or request.reviewer_user_id != reviewer.id:
        raise SafetyReviewConflict("Claimed review request not found")
    return _record_context_view(db, reviewer, request, escalation, consent)


def release_request(db: Session, reviewer: User, request_id: int) -> dict[str, object]:
    require_active_reviewer(db, reviewer, lock=True)
    request_owner = db.execute(select(SafetyReviewRequest.user_id, SafetyReviewRequest.escalation_id).where(SafetyReviewRequest.id == request_id)).one_or_none()
    if request_owner is None:
        raise SafetyReviewConflict("Claimed review request not found")
    user_id, escalation_id = request_owner
    db.scalar(select(User.id).where(User.id == user_id).with_for_update())
    db.scalar(select(SafetyEscalation.id).where(SafetyEscalation.id == escalation_id, SafetyEscalation.user_id == user_id).with_for_update())
    _consent(db, escalation_id, user_id, lock=True)
    request = db.scalar(
        select(SafetyReviewRequest)
        .where(
            SafetyReviewRequest.id == request_id,
            SafetyReviewRequest.user_id == user_id,
            SafetyReviewRequest.reviewer_user_id == reviewer.id,
            SafetyReviewRequest.status == "claimed",
        )
        .with_for_update()
    )
    if request is None:
        raise SafetyReviewConflict("Claimed review request not found")
    now = datetime.now(UTC)
    db.add(SafetyReviewEvent(request_id=request.id, user_id=request.user_id, actor_user_id=reviewer.id, event_type="released", actor_kind="reviewer", occurred_at=now))
    db.flush()
    request.status = "requested"
    request.reviewer_user_id = None
    request.claimed_at = None
    db.commit()
    return {"id": request.id, "status": request.status, "requested_at": request.requested_at, "claimed_at": request.claimed_at}


def _record_context_view(db: Session, reviewer: User, request: SafetyReviewRequest, escalation: SafetyEscalation | None, consent: SafetyReviewConsent | None) -> dict[str, object]:
    if consent is None or consent.status != "active" or escalation is None or escalation.status not in ACTIVE_CASE_STATUSES:
        raise SafetyReviewConflict("Review access is no longer authorized")
    db.add(SafetyReviewEvent(request_id=request.id, user_id=request.user_id, actor_user_id=reviewer.id, event_type="viewed", actor_kind="reviewer"))
    response = _context_response(request, escalation)
    db.commit()
    return response


def _context_response(request: SafetyReviewRequest, escalation: SafetyEscalation) -> dict[str, object]:
    from app.services.safety_escalations import _COPY

    copy = _COPY[escalation.trigger_kind]
    return {
        "id": request.id,
        "status": request.status,
        "requested_at": request.requested_at,
        "claimed_at": request.claimed_at,
        "trigger_kind": escalation.trigger_kind,
        "severity": escalation.severity,
        "case_status": escalation.status,
        "rule_version": escalation.rule_version,
        "source_rule_id": escalation.source_rule_id,
        "local_date": escalation.local_date,
        "title": copy["title"],
        "guidance": copy["guidance"],
        "disclaimer": DISCLAIMER,
    }


def complete_request(db: Session, reviewer: User, request_id: int, disposition_code: str) -> dict[str, object]:
    require_active_reviewer(db, reviewer, lock=True)
    request_owner = db.execute(select(SafetyReviewRequest.user_id, SafetyReviewRequest.escalation_id).where(SafetyReviewRequest.id == request_id)).one_or_none()
    if request_owner is None:
        raise SafetyReviewConflict("Claimed review request not found")
    user_id, escalation_id = request_owner
    db.scalar(select(User.id).where(User.id == user_id).with_for_update())
    escalation = db.scalar(select(SafetyEscalation).where(SafetyEscalation.id == escalation_id, SafetyEscalation.user_id == user_id).with_for_update())
    consent = _consent(db, escalation_id, user_id, lock=True)
    request = db.scalar(select(SafetyReviewRequest).where(SafetyReviewRequest.id == request_id, SafetyReviewRequest.user_id == user_id).with_for_update())
    if request is None or request.status != "claimed":
        raise SafetyReviewConflict("Claimed review request not found")
    if request.reviewer_user_id != reviewer.id:
        raise SafetyReviewConflict("Claimed review request not found")
    if consent is None or consent.status != "active" or escalation is None or escalation.status not in ACTIVE_CASE_STATUSES:
        raise SafetyReviewConflict("Review access is no longer authorized")
    now = datetime.now(UTC)
    event_type = "unable_to_review" if disposition_code == "unable_to_review" else "completed"
    request.status = event_type
    request.disposition_code = disposition_code
    request.completed_at = now
    db.flush()
    db.add(SafetyReviewEvent(request_id=request.id, user_id=request.user_id, actor_user_id=reviewer.id, event_type=event_type, actor_kind="reviewer", disposition_code=disposition_code, occurred_at=now))
    log_audit_event(db, request.user_id, "safety_review.completed", "safety_review_request", request.id, {"disposition_code": disposition_code})
    db.commit()
    return {"id": request.id, "status": request.status, "disposition_code": request.disposition_code, "completed_at": request.completed_at, "disclaimer": DISCLAIMER}
