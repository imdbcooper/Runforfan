from datetime import date
from math import ceil

from sqlalchemy.orm import Session

from app.models import TrainingPlan, TrainingPlanWorkout, User
from app.schemas.common import PlanGenerateRequest


def weeks_until(target_date: date | None) -> int:
    if not target_date:
        return 8
    return max(4, min(24, ceil((target_date - date.today()).days / 7)))


def race_name(distance_km: float | None) -> str:
    if not distance_km:
        return "цель"
    if distance_km <= 5.5:
        return "5K"
    if distance_km <= 11:
        return "10K"
    if distance_km <= 22:
        return "полумарафон"
    if distance_km <= 43:
        return "марафон"
    return f"{distance_km:g} км"


def generate_plan(db: Session, user: User, request: PlanGenerateRequest) -> TrainingPlan:
    weeks = weeks_until(request.target_date)
    days = request.available_days_per_week
    current_volume = request.current_weekly_distance_km or 15.0
    goal_distance = request.race_distance_km or 10.0
    peak_volume = max(current_volume * 1.35, goal_distance * (1.15 if goal_distance >= 21 else 0.9))

    plan = TrainingPlan(
        user_id=user.id,
        title=request.title or f"План на {race_name(goal_distance)}",
        goal_type=request.goal_type,
        race_distance_km=goal_distance,
        target_date=request.target_date,
        available_days_per_week=days,
        status="draft",
        explanation=(
            "Гибридный MVP: правила ограничивают рост объема и распределяют легкие, интервальные, "
            "темповые и длинные тренировки. LLM-слой позже добавит персональные пояснения и корректировки."
        ),
    )
    db.add(plan)
    db.flush()

    for week in range(1, weeks + 1):
        progression = week / weeks
        week_volume = current_volume + (peak_volume - current_volume) * min(1, progression * 1.15)
        if week % 4 == 0:
            week_volume *= 0.78
        long_run = min(goal_distance * 0.75, week_volume * 0.38)
        easy_distance = max(3.0, (week_volume - long_run) / max(1, days - 1))
        workouts = [
            (1, "easy", "Легкий бег", easy_distance, "easy", "Комфортный бег в разговорном темпе."),
            (2, "interval", "Длинные интервалы", easy_distance, "threshold", "Работа около порога: 3-5 длинных отрезков с восстановлением."),
            (3, "tempo", "Темповая работа", easy_distance, "steady", "Устойчивый темп ниже порога, без закисления."),
            (days, "long", "Длинная тренировка", long_run, "easy-long", "Главная тренировка недели для марафонской базы."),
        ]
        for day_index, workout_type, title, distance, intensity, description in workouts[:days]:
            db.add(TrainingPlanWorkout(
                plan_id=plan.id,
                week_index=week,
                day_index=day_index,
                workout_type=workout_type,
                title=title,
                distance_km=round(distance, 1),
                intensity=intensity,
                description=description,
            ))

    db.commit()
    db.refresh(plan)
    return plan
