from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.models import TrainingPlan, User
from app.schemas.common import PlanGenerateRequest, PlanOut
from app.services.auth import get_current_user
from app.services.planning import generate_plan


router = APIRouter(prefix="/planning", tags=["planning"])


@router.post("/generate", response_model=PlanOut)
def generate_training_plan(payload: PlanGenerateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return generate_plan(db, user, payload)


@router.get("/plans", response_model=list[PlanOut])
def list_training_plans(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list(db.scalars(
        select(TrainingPlan)
        .where(TrainingPlan.user_id == user.id)
        .options(selectinload(TrainingPlan.workouts))
        .order_by(TrainingPlan.created_at.desc())
    ))
