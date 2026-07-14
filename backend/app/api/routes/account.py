from fastapi import APIRouter, Depends
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.settings import get_settings
from app.models import User
from app.schemas.common import AccountDataDeleteIn, AccountDataDeleteOut
from app.services.audit import log_audit_event
from app.services.auth import get_current_user
from app.services.data_management import create_upload_deletion_job, delete_user_data, finish_upload_deletion_job, restore_user_upload_deletion, stage_user_upload_deletion


router = APIRouter(prefix="/account", tags=["account"])


@router.delete("/data", response_model=AccountDataDeleteOut)
def delete_account_data(payload: AccountDataDeleteIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    upload_dir = get_settings().upload_dir
    staged_uploads, screenshot_files = stage_user_upload_deletion(upload_dir, user.id)
    deletion_job_id = None
    try:
        counts = delete_user_data(db, user.id)
        counts["screenshot_files"] = screenshot_files
        event = log_audit_event(db, user.id, "data.deleted", "account", user.id, {"counts": counts})
        if staged_uploads is not None:
            deletion_job_id = create_upload_deletion_job(db, staged_uploads, screenshot_files).id
        db.flush()
        db.commit()
    except Exception:
        db.rollback()
        restore_user_upload_deletion(staged_uploads, upload_dir, user.id)
        raise
    if deletion_job_id is not None:
        try:
            finish_upload_deletion_job(db, upload_dir, deletion_job_id)
        except (OSError, SQLAlchemyError):
            db.rollback()
    return AccountDataDeleteOut(deleted=True, counts=counts, audit_id=event.id)
