import unittest
from datetime import date
from unittest.mock import patch

try:
    from app.db.migrations.runner import MIGRATIONS
    from app.models import AthleteProfile, DailyReadinessCheckIn, TrainingPlan, TrainingPlanVersion, TrainingPlanWorkout, User
    from app.services.plan_recalculations import RECALCULATION_RULE_VERSION, request_plan_recalculation, user_recalculation_lock_query
    from app.services.plan_rollbacks import PlanRollbackConflict, build_rollback_preview, snapshot_changes, validate_action_snapshot, validate_rollback_target
except ModuleNotFoundError as exc:
    if exc.name in {"pydantic", "sqlalchemy"}:
        raise unittest.SkipTest("Backend dependencies are required for rollback tests") from exc
    raise


TODAY = date(2026, 7, 13)


def workout_snapshot(workout_id: int, *, scheduled_date: str = "2026-07-15", status: str = "planned", workout_type: str = "easy", intensity: str = "easy"):
    return {
        "id": workout_id,
        "scheduled_date": scheduled_date,
        "status": status,
        "completed_activity_id": None,
        "workout_type": workout_type,
        "title": "Workout",
        "distance_km": 8.0,
        "duration_seconds": 3000,
        "intensity": intensity,
        "description": None,
        "blocks": [],
    }


class RollbackDb:
    def __init__(self, profile=None, checkin=None):
        self.values = [profile, checkin]

    def scalar(self, _query):
        return self.values.pop(0) if self.values else None


class RecalculationDb:
    def __init__(self):
        self.added = []

    def scalar(self, _query):
        return None

    def add(self, item):
        self.added.append(item)


