from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import User
from app.services.audit import log_audit_event
from app.services.auth import get_current_user
from app.services.data_management import export_user_data


router = APIRouter(tags=["export"])


@router.get("/export")
def export_data(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    log_audit_event(db, user.id, "data.exported", "account", user.id)
    db.commit()
    return export_user_data(db, user)
