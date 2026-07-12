import unittest
from datetime import date

try:
    from app.models import Activity, TrainingPlan, TrainingPlanWorkout, TrainingPlanWorkoutBlock, TrainingPlanWorkoutFeedback, User
    from app.schemas.common import PlanUpdate, PlanWorkoutUpdate
    from app.services.planning import delete_plan, duplicate_plan, update_plan, update_workout
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
        target_time_seconds=2700,
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

    def scalar(self, _query):
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

    def test_duplicate_plan_is_rejected_to_keep_one_current_program(self):
        workout = make_workout(1, status="done", linked=True)
        workout.feedback = TrainingPlanWorkoutFeedback(id=1, user_id=1, workout_id=1, rpe=8)
        workout.blocks = [TrainingPlanWorkoutBlock(id=11, workout_id=1, block_index=1, block_type="work", repeat_count=1, target_distance_km=5.0)]
        plan = make_plan(workout, status="active")
        db = FakeDb()

        with self.assertRaisesRegex(ValueError, "Only one current training program"):
            duplicate_plan(db, make_user(), plan)

        self.assertFalse(db.committed)

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

    def test_rescheduling_missed_workout_marks_rescheduled(self):
        workout = make_workout(1, status="missed")
        db = FakeDb()

        update_workout(db, make_user(), workout, PlanWorkoutUpdate(scheduled_date=date(2026, 6, 20)))

        self.assertEqual(workout.scheduled_date, date(2026, 6, 20))
        self.assertEqual(workout.status, "rescheduled")
        self.assertTrue(db.committed)

    def test_rescheduling_linked_done_workout_is_rejected(self):
        workout = make_workout(1, status="done", linked=True)

        with self.assertRaises(ValueError):
            update_workout(FakeDb(), make_user(), workout, PlanWorkoutUpdate(scheduled_date=date(2026, 6, 20)))

    def test_unlink_clears_loaded_activity_relationship(self):
        workout = make_workout(1, status="done", linked=True)

        update_workout(FakeDb(), make_user(), workout, PlanWorkoutUpdate(completed_activity_id=None))

        self.assertIsNone(workout.completed_activity_id)
        self.assertIsNone(workout.completed_activity)
        self.assertEqual(workout.status, "planned")


if __name__ == "__main__":
    unittest.main()
