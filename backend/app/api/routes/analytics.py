from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import User
from app.services.analytics import user_analytics
from app.services.auth import get_current_user


router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary")
def analytics_summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return user_analytics(db, user)
