from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import User
from app.schemas.common import DashboardSummaryOut
from app.services.auth import get_current_user
from app.services.dashboard import dashboard_summary


router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummaryOut)
def get_dashboard_summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return dashboard_summary(db, user)
