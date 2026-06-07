import unittest
from datetime import date

try:
    from app.models import Activity, TrainingPlan, TrainingPlanWorkout, TrainingPlanWorkoutFeedback, User
    from app.schemas.common import PlanUpdate
    from app.services.planning import delete_plan, duplicate_plan, update_plan
except ModuleNotFoundError as exc:
    if exc.name in {"pydantic", "sqlalchemy"}:
        raise unittest.SkipTest("Backend dependencies are required for plan management tests") from exc
    raise


def make_user() -> User:
    return User(id=1, display_name="Test runner")


def make_workout(workout_id: int, *, status: str = "planned", linked: bool = False) -> TrainingPlanWorkout:
    activity = Activity(id=101, user_id=1, title="Linked activity", distance_km=5.0, duration_seconds=1800) if linked else None
    return TrainingPlanWorkout(
        id=workout_id,
        plan_id=10,
        scheduled_date=date(2026, 6, workout_id),
        status=status,
        completed_activity_id=activity.id if activity else None,
        completed_activity=activity,
        week_index=1,
        day_index=workout_id,
        workout_type="easy",
        title=f"Workout {workout_id}",
        distance_km=5.0,
        duration_seconds=1800,
        intensity="easy",
        description="Run easy",
    )


def make_plan(*workouts: TrainingPlanWorkout, status: str = "draft") -> TrainingPlan:
    return TrainingPlan(
        id=10,
        user_id=1,
        title="Base plan",
        goal_type="race",
        race_distance_km=10.0,
        target_date=date(2026, 8, 1),
        available_days_per_week=3,
        status=status,
        explanation="Safety gates: no active safety gates",
        workouts=list(workouts),
    )


class FakeDb:
    def __init__(self):
        self.added = []
        self.deleted = []
        self.committed = False

    def add(self, item):
        self.added.append(item)

    def delete(self, item):
        self.deleted.append(item)

    def flush(self):
        for index, item in enumerate(self.added, start=77):
            if getattr(item, "id", None) is None:
                item.id = index

    def commit(self):
        self.committed = True

    def refresh(self, _item):
        return None


class PlanManagementTests(unittest.TestCase):
    def test_update_plan_changes_title_and_status(self):
        plan = make_plan(make_workout(1), status="draft")
        db = FakeDb()

        updated = update_plan(db, make_user(), plan, PlanUpdate(title="Updated plan", status="completed"))

        self.assertIs(updated, plan)
        self.assertEqual(plan.title, "Updated plan")
        self.assertEqual(plan.status, "completed")
        self.assertTrue(db.committed)

    def test_duplicate_plan_resets_status_links_and_feedback(self):
        workout = make_workout(1, status="done", linked=True)
        workout.feedback = TrainingPlanWorkoutFeedback(id=1, user_id=1, workout_id=1, rpe=8)
        plan = make_plan(workout, status="active")
        db = FakeDb()

        duplicate = duplicate_plan(db, make_user(), plan)

        self.assertEqual(duplicate.status, "draft")
        self.assertEqual(duplicate.title, "Base plan copy")
        self.assertEqual(duplicate.user_id, 1)
        self.assertEqual(len(duplicate.workouts), 1)
        self.assertEqual(duplicate.workouts[0].status, "planned")
        self.assertIsNone(duplicate.workouts[0].completed_activity_id)
        self.assertIsNone(duplicate.workouts[0].feedback)
        self.assertTrue(db.committed)

    def test_delete_plan_rejects_active_plan(self):
        plan = make_plan(make_workout(1), status="active")

        with self.assertRaises(ValueError):
            delete_plan(FakeDb(), make_user(), plan)

    def test_delete_plan_deletes_non_active_plan(self):
        plan = make_plan(make_workout(1), status="archived")
        db = FakeDb()

        deleted_id = delete_plan(db, make_user(), plan)

        self.assertEqual(deleted_id, 10)
        self.assertEqual(db.deleted, [plan])
        self.assertTrue(db.committed)


if __name__ == "__main__":
    unittest.main()
