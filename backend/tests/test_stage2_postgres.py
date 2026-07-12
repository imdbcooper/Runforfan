import os
import threading
import unittest
import uuid
from datetime import date

try:
    from sqlalchemy import create_engine, func, select, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import sessionmaker

    from app.db.base import Base
    from app.db.migrations.runner import run_migrations
    from app.models import Activity, AthleteProfile, CoachingEvent, PlanRecalculationRequest, PlanRollbackPreview, TrainingPlan, TrainingPlanVersion, TrainingPlanWorkout, User
    from app.schemas.common import CoachActionPreviewRequest
    from app.services.coach_actions import apply_coach_action_preview, create_coach_action_preview
    from app.services.plan_recalculations import record_activity_import_recalculation, request_plan_recalculation
    from app.services.plan_rollbacks import apply_plan_rollback_preview, create_plan_rollback_preview
except ModuleNotFoundError as exc:
    if exc.name in {"psycopg", "sqlalchemy"}:
        raise unittest.SkipTest("PostgreSQL dependencies are required for stage 2 integration tests") from exc
    raise


TEST_DATABASE_URL = os.getenv("RUNFORFAN_TEST_DATABASE_URL")


@unittest.skipUnless(TEST_DATABASE_URL, "RUNFORFAN_TEST_DATABASE_URL is required for PostgreSQL integration tests")
class Stage2PostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database_name = make_url(TEST_DATABASE_URL).database or ""
        if not database_name.endswith("_test"):
            raise RuntimeError("RUNFORFAN_TEST_DATABASE_URL must point to a database whose name ends with _test")
        cls.schema = f"stage2_{uuid.uuid4().hex}"
        cls.admin_engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
        with cls.admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{cls.schema}"'))
        cls.engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True, connect_args={"options": f"-csearch_path={cls.schema}"})
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
            user = User(display_name="Stage 2 Runner", is_demo=False)
            db.add(user)
            db.flush()
            db.add(AthleteProfile(user_id=user.id, sex="unspecified", timezone="Europe/Moscow", locale="ru-RU", unit_system="metric", recovery_status="normal"))
            plan = TrainingPlan(user_id=user.id, title="Stage 2 Plan", goal_type="10k", target_date=date(2026, 7, 31), available_days_per_week=3, status="active")
            plan.workouts = [
                TrainingPlanWorkout(scheduled_date=date(2026, 7, 14), status="planned", week_index=1, day_index=1, workout_type="easy", title="Easy", distance_km=8.0, duration_seconds=3000, intensity="easy"),
                TrainingPlanWorkout(scheduled_date=date(2026, 7, 18), status="planned", week_index=1, day_index=2, workout_type="tempo", title="Tempo", distance_km=6.0, duration_seconds=2400, intensity="threshold"),
            ]
            db.add(plan)
            db.commit()
            self.user_id = user.id
            self.plan_id = plan.id
            self.workout_id = plan.workouts[0].id

    def applied_skip_version(self) -> int:
        with self.SessionLocal() as db:
            user = db.get(User, self.user_id)
            preview = create_coach_action_preview(db, user, self.workout_id, CoachActionPreviewRequest(action="skip", reason="fatigue"))
            result = apply_coach_action_preview(db, user, preview["preview_id"])
            return result["plan_version_id"]

    def test_rollback_is_persisted_and_idempotent(self):
        version_id = self.applied_skip_version()
        with self.SessionLocal() as db:
            user = db.get(User, self.user_id)
            preview = create_plan_rollback_preview(db, user, self.plan_id, version_id)
            applied = apply_plan_rollback_preview(db, user, preview["preview_id"])
            retried = apply_plan_rollback_preview(db, user, preview["preview_id"])

        self.assertEqual(applied["status"], "applied")
        self.assertEqual(retried["status"], "already_applied")
        self.assertEqual(retried["rollback_version_id"], applied["rollback_version_id"])
        with self.SessionLocal() as db:
            self.assertEqual(db.get(TrainingPlanWorkout, self.workout_id).status, "planned")
            versions = list(db.scalars(select(TrainingPlanVersion).order_by(TrainingPlanVersion.version_number)))
            self.assertEqual(len(versions), 2)
            self.assertIsNotNone(versions[0].pre_snapshot_json)
            self.assertEqual(versions[1].rollback_of_version_id, versions[0].id)
            self.assertEqual(db.scalar(select(func.count()).select_from(PlanRollbackPreview)), 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(CoachingEvent).where(CoachingEvent.event_type == "plan_version_rolled_back")), 1)

    def test_concurrent_rollback_creates_one_compensating_version(self):
        version_id = self.applied_skip_version()
        with self.SessionLocal() as db:
            user = db.get(User, self.user_id)
            preview_id = create_plan_rollback_preview(db, user, self.plan_id, version_id)["preview_id"]
        barrier = threading.Barrier(2)
        statuses = []
        errors = []

        def apply_in_session():
            try:
                with self.SessionLocal() as db:
                    barrier.wait(timeout=5)
                    statuses.append(apply_plan_rollback_preview(db, db.get(User, self.user_id), preview_id)["status"])
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
            self.assertEqual(db.scalar(select(func.count()).select_from(TrainingPlanVersion)), 2)

    def test_recalculation_source_is_idempotent_and_read_only(self):
        with self.SessionLocal() as db:
            user = db.get(User, self.user_id)
            plan = db.scalar(select(TrainingPlan).where(TrainingPlan.id == self.plan_id))
            first = request_plan_recalculation(db, user, trigger_type="activity_imported", source_key="import:42", plan=plan)
            db.flush()
            second = request_plan_recalculation(db, user, trigger_type="activity_imported", source_key="import:42", plan=plan)
            db.commit()
            request_id = first.id
            self.assertEqual(second.id, request_id)

        with self.SessionLocal() as db:
            request = db.get(PlanRecalculationRequest, request_id)
            self.assertEqual(request.status, "completed")
            self.assertFalse(request.assessment_json["mutation_applied"])
            self.assertTrue(request.assessment_json["preview_required"])
            self.assertEqual(db.scalar(select(func.count()).select_from(PlanRecalculationRequest)), 1)
            self.assertEqual(db.get(TrainingPlanWorkout, self.workout_id).status, "planned")

    def test_concurrent_import_recalculation_creates_one_request_and_event(self):
        barrier = threading.Barrier(2)
        request_ids = []
        errors = []

        def record_in_session():
            try:
                with self.SessionLocal() as db:
                    activity = Activity(user_id=self.user_id, title="Imported", activity_type="outdoor_run", duration_seconds=1800, distance_km=5.0)
                    db.add(activity)
                    db.flush()
                    barrier.wait(timeout=5)
                    request = record_activity_import_recalculation(db, db.get(User, self.user_id), activity, source_key="import:concurrent")
                    db.commit()
                    request_ids.append(request.id)
            except Exception as error:
                errors.append(error)

        threads = [threading.Thread(target=record_in_session) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(errors, [])
        self.assertEqual(len(set(request_ids)), 1)
        with self.SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(PlanRecalculationRequest).where(PlanRecalculationRequest.source_key == "import:concurrent")), 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(CoachingEvent).where(CoachingEvent.correlation_id == "import:concurrent")), 1)

    def test_migration_runner_applies_stage_two_schema(self):
        run_migrations(self.engine)
        with self.engine.connect() as connection:
            columns = set(connection.execute(text("SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = 'plan_versions'" )).scalars())
            tables = set(connection.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()" )).scalars())
        self.assertTrue({"pre_snapshot_json", "post_snapshot_json", "rollback_of_version_id"}.issubset(columns))
        self.assertIn("plan_rollback_previews", tables)
        self.assertIn("plan_recalculation_requests", tables)


if __name__ == "__main__":
    unittest.main()
