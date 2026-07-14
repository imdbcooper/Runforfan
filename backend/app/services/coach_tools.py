from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CoachMemory, CoachMessage, CoachingEvent, TrainingPlan, TrainingPlanWorkout, User, WeeklyReview
from app.services.athlete_state import materialize_athlete_state
from app.services.readiness import daily_readiness_for_today
from app.services.weekly_review import materialize_weekly_review


def _safe_state(state: dict[str, object]) -> dict[str, object]:
    signals = []
    for raw_signal in state.get("signals") or []:
        if not isinstance(raw_signal, dict):
            continue
        item = dict(raw_signal)
        if item.get("key") == "recovery_signals" and isinstance(item.get("value"), dict):
            value = dict(item["value"])
            value["metrics"] = [
                {key: metric.get(key) for key in ("id", "metric_key", "value", "unit", "observed_at", "quality", "freshness", "baseline", "baseline_samples", "anomaly")}
                for metric in value.get("metrics") or []
                if isinstance(metric, dict)
            ]
            item["value"] = value
        signals.append(item)
    return {
        "snapshot_id": state.get("snapshot_id"), "local_date": state.get("local_date"),
        "status": state.get("status"), "headline": state.get("headline"),
        "summary": state.get("summary"), "signals": signals,
        "weekly": state.get("weekly"), "limitations": state.get("limitations"),
    }


def build_coach_context(db: Session, user: User, conversation_id: str) -> dict[str, Any]:
    """Build a deliberately narrow DTO. User text is data, never instructions."""
    limitations: list[str] = []
    try:
        state = _safe_state(materialize_athlete_state(db, user))
    except Exception:
        state = {"snapshot_id": None, "local_date": datetime.now().date(), "status": "unknown", "signals": [], "limitations": ["Athlete State unavailable."]}
        limitations.append("Athlete State unavailable; use caution.")
    try:
        readiness = daily_readiness_for_today(db, user)
    except Exception:
        readiness = {"date": state["local_date"], "recommendation": {"status": "checkin_required", "action": "checkin_required", "rule_version": None}, "today_workout": None}
        limitations.append("Today readiness unavailable; use caution.")
    try:
        review = materialize_weekly_review(db, user)
    except Exception:
        review = {"review_id": None, "recommended_strategy": None, "resolution_status": "partial", "coverage": {"confidence": "none", "freshness": "missing"}, "limitations": ["Weekly Review unavailable."]}
        limitations.append("Weekly Review unavailable; no progression previews.")
    today = state["local_date"]
    upcoming = list(db.scalars(
        select(TrainingPlanWorkout).join(TrainingPlan, TrainingPlan.id == TrainingPlanWorkout.plan_id).where(
            TrainingPlan.user_id == user.id, TrainingPlan.status == "active",
            TrainingPlanWorkout.status.in_(("planned", "rescheduled")),
            TrainingPlanWorkout.scheduled_date >= today,
            TrainingPlanWorkout.scheduled_date <= today + timedelta(days=14),
        ).order_by(TrainingPlanWorkout.scheduled_date, TrainingPlanWorkout.id)
    ))
    events = list(db.scalars(
        select(CoachingEvent).where(CoachingEvent.user_id == user.id)
        .order_by(CoachingEvent.occurred_at.desc(), CoachingEvent.id.desc()).limit(20)
    ))
    memory = list(db.scalars(select(CoachMemory).where(CoachMemory.user_id == user.id, CoachMemory.status == "confirmed").order_by(CoachMemory.memory_key)))
    history = list(db.scalars(
        select(CoachMessage).where(CoachMessage.user_id == user.id, CoachMessage.conversation_id == conversation_id)
        .order_by(CoachMessage.created_at.desc(), CoachMessage.id.desc()).limit(12)
    ))
    history.reverse()
    history_out: list[dict[str, str]] = []
    remaining = 6000
    for item in history:
        if item.content_redacted or not item.content or remaining <= 0:
            continue
        content = item.content[: min(1200, remaining)]
        remaining -= len(content)
        history_out.append({"role": item.role, "content": content})
    sources = {"athlete_state", "today_readiness", "weekly_review"}
    sources.update(f"workout:{item.id}" for item in upcoming)
    sources.update(f"event:{item.id}" for item in events)
    sources.update(f"memory:{item.memory_key}" for item in memory)
    return {
        "sources": sorted(sources),
        "athlete_state": state,
        "today_readiness": {"date": readiness["date"], "recommendation": readiness["recommendation"], "today_workout": _safe_workout(readiness["today_workout"])},
        "weekly_review": {"review_id": review["review_id"], "recommended_strategy": review.get("recommended_strategy"), "resolution_status": review.get("resolution_status"), "coverage": review.get("coverage"), "limitations": review.get("limitations")},
        "upcoming_workouts": [{"id": item.id, "scheduled_date": item.scheduled_date, "status": item.status, "workout_type": item.workout_type, "distance_km": item.distance_km, "duration_seconds": item.duration_seconds, "intensity": item.intensity} for item in upcoming],
        "coaching_events": [{"id": item.id, "type": item.event_type, "source": item.source, "occurred_at": item.occurred_at, "plan_id": item.plan_id, "workout_id": item.workout_id, "checkin_id": item.checkin_id} for item in events],
        "memory": {item.memory_key: item.value_json for item in memory},
        "history": history_out,
        "limitations": limitations,
    }


