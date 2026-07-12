import hashlib
import json
import secrets
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import AthleteProfile, DailyReadinessActionPreview, DailyReadinessCheckIn, TrainingPlan, TrainingPlanRecommendationAudit, TrainingPlanWorkout, TrainingPlanWorkoutBlock, User
from app.schemas.common import DailyReadinessCheckInUpsert
from app.services.audit import log_audit_event
from app.services.coaching_events import record_coaching_event
from app.services.constraint_engine import HardWorkoutPolicy, is_hard_workout, validate_readiness_action_target
from app.services.dashboard import active_training_plan
from app.services.plan_versions import action_plan_snapshot, create_plan_version, json_safe, workout_snapshot
from app.services.planning import today_for_user, workout_to_dict
from app.services.profile import get_or_create_profile, safety_check


RULE_VERSION = "daily-readiness-v1"
DISCLAIMER = "Runforfan не является медицинским устройством. При боли, головокружении, одышке или ухудшении самочувствия прекратите нагрузку и обратитесь к специалисту."
HARD_WORKOUT_TYPES = {"interval", "intervals", "tempo", "threshold", "race", "fartlek", "hills", "hill_repeats"}
HARD_INTENSITIES = {"hard", "tempo", "threshold", "interval", "race", "vo2max"}
READINESS_HARD_POLICY = HardWorkoutPolicy(frozenset(HARD_WORKOUT_TYPES), frozenset(HARD_INTENSITIES), normalize_case=True)
APPLICABLE_ACTIONS = {"shorten_easy", "easy_replacement"}
ACTION_PREVIEW_TTL_MINUTES = 10
READINESS_ADJUSTMENT_MARKER = "Readiness adjustment:"


class ReadinessActionConflict(ValueError):
    def __init__(self, message: str, reason: str):
        super().__init__(message)
        self.reason = reason


