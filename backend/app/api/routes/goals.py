from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import RunningGoal, User
from app.schemas.common import GoalCreate, GoalOut
from app.services.auth import get_current_user


router = APIRouter(prefix="/goals", tags=["goals"])


@router.get("", response_model=list[GoalOut])
def list_goals(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list(db.scalars(select(RunningGoal).where(RunningGoal.user_id == user.id).order_by(RunningGoal.created_at.desc())))


@router.post("", response_model=GoalOut)
def create_goal(payload: GoalCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    goal = RunningGoal(user_id=user.id, **payload.model_dump())
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


@router.delete("/{goal_id}")
def delete_goal(goal_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    goal = db.scalar(select(RunningGoal).where(RunningGoal.id == goal_id, RunningGoal.user_id == user.id))
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    db.delete(goal)
    db.commit()
    return {"deleted": True, "id": goal_id}
