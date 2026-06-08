import unittest
from datetime import UTC, date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

try:
    from app.models import Activity, AthleteProfile, DailyTrainingLoad, TrainingPlanWorkout, TrainingPlanWorkoutFeedback
    from app.services import training_load as training_load_service
    from app.services.training_load import daily_training_load_row_matches_point, load_warnings, load_planned_workouts_with_feedback, sync_daily_training_loads, training_load_from_data
except ModuleNotFoundError as exc:
    if exc.name in {"pydantic", "pydantic_core", "sqlalchemy"}:
        raise unittest.SkipTest("Backend dependencies are required for training load tests") from exc
    raise


def make_activity(activity_id: int, started_at: datetime, distance_km: float = 5.0, duration_seconds: int = 1800, stress: float | None = None) -> Activity:
    return Activity(
        id=activity_id,
        user_id=1,
        title=f"Activity {activity_id}",
        started_at=started_at,
        distance_km=distance_km,
        duration_seconds=duration_seconds,
        average_pace_seconds_per_km=round(duration_seconds / distance_km) if distance_km else None,
        aerobic_training_stress=stress,
    )


def make_workout(workout_id: int, activity_id: int, rpe: int | None = None, fatigue: int | None = None, workout_type: str = "easy") -> TrainingPlanWorkout:
    workout = TrainingPlanWorkout(
        id=workout_id,
        plan_id=1,
        scheduled_date=date(2026, 6, 1),
        status="done",
        completed_activity_id=activity_id,
        week_index=1,
        day_index=1,
        workout_type=workout_type,
        title=f"Workout {workout_id}",
        distance_km=5.0,
        duration_seconds=1800,
        intensity=workout_type,
    )
    workout.feedback = TrainingPlanWorkoutFeedback(id=workout_id, user_id=1, workout_id=workout_id, rpe=rpe, fatigue=fatigue, pain=False)
    return workout


def make_daily_load_point(day: date, load: float = 42.0) -> dict[str, object]:
    return {
        "date": day,
        "load": load,
        "load_method": "aerobic_training_stress",
        "load_methods": ["aerobic_training_stress"],
        "distance_km": 5.0,
        "duration_seconds": 3600,
        "duration_minutes": 60.0,
        "activity_ids": [1],
        "activity_count": 1,
        "srpe_count": 0,
        "hard_session": False,
        "hard_reasons": [],
        "recovery_day": False,
        "ctl": 1.0,
        "atl": 2.0,
        "tsb": -1.0,
        "monotony_window_value": 1.1,
        "strain_window_value": 42.0,
    }


def make_daily_load_row(point: dict[str, object]) -> DailyTrainingLoad:
    return DailyTrainingLoad(
        user_id=1,
        date=point["date"],
        load_value=point["load"],
        method="manual",
        duration_minutes=point["duration_minutes"],
        activity_ids=point["activity_ids"],
        ctl=point["ctl"],
        atl=point["atl"],
        tsb=point["tsb"],
        monotony_window_value=point["monotony_window_value"],
        strain_window_value=point["strain_window_value"],
    )


def import_analytics_route_dependencies(test_case: unittest.TestCase):
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api.errors import add_exception_handlers
        from app.api.routes import analytics as analytics_routes
    except ModuleNotFoundError as exc:
        if exc.name in {"fastapi", "httpx", "starlette"}:
            test_case.skipTest("FastAPI dependencies are required for analytics route tests")
        raise

    def fastapi_with_handlers():
        app = FastAPI()
        add_exception_handlers(app)
        return app

    return fastapi_with_handlers, TestClient, analytics_routes