def workout_is_hard(workout: TrainingPlanWorkout | None) -> bool:
    if workout is None:
        return False
    return is_hard_workout(workout.workout_type, workout.intensity, policy=READINESS_HARD_POLICY)


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

    if workout is not None and READINESS_ADJUSTMENT_MARKER in (workout.description or ""):
        return recommendation(
            rule_id="readiness_action_already_applied",
            status="proceed",
            action="proceed_conservatively",
            title="Сегодняшняя тренировка уже облегчена",
            message="Рекомендация уже применена к тренировке. Не сокращайте её повторно и не компенсируйте объём позже.",
            reasons=["К сегодняшней тренировке уже применена readiness-корректировка."],
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
    pain_was_reported = bool(checkin and checkin.pain)
    illness_was_reported = bool(checkin and checkin.illness_symptoms)
    previous_signals = checkin_to_dict(checkin)
    if previous_signals:
        previous_signals = {key: value for key, value in previous_signals.items() if key not in {"id", "created_at", "updated_at"}}
    previous_recommendation = canonical_recommendation(checkin.recommendation_snapshot or {}) if checkin else None
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
    current_signals = checkin_to_dict(checkin) or {}
    comparable_signals = {key: value for key, value in current_signals.items() if key not in {"id", "created_at", "updated_at"}}
    if comparable_signals != previous_signals or canonical_recommendation(current_recommendation) != previous_recommendation:
        record_coaching_event(
            db,
            user_id=user.id,
            event_type="readiness_checkin_saved",
            category="user_input",
            source="daily_readiness",
            occurred_at=datetime.now(UTC),
            plan_id=workout.plan_id if workout else None,
            workout_id=workout.id if workout else None,
            checkin_id=checkin.id,
            payload={
                "checkin_date": checkin_date,
                "signals": current_signals,
                "recommendation": current_recommendation,
            },
        )
    if checkin.pain and not pain_was_reported:
        record_coaching_event(
            db,
            user_id=user.id,
            event_type="pain_reported",
            category="user_input",
            source="daily_readiness",
            plan_id=workout.plan_id if workout else None,
            workout_id=workout.id if workout else None,
            checkin_id=checkin.id,
            payload={"pain_level_0_10": checkin.pain_level_0_10, "notes": checkin.pain_notes},
        )
    if checkin.illness_symptoms and not illness_was_reported:
        record_coaching_event(
            db,
            user_id=user.id,
            event_type="illness_reported",
            category="user_input",
            source="daily_readiness",
            plan_id=workout.plan_id if workout else None,
            workout_id=workout.id if workout else None,
            checkin_id=checkin.id,
            payload={"notes": checkin.illness_notes},
        )
    result = readiness_to_dict(checkin_date, checkin, workout, current_recommendation)
    db.commit()
    return result


def canonical_recommendation(value: dict[str, object]) -> dict[str, object]:
    return {key: item for key, item in value.items() if key != "generated_at"}


def action_state_snapshot(
    user: User,
    checkin: DailyReadinessCheckIn,
    profile: AthleteProfile,
    plan: TrainingPlan,
    workout: TrainingPlanWorkout,
    current_recommendation: dict[str, object],
) -> dict[str, object]:
    return json_safe({
        "user_id": user.id,
        "checkin": {
            **(checkin_to_dict(checkin) or {}),
            "recommendation_snapshot": checkin.recommendation_snapshot,
        },
        "profile": {
            "id": profile.id,
            "updated_at": profile.updated_at,
            "recovery_status": profile.recovery_status,
            "conservative_mode": profile.conservative_mode,
            "injury_notes": profile.injury_notes,
            "health_conditions": profile.health_conditions,
        },
        "plan": {"id": plan.id, "status": plan.status, "updated_at": plan.updated_at},
        "workout": workout_snapshot(workout),
        "week_workouts": [
            workout_snapshot(item)
            for item in sorted(plan.workouts, key=lambda candidate: (candidate.week_index, candidate.day_index, candidate.id or 0))
            if item.week_index == workout.week_index
        ],
        "recommendation": canonical_recommendation(current_recommendation),
    })


def action_state_fingerprint(snapshot: dict[str, object]) -> str:
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def appended_adjustment_description(workout: TrainingPlanWorkout, action: str) -> str:
    instruction = (
        "сократить сегодняшний объём примерно на 30% и не компенсировать его позже"
        if action == "shorten_easy"
        else "заменить интенсивную работу лёгким бегом и не переносить интервалы на другой день"
    )
    marker = f"{READINESS_ADJUSTMENT_MARKER} {instruction}."
    return f"{workout.description.rstrip()}\n\n{marker}" if workout.description else marker


def preview_block(block: TrainingPlanWorkoutBlock, *, scale: float = 1.0) -> dict[str, object]:
    return {
        "block_index": block.block_index,
        "block_type": block.block_type,
        "repeat_count": block.repeat_count,
        "target_distance_km": round(block.target_distance_km * scale, 2) if block.target_distance_km is not None else None,
        "target_duration_seconds": round(block.target_duration_seconds * scale) if block.target_duration_seconds is not None else None,
        "target_pace_min_seconds_per_km": block.target_pace_min_seconds_per_km,
        "target_pace_max_seconds_per_km": block.target_pace_max_seconds_per_km,
        "target_hr_min_bpm": block.target_hr_min_bpm,
        "target_hr_max_bpm": block.target_hr_max_bpm,
        "target_rpe_min": block.target_rpe_min,
        "target_rpe_max": block.target_rpe_max,
        "description": block.description,
    }


def action_target(workout: TrainingPlanWorkout, current_recommendation: dict[str, object]) -> dict[str, object]:
    action = str(current_recommendation.get("action") or "")
    prescription = current_recommendation.get("prescribed_workout")
    validation = validate_readiness_action_target(
        action=action,
        prescription=prescription,
        applicable_actions=APPLICABLE_ACTIONS,
        completed_activity_id=workout.completed_activity_id,
        status=workout.status,
        workout_is_hard=workout_is_hard(workout),
        block_target_rpe_maxes=(block.target_rpe_max for block in workout.blocks),
    )
    if not validation.allowed:
        raise ReadinessActionConflict(validation.message or "Today's readiness recommendation cannot be applied", validation.reason or "action_not_applicable")
    if action == "shorten_easy" and isinstance(prescription, dict):
        blocks = [preview_block(block, scale=0.7) for block in sorted(workout.blocks, key=lambda item: (item.block_index, item.id or 0))]
        return {
            "workout_type": workout.workout_type,
            "title": workout.title,
            "distance_km": prescription.get("distance_km"),
            "duration_seconds": prescription.get("duration_seconds"),
            "intensity": workout.intensity,
            "description": appended_adjustment_description(workout, action),
            "blocks": blocks,
        }
    if not isinstance(prescription, dict):
        raise ReadinessActionConflict("Today's readiness recommendation cannot be applied", "action_not_applicable")
    duration = prescription.get("duration_seconds")
    return {
        "workout_type": "easy",
        "title": "Лёгкий восстановительный бег",
        "distance_km": None,
        "duration_seconds": duration,
        "intensity": "easy",
        "description": appended_adjustment_description(workout, action),
        "blocks": [{
            "block_index": 1,
            "block_type": "work",
            "repeat_count": 1,
            "target_distance_km": None,
            "target_duration_seconds": duration,
            "target_pace_min_seconds_per_km": None,
            "target_pace_max_seconds_per_km": None,
            "target_hr_min_bpm": None,
            "target_hr_max_bpm": None,
            "target_rpe_min": 2,
            "target_rpe_max": 3,
            "description": "Непрерывный лёгкий бег в разговорном темпе без ускорений.",
        }],
    }


def action_changes(workout: TrainingPlanWorkout, target: dict[str, object]) -> list[dict[str, object]]:
    before = workout_snapshot(workout)
    fields = ("workout_type", "title", "distance_km", "duration_seconds", "intensity", "description", "blocks")
    return [
        {"field": field, "before": before.get(field), "after": json_safe(target.get(field))}
        for field in fields
        if before.get(field) != json_safe(target.get(field))
    ]


def weekly_effect(plan: TrainingPlan, workout: TrainingPlanWorkout, target: dict[str, object]) -> dict[str, object]:
    week_workouts = [item for item in plan.workouts if item.week_index == workout.week_index]
    distance_before = round(sum(item.distance_km or 0 for item in week_workouts), 2)
    duration_before = sum(item.duration_seconds or 0 for item in week_workouts)
    return {
        "planned_distance_km_before": distance_before,
        "planned_distance_km_after": round(distance_before - (workout.distance_km or 0) + (target.get("distance_km") or 0), 2),
        "planned_duration_seconds_before": duration_before,
        "planned_duration_seconds_after": duration_before - (workout.duration_seconds or 0) + int(target.get("duration_seconds") or 0),
    }


def active_plan_for_workout(db: Session, user: User, workout: TrainingPlanWorkout, *, lock: bool) -> TrainingPlan | None:
    query = (
        select(TrainingPlan)
        .where(TrainingPlan.id == workout.plan_id, TrainingPlan.user_id == user.id, TrainingPlan.status == "active")
        .options(
            selectinload(TrainingPlan.workouts).selectinload(TrainingPlanWorkout.completed_activity),
            selectinload(TrainingPlan.workouts).selectinload(TrainingPlanWorkout.feedback),
            selectinload(TrainingPlan.workouts).selectinload(TrainingPlanWorkout.blocks),
        )
        .execution_options(populate_existing=True)
    )
    if lock:
        query = query.with_for_update()
    return db.scalar(query)


def build_action_preview_snapshot(
    preview_id: str,
    expires_at: datetime,
    checkin_date: date,
    plan: TrainingPlan,
    workout: TrainingPlanWorkout,
    current_recommendation: dict[str, object],
    target: dict[str, object],
) -> dict[str, object]:
    action = str(current_recommendation["action"])
    summary = (
        "Сегодняшняя тренировка будет сокращена примерно на 30%. Другие тренировки не изменятся."
        if action == "shorten_easy"
        else "Сегодняшняя интенсивная тренировка будет заменена лёгким бегом. Другие тренировки не изменятся."
    )
    return json_safe({
        "preview_id": preview_id,
        "expires_at": expires_at,
        "date": checkin_date,
        "action": action,
        "action_type": "shorten" if action == "shorten_easy" else "replace_easy",
        "rule_version": current_recommendation["rule_version"],
        "rule_id": current_recommendation["rule_id"],
        "workout": workout_to_dict(workout),
        "changes": action_changes(workout, target),
        "weekly_effect": weekly_effect(plan, workout, target),
        "summary": summary,
        "disclaimer": DISCLAIMER,
        "target": target,
    })


def create_daily_readiness_action_preview(db: Session, user: User) -> dict[str, object]:
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    checkin_date, profile, workout = today_context(db, user, lock=True)
    if workout is None:
        raise ReadinessActionConflict("Today's readiness recommendation cannot be applied", "no_today_workout")
    plan = active_plan_for_workout(db, user, workout, lock=True)
    if plan is None:
        raise ReadinessActionConflict("Today's readiness recommendation cannot be applied", "no_current_plan")
    checkin = today_checkin(db, user, checkin_date, lock=True)
    if checkin is None:
        raise ReadinessActionConflict("Today's readiness recommendation cannot be applied", "checkin_required")
    current_recommendation = daily_readiness_recommendation(checkin, profile, workout)
    target = action_target(workout, current_recommendation)
    preview_id = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(minutes=ACTION_PREVIEW_TTL_MINUTES)
    snapshot = action_state_snapshot(user, checkin, profile, plan, workout, current_recommendation)
    preview_snapshot = build_action_preview_snapshot(preview_id, expires_at, checkin_date, plan, workout, current_recommendation, target)
    preview = DailyReadinessActionPreview(
        id=preview_id,
        user_id=user.id,
        plan_id=plan.id,
        workout_id=workout.id,
        checkin_id=checkin.id,
        checkin_date=checkin_date,
        action=str(current_recommendation["action"]),
        rule_version=str(current_recommendation["rule_version"]),
        recommendation_snapshot=json_safe(current_recommendation),
        preview_snapshot=preview_snapshot,
        state_fingerprint=action_state_fingerprint(snapshot),
        expires_at=expires_at,
    )
    db.add(preview)
    db.commit()
    return {key: value for key, value in preview_snapshot.items() if key != "target"}


def apply_target(db: Session, workout: TrainingPlanWorkout, target: dict[str, object]) -> None:
    for field in ("workout_type", "title", "distance_km", "duration_seconds", "intensity", "description"):
        setattr(workout, field, target.get(field))
    for block in list(workout.blocks):
        workout.blocks.remove(block)
        db.delete(block)
    db.flush()
    for block in target.get("blocks") or []:
        workout.blocks.append(TrainingPlanWorkoutBlock(**block))


def load_action_preview(db: Session, user: User, preview_id: str) -> DailyReadinessActionPreview | None:
    return db.scalar(
        select(DailyReadinessActionPreview)
        .where(DailyReadinessActionPreview.id == preview_id, DailyReadinessActionPreview.user_id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def apply_daily_readiness_action_preview(db: Session, user: User, preview_id: str) -> dict[str, object]:
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    preview = load_action_preview(db, user, preview_id)
    now = datetime.now(UTC)
    if preview is None:
        raise ReadinessActionConflict("Action preview is invalid, expired, or no longer applicable", "preview_invalid_or_expired")
    if preview.applied_at is not None and preview.applied_response_json:
        return {**preview.applied_response_json, "status": "already_applied"}
    if preview.expires_at < now:
        raise ReadinessActionConflict("Action preview is invalid, expired, or no longer applicable", "preview_invalid_or_expired")

    checkin_date, profile, workout = today_context(db, user, lock=True)
    if workout is None:
        raise ReadinessActionConflict("Action preview is stale; create a new preview", "preview_stale")
    plan = active_plan_for_workout(db, user, workout, lock=True)
    checkin = today_checkin(db, user, checkin_date, lock=True)
    if (
        plan is None
        or checkin is None
        or checkin_date != preview.checkin_date
        or plan.id != preview.plan_id
        or workout.id != preview.workout_id
        or checkin.id != preview.checkin_id
    ):
        raise ReadinessActionConflict("Action preview is stale; create a new preview", "preview_stale")
    current_recommendation = daily_readiness_recommendation(checkin, profile, workout)
    target = action_target(workout, current_recommendation)
    snapshot = action_state_snapshot(user, checkin, profile, plan, workout, current_recommendation)
    if (
        action_state_fingerprint(snapshot) != preview.state_fingerprint
        or canonical_recommendation(current_recommendation) != canonical_recommendation(preview.recommendation_snapshot)
        or target != preview.preview_snapshot.get("target")
    ):
        raise ReadinessActionConflict("Action preview is stale; create a new preview", "preview_stale")

    changes = list(preview.preview_snapshot.get("changes") or [])
    pre_snapshot = action_plan_snapshot(plan)
    apply_target(db, workout, target)
    db.flush()
    recommendation_audit = TrainingPlanRecommendationAudit(
        user_id=user.id,
        plan_id=plan.id,
        action="apply_daily_readiness_action",
        status="applied",
        recommendations_snapshot=preview.recommendation_snapshot,
        preview_changes={"preview_id": preview.id, "changes": changes},
        applied_changes={"preview_id": preview.id, "changes": changes},
    )
    db.add(recommendation_audit)
    db.flush()
    version = create_plan_version(
        db,
        user,
        plan,
        "daily_readiness_action",
        f"Applied {preview.action} to workout #{workout.id}",
        pre_snapshot=pre_snapshot,
    )
    db.flush()
    audit_event = log_audit_event(
        db,
        user.id,
        "daily_readiness_action_applied",
        "training_plan_workout",
        workout.id,
        {
            "preview_id": preview.id,
            "plan_id": plan.id,
            "action": preview.action,
            "rule_version": preview.rule_version,
            "rule_id": preview.recommendation_snapshot.get("rule_id"),
            "recommendation_audit_id": recommendation_audit.id,
            "plan_version_id": version.id,
            "date": checkin_date.isoformat(),
            "changes": changes,
        },
    )
    db.flush()
    response = json_safe({
        "status": "applied",
        "preview_id": preview.id,
        "action": preview.action,
        "action_type": preview.preview_snapshot.get("action_type") or ("shorten" if preview.action == "shorten_easy" else "replace_easy"),
        "date": checkin_date,
        "workout": workout_to_dict(workout),
        "plan_version_id": version.id,
        "plan_version_number": version.version_number,
        "recommendation_audit_id": recommendation_audit.id,
        "audit_log_id": audit_event.id,
        "summary": preview.preview_snapshot["summary"],
    })
    preview.applied_at = now
    preview.recommendation_audit_id = recommendation_audit.id
    preview.plan_version_id = version.id
    preview.audit_log_id = audit_event.id
    preview.applied_response_json = response
    db.commit()
    return response
