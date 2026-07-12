from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import AthleteProfile, DailyReadinessCheckIn, TrainingPlan, TrainingPlanWorkout, User
from app.schemas.common import DailyReadinessCheckInUpsert
from app.services.dashboard import active_training_plan
from app.services.planning import today_for_user, workout_to_dict
from app.services.profile import get_or_create_profile, safety_check


RULE_VERSION = "daily-readiness-v1"
DISCLAIMER = "Runforfan не является медицинским устройством. При боли, головокружении, одышке или ухудшении самочувствия прекратите нагрузку и обратитесь к специалисту."
HARD_WORKOUT_TYPES = {"interval", "intervals", "tempo", "threshold", "race", "fartlek", "hills", "hill_repeats"}
HARD_INTENSITIES = {"hard", "tempo", "threshold", "interval", "race", "vo2max"}


def workout_is_hard(workout: TrainingPlanWorkout | None) -> bool:
    if workout is None:
        return False
    return workout.workout_type.lower() in HARD_WORKOUT_TYPES or (workout.intensity or "").lower() in HARD_INTENSITIES


def easy_replacement(workout: TrainingPlanWorkout) -> dict[str, object]:
    planned_duration = workout.duration_seconds
    duration = min(planned_duration, max(900, round(planned_duration * 0.6))) if planned_duration else 1800
    return {
        "kind": "easy_run",
        "duration_seconds": duration,
        "distance_km": None,
        "intensity": "easy",
        "rpe_range": [2, 3],
        "instructions": [
            "Сохраняйте разговорный темп и не добавляйте ускорения.",
            "Прекратите тренировку, если появляется или усиливается боль.",
        ],
    }


def shortened_workout(workout: TrainingPlanWorkout) -> dict[str, object]:
    duration = round(workout.duration_seconds * 0.7) if workout.duration_seconds else None
    distance = round(workout.distance_km * 0.7, 1) if workout.distance_km is not None else None
    return {
        "kind": workout.workout_type,
        "duration_seconds": duration,
        "distance_km": distance,
        "intensity": "easy" if not workout_is_hard(workout) else "moderate",
        "rpe_range": [2, 4],
        "instructions": [
            "Сократите объём и не компенсируйте его позже на этой неделе.",
            "Остановитесь, если самочувствие ухудшается.",
        ],
    }


def recommendation(
    *,
    rule_id: str,
    status: str,
    action: str,
    title: str,
    message: str,
    reasons: list[str],
    workout: TrainingPlanWorkout | None,
    prescribed_workout: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "rule_version": RULE_VERSION,
        "rule_id": rule_id,
        "status": status,
        "action": action,
        "title": title,
        "message": message,
        "reasons": reasons,
        "workout_id": workout.id if workout else None,
        "prescribed_workout": prescribed_workout,
        "disclaimer": DISCLAIMER,
        "generated_at": datetime.now(UTC).isoformat(),
    }