class TrainingLoadTests(unittest.TestCase):
    def test_workout_query_uses_activity_ids_not_scheduled_date_window(self):
        class FakeScalarResult:
            def __iter__(self):
                return iter([])

        class FakeDb:
            def __init__(self):
                self.query_text = ""

            def scalars(self, query):
                self.query_text = str(query)
                return FakeScalarResult()

        db = FakeDb()
        load_planned_workouts_with_feedback(db, type("User", (), {"id": 1})(), [10, 11])

        self.assertIn("completed_activity_id", db.query_text)
        self.assertNotIn("scheduled_date >=", db.query_text)

    def test_training_load_prefers_activity_stress_over_srpe_fallback(self):
        activity = make_activity(1, datetime(2026, 6, 1, 8, tzinfo=UTC), duration_seconds=3600, stress=42)
        workout = make_workout(1, activity.id, rpe=9)

        result = training_load_from_data([activity], [workout], None, date(2026, 6, 1), date(2026, 6, 1))
        point = result["daily"]["points"][0]

        self.assertEqual(point["load"], 42)
        self.assertEqual(point["load_method"], "aerobic_training_stress")
        self.assertEqual(point["duration_minutes"], 60.0)
        self.assertEqual(point["activity_ids"], [1])
        self.assertIsNotNone(point["ctl"])
        self.assertIsNotNone(point["atl"])
        self.assertIsNotNone(point["tsb"])
        self.assertEqual(point["srpe_count"], 0)

    def test_training_load_uses_srpe_when_stress_missing(self):
        activity = make_activity(1, datetime(2026, 6, 1, 8, tzinfo=UTC), duration_seconds=3600, stress=None)
        workout = make_workout(1, activity.id, rpe=5)

        result = training_load_from_data([activity], [workout], None, date(2026, 6, 1), date(2026, 6, 1))
        point = result["daily"]["points"][0]

        self.assertEqual(point["load"], 300)
        self.assertEqual(point["load_method"], "session_rpe")
        self.assertEqual(point["srpe_count"], 1)

    def test_training_load_buckets_activities_by_profile_timezone(self):
        timezone = ZoneInfo("Europe/Moscow")
        activity = make_activity(1, datetime(2026, 6, 1, 22, 30, tzinfo=UTC), stress=30)

        result = training_load_from_data([activity], [], None, date(2026, 6, 2), date(2026, 6, 2), timezone)
        point = result["daily"]["points"][0]

        self.assertEqual(point["date"], date(2026, 6, 2))
        self.assertEqual(point["load"], 30)

    def test_training_load_fitness_points_and_weekly_monotony(self):
        activities = [
            make_activity(1, datetime(2026, 6, 1, 8, tzinfo=UTC), stress=50),
            make_activity(2, datetime(2026, 6, 3, 8, tzinfo=UTC), stress=80),
            make_activity(3, datetime(2026, 6, 5, 8, tzinfo=UTC), stress=20),
        ]

        result = training_load_from_data(activities, [], None, date(2026, 6, 1), date(2026, 6, 7))

        self.assertEqual(len(result["fitness_fatigue"]["points"]), 7)
        self.assertIn("ctl", result["fitness_fatigue"]["current"])
        self.assertIsNotNone(result["weekly"]["points"][0]["monotony"])
        self.assertIsNotNone(result["daily"]["points"][-1]["monotony_window_value"])
        self.assertIsNotNone(result["daily"]["points"][-1]["strain_window_value"])

    def test_load_warnings_include_close_hard_sessions_and_intensity_share(self):
        activities = [
            make_activity(1, datetime(2026, 6, 1, 8, tzinfo=UTC), stress=90),
            make_activity(2, datetime(2026, 6, 2, 8, tzinfo=UTC), stress=95),
        ]
        result = training_load_from_data(activities, [], None, date(2026, 6, 1), date(2026, 6, 7))
        titles = {warning["title"] for warning in load_warnings(result["daily"]["points"], result["weekly"]["points"], result["fitness_fatigue"]["points"])}

        self.assertIn("Hard sessions too close", titles)
        self.assertIn("Too much intensity", titles)

    def test_hard_spacing_warning_uses_entire_selected_period(self):
        activities = [
            make_activity(1, datetime(2026, 6, 1, 8, tzinfo=UTC), stress=90),
            make_activity(2, datetime(2026, 6, 2, 8, tzinfo=UTC), stress=95),
            make_activity(3, datetime(2026, 6, 20, 8, tzinfo=UTC), stress=20),
        ]
        result = training_load_from_data(activities, [], None, date(2026, 6, 1), date(2026, 6, 28))
        titles = {warning["title"] for warning in load_warnings(result["daily"]["points"], result["weekly"]["points"], result["fitness_fatigue"]["points"])}

        self.assertIn("Hard sessions too close", titles)

    def test_hr_profile_enables_hr_trimp_fallback(self):
        profile = AthleteProfile(user_id=1, resting_heart_rate_bpm=50, max_heart_rate_bpm=190, lactate_threshold_pace_seconds_per_km=300)
        activity = make_activity(1, datetime(2026, 6, 1, 8, tzinfo=UTC), duration_seconds=3600, stress=None)
        activity.average_heart_rate_bpm = 160

        result = training_load_from_data([activity], [], profile, date(2026, 6, 1), date(2026, 6, 1))
        point = result["daily"]["points"][0]

        self.assertEqual(point["load_method"], "hr_trimp")
        self.assertGreater(point["load"], 0)

    def test_support_activity_uses_duration_fallback_without_distance(self):
        activity = make_activity(1, datetime(2026, 6, 1, 8, tzinfo=UTC), distance_km=None, duration_seconds=1800, stress=None)
        activity.activity_type = "manual_strength"

        result = training_load_from_data([activity], [], None, date(2026, 6, 1), date(2026, 6, 1))
        point = result["daily"]["points"][0]

        self.assertEqual(point["load_method"], "support_duration_fallback")
        self.assertEqual(point["load"], 22.5)

    def test_sync_daily_training_loads_upserts_materialized_rows(self):
        class FakeScalarResult:
            def __iter__(self):
                return iter([])

        class FakeDb:
            def __init__(self):
                self.added = []
                self.flushed = False

            def add(self, item):
                self.added.append(item)

            def flush(self):
                self.flushed = True

            def scalar(self, _query):
                return None

            def scalars(self, _query):
                return FakeScalarResult()

        activity = make_activity(1, datetime(2026, 6, 1, 8, tzinfo=UTC), duration_seconds=3600, stress=42)
        db = FakeDb()
        original_timezone = training_load_service.profile_timezone
        original_activities = training_load_service.load_activities
        original_workouts = training_load_service.load_planned_workouts_with_feedback
        try:
            training_load_service.profile_timezone = lambda _db, _user: ZoneInfo("UTC")
            training_load_service.load_activities = lambda _db, _user, _from_date, _to_date, _timezone: [activity]
            training_load_service.load_planned_workouts_with_feedback = lambda _db, _user, _activity_ids: []

            synced = sync_daily_training_loads(db, type("User", (), {"id": 1})(), date(2026, 6, 1), date(2026, 6, 1))
        finally:
            training_load_service.profile_timezone = original_timezone
            training_load_service.load_activities = original_activities
            training_load_service.load_planned_workouts_with_feedback = original_workouts

        self.assertTrue(db.flushed)
        self.assertEqual(synced, 1)
        self.assertEqual(len(db.added), 1)
        row = db.added[0]
        self.assertIsInstance(row, DailyTrainingLoad)
        self.assertEqual(row.load_value, 42)
        self.assertEqual(row.method, "manual")
        self.assertEqual(row.duration_minutes, 60.0)
        self.assertEqual(row.activity_ids, [1])

    def test_daily_training_load_row_compare_matches_on_the_fly_point(self):
        activity = make_activity(1, datetime(2026, 6, 1, 8, tzinfo=UTC), duration_seconds=3600, stress=42)
        point = training_load_from_data([activity], [], None, date(2026, 6, 1), date(2026, 6, 1))["daily"]["points"][0]
        row = DailyTrainingLoad(
            user_id=1,
            date=point["date"],
            load_value=point["load"],
            method="manual",
            duration_minutes=point["duration_minutes"],
            activity_ids=point["activity_ids"],
            ctl=point["ctl"],
            atl=point["atl"],
            tsb=point["tsb"],
            monotony_window_value=point["monotony_window_value"],
            strain_window_value=point["strain_window_value"],
        )

        self.assertTrue(daily_training_load_row_matches_point(row, point))
        row.load_value = 99
        self.assertFalse(daily_training_load_row_matches_point(row, point))

    def test_materialization_status_reports_fresh_missing_and_stale_dates(self):
        class FakeScalarResult:
            def __init__(self, rows):
                self.rows = rows

            def __iter__(self):
                return iter(self.rows)

        class FakeDb:
            def __init__(self, rows):
                self.rows = rows

            def scalars(self, _query):
                return FakeScalarResult(self.rows)

        user = type("User", (), {"id": 1})()
        points = [make_daily_load_point(date(2026, 6, 1)), make_daily_load_point(date(2026, 6, 2), load=12.0)]
        context = {"daily": {"period": {"from_date": date(2026, 6, 1), "to_date": date(2026, 6, 2), "label": "2026-06-01..2026-06-02"}, "points": points}}

        with patch.object(training_load_service, "training_load_context", return_value=context):
            fresh = training_load_service.daily_training_load_materialization_status(FakeDb([make_daily_load_row(points[0]), make_daily_load_row(points[1])]), user, date(2026, 6, 1), date(2026, 6, 2))
            missing = training_load_service.daily_training_load_materialization_status(FakeDb([make_daily_load_row(points[0])]), user, date(2026, 6, 1), date(2026, 6, 2))
            stale_row = make_daily_load_row(points[1])
            stale_row.load_value = 99.0
            stale = training_load_service.daily_training_load_materialization_status(FakeDb([make_daily_load_row(points[0]), stale_row]), user, date(2026, 6, 1), date(2026, 6, 2))

        self.assertTrue(fresh["fresh"])
        self.assertEqual(missing["missing_dates"], [date(2026, 6, 2)])
        self.assertFalse(missing["fresh"])
        self.assertEqual(stale["stale_dates"], [date(2026, 6, 2)])
        self.assertFalse(stale["fresh"])

    def test_backfill_rejects_invalid_or_unbounded_date_ranges(self):
        user = type("User", (), {"id": 1})()
        db = object()

        with self.assertRaises(ValueError):
            training_load_service.backfill_daily_training_loads(db, user, date(2026, 6, 2), date(2026, 6, 1))
        with self.assertRaises(ValueError):
            training_load_service.backfill_daily_training_loads(db, user, date(2025, 1, 1), date(2026, 2, 1))

    def test_materialization_status_rejects_invalid_or_unbounded_date_ranges(self):
        user = type("User", (), {"id": 1})()
        db = object()

        with self.assertRaises(ValueError):
            training_load_service.daily_training_load_materialization_status(db, user, date(2026, 6, 2), date(2026, 6, 1))
        with self.assertRaises(ValueError):
            training_load_service.daily_training_load_materialization_status(db, user, date(2025, 1, 1), date(2026, 2, 1))

    def test_backfill_flushes_synced_rows_before_status_check(self):
        class FakeDb:
            def __init__(self):
                self.flushed = False

            def flush(self):
                self.flushed = True

        user = type("User", (), {"id": 1})()
        db = FakeDb()
        status = {"period": {"from_date": date(2026, 6, 1), "to_date": date(2026, 6, 1), "label": "2026-06-01"}, "expected_days": 1, "persisted_days": 1, "missing_dates": [], "stale_dates": [], "fresh": True}

        def fake_status(_db, _user, _from_date, _to_date):
            self.assertTrue(db.flushed)
            return status

        with patch.object(training_load_service, "sync_daily_training_loads", return_value=1) as sync, patch.object(training_load_service, "daily_training_load_materialization_status", side_effect=fake_status) as materialization_status:
            result = training_load_service.backfill_daily_training_loads(db, user, date(2026, 6, 1), date(2026, 6, 1))

        self.assertEqual(result, {"synced_rows": 1, "status": status})
        sync.assert_called_once_with(db, user, date(2026, 6, 1), date(2026, 6, 1))
        materialization_status.assert_called_once_with(db, user, date(2026, 6, 1), date(2026, 6, 1))

    def test_materialization_status_route_serializes_dates(self):
        FastAPI, TestClient, analytics_routes = import_analytics_route_dependencies(self)
        app = FastAPI()
        app.include_router(analytics_routes.router, prefix="/api")
        user = type("User", (), {"id": 1})()
        db = object()

        def override_db():
            yield db

        app.dependency_overrides[analytics_routes.get_current_user] = lambda: user
        app.dependency_overrides[analytics_routes.get_db] = override_db
        client = TestClient(app)
        result = {
            "period": {"from_date": date(2026, 6, 1), "to_date": date(2026, 6, 2), "label": "2026-06-01..2026-06-02"},
            "expected_days": 2,
            "persisted_days": 1,
            "missing_dates": [date(2026, 6, 2)],
            "stale_dates": [],
            "fresh": False,
        }

        with patch.object(analytics_routes, "daily_training_load_materialization_status", return_value=result) as status:
            response = client.get("/api/analytics/load/materialization?from=2026-06-01&to=2026-06-02")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["missing_dates"], ["2026-06-02"])
        status.assert_called_once_with(db, user, date(2026, 6, 1), date(2026, 6, 2))

    def test_backfill_route_commits_and_serializes_status(self):
        FastAPI, TestClient, analytics_routes = import_analytics_route_dependencies(self)

        class FakeDb:
            def __init__(self):
                self.committed = False

            def commit(self):
                self.committed = True

        app = FastAPI()
        app.include_router(analytics_routes.router, prefix="/api")
        user = type("User", (), {"id": 1})()
        db = FakeDb()

        def override_db():
            yield db

        app.dependency_overrides[analytics_routes.get_current_user] = lambda: user
        app.dependency_overrides[analytics_routes.get_db] = override_db
        client = TestClient(app)
        result = {
            "synced_rows": 2,
            "status": {
                "period": {"from_date": date(2026, 6, 1), "to_date": date(2026, 6, 2), "label": "2026-06-01..2026-06-02"},
                "expected_days": 2,
                "persisted_days": 2,
                "missing_dates": [],
                "stale_dates": [],
                "fresh": True,
            },
        }

        with patch.object(analytics_routes, "backfill_daily_training_loads", return_value=result) as backfill:
            response = client.post("/api/analytics/load/backfill?from=2026-06-01&to=2026-06-02", json={})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"]["period"]["from_date"], "2026-06-01")
        self.assertTrue(db.committed)
        backfill.assert_called_once_with(db, user, date(2026, 6, 1), date(2026, 6, 2))

    def test_backfill_route_returns_400_for_unbounded_range(self):
        FastAPI, TestClient, analytics_routes = import_analytics_route_dependencies(self)

        class FakeDb:
            def commit(self):
                raise AssertionError("invalid backfill ranges must not commit")

        app = FastAPI()
        app.include_router(analytics_routes.router, prefix="/api")
        user = type("User", (), {"id": 1})()
        db = FakeDb()

        def override_db():
            yield db

        app.dependency_overrides[analytics_routes.get_current_user] = lambda: user
        app.dependency_overrides[analytics_routes.get_db] = override_db
        client = TestClient(app)

        with patch.object(analytics_routes, "backfill_daily_training_loads", side_effect=ValueError("too many days")):
            response = client.post("/api/analytics/load/backfill?from=2025-01-01&to=2026-02-01", json={})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"code": "bad_request", "message": "too many days", "details": None})

    def test_materialization_route_returns_400_for_unbounded_range(self):
        FastAPI, TestClient, analytics_routes = import_analytics_route_dependencies(self)

        app = FastAPI()
        app.include_router(analytics_routes.router, prefix="/api")
        user = type("User", (), {"id": 1})()
        db = object()

        def override_db():
            yield db

        app.dependency_overrides[analytics_routes.get_current_user] = lambda: user
        app.dependency_overrides[analytics_routes.get_db] = override_db
        client = TestClient(app)

        with patch.object(analytics_routes, "daily_training_load_materialization_status", side_effect=ValueError("too many days")):
            response = client.get("/api/analytics/load/materialization?from=2025-01-01&to=2026-02-01")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"code": "bad_request", "message": "too many days", "details": None})


if __name__ == "__main__":
    unittest.main()
