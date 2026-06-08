from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import User
from app.services.audit import log_audit_event
from app.services.auth import get_current_user
from app.services.data_management import export_activities_csv, export_user_data


router = APIRouter(tags=["export"])


@router.get("/export")
def export_data(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    log_audit_event(db, user.id, "data.exported", "account", user.id)
    db.commit()
    return export_user_data(db, user)


@router.get("/export/activities.csv")
def export_activities_csv_file(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    log_audit_event(db, user.id, "data.exported_csv", "account", user.id, {"dataset": "activities"})
    csv_content = export_activities_csv(db, user)
    db.commit()
    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=runforfan-activities.csv"},
    )
