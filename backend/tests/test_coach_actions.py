import unittest
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

try:
    from app.db.migrations.runner import MIGRATIONS
    from app.models import CoachActionPreview, TrainingPlan, TrainingPlanWorkout, User
    from app.schemas.common import CoachActionPreviewRequest
    from app.services.coach_actions import action_state_snapshot, action_target, apply_coach_action_preview, calendar_week_effects, state_fingerprint, weekly_effect
except ModuleNotFoundError as exc:
    if exc.name in {"pydantic", "sqlalchemy"}:
        raise unittest.SkipTest("Backend dependencies are required for coach action tests") from exc
    raise


TODAY = date(2026, 7, 12)


def make_workout(workout_id: int, scheduled_date: date, *, workout_type: str = "easy", intensity: str = "easy", status: str = "planned", distance_km: float = 8.0) -> TrainingPlanWorkout:
    workout = TrainingPlanWorkout(
        id=workout_id, plan_id=20, scheduled_date=scheduled_date, status=status, week_index=1, day_index=workout_id,
        workout_type=workout_type, title=f"Workout {workout_id}", distance_km=distance_km, duration_seconds=3000, intensity=intensity,
    )
    workout.blocks = []
    workout.feedback = None
    workout.completed_activity = None
    return workout


def make_plan(*workouts: TrainingPlanWorkout) -> TrainingPlan:
    return TrainingPlan(id=20, user_id=1, title="Plan", goal_type="10k", available_days_per_week=3, status="active", workouts=list(workouts))


