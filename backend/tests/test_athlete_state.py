import unittest
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import ANY, patch

try:
    from app.db.migrations.runner import MIGRATIONS
    from app.models import Activity, AthleteStateSnapshot, TrainingPlanWorkout, User
    from app.services.athlete_state import (
        RULE_VERSION,
        STATE_VERSION,
        _workout_input,
        canonical_fingerprint,
        compute_athlete_state,
        local_date_for,
        materialize_athlete_state,
    )
except ModuleNotFoundError as exc:
    if exc.name in {"pydantic", "sqlalchemy"}:
        raise unittest.SkipTest("Backend dependencies are required for athlete state tests") from exc
    raise


TODAY = date(2026, 7, 12)


def load_point(day: date, *, activity_ids: list[int] | None = None, load: float = 0.0, method: str = "unavailable") -> dict[str, object]:
    identifiers = activity_ids or []
    return {
        "date": day,
        "load": load,
        "load_method": method,
        "load_methods": [method] if identifiers else [],
        "distance_km": 5.0 if identifiers else 0.0,
        "duration_seconds": 1800 if identifiers else 0,
        "duration_minutes": 30.0 if identifiers else 0.0,
        "activity_ids": identifiers,
        "activity_count": len(identifiers),
        "srpe_count": len(identifiers) if method == "srpe" else 0,
        "hard_session": False,
        "hard_reasons": [],
        "recovery_day": not identifiers,
        "ctl": 1.0,
        "atl": 2.0,
        "tsb": -1.0,
        "monotony_window_value": 1.0,
        "strain_window_value": load,
    }


def base_inputs() -> dict[str, object]:
    return {
        "state_version": STATE_VERSION,
        "rule_version": RULE_VERSION,
        "local_date": TODAY,
        "timezone": "Europe/Moscow",
        "week_start": date(2026, 7, 6),
        "week_end": TODAY,
        "profile": {
            "id": 2,
            "timezone": "Europe/Moscow",
            "conservative_mode": False,
            "injury_notes": None,
            "health_conditions": None,
            "recovery_status": "normal",
            "updated_at": datetime(2026, 7, 1, tzinfo=UTC),
        },
        "checkins": [],
        "active_plan": None,
        "due_workouts": [],
        "recent_workouts": [],
        "adherence": None,
        "events": [],
        "training_load": {
            "from_date": TODAY - timedelta(days=6),
            "to_date": TODAY,
            "points": [load_point(TODAY - timedelta(days=offset)) for offset in range(6, -1, -1)],
            "warnings": [],
        },
    }


def checkin(**changes) -> dict[str, object]:
    result = {
        "id": 4,
        "checkin_date": TODAY,
        "sleep_quality_0_10": 8,
        "fatigue_0_10": 3,
        "soreness_0_10": 2,
        "stress_0_10": 3,
        "pain": False,
        "pain_level_0_10": None,
        "illness_symptoms": False,
        "updated_at": datetime(2026, 7, 12, 6, tzinfo=UTC),
    }
    result.update(changes)
    return result


