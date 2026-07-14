from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import RecoverySignalObservation, User
from app.schemas.common import RecoverySignalImportOut, RecoverySignalImportRequest
from app.services.audit import log_audit_event
from app.services.auth import get_current_user
from app.services.recovery_signals import NORMALIZATION_VERSION, observation_input, validate_metric


router = APIRouter(prefix="/recovery-signals", tags=["recovery-signals"])


@router.post("/imports", response_model=RecoverySignalImportOut)
def import_recovery_signals(payload: RecoverySignalImportRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    now = datetime.now(UTC)
    normalized = []
    identities = set()
    for item in payload.observations:
        observed_at = item.observed_at.astimezone(UTC)
        if observed_at > now:
            raise HTTPException(status_code=422, detail="observed_at cannot be in the future")
        try:
            validate_metric(item.metric_key, item.unit, float(item.value))
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        identity = (item.source_system, item.metric_key, item.source_record_id)
        if identity in identities:
            raise HTTPException(status_code=422, detail="duplicate source record in request")
        identities.add(identity)
        normalized.append((item, observed_at))

    values = [dict(
            user_id=user.id,
            metric_key=item.metric_key,
            value_numeric=float(item.value),
            unit=item.unit,
            observed_at=observed_at,
            received_at=now,
            source_kind=item.source_kind,
            source_system=item.source_system,
            source_label=item.source_label,
            source_record_id=item.source_record_id,
            quality=item.quality,
            quality_score=float(item.quality_score) if item.quality_score is not None else None,
            normalization_version=NORMALIZATION_VERSION,
        ) for item, observed_at in normalized]
    created_ids = list(db.scalars(
        pg_insert(RecoverySignalObservation)
        .values(values)
        .on_conflict_do_nothing(constraint="uq_recovery_signal_source_record")
        .returning(RecoverySignalObservation.id)
    ))
    created = list(db.scalars(
        select(RecoverySignalObservation)
        .where(RecoverySignalObservation.id.in_(created_ids))
        .order_by(RecoverySignalObservation.id.asc())
    )) if created_ids else []
    duplicates = len(normalized) - len(created)
    if duplicates:
        created_identities = {(item.source_system, item.metric_key, item.source_record_id) for item in created}
        duplicate_inputs = [(item, observed_at) for item, observed_at in normalized if (item.source_system, item.metric_key, item.source_record_id) not in created_identities]
        existing_rows = list(db.scalars(
            select(RecoverySignalObservation).where(
                RecoverySignalObservation.user_id == user.id,
                RecoverySignalObservation.source_system.in_({item.source_system for item, _ in duplicate_inputs}),
                RecoverySignalObservation.source_record_id.in_({item.source_record_id for item, _ in duplicate_inputs}),
            )
        ))
        existing_by_identity = {(item.source_system, item.metric_key, item.source_record_id): item for item in existing_rows}
        for item, observed_at in duplicate_inputs:
            row = existing_by_identity.get((item.source_system, item.metric_key, item.source_record_id))
            equivalent = row is not None and (
                row.value_numeric == float(item.value)
                and row.unit == item.unit
                and row.observed_at.astimezone(UTC) == observed_at
                and row.source_kind == item.source_kind
                and row.source_label == item.source_label
                and row.quality == item.quality
                and row.quality_score == (float(item.quality_score) if item.quality_score is not None else None)
            )
            if not equivalent:
                db.rollback()
                raise HTTPException(status_code=409, detail="source record identity is immutable and already contains different normalized data")
    log_audit_event(db, user.id, "recovery_signals.imported", "recovery_signal_observation", created[0].id if created else None, {
        "accepted": len(created), "duplicates": duplicates, "metric_keys": sorted({item.metric_key for item, _ in normalized}),
    })
    db.commit()
    return {"accepted": len(created), "duplicates": duplicates, "observations": [observation_input(item) for item in created]}