class CoachActionTests(unittest.TestCase):
    def test_migration_creates_durable_action_previews(self):
        migration = next(statements for version, statements in MIGRATIONS if version == "20260712_0024_coach_action_previews")
        sql = "\n".join(migration)

        self.assertIn("CREATE TABLE IF NOT EXISTS coach_action_previews", sql)
        self.assertIn("coaching_event_id", sql)
        self.assertIn("ix_coach_action_previews_expires_at", sql)

    def test_readiness_actions_have_canonical_stage_two_names(self):
        from app.services.readiness import build_action_preview_snapshot

        workout = make_workout(1, TODAY)
        plan = make_plan(workout)
        recommendation = {"action": "shorten_easy", "rule_version": "v1", "rule_id": "low_readiness"}
        target = {"distance_km": 5.0, "duration_seconds": 2100}
        preview = build_action_preview_snapshot("token", datetime.now(UTC), TODAY, plan, workout, recommendation, target)
        self.assertEqual(preview["action"], "shorten_easy")
        self.assertEqual(preview["action_type"], "shorten")

    def test_schema_requires_reason_and_action_specific_date(self):
        with self.assertRaises(ValueError):
            CoachActionPreviewRequest(action="reschedule", reason="schedule_conflict")
        with self.assertRaises(ValueError):
            CoachActionPreviewRequest(action="skip", reason="fatigue", target_date=TODAY)
        with self.assertRaises(ValueError):
            CoachActionPreviewRequest.model_validate({"action": "skip", "reason": "fatigue", "unexpected": True})

    def test_skip_target_and_weekly_effect_remove_load(self):
        workout = make_workout(1, TODAY)
        plan = make_plan(workout, make_workout(2, TODAY + timedelta(days=2), distance_km=5.0))

        with patch("app.services.coach_actions.today_for_user", return_value=TODAY):
            target, facts = action_target(object(), User(id=1, display_name="Runner"), plan, workout, {"action": "skip", "reason": "fatigue", "target_date": None})

        self.assertEqual(target, {"status": "skipped", "scheduled_date": TODAY})
        self.assertIn("No missed volume", facts[0])
        self.assertEqual(weekly_effect(plan, workout, "skip")["planned_distance_km_after"], 5.0)

    def test_reschedule_from_skipped_restores_weekly_load(self):
        workout = make_workout(1, TODAY, status="skipped")
        plan = make_plan(workout, make_workout(2, TODAY + timedelta(days=2), distance_km=5.0))

        effect = weekly_effect(plan, workout, "reschedule")

        self.assertEqual(effect["planned_distance_km_before"], 5.0)
        self.assertEqual(effect["planned_distance_km_after"], 13.0)

    def test_cross_week_reschedule_reports_source_and_destination_effects(self):
        workout = make_workout(1, date(2026, 7, 12))
        plan = make_plan(workout, make_workout(2, date(2026, 7, 13), distance_km=5.0))

        effects = calendar_week_effects(plan, workout, {"status": "rescheduled", "scheduled_date": date(2026, 7, 14)})

        self.assertEqual(len(effects), 2)
        self.assertEqual(effects[0]["planned_distance_km_before"], 8.0)
        self.assertEqual(effects[0]["planned_distance_km_after"], 0)
        self.assertEqual(effects[1]["planned_distance_km_before"], 5.0)
        self.assertEqual(effects[1]["planned_distance_km_after"], 13.0)

    def test_same_week_reschedule_reports_one_calendar_week_effect(self):
        workout = make_workout(1, date(2026, 7, 13))
        plan = make_plan(workout)

        effects = calendar_week_effects(plan, workout, {"status": "rescheduled", "scheduled_date": date(2026, 7, 15)})

        self.assertEqual(len(effects), 1)
        self.assertEqual(effects[0]["planned_distance_km_before"], effects[0]["planned_distance_km_after"])

    def test_plan_without_target_date_uses_final_calendar_week_as_horizon(self):
        workout = make_workout(1, date(2026, 7, 13))
        plan = make_plan(workout)

        with patch("app.services.coach_actions.today_for_user", return_value=TODAY):
            target, _facts = action_target(
                object(), User(id=1, display_name="Runner"), plan, workout,
                {"action": "reschedule", "reason": "schedule_conflict", "target_date": "2026-07-19"},
            )

        self.assertEqual(target["scheduled_date"], date(2026, 7, 19))

        with patch("app.services.coach_actions.today_for_user", return_value=TODAY):
            with self.assertRaisesRegex(ValueError, "plan horizon"):
                action_target(
                    object(), User(id=1, display_name="Runner"), plan, workout,
                    {"action": "reschedule", "reason": "schedule_conflict", "target_date": "2026-07-20"},
                )

    def test_neighboring_workout_changes_action_fingerprint(self):
        workout = make_workout(1, TODAY, workout_type="interval", intensity="threshold")
        neighbor = make_workout(2, TODAY + timedelta(days=4), workout_type="tempo", intensity="threshold")
        plan = make_plan(workout, neighbor)
        user = User(id=1, display_name="Runner")
        request = {"action": "reschedule", "reason": "schedule_conflict", "target_date": "2026-07-13"}

        before = state_fingerprint(action_state_snapshot(user, plan, request))
        neighbor.scheduled_date = TODAY + timedelta(days=5)
        after = state_fingerprint(action_state_snapshot(user, plan, request))

        self.assertNotEqual(before, after)

    def test_applied_preview_remains_idempotent_after_expiry(self):
        response = {
            "status": "applied", "preview_id": "token", "action": "skip", "workout": {"id": 3},
            "plan_version_id": 6, "plan_version_number": 2, "recommendation_audit_id": 7, "audit_log_id": 8,
            "coaching_event_id": 9, "summary": "Applied",
        }
        preview = CoachActionPreview(
            id="token", user_id=1, plan_id=4, workout_id=3, action="skip", rule_version="coach-constraints-v1",
            request_snapshot={}, preview_snapshot={}, state_fingerprint="fingerprint",
            expires_at=datetime.now(UTC) - timedelta(minutes=1), applied_at=datetime.now(UTC) - timedelta(minutes=2), applied_response_json=response,
        )

        class Db:
            def __init__(self):
                self.calls = 0

            def scalar(self, _query):
                self.calls += 1
                return User(id=1, display_name="Runner") if self.calls == 1 else preview

        result = apply_coach_action_preview(Db(), User(id=1, display_name="Runner"), "token")

        self.assertEqual(result["status"], "already_applied")
        self.assertEqual(result["coaching_event_id"], 9)


if __name__ == "__main__":
    unittest.main()
