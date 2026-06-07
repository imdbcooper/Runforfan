import unittest
from datetime import UTC, date, datetime

try:
    from app.models import TrainingPlan, TrainingPlanWorkout, TrainingPlanWorkoutFeedback, User
    from app.schemas.common import PlanWorkoutCompleteIn, PlanWorkoutFeedbackPatchIn
    from app.services.planning import complete_workout, patch_workout_feedback, workout_execution_score
except ModuleNotFoundError as exc:
    if exc.name in {"pydantic", "sqlalchemy"}:
        raise unittest.SkipTest("Backend dependencies are required for workout completion tests") from exc
    raise


def make_user() -> User:
    return User(id=1, display_name="Runner")


def make_workout(*, status: str = "planned", distance_km: float | None = 10.0, workout_type: str = "easy", duration_seconds: int = 3600) -> TrainingPlanWorkout:
    workout = TrainingPlanWorkout(
        id=10,
        plan_id=20,
        scheduled_date=date(2026, 6, 8),
        status=status,
        week_index=1,
        day_index=1,
        workout_type=workout_type,
        title="Workout",
        distance_km=distance_km,
        duration_seconds=duration_seconds,
        intensity="threshold" if workout_type == "interval" else "easy",
        description="Run",
    )
    TrainingPlan(
        id=20,
        user_id=1,
        title="Plan",
        goal_type="10k",
        available_days_per_week=3,
        status="active",
        workouts=[workout],
    )
    return workout


class FakeDb:
    def __init__(self):
        self.added = []
        self.committed = False

    def add(self, item):
        self.added.append(item)

    def flush(self):
        for index, item in enumerate(self.added, start=100):
            if getattr(item, "id", None) is None:
                item.id = index

    def commit(self):
        self.committed = True

    def refresh(self, _item):
        return None


class WorkoutCompletionTests(unittest.TestCase):
    def test_complete_workout_creates_manual_activity_and_feedback(self):
        workout = make_workout()
        db = FakeDb()

        complete_workout(db, make_user(), workout, PlanWorkoutCompleteIn(
            actual_distance_km=10.5,
            actual_duration_seconds=3300,
            completed_at=datetime(2026, 6, 8, 12, 0, tzinfo=UTC),
            rpe=4,
            fatigue=3,
            sleep_quality=7,
            weather_notes="warm",
            notes="felt good",
        ))

        self.assertEqual(workout.status, "done")
        self.assertIsNotNone(workout.completed_activity_id)
        self.assertEqual(workout.completed_activity.distance_km, 10.5)
        self.assertEqual(workout.completed_activity.duration_seconds, 3300)
        self.assertEqual(workout.completed_activity.activity_type, "manual_workout")
        self.assertEqual(workout.feedback.rpe, 4)
        self.assertEqual(workout.feedback.weather_notes, "warm")
        self.assertTrue(db.committed)

    def test_patch_feedback_preserves_unset_values(self):
        workout = make_workout(status="done")
        workout.feedback = TrainingPlanWorkoutFeedback(id=1, user_id=1, workout_id=10, rpe=7, fatigue=6, weather_notes="rain", notes="old")
        db = FakeDb()

        feedback = patch_workout_feedback(db, make_user(), workout, PlanWorkoutFeedbackPatchIn(notes="new"))

        self.assertEqual(feedback.rpe, 7)
        self.assertEqual(feedback.fatigue, 6)
        self.assertEqual(feedback.weather_notes, "rain")
        self.assertEqual(feedback.notes, "new")
        self.assertTrue(db.committed)

    def test_complete_workout_can_clear_existing_pain_feedback(self):
        workout = make_workout(status="missed")
        workout.feedback = TrainingPlanWorkoutFeedback(id=1, user_id=1, workout_id=10, pain=True, pain_level=6)

        complete_workout(FakeDb(), make_user(), workout, PlanWorkoutCompleteIn(actual_duration_seconds=3000, pain=False))

        self.assertFalse(workout.feedback.pain)
        self.assertIsNone(workout.feedback.pain_level)

    def test_execution_score_marks_overdone_volume(self):
        workout = make_workout(status="planned", distance_km=10.0, workout_type="interval")
        complete_workout(FakeDb(), make_user(), workout, PlanWorkoutCompleteIn(actual_distance_km=13.0, actual_duration_seconds=4200, rpe=9))

        score = workout_execution_score(workout)

        self.assertEqual(score["status"], "overdone")
        self.assertEqual(score["adherence_status"], "overdone")
        self.assertIn("actual volume above plan", score["flags"])
        self.assertIsNotNone(score["intensity_score"])

    def test_complete_strength_workout_creates_duration_only_support_activity(self):
        workout = make_workout(distance_km=None, duration_seconds=1800, workout_type="strength")

        complete_workout(FakeDb(), make_user(), workout, PlanWorkoutCompleteIn(actual_duration_seconds=1740, rpe=5))

        self.assertEqual(workout.completed_activity.activity_type, "manual_strength")
        self.assertIsNone(workout.completed_activity.distance_km)
        self.assertIsNone(workout.completed_activity.average_pace_seconds_per_km)
        score = workout_execution_score(workout)
        self.assertEqual(score["status"], "completed")
        self.assertGreaterEqual(score["volume_score"], 0.9)


if __name__ == "__main__":
    unittest.main()
