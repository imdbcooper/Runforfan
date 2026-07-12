import unittest
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import patch

try:
    from app.api.routes.coaching_events import list_coaching_events
    from app.db.migrations.runner import MIGRATIONS
    from app.models import Activity, CoachingEvent, DailyReadinessCheckIn, TrainingPlan, TrainingPlanWorkout, TrainingPlanWorkoutFeedback, User
    from app.schemas.common import DailyReadinessCheckInUpsert, PlanWorkoutFeedbackIn, PlanWorkoutMissIn, PlanWorkoutUpdate
    from app.services.planning import mark_workout_missed, record_workout_completed_event, save_workout_feedback, update_workout
    from app.services.readiness import save_daily_readiness_checkin
except ModuleNotFoundError as exc:
    if exc.name in {"fastapi", "pydantic", "sqlalchemy"}:
        raise unittest.SkipTest("Backend dependencies are required for coaching event tests") from exc
    raise


TODAY = date(2026, 7, 12)


def make_user() -> User:
    return User(id=1, display_name="Runner")


def make_workout(*, status: str = "planned") -> TrainingPlanWorkout:
    workout = TrainingPlanWorkout(
        id=10,
        plan_id=20,
        scheduled_date=TODAY,
        status=status,
        week_index=1,
        day_index=1,
        workout_type="easy",
        title="Easy run",
        distance_km=8.0,
        duration_seconds=3000,
        intensity="easy",
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


class EventDb:
    def __init__(self):
        self.added = []
        self.committed = False
        self.scalar_queries = []

    def add(self, item):
        self.added.append(item)

    def scalar(self, query):
        self.scalar_queries.append(query)
        return None

    def scalars(self, query):
        self.scalar_queries.append(query)
        return []

    def flush(self):
        for index, item in enumerate(self.added, start=100):
            if getattr(item, "id", None) is None:
                item.id = index

    def commit(self):
        self.committed = True

    def refresh(self, _item):
        return None


class CoachingEventTests(unittest.TestCase):
    def test_migration_creates_coaching_event_timeline(self):
        migration = next(statements for version, statements in MIGRATIONS if version == "20260712_0022_coaching_events")
        sql = "\n".join(migration)

        self.assertIn("CREATE TABLE IF NOT EXISTS coaching_events", sql)
        self.assertIn("ix_coaching_events_user_occurred", sql)

    def test_missed_workout_requires_reason_and_records_typed_events(self):
        workout = make_workout()
        db = EventDb()

        mark_workout_missed(db, make_user(), workout, PlanWorkoutMissIn(reason="pain", notes="Achilles discomfort"))

        events = [item for item in db.added if isinstance(item, CoachingEvent)]
        self.assertEqual(workout.status, "missed")
        self.assertEqual([item.event_type for item in events], ["workout_missed", "pain_reported"])
        self.assertEqual(events[0].payload_json["reason"], "pain")
        self.assertEqual(events[0].workout_id, workout.id)
        self.assertTrue(db.committed)

    def test_generic_patch_cannot_create_unexplained_missed_transition(self):
        with self.assertRaisesRegex(ValueError, "missed workout action"):
            update_workout(EventDb(), make_user(), make_workout(), PlanWorkoutUpdate(status="missed"))

    def test_identical_missed_retry_returns_current_workout_without_new_event(self):
        workout = make_workout(status="missed")
        existing = CoachingEvent(
            id=8,
            user_id=1,
            event_type="workout_missed",
            event_version="v1",
            category="outcome",
            source="user",
            occurred_at=datetime.now(UTC),
            workout_id=workout.id,
            payload_json={"reason": "fatigue", "notes": "Heavy legs"},
        )

        class RetryDb(EventDb):
            def scalar(self, query):
                self.scalar_queries.append(query)
                return existing

        db = RetryDb()
        result = mark_workout_missed(db, make_user(), workout, PlanWorkoutMissIn(reason="fatigue", notes="Heavy legs"))

        self.assertIs(result, workout)
        self.assertEqual(db.added, [])
        self.assertFalse(db.committed)

    def test_conflicting_missed_retry_is_rejected(self):
        workout = make_workout(status="missed")
        existing = CoachingEvent(
            id=8,
            user_id=1,
            event_type="workout_missed",
            event_version="v1",
            category="outcome",
            source="user",
            occurred_at=datetime.now(UTC),
            workout_id=workout.id,
            payload_json={"reason": "fatigue", "notes": None},
        )

        class RetryDb(EventDb):
            def scalar(self, query):
                self.scalar_queries.append(query)
                return existing

        with self.assertRaisesRegex(ValueError, "another reason"):
            mark_workout_missed(RetryDb(), make_user(), workout, PlanWorkoutMissIn(reason="illness"))

    def test_historical_missed_workout_can_receive_first_typed_reason(self):
        workout = make_workout(status="missed")
        db = EventDb()

        mark_workout_missed(db, make_user(), workout, PlanWorkoutMissIn(reason="other", notes="Historical status"))

        events = [item for item in db.added if isinstance(item, CoachingEvent)]
        self.assertEqual([item.event_type for item in events], ["workout_missed"])
        self.assertEqual(events[0].payload_json["reason"], "other")
        self.assertTrue(db.committed)

    def test_unchanged_feedback_put_does_not_duplicate_timeline_event(self):
        workout = make_workout(status="done")
        workout.feedback = TrainingPlanWorkoutFeedback(id=7, user_id=1, workout_id=10, completion_status="done", rpe=4, pain=False)
        db = EventDb()

        save_workout_feedback(db, make_user(), workout, PlanWorkoutFeedbackIn(rpe=4, pain=False))

        self.assertEqual([item for item in db.added if isinstance(item, CoachingEvent)], [])
        self.assertTrue(db.committed)

    def test_completion_event_uses_recorded_time_when_activity_time_is_missing(self):
        db = EventDb()
        workout = make_workout(status="done")
        activity = Activity(id=12, user_id=1, title="Imported", duration_seconds=1200, started_at=None)

        record_workout_completed_event(db, make_user(), workout, activity, "activity_import")

        event = next(item for item in db.added if isinstance(item, CoachingEvent))
        self.assertIsNotNone(event.occurred_at)

    def test_readiness_save_records_snapshot_and_new_health_signals(self):
        db = EventDb()
        user = make_user()
        workout = make_workout()
        profile = SimpleNamespace(recovery_status="normal", conservative_mode=False, injury_notes=None, health_conditions=None)
        payload = DailyReadinessCheckInUpsert(
            sleep_quality_0_10=5,
            fatigue_0_10=7,
            soreness_0_10=4,
            stress_0_10=6,
            pain=True,
            pain_level_0_10=2,
            pain_notes="Mild foot pain",
            illness_symptoms=True,
            illness_notes="Sore throat",
        )

        with (
            patch("app.services.readiness.today_context", return_value=(TODAY, profile, workout)),
            patch("app.services.readiness.today_checkin", return_value=None),
        ):
            save_daily_readiness_checkin(db, user, payload)

        events = [item for item in db.added if isinstance(item, CoachingEvent)]
        self.assertEqual([item.event_type for item in events], ["readiness_checkin_saved", "pain_reported", "illness_reported"])
        self.assertEqual(events[0].checkin_id, 100)
        self.assertEqual(events[0].payload_json["recommendation"]["rule_id"], "pain_or_illness_stop")
        self.assertTrue(db.committed)

    def test_timeline_query_is_user_scoped(self):
        db = EventDb()

        result = list_coaching_events(
            event_type="workout_completed",
            workout_id=10,
            limit=20,
            offset=0,
            user=SimpleNamespace(id=42),
            db=db,
        )

        self.assertEqual(result, [])
        sql = str(db.scalar_queries[0].compile(compile_kwargs={"literal_binds": True}))
        self.assertIn("coaching_events.user_id = 42", sql)
        self.assertIn("coaching_events.event_type = 'workout_completed'", sql)
        self.assertIn("coaching_events.workout_id = 10", sql)


if __name__ == "__main__":
    unittest.main()
