import tempfile
import unittest
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.errors import add_exception_handlers
    from app.api.routes import account as account_routes
    from app.api.routes import activities as activities_routes
    from app.api.routes import goals as goals_routes
    from app.api.routes import imports as imports_routes
    from app.api.routes import planning as planning_routes
    from app.api.routes import readiness as readiness_routes
    from app.models import Activity
except ModuleNotFoundError as exc:
    if exc.name in {"fastapi", "httpx", "pydantic", "pydantic_core", "sqlalchemy", "starlette", "multipart"}:
        raise unittest.SkipTest("Backend dependencies are required for API ownership tests") from exc
    raise
except RuntimeError as exc:
    if "python-multipart" in str(exc):
        raise unittest.SkipTest("python-multipart is required for import route tests") from exc
    raise


USER = SimpleNamespace(id=42)


def valid_import_candidate_payload() -> dict:
    return {
        "activity": {
            "title": "Morning run",
            "started_at": "2026-06-08T07:00:00+00:00",
            "distance_km": 5.0,
            "duration_seconds": 1500,
            "average_pace_seconds_per_km": 300,
            "average_heart_rate_bpm": 145,
        },
        "segments": [],
        "split_blocks": [],
        "workout_blocks": [],
        "confidence": "medium",
        "uncertainty_notes": ["pace visible, calories hidden"],
        "estimated_fields": ["activity.average_speed_kmh"],
    }


def compiled_query(query) -> str:
    return str(query.compile(compile_kwargs={"literal_binds": True}))


class EmptyExecuteResult:
    def all(self):
        return []


class CapturingDb:
    def __init__(self):
        self.scalar_queries = []
        self.scalars_queries = []
        self.execute_queries = []

    def scalar(self, query):
        self.scalar_queries.append(query)
        return None

    def scalars(self, query):
        self.scalars_queries.append(query)
        return []

    def execute(self, query):
        self.execute_queries.append(query)
        return EmptyExecuteResult()


class CommitDb:
    def flush(self):
        pass

    def commit(self):
        pass


class ImportRejectDb(CommitDb):
    def __init__(self):
        self.committed = False
        self.batch = SimpleNamespace(
            id=7,
            user_id=42,
            status="pending_confirmation",
            source_app=None,
            recognition_engine="llm:gpt-4o-mini",
            recognition_message="Подтвердите импорт",
            created_activity_id=None,
            created_at=None,
            sources=[],
        )
        self.scalar_queries = []

    def scalar(self, query):
        self.scalar_queries.append(query)
        return self.batch

    def commit(self):
        self.committed = True


class ImportUploadDb(CommitDb):
    def __init__(self):
        self.added = []
        self.committed = False

    def add(self, item):
        if item.__class__.__name__ == "ImportBatch":
            item.id = 7
        elif item.__class__.__name__ == "ScreenshotSource":
            item.id = 101
        self.added.append(item)

    def scalars(self, query):
        return []

    def commit(self):
        self.committed = True


class ImportRetryDb(ImportRejectDb):
    def __init__(self):
        super().__init__()
        self.batch.status = "recognition_failed"
        self.batch.created_activity_id = None
        self.batch.sources = [SimpleNamespace(source_id=101)]
        self.batch.queued_at = None
        self.batch.recognition_started_at = None
        self.batch.recognition_finished_at = None
        self.batch.recognition_retry_at = None
        self.batch.recognition_attempt_count = 3
        self.batch.recognition_max_attempts = 3
        self.batch.recognition_locked_at = None
        self.batch.recognition_locked_by = None
        self.batch.recognition_last_error = "Provider timed out"


class ActivityWriteDb(CommitDb):
    def __init__(self, activity=None):
        self.activity = activity
        self.added = []
        self.committed = False
        self.flushed = False
        self.scalar_queries = []

    def add(self, item):
        if item.__class__.__name__ == "Activity" and item.id is None:
            item.id = 77
            self.activity = item
        self.added.append(item)

    def scalar(self, query):
        self.scalar_queries.append(query)
        if "activities" in str(query):
            return self.activity
        return None

    def flush(self):
        self.flushed = True

    def commit(self):
        self.committed = True


def app_with_router(router, current_user_dependency, db_dependency, db):
    app = FastAPI()
    add_exception_handlers(app)
    app.include_router(router, prefix="/api")

    def override_db():
        yield db

    app.dependency_overrides[current_user_dependency] = lambda: USER
    app.dependency_overrides[db_dependency] = override_db
    return app


