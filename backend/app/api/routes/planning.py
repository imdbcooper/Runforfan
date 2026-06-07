from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.models import Activity, TrainingPlan, TrainingPlanRecommendationAudit, TrainingPlanWorkout, User
from app.schemas.common import CurrentWeekOut, PlanActivityMatchCandidateOut, PlanBuilderPreviewOut, PlanGenerateRequest, PlanOut, PlanRecommendationApplyOut, PlanRecommendationApplyRequest, PlanRecommendationAuditOut, PlanRecommendationPreviewOut, PlanRecommendationsOut, PlanUpdate, PlanWeekSummaryOut, PlanWorkoutCompleteIn, PlanWorkoutFeedbackIn, PlanWorkoutFeedbackOut, PlanWorkoutFeedbackPatchIn, PlanWorkoutLinkActivityRequest, PlanWorkoutMatchCandidateOut, PlanWorkoutOut, PlanWorkoutUpdate
from app.services.auth import get_current_user
from app.services.dashboard import current_week_for_user
from app.services.planning import activity_match_candidates_for_workout, activate_plan, apply_plan_recommendations, complete_workout, delete_plan, duplicate_plan, generate_plan, link_activity_to_workout, patch_workout_feedback, plan_adjustment_recommendations, plan_builder_preview, plan_recommendation_preview_changes, plan_to_dict, plan_week_summaries, save_workout_feedback, update_plan, update_workout, workout_match_candidates_for_activity, workout_to_dict


router = APIRouter(prefix="/planning", tags=["planning"])


def plan_options():
    return (
        selectinload(TrainingPlan.workouts).selectinload(TrainingPlanWorkout.completed_activity),
        selectinload(TrainingPlan.workouts).selectinload(TrainingPlanWorkout.feedback),
    )


def get_user_plan(db: Session, user: User, plan_id: int) -> TrainingPlan:
    plan = db.scalar(
        select(TrainingPlan)
        .where(TrainingPlan.id == plan_id, TrainingPlan.user_id == user.id)
        .options(*plan_options())
    )
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan


def get_user_workout(db: Session, user: User, workout_id: int) -> TrainingPlanWorkout:
    workout = db.scalar(
        select(TrainingPlanWorkout)
        .join(TrainingPlan)
        .where(TrainingPlanWorkout.id == workout_id, TrainingPlan.user_id == user.id)
        .options(selectinload(TrainingPlanWorkout.completed_activity), selectinload(TrainingPlanWorkout.feedback))
    )
    if not workout:
        raise HTTPException(status_code=404, detail="Workout not found")
    return workout


def get_user_activity(db: Session, user: User, activity_id: int) -> Activity:
    activity = db.scalar(
        select(Activity)
        .where(Activity.id == activity_id, Activity.user_id == user.id)
        .options(selectinload(Activity.segments), selectinload(Activity.split_blocks), selectinload(Activity.workout_blocks))
    )
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")
    return activity