class AthleteStateTests(unittest.TestCase):
    def test_migration_creates_versioned_snapshot_projection(self):
        migration = next(statements for version, statements in MIGRATIONS if version == "20260712_0023_athlete_state_snapshots")
        sql = "\n".join(migration)

        self.assertIn("CREATE TABLE IF NOT EXISTS athlete_state_snapshots", sql)
        self.assertIn("input_fingerprint VARCHAR(64) NOT NULL", sql)
        self.assertIn("uq_athlete_state_snapshot_input", sql)

    def test_missing_signals_are_not_interpreted_as_good(self):
        result = compute_athlete_state(base_inputs())
        signals = {item["key"]: item for item in result["signals"]}

        self.assertEqual(result["status"], "unknown")
        self.assertEqual(signals["readiness"]["status"], "unknown")
        self.assertEqual(signals["readiness"]["freshness"], "missing")
        self.assertEqual(signals["readiness"]["confidence"], "none")
        self.assertIn("not interpreted as good readiness", signals["readiness"]["limitations"][0])

    def test_incomplete_persisted_checkin_is_unknown_instead_of_crashing(self):
        inputs = base_inputs()
        inputs["checkins"] = [checkin(fatigue_0_10=None)]

        result = compute_athlete_state(inputs)
        readiness = next(item for item in result["signals"] if item["key"] == "readiness")

        self.assertEqual(readiness["status"], "unknown")
        self.assertEqual(readiness["confidence"], "low")
        self.assertIn("fatigue_0_10", readiness["limitations"][0])

    def test_pain_has_priority_over_other_good_signals(self):
        inputs = base_inputs()
        inputs["checkins"] = [checkin(pain=True, pain_level_0_10=2)]

        result = compute_athlete_state(inputs)
        readiness = next(item for item in result["signals"] if item["key"] == "readiness")

        self.assertEqual(result["status"], "risk")
        self.assertEqual(result["weekly"]["recommended_strategy"], "deload")
        self.assertEqual(readiness["status"], "risk")
        self.assertEqual(readiness["source_refs"], [{"model": "daily_readiness_checkins", "id": 4}])

    def test_current_negative_checkin_resolves_missing_safety_report_signal(self):
        inputs = base_inputs()
        inputs["checkins"] = [checkin()]

        result = compute_athlete_state(inputs)
        safety_reports = next(item for item in result["signals"] if item["key"] == "recent_safety_reports")

        self.assertEqual(safety_reports["status"], "ok")
        self.assertEqual(safety_reports["freshness"], "fresh")
        self.assertEqual(safety_reports["source_refs"], [{"model": "daily_readiness_checkins", "id": 4}])

    def test_positive_legacy_checkin_is_never_labeled_as_negative_safety_report(self):
        inputs = base_inputs()
        inputs["checkins"] = [checkin(pain=True, pain_level_0_10=2)]

        result = compute_athlete_state(inputs)
        safety_reports = next(item for item in result["signals"] if item["key"] == "recent_safety_reports")

        self.assertEqual(safety_reports["status"], "risk")
        self.assertIn("reports pain", safety_reports["summary"])

    def test_critical_load_warning_is_risk_but_not_diagnosis(self):
        inputs = base_inputs()
        inputs["checkins"] = [checkin()]
        inputs["training_load"] = {
            "from_date": TODAY - timedelta(days=6),
            "to_date": TODAY,
            "points": [load_point(TODAY, activity_ids=[7], load=120, method="srpe")],
            "warnings": [{"severity": "critical", "title": "High fatigue balance", "message": "TSB is deeply negative."}],
        }

        result = compute_athlete_state(inputs)
        load = next(item for item in result["signals"] if item["key"] == "training_load")

        self.assertEqual(load["status"], "risk")
        self.assertIn("not medical predictions", load["limitations"][0])

    def test_feedback_freshness_uses_observation_date_not_workout_date(self):
        inputs = base_inputs()
        inputs["checkins"] = [checkin()]
        inputs["recent_workouts"] = [{
            "id": 10,
            "plan_id": 20,
            "scheduled_date": TODAY - timedelta(days=20),
            "status": "done",
            "workout_type": "easy",
            "intensity": "easy",
            "distance_km": 5.0,
            "duration_seconds": 1800,
            "completed_activity_id": 30,
            "completed_activity": {"id": 30},
            "feedback": {
                "id": 40,
                "updated_at": datetime(2026, 7, 12, 8, tzinfo=UTC),
                "observed_date": TODAY,
            },
            "execution": {"score": 1.0, "adherence_status": "completed", "subjective_risk": "low"},
        }]

        result = compute_athlete_state(inputs)
        feedback = next(item for item in result["signals"] if item["key"] == "recent_feedback")

        self.assertEqual(feedback["freshness"], "fresh")
        self.assertEqual(feedback["observed_at"], datetime(2026, 7, 12, 8, tzinfo=UTC))

    def test_no_due_workouts_is_unknown_not_full_adherence(self):
        inputs = base_inputs()
        inputs["checkins"] = [checkin()]
        inputs["active_plan"] = {"id": 9, "updated_at": datetime(2026, 7, 1, tzinfo=UTC)}

        result = compute_athlete_state(inputs)
        adherence = next(item for item in result["signals"] if item["key"] == "weekly_adherence")

        self.assertEqual(adherence["status"], "unknown")
        self.assertEqual(adherence["value"], {"due_workouts": 0})
        self.assertIn("distinct from successful completion", adherence["limitations"][0])

    def test_fingerprint_is_stable_and_changes_with_evidence(self):
        first = base_inputs()
        second = base_inputs()

        self.assertEqual(canonical_fingerprint(first), canonical_fingerprint(second))
        second["checkins"] = [checkin()]
        self.assertNotEqual(canonical_fingerprint(first), canonical_fingerprint(second))

    def test_fingerprint_changes_when_actual_activity_fact_changes(self):
        first = base_inputs()
        workout = {
            "id": 10,
            "plan_id": 20,
            "scheduled_date": TODAY,
            "status": "done",
            "workout_type": "easy",
            "intensity": "easy",
            "distance_km": 5.0,
            "duration_seconds": 1800,
            "completed_activity_id": 30,
            "completed_activity": {"id": 30, "distance_km": 5.0, "duration_seconds": 1800},
            "feedback": None,
            "execution": {"score": 1.0, "adherence_status": "completed", "subjective_risk": "unknown"},
        }
        first["recent_workouts"] = [workout]
        second = base_inputs()
        second_workout = {**workout, "completed_activity": {"id": 30, "distance_km": 5.01, "duration_seconds": 1800}}
        second["recent_workouts"] = [second_workout]

        self.assertNotEqual(canonical_fingerprint(first), canonical_fingerprint(second))

    def test_timezone_boundary_uses_profile_timezone(self):
        profile = SimpleNamespace(timezone="Europe/Moscow")

        local_day, timezone_name = local_date_for(profile, datetime(2026, 7, 11, 22, 30, tzinfo=UTC))

        self.assertEqual(local_day, TODAY)
        self.assertEqual(timezone_name, "Europe/Moscow")

    def test_invalid_timezone_falls_back_to_utc(self):
        local_day, timezone_name = local_date_for(SimpleNamespace(timezone="Invalid/Timezone"), datetime(2026, 7, 12, 1, tzinfo=UTC))

        self.assertEqual(local_day, TODAY)
        self.assertEqual(timezone_name, "UTC")

    def test_future_same_day_activity_is_excluded_from_as_of_workout(self):
        cutoff = datetime(2026, 7, 12, 8, tzinfo=UTC)
        activity = Activity(
            id=30,
            user_id=1,
            title="Future activity",
            started_at=datetime(2026, 7, 12, 10, tzinfo=UTC),
            distance_km=5.0,
            duration_seconds=1800,
        )
        workout = TrainingPlanWorkout(
            id=10,
            plan_id=20,
            scheduled_date=TODAY,
            status="done",
            completed_activity_id=30,
            week_index=1,
            day_index=1,
            workout_type="easy",
            title="Easy",
            distance_km=5.0,
            duration_seconds=1800,
            intensity="easy",
        )
        workout.completed_activity = activity

        result = _workout_input(workout, cutoff)

        self.assertEqual(result["status"], "planned")
        self.assertIsNone(result["completed_activity"])
        self.assertIsNone(result["execution"]["score"])

    def test_exact_snapshot_is_reused_without_writing(self):
        inputs = base_inputs()
        fingerprint = canonical_fingerprint(inputs)
        existing = AthleteStateSnapshot(
            id=15,
            user_id=1,
            local_date=TODAY,
            timezone="Europe/Moscow",
            state_version=STATE_VERSION,
            rule_version=RULE_VERSION,
            input_fingerprint=fingerprint,
            snapshot_json=compute_athlete_state(inputs),
            as_of_at=datetime(2026, 7, 12, 9, tzinfo=UTC),
            computed_at=datetime(2026, 7, 12, 9, tzinfo=UTC),
            trigger_type="on_read",
        )

        class ReuseDb:
            def __init__(self):
                self.scalar_calls = 0
                self.added = []
                self.committed = False

            def scalar(self, _query):
                self.scalar_calls += 1
                return None if self.scalar_calls == 1 else existing

            def add(self, item):
                self.added.append(item)

            def commit(self):
                self.committed = True

        db = ReuseDb()
        original = __import__("app.services.athlete_state", fromlist=["build_athlete_state_inputs"])
        saved_builder = original.build_athlete_state_inputs
        original.build_athlete_state_inputs = lambda *_args, **_kwargs: inputs
        try:
            result = materialize_athlete_state(db, User(id=1, display_name="Runner"))
        finally:
            original.build_athlete_state_inputs = saved_builder

        self.assertEqual(result["snapshot_id"], 15)
        self.assertEqual(db.added, [])
        self.assertFalse(db.committed)

    def test_materialization_timestamps_follow_input_collection(self):
        inputs = base_inputs()
        observation_cutoff = datetime(2026, 7, 12, 9, 0, tzinfo=UTC)
        inputs_collected_at = datetime(2026, 7, 12, 9, 0, 1, tzinfo=UTC)
        computed_at = datetime(2026, 7, 12, 9, 0, 2, tzinfo=UTC)

        class CreateDb:
            def __init__(self):
                self.scalar_calls = 0
                self.added = []

            def scalar(self, _query):
                self.scalar_calls += 1
                return None

            def add(self, item):
                item.id = 16
                self.added.append(item)

            def flush(self):
                pass

            def commit(self):
                pass

            def refresh(self, _item):
                pass

        db = CreateDb()
        with (
            patch("app.services.athlete_state.build_athlete_state_inputs", return_value=inputs) as builder,
            patch("app.services.athlete_state._utcnow", side_effect=[observation_cutoff, inputs_collected_at, computed_at]),
        ):
            result = materialize_athlete_state(db, User(id=1, display_name="Runner"))

        builder.assert_called_once_with(db, ANY, observation_cutoff)
        self.assertEqual(result["as_of_at"], inputs_collected_at)
        self.assertEqual(result["computed_at"], computed_at)
        self.assertLessEqual(result["as_of_at"], result["computed_at"])


if __name__ == "__main__":
    unittest.main()