class ApiOwnershipTests(unittest.TestCase):
    def test_planning_plan_lookup_is_user_scoped(self):
        db = CapturingDb()
        app = app_with_router(planning_routes.router, planning_routes.get_current_user, planning_routes.get_db, db)

        response = TestClient(app).get("/api/planning/plans/7")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"code": "not_found", "message": "Plan not found", "details": None})
        query = compiled_query(db.scalar_queries[0])
        self.assertIn("training_plans.id = 7", query)
        self.assertIn("training_plans.user_id = 42", query)

    def test_planning_workout_lookup_is_user_scoped(self):
        db = CapturingDb()
        app = app_with_router(planning_routes.router, planning_routes.get_current_user, planning_routes.get_db, db)

        response = TestClient(app).get("/api/planning/workouts/9")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"code": "not_found", "message": "Workout not found", "details": None})
        query = compiled_query(db.scalar_queries[0])
        self.assertIn("training_plan_workouts.id = 9", query)
        self.assertIn("training_plans.user_id = 42", query)

    def test_planning_workout_patch_rejects_direct_skip_and_reschedule(self):
        workout = SimpleNamespace(id=9)
        db = CapturingDb()
        app = app_with_router(planning_routes.router, planning_routes.get_current_user, planning_routes.get_db, db)

        with patch("app.api.routes.planning.get_user_workout", return_value=workout):
            skipped = TestClient(app).patch("/api/planning/workouts/9", json={"status": "skipped"})
            rescheduled = TestClient(app).patch("/api/planning/workouts/9", json={"scheduled_date": "2026-07-15"})
            restored = TestClient(app).patch("/api/planning/workouts/9", json={"status": "planned"})
            unlinked = TestClient(app).patch("/api/planning/workouts/9", json={"completed_activity_id": None})
            linked = TestClient(app).patch("/api/planning/workouts/9", json={"completed_activity_id": 12, "status": "done"})

        self.assertEqual(skipped.status_code, 409)
        self.assertEqual(rescheduled.status_code, 409)
        self.assertEqual(restored.status_code, 409)
        self.assertEqual(unlinked.status_code, 409)
        self.assertEqual(linked.status_code, 409)
        self.assertEqual(skipped.json()["code"], "coach_action_required")
        self.assertEqual(unlinked.json()["code"], "completion_action_required")
        self.assertEqual(linked.json()["code"], "completion_action_required")

    def test_planning_activity_match_lookup_is_user_scoped(self):
        db = CapturingDb()
        app = app_with_router(planning_routes.router, planning_routes.get_current_user, planning_routes.get_db, db)

        response = TestClient(app).get("/api/planning/activities/11/match-candidates")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"code": "not_found", "message": "Activity not found", "details": None})
        query = compiled_query(db.scalar_queries[0])
        self.assertIn("activities.id = 11", query)
        self.assertIn("activities.user_id = 42", query)

    def test_readiness_checkin_lookup_is_user_and_date_scoped(self):
        db = CapturingDb()
        app = app_with_router(readiness_routes.router, readiness_routes.get_current_user, readiness_routes.get_db, db)

        with (
            patch("app.services.readiness.today_for_user", return_value=date(2026, 7, 12)),
            patch("app.services.readiness.get_or_create_profile", return_value=SimpleNamespace(recovery_status="normal")),
            patch("app.services.readiness.active_training_plan", return_value=None),
        ):
            response = TestClient(app).get("/api/readiness/today")

        self.assertEqual(response.status_code, 200)
        query = compiled_query(db.scalar_queries[0])
        self.assertIn("daily_readiness_checkins.user_id = 42", query)
        self.assertIn("daily_readiness_checkins.checkin_date = '2026-07-12'", query)

    def test_activity_delete_is_user_scoped(self):
        db = CapturingDb()
        app = app_with_router(activities_routes.router, activities_routes.get_current_user, activities_routes.get_db, db)

        response = TestClient(app).delete("/api/activities/7")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"code": "not_found", "message": "Activity not found", "details": None})
        query = compiled_query(db.scalar_queries[0])
        self.assertIn("activities.id = 7", query)
        self.assertIn("activities.user_id = 42", query)

    def test_activity_validation_lookup_is_user_scoped(self):
        db = CapturingDb()
        app = app_with_router(activities_routes.router, activities_routes.get_current_user, activities_routes.get_db, db)

        response = TestClient(app).get("/api/activities/7/validation")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"code": "not_found", "message": "Activity not found", "details": None})
        query = compiled_query(db.scalar_queries[0])
        self.assertIn("activities.id = 7", query)
        self.assertIn("activities.user_id = 42", query)

    def test_activity_create_derives_summary_fields_and_syncs_load(self):
        db = ActivityWriteDb()
        app = app_with_router(activities_routes.router, activities_routes.get_current_user, activities_routes.get_db, db)

        with patch.object(activities_routes, "sync_daily_training_loads_for_dates", return_value=1) as sync_load:
            response = TestClient(app).post("/api/activities", json={"title": "Manual run", "started_at": "2026-06-08T07:00:00+00:00", "distance_km": 5.0, "duration_seconds": 1500, "average_heart_rate_bpm": 145})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["id"], 77)
        self.assertEqual(body["title"], "Manual run")
        self.assertEqual(body["average_pace_seconds_per_km"], 300)
        self.assertEqual(body["average_speed_kmh"], 12.0)
        self.assertEqual(body["source_note"], "Manually entered in admin UI.")
        self.assertTrue(db.committed)
        sync_load.assert_called_once()

    def test_activity_update_is_user_scoped_and_recomputes_when_pace_omitted(self):
        activity = Activity(id=7, user_id=42, title="Old run", started_at=datetime(2026, 6, 8, 7, tzinfo=UTC), distance_km=5.0, duration_seconds=1500, average_pace_seconds_per_km=300, average_speed_kmh=12.0)
        db = ActivityWriteDb(activity)
        app = app_with_router(activities_routes.router, activities_routes.get_current_user, activities_routes.get_db, db)

        with patch.object(activities_routes, "sync_daily_training_loads_for_dates", return_value=1) as sync_load:
            response = TestClient(app).patch("/api/activities/7", json={"distance_km": 6.0})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["distance_km"], 6.0)
        self.assertEqual(body["average_pace_seconds_per_km"], 250)
        self.assertEqual(body["average_speed_kmh"], 14.4)
        self.assertTrue(db.committed)
        sync_load.assert_called_once()
        query = compiled_query(db.scalar_queries[0])
        self.assertIn("activities.id = 7", query)
        self.assertIn("activities.user_id = 42", query)

    def test_activity_update_preserves_imported_pace_on_unrelated_patch(self):
        activity = Activity(id=7, user_id=42, title="Old run", distance_km=5.0, duration_seconds=1500, average_pace_seconds_per_km=290, average_speed_kmh=12.4)
        db = ActivityWriteDb(activity)
        app = app_with_router(activities_routes.router, activities_routes.get_current_user, activities_routes.get_db, db)

        with patch.object(activities_routes, "sync_daily_training_loads_for_dates", return_value=1):
            response = TestClient(app).patch("/api/activities/7", json={"title": "Renamed run"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["title"], "Renamed run")
        self.assertEqual(body["average_pace_seconds_per_km"], 290)
        self.assertEqual(body["average_speed_kmh"], 12.4)

    def test_activity_update_preserves_imported_pace_when_summary_values_are_unchanged(self):
        activity = Activity(id=7, user_id=42, title="Old run", distance_km=5.0, duration_seconds=1500, average_pace_seconds_per_km=290, average_speed_kmh=12.4)
        db = ActivityWriteDb(activity)
        app = app_with_router(activities_routes.router, activities_routes.get_current_user, activities_routes.get_db, db)

        with patch.object(activities_routes, "sync_daily_training_loads_for_dates", return_value=1):
            response = TestClient(app).patch("/api/activities/7", json={"title": "Renamed run", "distance_km": 5.0, "duration_seconds": 1500})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["average_pace_seconds_per_km"], 290)
        self.assertEqual(body["average_speed_kmh"], 12.4)

    def test_activity_update_rejects_inconsistent_explicit_pace(self):
        activity = Activity(id=7, user_id=42, title="Old run", distance_km=5.0, duration_seconds=1500, average_pace_seconds_per_km=300)
        db = ActivityWriteDb(activity)
        app = app_with_router(activities_routes.router, activities_routes.get_current_user, activities_routes.get_db, db)

        with patch.object(activities_routes, "sync_daily_training_loads_for_dates", return_value=1) as sync_load:
            response = TestClient(app).patch("/api/activities/7", json={"average_pace_seconds_per_km": 600})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"code": "bad_request", "message": "Average pace must match distance and duration within tolerance", "details": None})
        self.assertFalse(db.committed)
        sync_load.assert_not_called()

    def test_activity_update_rejects_stale_explicit_pace_with_distance_change(self):
        activity = Activity(id=7, user_id=42, title="Old run", distance_km=5.0, duration_seconds=1500, average_pace_seconds_per_km=300)
        db = ActivityWriteDb(activity)
        app = app_with_router(activities_routes.router, activities_routes.get_current_user, activities_routes.get_db, db)

        with patch.object(activities_routes, "sync_daily_training_loads_for_dates", return_value=1) as sync_load:
            response = TestClient(app).patch("/api/activities/7", json={"distance_km": 6.0, "average_pace_seconds_per_km": 300})

        self.assertEqual(response.status_code, 400)
        self.assertIn("Average pace", response.json()["message"])
        self.assertFalse(db.committed)
        sync_load.assert_not_called()

    def test_goal_update_lookup_is_user_scoped(self):
        db = CapturingDb()
        app = app_with_router(goals_routes.router, goals_routes.get_current_user, goals_routes.get_db, db)

        response = TestClient(app).patch("/api/goals/7", json={"title": "Updated"})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"code": "not_found", "message": "Goal not found", "details": None})
        query = compiled_query(db.scalar_queries[0])
        self.assertIn("running_goals.id = 7", query)
        self.assertIn("running_goals.user_id = 42", query)

    def test_goal_completion_lookup_is_user_scoped(self):
        db = CapturingDb()
        app = app_with_router(goals_routes.router, goals_routes.get_current_user, goals_routes.get_db, db)

        response = TestClient(app).post("/api/goals/7/complete", json={})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"code": "not_found", "message": "Goal not found", "details": None})
        query = compiled_query(db.scalar_queries[0])
        self.assertIn("running_goals.id = 7", query)
        self.assertIn("running_goals.user_id = 42", query)

    def test_goal_create_training_plan_reference_is_user_scoped(self):
        db = CapturingDb()
        app = app_with_router(goals_routes.router, goals_routes.get_current_user, goals_routes.get_db, db)

        response = TestClient(app).post("/api/goals", json={"title": "Race", "training_plan_id": 99})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"code": "bad_request", "message": "Training plan not found", "details": None})
        query = compiled_query(db.scalar_queries[0])
        self.assertIn("training_plans.id = 99", query)
        self.assertIn("training_plans.user_id = 42", query)

    def test_import_list_is_user_scoped(self):
        db = CapturingDb()
        app = app_with_router(imports_routes.router, imports_routes.get_current_user, imports_routes.get_db, db)

        response = TestClient(app).get("/api/imports")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])
        query = compiled_query(db.scalars_queries[0])
        self.assertIn("import_batches.user_id = 42", query)

    def test_import_matched_workout_lookup_is_user_scoped(self):
        db = CapturingDb()

        result = imports_routes.matched_workout_ids_for_activities(db, USER, [5, 6])

        self.assertEqual(result, {})
        query = compiled_query(db.execute_queries[0])
        self.assertIn("training_plans.user_id = 42", query)
        self.assertIn("training_plan_workouts.completed_activity_id IN (5, 6)", query)

    def test_import_reject_keeps_candidate_and_does_not_create_activity(self):
        db = ImportRejectDb()
        app = app_with_router(imports_routes.router, imports_routes.get_current_user, imports_routes.get_db, db)
        attempt = SimpleNamespace(parsed_payload=valid_import_candidate_payload())

        with (
            patch.object(imports_routes, "latest_recognition_attempt", return_value=attempt),
            patch.object(imports_routes, "matched_workout_id_for_activity", return_value=None),
            patch.object(imports_routes, "create_activity_from_payload") as create_activity,
            patch.object(imports_routes, "log_audit_event") as audit,
        ):
            response = TestClient(app).post("/api/imports/7/reject")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "rejected_by_user")
        self.assertIsNone(body["created_activity_id"])
        self.assertFalse(body["requires_confirmation"])
        self.assertEqual(body["candidate"]["confidence"], "medium")
        self.assertTrue(db.committed)
        create_activity.assert_not_called()
        audit.assert_called_once()
        query = compiled_query(db.scalar_queries[0])
        self.assertIn("import_batches.id = 7", query)
        self.assertIn("import_batches.user_id = 42", query)

    def test_import_candidate_patch_is_user_scoped_and_updates_candidate(self):
        db = ImportRejectDb()
        app = app_with_router(imports_routes.router, imports_routes.get_current_user, imports_routes.get_db, db)
        attempt = SimpleNamespace(parsed_payload=valid_import_candidate_payload())

        with patch.object(imports_routes, "latest_recognition_attempt", return_value=attempt), patch.object(imports_routes, "log_audit_event") as audit:
            response = TestClient(app).patch("/api/imports/7/candidate", json={"distance_km": 6.0, "duration_seconds": 1800, "average_pace_seconds_per_km": 300})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["requires_confirmation"])
        self.assertIsNone(body["created_activity_id"])
        self.assertEqual(body["candidate"]["activity"]["distance_km"], 6.0)
        self.assertEqual(body["candidate"]["activity"]["duration_seconds"], 1800)
        self.assertTrue(db.committed)
        audit.assert_called_once()
        query = compiled_query(db.scalar_queries[0])
        self.assertIn("import_batches.id = 7", query)
        self.assertIn("import_batches.user_id = 42", query)

    def test_import_candidate_patch_rejects_non_pending_batch(self):
        db = ImportRejectDb()
        db.batch.status = "recognized"
        app = app_with_router(imports_routes.router, imports_routes.get_current_user, imports_routes.get_db, db)

        response = TestClient(app).patch("/api/imports/7/candidate", json={"distance_km": 6.0})

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"code": "conflict", "message": "Import batch is not pending confirmation", "details": None})
        self.assertFalse(db.committed)

    def test_import_candidate_patch_rejects_missing_candidate_payload(self):
        db = ImportRejectDb()
        app = app_with_router(imports_routes.router, imports_routes.get_current_user, imports_routes.get_db, db)
        attempt = SimpleNamespace(parsed_payload=None)

        with patch.object(imports_routes, "latest_recognition_attempt", return_value=attempt):
            response = TestClient(app).patch("/api/imports/7/candidate", json={"distance_km": 6.0})

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"code": "conflict", "message": "Import candidate payload is missing", "details": None})
        self.assertFalse(db.committed)

    def test_import_candidate_patch_noop_commits_without_audit(self):
        db = ImportRejectDb()
        app = app_with_router(imports_routes.router, imports_routes.get_current_user, imports_routes.get_db, db)
        attempt = SimpleNamespace(parsed_payload=valid_import_candidate_payload())

        with patch.object(imports_routes, "latest_recognition_attempt", return_value=attempt), patch.object(imports_routes, "log_audit_event") as audit:
            response = TestClient(app).patch("/api/imports/7/candidate", json={"distance_km": 5.0, "duration_seconds": 1500, "average_pace_seconds_per_km": 300})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(db.committed)
        audit.assert_not_called()

    def test_import_candidate_patch_rejects_invalid_corrected_payload(self):
        db = ImportRejectDb()
        app = app_with_router(imports_routes.router, imports_routes.get_current_user, imports_routes.get_db, db)
        attempt = SimpleNamespace(parsed_payload=valid_import_candidate_payload())

        with patch.object(imports_routes, "latest_recognition_attempt", return_value=attempt), patch.object(imports_routes, "log_audit_event") as audit:
            response = TestClient(app).patch("/api/imports/7/candidate", json={"average_pace_seconds_per_km": 600})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "bad_request")
        self.assertIn("distance/time/pace", response.json()["message"])
        self.assertFalse(db.committed)
        audit.assert_not_called()

    def test_screenshot_upload_queues_recognition_without_creating_activity(self):
        db = ImportUploadDb()
        app = app_with_router(imports_routes.router, imports_routes.get_current_user, imports_routes.get_db, db)

        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = SimpleNamespace(upload_dir=Path(tmp_dir), llm_timeout=10)
            with (
                patch.object(imports_routes, "get_settings", return_value=settings),
                patch.object(imports_routes, "log_audit_event") as audit,
            ):
                response = TestClient(app).post(
                    "/api/imports/screenshots",
                    files=[("screenshots", ("unknown.png", b"fake image bytes", "image/png"))],
                )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "queued")
        self.assertIsNone(body["created_activity_id"])
        self.assertFalse(body["requires_confirmation"])
        self.assertIsNone(body["candidate"])
        self.assertEqual(body["recognition_engine"], "queued")
        self.assertTrue(db.committed)
        audit.assert_called_once()

    def test_failed_screenshot_import_can_be_requeued(self):
        db = ImportRetryDb()
        app = app_with_router(imports_routes.router, imports_routes.get_current_user, imports_routes.get_db, db)
        settings = SimpleNamespace(import_recognition_max_attempts=4)

        with patch.object(imports_routes, "get_settings", return_value=settings), patch.object(imports_routes, "log_audit_event") as audit:
            response = TestClient(app).post("/api/imports/7/retry")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "queued")
        self.assertEqual(response.json()["recognition_attempt_count"], 0)
        self.assertIsNone(response.json()["recognition_last_error"])
        self.assertTrue(db.committed)
        audit.assert_called_once_with(db, 42, "import.recognition.requeued", "import_batch", 7, {})

    def test_account_delete_passes_current_user_to_deletion_service(self):
        db = CommitDb()
        app = app_with_router(account_routes.router, account_routes.get_current_user, account_routes.get_db, db)
        delete_user_data = Mock(return_value={"activities": 3})
        log_audit_event = Mock(return_value=SimpleNamespace(id=777))

        with patch.object(account_routes, "delete_user_data", delete_user_data), patch.object(account_routes, "log_audit_event", log_audit_event):
            response = TestClient(app).request("DELETE", "/api/account/data", json={"confirmation": "DELETE"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"deleted": True, "counts": {"activities": 3, "screenshot_files": 0}, "audit_id": 777})
        delete_user_data.assert_called_once_with(db, 42)
        log_audit_event.assert_called_once_with(db, 42, "data.deleted", "account", 42, {"counts": {"activities": 3, "screenshot_files": 0}})

    def test_account_delete_keeps_retry_job_when_post_commit_cleanup_fails(self):
        db = CommitDb()
        db.commit = Mock()
        db.rollback = Mock()
        app = app_with_router(account_routes.router, account_routes.get_current_user, account_routes.get_db, db)
        staged = Path("/tmp/kilo/staged-account-delete")
        job = SimpleNamespace(id=99)

        with (
            patch.object(account_routes, "stage_user_upload_deletion", return_value=(staged, 1)),
            patch.object(account_routes, "delete_user_data", return_value={"activities": 3}),
            patch.object(account_routes, "log_audit_event", return_value=SimpleNamespace(id=777)),
            patch.object(account_routes, "create_upload_deletion_job", return_value=job),
            patch.object(account_routes, "finish_upload_deletion_job", side_effect=OSError("disk cleanup failed")),
            patch.object(account_routes, "restore_user_upload_deletion") as restore,
        ):
            response = TestClient(app).request("DELETE", "/api/account/data", json={"confirmation": "DELETE"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["counts"]["screenshot_files"], 1)
        db.commit.assert_called_once_with()
        db.rollback.assert_called_once_with()
        restore.assert_not_called()

    def test_account_delete_restores_staged_uploads_when_database_commit_fails(self):
        db = CommitDb()
        db.commit = Mock(side_effect=RuntimeError("database commit failed"))
        db.rollback = Mock()
        app = app_with_router(account_routes.router, account_routes.get_current_user, account_routes.get_db, db)
        staged = Path("/tmp/kilo/staged-account-delete")

        with (
            patch.object(account_routes, "stage_user_upload_deletion", return_value=(staged, 1)),
            patch.object(account_routes, "delete_user_data", return_value={"activities": 3}),
            patch.object(account_routes, "log_audit_event", return_value=SimpleNamespace(id=777)),
            patch.object(account_routes, "create_upload_deletion_job", return_value=SimpleNamespace(id=99)),
            patch.object(account_routes, "restore_user_upload_deletion") as restore,
        ):
            with self.assertRaises(RuntimeError):
                TestClient(app, raise_server_exceptions=True).request("DELETE", "/api/account/data", json={"confirmation": "DELETE"})

        db.rollback.assert_called_once_with()
        restore.assert_called_once_with(staged, account_routes.get_settings().upload_dir, 42)


if __name__ == "__main__":
    unittest.main()