@router.post("/generate", response_model=PlanOut)
def generate_training_plan(payload: PlanGenerateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    plan = generate_plan(db, user, payload)
    plan = get_user_plan(db, user, plan.id)
    return plan_to_dict(plan)


@router.post("/preview", response_model=PlanBuilderPreviewOut)
def preview_training_plan(payload: PlanGenerateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return plan_builder_preview(db, user, payload)


@router.get("/plans", response_model=list[PlanOut])
def list_training_plans(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    plans = list(db.scalars(
        select(TrainingPlan)
        .where(TrainingPlan.user_id == user.id)
        .options(*plan_options())
        .order_by(TrainingPlan.created_at.desc())
    ))
    return [plan_to_dict(plan) for plan in plans]


@router.get("/current-week", response_model=CurrentWeekOut)
def get_current_week(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return current_week_for_user(db, user)


@router.get("/plans/{plan_id}", response_model=PlanOut)
def get_training_plan(plan_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return plan_to_dict(get_user_plan(db, user, plan_id))


@router.get("/plans/{plan_id}/adherence")
def get_training_plan_adherence(plan_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    plan = plan_to_dict(get_user_plan(db, user, plan_id))
    return {"adherence": plan["adherence"], "weekly_adherence": plan["weekly_adherence"]}


@router.get("/plans/{plan_id}/weeks", response_model=list[PlanWeekSummaryOut])
def get_training_plan_weeks(plan_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return plan_week_summaries(get_user_plan(db, user, plan_id))


@router.post("/plans/{plan_id}/adapt", response_model=PlanRecommendationApplyOut)
def adapt_training_plan(plan_id: int, payload: PlanRecommendationApplyRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not payload.changes:
        raise HTTPException(status_code=409, detail="Recommendation preview is required before adapting")
    try:
        result = apply_plan_recommendations(db, user, get_user_plan(db, user, plan_id), payload.changes)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    result["plan"] = plan_to_dict(get_user_plan(db, user, plan_id))
    return result


@router.get("/plans/{plan_id}/recommendations", response_model=PlanRecommendationsOut)
def get_training_plan_recommendations(plan_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return plan_adjustment_recommendations(db, user, get_user_plan(db, user, plan_id))


@router.post("/plans/{plan_id}/recommendations/preview", response_model=PlanRecommendationPreviewOut)
def preview_training_plan_recommendations(plan_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return plan_recommendation_preview_changes(db, user, get_user_plan(db, user, plan_id))


@router.post("/plans/{plan_id}/recommendations/apply", response_model=PlanRecommendationApplyOut)
def apply_training_plan_recommendations(plan_id: int, payload: PlanRecommendationApplyRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        result = apply_plan_recommendations(db, user, get_user_plan(db, user, plan_id), payload.changes)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    result["plan"] = plan_to_dict(get_user_plan(db, user, plan_id))
    return result


@router.get("/plans/{plan_id}/recommendations/audit", response_model=list[PlanRecommendationAuditOut])
def list_training_plan_recommendation_audits(plan_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    get_user_plan(db, user, plan_id)
    return list(db.scalars(
        select(TrainingPlanRecommendationAudit)
        .where(TrainingPlanRecommendationAudit.plan_id == plan_id, TrainingPlanRecommendationAudit.user_id == user.id)
        .order_by(TrainingPlanRecommendationAudit.created_at.desc(), TrainingPlanRecommendationAudit.id.desc())
        .limit(20)
    ))


@router.post("/plans/{plan_id}/activate", response_model=PlanOut)
def activate_training_plan(plan_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    plan = activate_plan(db, user, get_user_plan(db, user, plan_id))
    return plan_to_dict(get_user_plan(db, user, plan.id))


@router.patch("/plans/{plan_id}", response_model=PlanOut)
def update_training_plan(plan_id: int, payload: PlanUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        plan = update_plan(db, user, get_user_plan(db, user, plan_id), payload)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return plan_to_dict(get_user_plan(db, user, plan.id))


@router.post("/plans/{plan_id}/duplicate", response_model=PlanOut)
def duplicate_training_plan(plan_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    plan = duplicate_plan(db, user, get_user_plan(db, user, plan_id))
    return plan_to_dict(get_user_plan(db, user, plan.id))


@router.delete("/plans/{plan_id}")
def delete_training_plan(plan_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        deleted_id = delete_plan(db, user, get_user_plan(db, user, plan_id))
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"deleted": True, "id": deleted_id}


@router.patch("/workouts/{workout_id}", response_model=PlanWorkoutOut)
def update_training_plan_workout(workout_id: int, payload: PlanWorkoutUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    workout = get_user_workout(db, user, workout_id)
    try:
        updated = update_workout(db, user, workout, payload)
    except ValueError as error:
        status_code = 404 if "not found" in str(error).lower() else 400
        raise HTTPException(status_code=status_code, detail=str(error)) from error
    return workout_to_dict(updated)


@router.get("/workouts/{workout_id}", response_model=PlanWorkoutOut)
def get_training_plan_workout(workout_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return workout_to_dict(get_user_workout(db, user, workout_id))


@router.post("/workouts/{workout_id}/complete", response_model=PlanWorkoutOut)
def complete_training_plan_workout(workout_id: int, payload: PlanWorkoutCompleteIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        completed = complete_workout(db, user, get_user_workout(db, user, workout_id), payload)
    except ValueError as error:
        status_code = 404 if "not found" in str(error).lower() else 400
        raise HTTPException(status_code=status_code, detail=str(error)) from error
    return workout_to_dict(completed)


@router.get("/workouts/{workout_id}/feedback", response_model=PlanWorkoutFeedbackOut | None)
def get_training_plan_workout_feedback(workout_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return get_user_workout(db, user, workout_id).feedback


@router.put("/workouts/{workout_id}/feedback", response_model=PlanWorkoutFeedbackOut)
def save_training_plan_workout_feedback(workout_id: int, payload: PlanWorkoutFeedbackIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        return save_workout_feedback(db, user, get_user_workout(db, user, workout_id), payload)
    except ValueError as error:
        status_code = 404 if "not found" in str(error).lower() else 400
        raise HTTPException(status_code=status_code, detail=str(error)) from error


@router.patch("/workouts/{workout_id}/feedback", response_model=PlanWorkoutFeedbackOut)
def patch_training_plan_workout_feedback(workout_id: int, payload: PlanWorkoutFeedbackPatchIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        return patch_workout_feedback(db, user, get_user_workout(db, user, workout_id), payload)
    except ValueError as error:
        status_code = 404 if "not found" in str(error).lower() else 400
        raise HTTPException(status_code=status_code, detail=str(error)) from error


@router.get("/workouts/{workout_id}/match-candidates", response_model=list[PlanActivityMatchCandidateOut])
def get_workout_match_candidates(workout_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    workout = get_user_workout(db, user, workout_id)
    return activity_match_candidates_for_workout(db, user, workout)


@router.post("/workouts/{workout_id}/link-activity", response_model=PlanWorkoutOut)
def link_training_plan_workout_activity(workout_id: int, payload: PlanWorkoutLinkActivityRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    workout = get_user_workout(db, user, workout_id)
    try:
        linked = link_activity_to_workout(db, user, workout, payload.activity_id)
    except ValueError as error:
        status_code = 404 if "not found" in str(error).lower() else 400
        raise HTTPException(status_code=status_code, detail=str(error)) from error
    return workout_to_dict(linked)


@router.post("/workouts/{workout_id}/attach-activity", response_model=PlanWorkoutOut)
def attach_training_plan_workout_activity(workout_id: int, payload: PlanWorkoutLinkActivityRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return link_training_plan_workout_activity(workout_id, payload, user, db)


@router.get("/activities/{activity_id}/match-candidates", response_model=list[PlanWorkoutMatchCandidateOut])
def get_activity_match_candidates(activity_id: int, active_only: bool = Query(False), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    activity = get_user_activity(db, user, activity_id)
    return workout_match_candidates_for_activity(db, user, activity, active_only=active_only)
