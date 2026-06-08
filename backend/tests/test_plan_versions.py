from __future__ import annotations

import unittest
from datetime import date, datetime

DEPENDENCY_SKIP_REASON = None

try:
    from app.models import TrainingPlan, TrainingPlanWorkout, User
    from app.services.plan_versions import create_plan_version, plan_snapshot
except ModuleNotFoundError as exc:
    if exc.name in {"pydantic", "sqlalchemy"}:
        DEPENDENCY_SKIP_REASON = "Backend dependencies are required for plan version tests"
    else:
        raise


class FakeDb:
    def __init__(self, current_version: int | None = None):
        self.current_version = current_version
        self.flushed = False
        self.added = []

    def flush(self):
        self.flushed = True

    def scalar(self, query):
        return self.current_version

    def add(self, item):
        self.added.append(item)


@unittest.skipIf(DEPENDENCY_SKIP_REASON is not None, DEPENDENCY_SKIP_REASON or "")
class PlanVersionTests(unittest.TestCase):
    def test_plan_snapshot_orders_workouts_and_serializes_dates(self):
        plan = TrainingPlan(
            id=10,
            user_id=1,
            title="Plan",
            goal_type="10k",
            race_distance_km=10.0,
            target_date=date(2026, 9, 1),
            available_days_per_week=4,
            status="draft",
            explanation="safe plan",
            created_at=datetime(2026, 6, 8, 10, 0, 0),
            updated_at=datetime(2026, 6, 8, 10, 0, 0),
        )
        plan.workouts = [
            TrainingPlanWorkout(id=2, plan_id=10, week_index=2, day_index=1, scheduled_date=date(2026, 6, 15), status="planned", workout_type="long", title="Long", duration_seconds=3600),
            TrainingPlanWorkout(id=1, plan_id=10, week_index=1, day_index=1, scheduled_date=date(2026, 6, 8), status="planned", workout_type="easy", title="Easy", duration_seconds=1800),
        ]

        snapshot = plan_snapshot(plan)

        self.assertEqual(snapshot["target_date"], "2026-09-01")
        self.assertEqual([workout["id"] for workout in snapshot["workouts"]], [1, 2])
        self.assertEqual(snapshot["workouts"][0]["scheduled_date"], "2026-06-08")

    def test_create_plan_version_uses_next_number_and_snapshot(self):
        db = FakeDb(current_version=2)
        user = User(id=1, display_name="Runner")
        plan = TrainingPlan(id=10, user_id=1, title="Plan", goal_type="10k", available_days_per_week=4, status="draft")
        plan.workouts = []

        version = create_plan_version(db, user, plan, "manual_edit", "Updated title")

        self.assertTrue(db.flushed)
        self.assertEqual(version.version_number, 3)
        self.assertEqual(version.reason, "manual_edit")
        self.assertEqual(version.summary, "Updated title")
        self.assertEqual(version.snapshot_json["title"], "Plan")
        self.assertEqual(db.added, [version])


if __name__ == "__main__":
    unittest.main()
