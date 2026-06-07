import unittest
from datetime import date, datetime
from unittest.mock import patch

try:
    from app.models import Activity, TrainingPlan, TrainingPlanWorkout, TrainingPlanWorkoutFeedback, User
    from app.schemas.common import PlanWorkoutFeedbackIn
    from app.services.planning import AUTO_MATCH_MIN_SCORE, apply_plan_recommendations, plan_adjustment_recommendations, plan_recommendation_preview_changes, save_workout_feedback, score_activity_workout_match, workout_execution_score
except ModuleNotFoundError as exc:
    if exc.name == "sqlalchemy":
        raise unittest.SkipTest("SQLAlchemy is required for planning recommendation tests") from exc
    raise


TODAY = date(2026, 6, 7)


def make_user() -> User:
    return User(id=1, display_name="Test runner")


def make_plan(*workouts: TrainingPlanWorkout, status: str = "active", explanation: str | None = None) -> TrainingPlan:
    return TrainingPlan(
        id=10,
        user_id=1,
        title="Test plan",
        goal_type="race",
        available_days_per_week=3,
        status=status,
        explanation=explanation,
        workouts=list(workouts),
    )


def make_workout(
    workout_id: int,
    scheduled_date: date | None,
    *,
    status: str = "planned",
    workout_type: str = "easy",
    distance_km: float | None = 5.0,
    completed_activity: Activity | None = None,
    intensity: str = "easy",
    week_index: int = 1,
    day_index: int = 1,
    duration_seconds: int | None = None,
) -> TrainingPlanWorkout:
    return TrainingPlanWorkout(
        id=workout_id,
        plan_id=10,
        scheduled_date=scheduled_date,
        status=status,
        completed_activity=completed_activity,
        week_index=week_index,
        day_index=day_index,
        workout_type=workout_type,
        title=f"Workout {workout_id}",
        distance_km=distance_km,
        duration_seconds=duration_seconds,
        intensity=intensity,
        description=None,
    )


def make_activity(activity_id: int, distance_km: float) -> Activity:
    return Activity(
        id=activity_id,
        user_id=1,
        title=f"Activity {activity_id}",
        distance_km=distance_km,
        duration_seconds=1800,
    )


class FakeDb:
    def __init__(self):
        self.added = []
        self.committed = False
        self.rolled_back = False

    def add(self, item):
        self.added.append(item)

    def flush(self):
        for item in self.added:
            if getattr(item, "id", None) is None:
                item.id = 77

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def refresh(self, _item):
        return None


