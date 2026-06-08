from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import User
from app.schemas.common import GoalCompleteIn, GoalCreate, GoalOut, GoalUpdate
from app.services.auth import get_current_user
from app.services.goals import complete_goal as complete_goal_service
from app.services.goals import create_goal as create_goal_service
from app.services.goals import delete_goal as delete_goal_service
from app.services.goals import get_goal, goal_to_dict, list_goals as list_goals_service
from app.services.goals import update_goal as update_goal_service


router = APIRouter(prefix="/goals", tags=["goals"])


@router.get("", response_model=list[GoalOut])
def list_goals(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list_goals_service(db, user)


@router.post("", response_model=GoalOut)
def create_goal(payload: GoalCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        return goal_to_dict(db, user, create_goal_service(db, user, payload))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.patch("/{goal_id}", response_model=GoalOut)
def update_goal(goal_id: int, payload: GoalUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        goal = get_goal(db, user, goal_id)
        return goal_to_dict(db, user, update_goal_service(db, user, goal, payload))
    except ValueError as error:
        status_code = 404 if str(error) == "Goal not found" else 400
        raise HTTPException(status_code=status_code, detail=str(error)) from error


@router.post("/{goal_id}/complete", response_model=GoalOut)
def complete_goal(goal_id: int, payload: GoalCompleteIn = GoalCompleteIn(), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        goal = get_goal(db, user, goal_id)
        return goal_to_dict(db, user, complete_goal_service(db, user, goal, payload))
    except ValueError as error:
        status_code = 404 if str(error) == "Goal not found" else 400
        raise HTTPException(status_code=status_code, detail=str(error)) from error


@router.delete("/{goal_id}")
def delete_goal(goal_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        goal = get_goal(db, user, goal_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail="Goal not found")
    return {"deleted": True, "id": delete_goal_service(db, goal)}
