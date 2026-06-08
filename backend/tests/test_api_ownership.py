import tempfile
import unittest
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

    def test_planning_activity_match_lookup_is_user_scoped(self):
        db = CapturingDb()
        app = app_with_router(planning_routes.router, planning_routes.get_current_user, planning_routes.get_db, db)

        response = TestClient(app).get("/api/planning/activities/11/match-candidates")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"code": "not_found", "message": "Activity not found", "details": None})
        query = compiled_query(db.scalar_queries[0])
        self.assertIn("activities.id = 11", query)
        self.assertIn("activities.user_id = 42", query)

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

    def test_llm_upload_pending_confirmation_does_not_create_activity(self):
        db = ImportUploadDb()
        app = app_with_router(imports_routes.router, imports_routes.get_current_user, imports_routes.get_db, db)
        payload = valid_import_candidate_payload()
        attempt = SimpleNamespace(parsed_payload=payload)
        recognition = {
            "status": "pending_confirmation",
            "engine": "llm:gpt-4o-mini",
            "message": "Подтвердите импорт",
            "payload": payload,
            "requires_confirmation": True,
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = SimpleNamespace(upload_dir=Path(tmp_dir), llm_timeout=10)
            with (
                patch.object(imports_routes, "get_settings", return_value=settings),
                patch.object(imports_routes, "llm_or_template_recognize", return_value=recognition) as recognize,
                patch.object(imports_routes, "create_activity_from_payload") as create_activity,
                patch.object(imports_routes, "latest_recognition_attempt", return_value=attempt),
                patch.object(imports_routes, "log_audit_event") as audit,
            ):
                response = TestClient(app).post(
                    "/api/imports/screenshots",
                    files=[("screenshots", ("unknown.png", b"fake image bytes", "image/png"))],
                )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "pending_confirmation")
        self.assertIsNone(body["created_activity_id"])
        self.assertTrue(body["requires_confirmation"])
        self.assertEqual(body["candidate"]["confidence"], "medium")
        self.assertTrue(db.committed)
        recognize.assert_called_once()
        create_activity.assert_not_called()
        audit.assert_called_once()

    def test_account_delete_passes_current_user_to_deletion_service(self):
        db = CommitDb()
        app = app_with_router(account_routes.router, account_routes.get_current_user, account_routes.get_db, db)
        delete_user_data = Mock(return_value={"activities": 3})
        log_audit_event = Mock(return_value=SimpleNamespace(id=777))

        with patch.object(account_routes, "delete_user_data", delete_user_data), patch.object(account_routes, "log_audit_event", log_audit_event):
            response = TestClient(app).request("DELETE", "/api/account/data", json={"confirmation": "DELETE"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"deleted": True, "counts": {"activities": 3}, "audit_id": 777})
        delete_user_data.assert_called_once_with(db, 42)
        log_audit_event.assert_called_once_with(db, 42, "data.deleted", "account", 42, {"counts": {"activities": 3}})


if __name__ == "__main__":
    unittest.main()