class PlanAdjustmentRecommendationTests(unittest.TestCase):
    def recommendations(self, plan: TrainingPlan) -> dict[str, object]:
        with patch("app.services.planning.today_for_user", return_value=TODAY):
            return plan_adjustment_recommendations(object(), make_user(), plan)

    def recommendation_types(self, result: dict[str, object]) -> list[str]:
        return [item["type"] for item in result["recommendations"]]

    def preview(self, plan: TrainingPlan) -> dict[str, object]:
        with patch("app.services.planning.today_for_user", return_value=TODAY):
            return plan_recommendation_preview_changes(object(), make_user(), plan)

    def apply(self, plan: TrainingPlan, db: FakeDb | None = None, expected_changes: list[dict[str, object]] | None = None) -> tuple[dict[str, object], FakeDb]:
        fake_db = db or FakeDb()
        with patch("app.services.planning.today_for_user", return_value=TODAY):
            result = apply_plan_recommendations(fake_db, make_user(), plan, expected_changes)
        return result, fake_db

    def test_inactive_plan_recommends_activation(self):
        plan = make_plan(
            make_workout(1, TODAY),
            status="draft",
        )

        result = self.recommendations(plan)

        self.assertEqual(result["status"], "watch")
        self.assertIn("resume_plan", self.recommendation_types(result))
        self.assertEqual(result["recommendations"][0]["severity"], "warning")
        self.assertEqual(result["metrics"]["planned_distance_km"], 5.0)

    def test_missed_recent_key_workouts_trigger_hold_and_move(self):
        plan = make_plan(
            make_workout(1, date(2026, 6, 2), status="missed", workout_type="easy"),
            make_workout(2, date(2026, 6, 5), status="skipped", workout_type="long", day_index=2),
        )

        result = self.recommendations(plan)

        self.assertEqual(result["status"], "watch")
        self.assertEqual(result["metrics"]["missed_recent_workouts"], 2)
        self.assertIn("hold_volume", self.recommendation_types(result))
        self.assertIn("move_workout", self.recommendation_types(result))

    def test_done_workout_without_activity_recommends_linking(self):
        plan = make_plan(
            make_workout(1, TODAY, status="done", distance_km=6.0),
        )

        result = self.recommendations(plan)

        self.assertEqual(result["status"], "watch")
        self.assertEqual(result["metrics"]["unlinked_done_workouts"], 1)
        self.assertIn("link_activity", self.recommendation_types(result))

    def test_low_linked_distance_reduces_volume_and_ignores_unscheduled(self):
        plan = make_plan(
            make_workout(
                1,
                TODAY,
                status="done",
                distance_km=10.0,
                completed_activity=make_activity(101, 5.0),
            ),
            make_workout(2, None, distance_km=100.0, day_index=2),
        )

        result = self.recommendations(plan)

        self.assertEqual(result["status"], "watch")
        self.assertEqual(result["metrics"]["planned_distance_km"], 10.0)
        self.assertEqual(result["metrics"]["completed_distance_km"], 5.0)
        self.assertIn("reduce_volume", self.recommendation_types(result))
        self.assertIn("schedule_workouts", self.recommendation_types(result))

    def test_upcoming_jump_from_recent_linked_volume_triggers_hold(self):
        plan = make_plan(
            make_workout(
                1,
                TODAY,
                status="done",
                distance_km=4.0,
                completed_activity=make_activity(101, 4.0),
            ),
            make_workout(2, date(2026, 6, 9), distance_km=8.0, day_index=2),
        )

        result = self.recommendations(plan)

        self.assertEqual(result["metrics"]["recent_completed_distance_km"], 4.0)
        self.assertEqual(result["metrics"]["upcoming_planned_distance_km"], 8.0)
        self.assertIn("hold_volume", self.recommendation_types(result))

    def test_support_workouts_do_not_trigger_distance_reduction(self):
        strength_activity = Activity(id=201, user_id=1, title="Strength", activity_type="manual_strength", distance_km=None, duration_seconds=1800)
        plan = make_plan(
            make_workout(1, TODAY, status="done", workout_type="strength", distance_km=None, duration_seconds=1800, completed_activity=strength_activity),
            make_workout(2, date(2026, 6, 9), workout_type="strength", distance_km=None, duration_seconds=1800, day_index=2),
        )

        result = self.recommendations(plan)
        preview = self.preview(plan)

        self.assertEqual(result["metrics"]["planned_distance_km"], 0)
        self.assertNotIn("reduce_volume", self.recommendation_types(result))
        self.assertFalse([change for change in preview["changes"] if change["field"] == "distance_km"])

    def test_markerless_duration_activity_does_not_auto_match_support_workout(self):
        activity = Activity(
            id=202,
            user_id=1,
            title="Manual session",
            activity_type="manual",
            started_at=datetime(2026, 6, 7, 10, 0),
            distance_km=None,
            duration_seconds=1800,
        )
        workout = make_workout(1, TODAY, workout_type="strength", distance_km=None, duration_seconds=1800)

        score = score_activity_workout_match(activity, workout)

        self.assertLess(score["score"], AUTO_MATCH_MIN_SCORE)
        self.assertIn("auto-link отключен без явного support-маркера", score["reasons"])

    def test_cross_training_marker_is_normalized_for_support_match(self):
        activity = Activity(
            id=203,
            user_id=1,
            title="Manual cross training",
            activity_type="manual_cross_training",
            started_at=datetime(2026, 6, 7, 10, 0),
            distance_km=None,
            duration_seconds=1800,
        )
        workout = make_workout(1, TODAY, workout_type="cross_training", distance_km=None, duration_seconds=1800)

        score = score_activity_workout_match(activity, workout)

        self.assertGreaterEqual(score["score"], AUTO_MATCH_MIN_SCORE)

    def test_safety_gate_recommends_zone_review(self):
        plan = make_plan(
            make_workout(1, TODAY, status="done", completed_activity=make_activity(101, 5.0)),
            explanation="Safety gates: no threshold pace zones",
        )

        result = self.recommendations(plan)

        self.assertIn("review_zones", self.recommendation_types(result))

    def test_execution_score_uses_linked_distance(self):
        workout = make_workout(1, TODAY, status="done", distance_km=5.0, completed_activity=make_activity(101, 5.0))

        score = workout_execution_score(workout)

        self.assertEqual(score["score"], 1.0)
        self.assertEqual(score["status"], "completed")
        self.assertEqual(score["volume_score"], 1.0)

    def test_execution_score_flags_pain_feedback(self):
        workout = make_workout(1, TODAY, status="done", distance_km=5.0, completed_activity=make_activity(101, 5.0))
        workout.feedback = TrainingPlanWorkoutFeedback(id=1, user_id=1, workout_id=1, pain=True, pain_level=5)

        score = workout_execution_score(workout)

        self.assertEqual(score["subjective_risk"], "high")
        self.assertIn("pain reported", score["flags"])
        self.assertLess(score["score"], 1.0)

    def test_feedback_saves_on_completed_workout(self):
        workout = make_workout(1, TODAY, status="done", completed_activity=make_activity(101, 5.0))
        make_plan(workout)

        feedback = save_workout_feedback(FakeDb(), make_user(), workout, PlanWorkoutFeedbackIn(rpe=8, fatigue=7, pain=False, sleep_quality=5))

        self.assertEqual(feedback.rpe, 8)
        self.assertEqual(workout.feedback.fatigue, 7)

    def test_feedback_put_replaces_old_values_and_clears_pain_level(self):
        workout = make_workout(1, TODAY, status="done", completed_activity=make_activity(101, 5.0))
        make_plan(workout)
        save_workout_feedback(FakeDb(), make_user(), workout, PlanWorkoutFeedbackIn(rpe=8, fatigue=9, pain=True, pain_level=5, notes="old"))

        feedback = save_workout_feedback(FakeDb(), make_user(), workout, PlanWorkoutFeedbackIn(rpe=4, pain=False))

        self.assertEqual(feedback.rpe, 4)
        self.assertIsNone(feedback.fatigue)
        self.assertFalse(feedback.pain)
        self.assertIsNone(feedback.pain_level)
        self.assertIsNone(feedback.notes)

    def test_feedback_rejected_on_planned_workout(self):
        workout = make_workout(1, TODAY, status="planned")
        make_plan(workout)

        with self.assertRaises(ValueError):
            save_workout_feedback(FakeDb(), make_user(), workout, PlanWorkoutFeedbackIn(rpe=5))

    def test_feedback_schema_rejects_non_integer_scores(self):
        with self.assertRaises(ValueError):
            PlanWorkoutFeedbackIn(rpe=4.5)

    def test_risky_feedback_triggers_reduce_intensity_recommendation(self):
        completed = make_workout(1, TODAY, status="done", completed_activity=make_activity(101, 5.0))
        completed.feedback = TrainingPlanWorkoutFeedback(id=1, user_id=1, workout_id=1, fatigue=9)
        plan = make_plan(
            completed,
            make_workout(2, date(2026, 6, 9), workout_type="interval", day_index=2),
        )

        result = self.recommendations(plan)

        self.assertIn("reduce_intensity", self.recommendation_types(result))

    def test_reduce_intensity_eases_only_first_hard_workout_in_window(self):
        completed = make_workout(1, TODAY, status="done", completed_activity=make_activity(101, 5.0))
        completed.feedback = TrainingPlanWorkoutFeedback(id=1, user_id=1, workout_id=1, fatigue=9)
        first_hard = make_workout(2, date(2026, 6, 8), workout_type="interval", intensity="threshold", day_index=2)
        second_hard = make_workout(3, date(2026, 6, 9), workout_type="tempo", intensity="threshold", day_index=3)
        plan = make_plan(completed, first_hard, second_hard)

        preview = self.preview(plan)
        intensity_changes = [change for change in preview["changes"] if change["field"] == "intensity"]

        self.assertEqual(len(intensity_changes), 1)
        self.assertEqual(intensity_changes[0]["workout_id"], 2)

    def test_preview_reduces_upcoming_volume_without_mutating_plan(self):
        upcoming = make_workout(2, date(2026, 6, 9), distance_km=5.5, day_index=2)
        plan = make_plan(
            make_workout(
                1,
                TODAY,
                status="done",
                distance_km=10.0,
                completed_activity=make_activity(101, 5.0),
            ),
            upcoming,
        )

        preview = self.preview(plan)

        self.assertEqual(upcoming.distance_km, 5.5)
        distance_changes = [change for change in preview["changes"] if change["field"] == "distance_km"]
        self.assertEqual(len(distance_changes), 1)
        self.assertEqual(distance_changes[0]["workout_id"], 2)
        self.assertEqual(distance_changes[0]["before"], 5.5)
        self.assertEqual(distance_changes[0]["after"], 4.7)

    def test_apply_reduces_upcoming_volume_and_records_audit(self):
        upcoming = make_workout(2, date(2026, 6, 9), distance_km=5.5, day_index=2)
        plan = make_plan(
            make_workout(
                1,
                TODAY,
                status="done",
                distance_km=10.0,
                completed_activity=make_activity(101, 5.0),
            ),
            upcoming,
        )

        result, db = self.apply(plan)

        self.assertEqual(result["audit_id"], 77)
        self.assertEqual(upcoming.distance_km, 4.7)
        self.assertTrue(db.committed)
        self.assertEqual(len(db.added), 1)
        self.assertEqual(db.added[0].user_id, 1)
        self.assertEqual(db.added[0].plan_id, 10)
        self.assertEqual(db.added[0].action, "apply_recommendations")

    def test_repeat_apply_does_not_stack_volume_reduction(self):
        upcoming = make_workout(2, date(2026, 6, 9), distance_km=5.5, day_index=2)
        plan = make_plan(
            make_workout(
                1,
                TODAY,
                status="done",
                distance_km=10.0,
                completed_activity=make_activity(101, 5.0),
            ),
            upcoming,
        )

        self.apply(plan)
        first_distance = upcoming.distance_km
        second_result, _db = self.apply(plan)

        self.assertEqual(first_distance, 4.7)
        self.assertEqual(upcoming.distance_km, first_distance)
        self.assertFalse([change for change in second_result["changes"] if change["field"] == "distance_km"])

    def test_cap_growth_can_tighten_volume_after_reduction(self):
        upcoming = make_workout(2, date(2026, 6, 9), distance_km=10.0, day_index=2)
        plan = make_plan(
            make_workout(
                1,
                TODAY,
                status="done",
                distance_km=10.0,
                completed_activity=make_activity(101, 4.0),
            ),
            upcoming,
        )

        preview = self.preview(plan)
        distance_changes = [change for change in preview["changes"] if change["field"] == "distance_km"]

        self.assertEqual([change["after"] for change in distance_changes], [8.5, 5.0])

    def test_apply_rejects_stale_preview_changes(self):
        upcoming = make_workout(2, date(2026, 6, 9), distance_km=5.5, day_index=2)
        plan = make_plan(
            make_workout(
                1,
                TODAY,
                status="done",
                distance_km=10.0,
                completed_activity=make_activity(101, 5.0),
            ),
            upcoming,
        )
        preview = self.preview(plan)
        upcoming.distance_km = 6.0

        with self.assertRaises(ValueError):
            self.apply(plan, FakeDb(), preview["changes"])

    def test_apply_does_not_mutate_completed_upcoming_workouts(self):
        completed_upcoming = make_workout(
            2,
            date(2026, 6, 9),
            status="done",
            distance_km=5.5,
            completed_activity=make_activity(102, 5.5),
            day_index=2,
        )
        plan = make_plan(
            make_workout(
                1,
                TODAY,
                status="done",
                distance_km=10.0,
                completed_activity=make_activity(101, 5.0),
            ),
            completed_upcoming,
        )

        result, _db = self.apply(plan)

        self.assertEqual(completed_upcoming.distance_km, 5.5)
        self.assertEqual(result["changes"], [])
        self.assertTrue(any(item["action"] == "reduce_next_week_volume" for item in result["skipped"]))

    def test_apply_reschedules_missed_key_workout(self):
        missed_long = make_workout(2, date(2026, 6, 5), status="missed", workout_type="long", day_index=2)
        plan = make_plan(
            make_workout(1, date(2026, 6, 2), status="missed"),
            missed_long,
        )

        result, _db = self.apply(plan)

        self.assertEqual(missed_long.status, "rescheduled")
        self.assertEqual(missed_long.scheduled_date, date(2026, 6, 8))
        changed_fields = {(change["workout_id"], change["field"]) for change in result["changes"]}
        self.assertIn((2, "scheduled_date"), changed_fields)
        self.assertIn((2, "status"), changed_fields)


if __name__ == "__main__":
    unittest.main()
