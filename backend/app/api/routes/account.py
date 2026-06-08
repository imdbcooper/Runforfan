from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import User
from app.schemas.common import AccountDataDeleteIn, AccountDataDeleteOut
from app.services.audit import log_audit_event
from app.services.auth import get_current_user
from app.services.data_management import delete_user_data


router = APIRouter(prefix="/account", tags=["account"])


@router.delete("/data", response_model=AccountDataDeleteOut)
def delete_account_data(payload: AccountDataDeleteIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    counts = delete_user_data(db, user.id)
    event = log_audit_event(db, user.id, "data.deleted", "account", user.id, {"counts": counts})
    db.flush()
    db.commit()
    return AccountDataDeleteOut(deleted=True, counts=counts, audit_id=event.id)
