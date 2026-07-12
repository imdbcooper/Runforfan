import os
import threading
import unittest
import uuid
from datetime import UTC, date, datetime, timedelta

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, func, select, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import sessionmaker

    from app.api.errors import add_exception_handlers
    from app.api.routes import coach_actions as coach_action_routes
    from app.db.base import Base
    from app.models import AthleteProfile, AuditLog, CoachActionPreview, CoachingEvent, TrainingPlan, TrainingPlanRecommendationAudit, TrainingPlanVersion, TrainingPlanWorkout, User
    from app.services.coach_actions import CoachActionConflict, apply_coach_action_preview
except ModuleNotFoundError as exc:
    if exc.name in {"fastapi", "psycopg", "sqlalchemy"}:
        raise unittest.SkipTest("PostgreSQL dependencies are required for coach action integration tests") from exc
    raise


TEST_DATABASE_URL = os.getenv("RUNFORFAN_TEST_DATABASE_URL")


@unittest.skipUnless(TEST_DATABASE_URL, "RUNFORFAN_TEST_DATABASE_URL is required for PostgreSQL integration tests")
class CoachActionPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database_name = make_url(TEST_DATABASE_URL).database or ""
        if not database_name.endswith("_test"):
            raise RuntimeError("RUNFORFAN_TEST_DATABASE_URL must point to a database whose name ends with _test")
        cls.schema = f"coach_actions_{uuid.uuid4().hex}"
        cls.admin_engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
        with cls.admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{cls.schema}"'))
        cls.engine = create_engine(
            TEST_DATABASE_URL,
            pool_pre_ping=True,
            connect_args={"options": f"-csearch_path={cls.schema}"},
        )
        cls.SessionLocal = sessionmaker(bind=cls.engine, autoflush=False, autocommit=False)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()
        with cls.admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{cls.schema}" CASCADE'))
        cls.admin_engine.dispose()

    def setUp(self):
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        with self.SessionLocal() as db:
            user = User(display_name="Integration Runner", is_demo=False)
            other_user = User(display_name="Other Runner", is_demo=False)
            db.add_all([user, other_user])
            db.flush()
            db.add(AthleteProfile(user_id=user.id, sex="unspecified", timezone="Europe/Moscow", locale="ru-RU", unit_system="metric", recovery_status="normal"))
            plan = TrainingPlan(
                user_id=user.id,
                title="Integration Plan",
                goal_type="10k",
                target_date=date(2026, 7, 31),
                available_days_per_week=3,
                status="active",
            )
            plan.workouts = [
                TrainingPlanWorkout(scheduled_date=date(2026, 7, 14), status="planned", week_index=1, day_index=1, workout_type="easy", title="Easy", distance_km=8.0, duration_seconds=3000, intensity="easy"),
                TrainingPlanWorkout(scheduled_date=date(2026, 7, 18), status="planned", week_index=1, day_index=2, workout_type="tempo", title="Tempo", distance_km=6.0, duration_seconds=2400, intensity="threshold"),
            ]
            db.add(plan)
            db.commit()
            self.user_id = user.id
            self.other_user_id = other_user.id
            self.workout_id = plan.workouts[0].id
            self.neighbor_id = plan.workouts[1].id

    def client_for(self, user_id: int) -> TestClient:
        app = FastAPI()
        add_exception_handlers(app)
        app.include_router(coach_action_routes.router, prefix="/api")

        def override_db():
            with self.SessionLocal() as db:
                yield db

        app.dependency_overrides[coach_action_routes.get_db] = override_db
        app.dependency_overrides[coach_action_routes.get_current_user] = lambda: User(id=user_id, display_name="Runner")
        return TestClient(app)

    def test_api_apply_is_persisted_and_idempotent(self):
        client = self.client_for(self.user_id)
        preview_response = client.post(
            f"/api/coach-actions/workouts/{self.workout_id}/preview",
            json={"action": "skip", "reason": "fatigue", "notes": "integration"},
        )
        self.assertEqual(preview_response.status_code, 200)
        preview_id = preview_response.json()["preview_id"]

        applied = client.post(f"/api/coach-actions/{preview_id}/apply", json={})
        retried = client.post(f"/api/coach-actions/{preview_id}/apply", json={})

        self.assertEqual(applied.status_code, 200)
        self.assertEqual(applied.json()["status"], "applied")
        self.assertEqual(retried.json()["status"], "already_applied")
        self.assertEqual(retried.json()["coaching_event_id"], applied.json()["coaching_event_id"])
        with self.SessionLocal() as db:
            self.assertEqual(db.get(TrainingPlanWorkout, self.workout_id).status, "skipped")
            self.assertEqual(db.scalar(select(func.count()).select_from(TrainingPlanVersion)), 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(TrainingPlanRecommendationAudit)), 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(AuditLog)), 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(CoachingEvent)), 1)
            preview = db.get(CoachActionPreview, preview_id)
            self.assertEqual(preview.coaching_event_id, applied.json()["coaching_event_id"])

    def test_concurrent_apply_creates_one_side_effect_set(self):
        client = self.client_for(self.user_id)
        preview_id = client.post(
            f"/api/coach-actions/workouts/{self.workout_id}/preview",
            json={"action": "skip", "reason": "fatigue"},
        ).json()["preview_id"]
        barrier = threading.Barrier(2)
        statuses: list[str] = []
        errors: list[Exception] = []

        def apply_in_session():
            try:
                with self.SessionLocal() as db:
                    user = db.get(User, self.user_id)
                    barrier.wait(timeout=5)
                    statuses.append(apply_coach_action_preview(db, user, preview_id)["status"])
            except Exception as error:
                errors.append(error)

        threads = [threading.Thread(target=apply_in_session) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(errors, [])
        self.assertEqual(sorted(statuses), ["already_applied", "applied"])
        with self.SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(TrainingPlanVersion)), 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(CoachingEvent)), 1)

    def test_expired_stale_and_cross_user_previews_are_rejected(self):
        client = self.client_for(self.user_id)
        other_client = self.client_for(self.other_user_id)
        preview_id = client.post(
            f"/api/coach-actions/workouts/{self.workout_id}/preview",
            json={"action": "reschedule", "reason": "schedule_conflict", "target_date": "2026-07-15"},
        ).json()["preview_id"]

        cross_user = other_client.post(f"/api/coach-actions/{preview_id}/apply", json={})
        self.assertEqual(cross_user.status_code, 409)
        with self.SessionLocal() as db:
            db.get(TrainingPlanWorkout, self.neighbor_id).scheduled_date = date(2026, 7, 19)
            db.commit()
        stale = client.post(f"/api/coach-actions/{preview_id}/apply", json={})
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["details"]["reason"], "preview_stale")

        fresh_preview_id = client.post(
            f"/api/coach-actions/workouts/{self.workout_id}/preview",
            json={"action": "skip", "reason": "fatigue"},
        ).json()["preview_id"]
        with self.SessionLocal() as db:
            preview = db.get(CoachActionPreview, fresh_preview_id)
            preview.expires_at = datetime.now(UTC) - timedelta(minutes=1)
            db.commit()
        expired = client.post(f"/api/coach-actions/{fresh_preview_id}/apply", json={})
        self.assertEqual(expired.status_code, 409)
        self.assertEqual(expired.json()["details"]["reason"], "preview_invalid_or_expired")


if __name__ == "__main__":
    unittest.main()