def daily_readiness_recommendation(
    checkin: DailyReadinessCheckIn | None,
    profile: AthleteProfile,
    workout: TrainingPlanWorkout | None,
) -> dict[str, object]:
    if profile.recovery_status == "injured":
        return recommendation(
            rule_id="profile_injured",
            status="stop",
            action="rest_and_seek_guidance",
            title="Сегодня не начинайте беговую тренировку",
            message="В профиле отмечено восстановление после травмы. Возвращаться к нагрузке стоит только по согласованному безопасному сценарию.",
            reasons=["В профиле указан статус восстановления «травма»."],
            workout=workout,
        )

    if checkin is None:
        return recommendation(
            rule_id="checkin_required",
            status="checkin_required",
            action="checkin_required",
            title="Расскажите, как вы себя чувствуете",
            message="Короткий check-in поможет проверить, подходит ли запланированная нагрузка вашему состоянию сегодня.",
            reasons=["Сегодняшний check-in ещё не заполнен."],
            workout=workout,
        )

    pain_level = checkin.pain_level_0_10
    if checkin.illness_symptoms or (checkin.pain and pain_level is not None and pain_level >= 4):
        reasons = []
        if checkin.illness_symptoms:
            reasons.append("Отмечены симптомы болезни.")
        if checkin.pain and pain_level is not None and pain_level >= 4:
            reasons.append(f"Уровень боли отмечен как {pain_level} из 10.")
        return recommendation(
            rule_id="pain_or_illness_stop",
            status="stop",
            action="rest_and_seek_guidance",
            title="Сегодня пропустите тренировку",
            message="Боль или симптомы болезни несовместимы с безопасной тренировочной рекомендацией. Не начинайте нагрузку и оцените необходимость консультации специалиста.",
            reasons=reasons,
            workout=workout,
        )

    severe_fatigue = checkin.fatigue_0_10 is not None and checkin.fatigue_0_10 >= 9
    poor_sleep_with_fatigue = (
        checkin.sleep_quality_0_10 is not None
        and checkin.sleep_quality_0_10 <= 2
        and checkin.fatigue_0_10 is not None
        and checkin.fatigue_0_10 >= 7
    )
    if checkin.pain or profile.recovery_status == "strained" or severe_fatigue or poor_sleep_with_fatigue:
        reasons = []
        if checkin.pain:
            reasons.append("Отмечена боль, даже если её уровень невысокий.")
        if profile.recovery_status == "strained":
            reasons.append("В профиле указан статус перегрузки.")
        if severe_fatigue:
            reasons.append(f"Усталость отмечена как {checkin.fatigue_0_10} из 10.")
        if poor_sleep_with_fatigue:
            reasons.append("Очень плохой сон сочетается с высокой усталостью.")
        return recommendation(
            rule_id="rest_required",
            status="rest",
            action="rest_or_gentle_mobility",
            title="Сегодня восстановление важнее плана",
            message="Откажитесь от беговой нагрузки. Допустима только спокойная прогулка или мягкая mobility без боли и утомления.",
            reasons=reasons,
            workout=workout,
        )

    high_fatigue = checkin.fatigue_0_10 is not None and checkin.fatigue_0_10 >= 7
    poor_sleep = checkin.sleep_quality_0_10 is not None and checkin.sleep_quality_0_10 <= 4
    high_soreness = checkin.soreness_0_10 is not None and checkin.soreness_0_10 >= 7
    high_stress = checkin.stress_0_10 is not None and checkin.stress_0_10 >= 8
    if workout_is_hard(workout) and (high_fatigue or poor_sleep or high_soreness or high_stress):
        reasons = []
        if high_fatigue:
            reasons.append(f"Усталость отмечена как {checkin.fatigue_0_10} из 10.")
        if poor_sleep:
            reasons.append(f"Качество сна отмечено как {checkin.sleep_quality_0_10} из 10.")
        if high_soreness:
            reasons.append(f"Мышечная болезненность отмечена как {checkin.soreness_0_10} из 10.")
        if high_stress:
            reasons.append(f"Стресс отмечен как {checkin.stress_0_10} из 10.")
        reasons.append("Сегодня запланирована интенсивная тренировка.")
        return recommendation(
            rule_id="replace_hard_workout",
            status="modify",
            action="easy_replacement",
            title="Замените интенсивную работу лёгким бегом",
            message="Сегодняшние сигналы не поддерживают качественную интенсивную нагрузку. Лёгкая замена сохранит ритм без попытки догнать объём.",
            reasons=reasons,
            workout=workout,
            prescribed_workout=easy_replacement(workout),
        )

    moderate_fatigue = checkin.fatigue_0_10 is not None and checkin.fatigue_0_10 >= 6
    moderate_soreness = checkin.soreness_0_10 is not None and checkin.soreness_0_10 >= 5
    moderate_stress = checkin.stress_0_10 is not None and checkin.stress_0_10 >= 7
    if workout is not None and (moderate_fatigue or poor_sleep or moderate_soreness or moderate_stress):
        reasons = []
        if moderate_fatigue:
            reasons.append(f"Усталость отмечена как {checkin.fatigue_0_10} из 10.")
        if poor_sleep:
            reasons.append(f"Качество сна отмечено как {checkin.sleep_quality_0_10} из 10.")
        if moderate_soreness:
            reasons.append(f"Мышечная болезненность отмечена как {checkin.soreness_0_10} из 10.")
        if moderate_stress:
            reasons.append(f"Стресс отмечен как {checkin.stress_0_10} из 10.")
        return recommendation(
            rule_id="shorten_workout",
            status="modify",
            action="shorten_easy",
            title="Сократите сегодняшнюю тренировку",
            message="Снизьте объём примерно на 30% и держите нагрузку контролируемой. Не переносите сокращённый объём на другие дни.",
            reasons=reasons,
            workout=workout,
            prescribed_workout=shortened_workout(workout),
        )

    safety = safety_check(profile)
    if workout is None:
        return recommendation(
            rule_id="no_workout_planned",
            status="proceed",
            action="optional_easy_movement",
            title="Сегодня можно оставить день свободным",
            message="Запланированной тренировки нет. При желании выберите прогулку или очень лёгкое движение, но не компенсируйте пропущенные километры.",
            reasons=["На сегодня нет активной запланированной тренировки."],
            workout=None,
        )
    if safety["conservative_mode"]:
        return recommendation(
            rule_id="profile_conservative",
            status="proceed",
            action="proceed_conservatively",
            title="Выполняйте тренировку консервативно",
            message="Текущий check-in позволяет тренироваться, но профильные ограничения требуют запаса по интенсивности и немедленной остановки при ухудшении самочувствия.",
            reasons=list(safety["warnings"]),
            workout=workout,
        )
    return recommendation(
        rule_id="proceed_as_planned",
        status="proceed",
        action="proceed_as_planned",
        title="Сегодня можно тренироваться по плану",
        message="Check-in не выявил причин снижать запланированную нагрузку. Сохраняйте целевую интенсивность и следите за изменением самочувствия.",
        reasons=["Сигналы сна, усталости, стресса, soreness и боли не требуют снижения нагрузки."],
        workout=workout,
    )