class PlanRollbackTests(unittest.TestCase):
    def test_recalculation_lock_is_postgres_no_key_update(self):
        from sqlalchemy.dialects import postgresql

        sql = str(user_recalculation_lock_query(1).compile(dialect=postgresql.dialect()))
        self.assertIn("FOR NO KEY UPDATE", sql)
        self.assertNotIn("FOR KEY SHARE", sql)

    def test_migration_adds_rollback_and_recalculation_contracts(self):
        migration = next(statements for version, statements in MIGRATIONS if version == "20260713_0025_plan_rollback_and_recalculation")
        sql = "\n".join(migration)
        self.assertIn("pre_snapshot_json", sql)
        self.assertIn("rollback_of_version_id", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS plan_rollback_previews", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS plan_recalculation_requests", sql)
        self.assertIn("uq_plan_recalculation_user_source", sql)

    def test_snapshot_changes_are_workout_scoped(self):
        before = {"workouts": [workout_snapshot(1, status="skipped")]}
        after = {"workouts": [workout_snapshot(1)]}
        self.assertEqual(snapshot_changes(before, after), [{"workout_id": 1, "field": "status", "before": "skipped", "after": "planned"}])

    def test_preview_rejects_no_effect(self):
        snapshot = {"workouts": [workout_snapshot(1)]}
        version = TrainingPlanVersion(id=4, plan_id=2, version_number=3, reason="coach_action_skip", pre_snapshot_json=snapshot)
        with self.assertRaisesRegex(PlanRollbackConflict, "would not change"):
            build_rollback_preview("token", __import__("datetime").datetime.now(__import__("datetime").UTC), version, snapshot)

    def test_malformed_action_snapshot_is_rejected(self):
        with self.assertRaisesRegex(PlanRollbackConflict, "unsupported action snapshot"):
            validate_action_snapshot({"workouts": []})
        with self.assertRaisesRegex(PlanRollbackConflict, "incomplete workout snapshot"):
            validate_action_snapshot({"schema_version": "action-plan-state-v1", "plan_id": 2, "workouts": [{"id": 1}]})
        invalid = workout_snapshot(1)
        invalid["duration_seconds"] = "long"
        with self.assertRaisesRegex(PlanRollbackConflict, "invalid workout duration"):
            validate_action_snapshot({"schema_version": "action-plan-state-v1", "plan_id": 2, "workouts": [invalid]})

    def test_recovery_restrictions_block_restoring_load(self):
        workout = TrainingPlanWorkout(id=1, plan_id=2, scheduled_date=TODAY, status="skipped", week_index=1, day_index=1, workout_type="easy", title="Easy", intensity="easy")
        workout.blocks = []
        workout.completed_activity = None
        plan = TrainingPlan(id=2, user_id=1, title="Plan", goal_type="10k", available_days_per_week=3, status="active", workouts=[workout])
        target = {"workouts": [workout_snapshot(1, scheduled_date="2026-07-15", status="planned")]}
        db = RollbackDb(AthleteProfile(user_id=1, recovery_status="injured"), None)
        with patch("app.services.plan_rollbacks.today_for_user", return_value=TODAY):
            with self.assertRaisesRegex(PlanRollbackConflict, "profile restrictions"):
                validate_rollback_target(db, User(id=1, display_name="Runner"), plan, target)

    def test_hard_session_spacing_is_revalidated(self):
        workouts = []
        for workout_id, scheduled_date in ((1, date(2026, 7, 15)), (2, date(2026, 7, 17))):
            workout = TrainingPlanWorkout(id=workout_id, plan_id=2, scheduled_date=scheduled_date, status="planned", week_index=1, day_index=workout_id, workout_type="tempo", title="Tempo", intensity="threshold")
            workout.blocks = []
            workout.completed_activity = None
            workouts.append(workout)
        plan = TrainingPlan(id=2, user_id=1, title="Plan", goal_type="10k", available_days_per_week=3, status="active", workouts=workouts)
        target = {"workouts": [workout_snapshot(1, workout_type="tempo", intensity="threshold"), workout_snapshot(2, scheduled_date="2026-07-17", workout_type="tempo", intensity="threshold")]}
        profile = AthleteProfile(user_id=1, recovery_status="normal", conservative_mode=False)
        with patch("app.services.plan_rollbacks.today_for_user", return_value=TODAY):
            with self.assertRaisesRegex(PlanRollbackConflict, "stack hard workouts"):
                validate_rollback_target(RollbackDb(profile, None), User(id=1, display_name="Runner"), plan, target)

    def test_current_profile_duration_limit_blocks_rollback(self):
        workout = TrainingPlanWorkout(id=1, plan_id=2, scheduled_date=TODAY, status="planned", week_index=1, day_index=1, workout_type="easy", title="Easy", duration_seconds=1200, intensity="easy")
        workout.blocks = []
        workout.completed_activity = None
        plan = TrainingPlan(id=2, user_id=1, title="Plan", goal_type="10k", target_date=date(2026, 7, 31), available_days_per_week=3, status="active", workouts=[workout])
        target = {"workouts": [workout_snapshot(1, scheduled_date="2026-07-15", status="planned")], "schema_version": "action-plan-state-v1", "plan_id": 2}
        profile = AthleteProfile(user_id=1, recovery_status="normal", conservative_mode=False, max_run_duration_minutes=30)
        with patch("app.services.plan_rollbacks.today_for_user", return_value=TODAY):
            with self.assertRaisesRegex(PlanRollbackConflict, "maximum run duration"):
                validate_rollback_target(RollbackDb(profile, None), User(id=1, display_name="Runner"), plan, target)

    def test_recalculation_without_plan_is_read_only_and_idempotent(self):
        db = RecalculationDb()
        user = User(id=1, display_name="Runner")
        first = request_plan_recalculation(db, user, trigger_type="activity_imported", source_key="import:1")
        self.assertEqual(first.assessment_json["rule_version"], RECALCULATION_RULE_VERSION)
        self.assertFalse(first.assessment_json["mutation_applied"])
        self.assertTrue(first.assessment_json["preview_required"])
        self.assertEqual(len(db.added), 1)


if __name__ == "__main__":
    unittest.main()