def _safe_workout(workout: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(workout, dict):
        return None
    return {key: workout.get(key) for key in ("id", "scheduled_date", "status", "workout_type", "distance_km", "duration_seconds", "intensity")}


def authoritative_safety(context: dict[str, Any], message: str) -> str:
    text = message.casefold().replace("ё", "е")
    medical_patterns = (
        r"\b(?:pain(?:ful)?|hurt(?:ing)?|injur(?:y|ed|ies)|ill(?:ness)?|sick|fever|nausea|nauseous|dizz(?:y|iness)|swelling|swollen|fractur(?:e|ed)|sprain(?:ed)?|bleed(?:ing)?|faint(?:ed|ing)?)\b",
        r"\bchest\s+(?:pain|pressure)\b|\bshortness\s+of\s+breath\b|\b(?:cannot|can't|trouble)\s+breath(?:e|ing)\b",
        r"\b(?:боль|боли|болит|болят|больно|болезн\w*|болею|болеет|болеют|заболел\w*|травм\w*|температур\w*|лихорад\w*|тошн\w*|головокруж\w*|отек\w*|перелом\w*|растяжен\w*|растян\w*|кровотеч\w*|обморок\w*)\b",
        r"\b(?:боль|давление)\s+в\s+груди\b|\bодышк\w*\b|\bтрудно\s+дышать\b|\bпотер\w*\s+сознани\w*\b",
    )
    if any(re.search(pattern, text) for pattern in medical_patterns):
        return "medical_boundary"
    blocked_patterns = (
        r"\bignore\b|\bdouble\b|\bincrease\s+mileage\b|\bapply\b|\bcustom\s+workout\b|\b(?:system\s+)?prompt\b|\bapi\s+key\b|\banother\s+athlete\b",
        r"\bигнорир\w*\b|\bудвой\w*\b|\bпримени\w*\b|\bкастомн\w*\s+трениров\w*\b|\bсистемн\w*\s+промпт\w*\b|\bapi[- ]?ключ\w*\b|\bчуж\w*\s+(?:спортсмен|атлет|план|данн)\w*\b",
    )
    if any(re.search(pattern, text) for pattern in blocked_patterns):
        return "caution"
    recommendation = context["today_readiness"]["recommendation"]
    if recommendation.get("status") in {"stop", "rest"}:
        return "medical_boundary"
    if recommendation.get("status") in {"modify", "checkin_required"} or context["athlete_state"].get("status") in {"risk", "watch", "unknown"}:
        return "caution"
    return "normal"
