from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.models import TrainingPlan, TrainingPlanWorkout, User
from app.schemas.common import PlanGenerateRequest, PlanOut, PlanWorkoutOut, PlanWorkoutUpdate
from app.services.auth import get_current_user
from app.services.planning import activate_plan, generate_plan, plan_to_dict, update_workout, workout_to_dict


router = APIRouter(prefix="/planning", tags=["planning"])


def plan_options():
    return selectinload(TrainingPlan.workouts).selectinload(TrainingPlanWorkout.completed_activity)


def get_user_plan(db: Session, user: User, plan_id: int) -> TrainingPlan:
    plan = db.scalar(
        select(TrainingPlan)
        .where(TrainingPlan.id == plan_id, TrainingPlan.user_id == user.id)
        .options(plan_options())
    )
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan


@router.post("/generate", response_model=PlanOut)
def generate_training_plan(payload: PlanGenerateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    plan = generate_plan(db, user, payload)
    plan = get_user_plan(db, user, plan.id)
    return plan_to_dict(plan)


@router.get("/plans", response_model=list[PlanOut])
def list_training_plans(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    plans = list(db.scalars(
        select(TrainingPlan)
        .where(TrainingPlan.user_id == user.id)
        .options(plan_options())
        .order_by(TrainingPlan.created_at.desc())
    ))
    return [plan_to_dict(plan) for plan in plans]


@router.get("/plans/{plan_id}", response_model=PlanOut)
def get_training_plan(plan_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return plan_to_dict(get_user_plan(db, user, plan_id))


@router.post("/plans/{plan_id}/activate", response_model=PlanOut)
def activate_training_plan(plan_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    plan = activate_plan(db, user, get_user_plan(db, user, plan_id))
    return plan_to_dict(get_user_plan(db, user, plan.id))


@router.patch("/workouts/{workout_id}", response_model=PlanWorkoutOut)
def update_training_plan_workout(workout_id: int, payload: PlanWorkoutUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    workout = db.scalar(
        select(TrainingPlanWorkout)
        .join(TrainingPlan)
        .where(TrainingPlanWorkout.id == workout_id, TrainingPlan.user_id == user.id)
        .options(selectinload(TrainingPlanWorkout.completed_activity))
    )
    if not workout:
        raise HTTPException(status_code=404, detail="Workout not found")
    try:
        updated = update_workout(db, user, workout, payload)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return workout_to_dict(updated)
