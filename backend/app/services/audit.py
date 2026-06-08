from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog


def log_audit_event(
    db: Session,
    user_id: int,
    action: str,
    entity_type: str,
    entity_id: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    event = AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        metadata_json=metadata or {},
    )
    db.add(event)
    return event