def today_context(db: Session, user: User, *, lock: bool = False) -> tuple[date, AthleteProfile, TrainingPlanWorkout | None]:
    today = today_for_user(db, user)
    if lock:
        profile = db.scalar(
            select(AthleteProfile)
            .where(AthleteProfile.user_id == user.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ) or get_or_create_profile(db, user)
        plan = db.scalar(
            select(TrainingPlan)
            .where(TrainingPlan.user_id == user.id, TrainingPlan.status == "active")
            .options(
                selectinload(TrainingPlan.workouts).selectinload(TrainingPlanWorkout.completed_activity),
                selectinload(TrainingPlan.workouts).selectinload(TrainingPlanWorkout.feedback),
                selectinload(TrainingPlan.workouts).selectinload(TrainingPlanWorkout.blocks),
            )
            .order_by(TrainingPlan.created_at.desc(), TrainingPlan.id.desc())
            .limit(1)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    else:
        profile = get_or_create_profile(db, user)
        plan = active_training_plan(db, user)
    workout = None
    if lock and plan:
        workout = db.scalar(
            select(TrainingPlanWorkout)
            .where(
                TrainingPlanWorkout.plan_id == plan.id,
                TrainingPlanWorkout.scheduled_date == today,
                TrainingPlanWorkout.status.in_(("planned", "rescheduled")),
            )
            .options(
                selectinload(TrainingPlanWorkout.completed_activity),
                selectinload(TrainingPlanWorkout.feedback),
                selectinload(TrainingPlanWorkout.blocks),
            )
            .order_by(TrainingPlanWorkout.day_index, TrainingPlanWorkout.id)
            .limit(1)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    elif plan:
        workout = next(
            (
                item
                for item in sorted(plan.workouts, key=lambda candidate: (candidate.day_index, candidate.id))
                if item.scheduled_date == today and item.status in {"planned", "rescheduled"}
            ),
            None,
        )
    return today, profile, workout


def today_checkin(db: Session, user: User, checkin_date: date, *, lock: bool = False) -> DailyReadinessCheckIn | None:
    query = select(DailyReadinessCheckIn).where(
            DailyReadinessCheckIn.user_id == user.id,
            DailyReadinessCheckIn.checkin_date == checkin_date,
        )
    if lock:
        query = query.with_for_update()
    return db.scalar(query)


def checkin_to_dict(checkin: DailyReadinessCheckIn | None) -> dict[str, object] | None:
    if checkin is None:
        return None
    return {
        "id": checkin.id,
        "checkin_date": checkin.checkin_date,
        "sleep_quality_0_10": checkin.sleep_quality_0_10,
        "fatigue_0_10": checkin.fatigue_0_10,
        "soreness_0_10": checkin.soreness_0_10,
        "stress_0_10": checkin.stress_0_10,
        "pain": checkin.pain,
        "pain_level_0_10": checkin.pain_level_0_10,
        "pain_notes": checkin.pain_notes,
        "illness_symptoms": checkin.illness_symptoms,
        "illness_notes": checkin.illness_notes,
        "notes": checkin.notes,
        "created_at": checkin.created_at,
        "updated_at": checkin.updated_at,
    }


def readiness_to_dict(
    checkin_date: date,
    checkin: DailyReadinessCheckIn | None,
    workout: TrainingPlanWorkout | None,
    current_recommendation: dict[str, object],
) -> dict[str, object]:
    return {
        "date": checkin_date,
        "checkin": checkin_to_dict(checkin),
        "today_workout": workout_to_dict(workout) if workout else None,
        "recommendation": current_recommendation,
        "saved_recommendation": checkin.recommendation_snapshot if checkin else None,
    }


def daily_readiness_for_today(db: Session, user: User) -> dict[str, object]:
    checkin_date, profile, workout = today_context(db, user)
    checkin = today_checkin(db, user, checkin_date)
    current_recommendation = daily_readiness_recommendation(checkin, profile, workout)
    return readiness_to_dict(checkin_date, checkin, workout, current_recommendation)


def save_daily_readiness_checkin(db: Session, user: User, payload: DailyReadinessCheckInUpsert) -> dict[str, object]:
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    checkin_date, profile, workout = today_context(db, user, lock=True)
    checkin = today_checkin(db, user, checkin_date, lock=True)
    if checkin is None:
        checkin = DailyReadinessCheckIn(user_id=user.id, checkin_date=checkin_date)
        db.add(checkin)

    values = payload.model_dump()
    values["pain"] = bool(values["pain"])
    values["illness_symptoms"] = bool(values["illness_symptoms"])
    if not values["pain"]:
        values["pain_level_0_10"] = None
        values["pain_notes"] = None
    if not values["illness_symptoms"]:
        values["illness_notes"] = None
    for field, value in values.items():
        setattr(checkin, field, value)

    current_recommendation = daily_readiness_recommendation(checkin, profile, workout)
    checkin.recommendation_snapshot = current_recommendation
    db.add(checkin)
    db.flush()
    db.refresh(checkin)
    result = readiness_to_dict(checkin_date, checkin, workout, current_recommendation)
    db.commit()
    return result
