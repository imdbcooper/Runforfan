import os
import threading
import unittest
import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import patch

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, func, select, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import DBAPIError, IntegrityError
    from sqlalchemy.orm import sessionmaker

    from app.api.errors import add_exception_handlers
    from app.api.routes import profile as profile_routes
    from app.api.routes import safety_escalations as escalation_routes
    from app.db.base import Base
    from app.db.migrations.runner import run_migrations
    from app.models import AthleteProfile, SafetyEscalation, SafetyEscalationEvent, TrainingPlan, TrainingPlanVersion, User
    from app.services import safety_escalations
    from app.services.data_management import delete_user_data, export_user_data
except ModuleNotFoundError as exc:
    if exc.name in {"fastapi", "httpx", "psycopg", "sqlalchemy"}:
        raise unittest.SkipTest("PostgreSQL dependencies are required for safety escalation integration tests") from exc
    raise


TEST_DATABASE_URL = os.getenv("RUNFORFAN_TEST_DATABASE_URL")


@unittest.skipUnless(TEST_DATABASE_URL, "RUNFORFAN_TEST_DATABASE_URL is required for PostgreSQL integration tests")
class SafetyEscalationPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database_name = make_url(TEST_DATABASE_URL).database or ""
        if not database_name.endswith("_test"):
            raise RuntimeError("RUNFORFAN_TEST_DATABASE_URL must point to a database whose name ends with _test")
        cls.schema = f"safety_escalation_{uuid.uuid4().hex}"
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
        with self.engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS schema_migrations"))
        Base.metadata.create_all(bind=self.engine)
        run_migrations(self.engine)
        with self.SessionLocal() as db:
            user = User(display_name="Safety Runner", is_demo=False)
            other = User(display_name="Other Runner", is_demo=False)
            db.add_all([user, other])
            db.flush()
            db.add_all([
                AthleteProfile(user_id=user.id, timezone="Europe/Moscow", recovery_status="injured", injury_notes="private injury detail", health_conditions="private condition"),
                AthleteProfile(user_id=other.id, timezone="Europe/Moscow", recovery_status="normal"),
            ])
            db.commit()
            self.user_id = user.id
            self.other_user_id = other.id

    def enabled(self, value=True):
        return patch.object(safety_escalations, "get_settings", return_value=SimpleNamespace(safety_escalation_enabled=value))

    def client_for(self, user_id: int) -> TestClient:
        app = FastAPI()
        add_exception_handlers(app)
        app.include_router(escalation_routes.router, prefix="/api")
        app.include_router(profile_routes.router, prefix="/api")

        def override_db():
            with self.SessionLocal() as db:
                yield db

        app.dependency_overrides[escalation_routes.get_db] = override_db
        app.dependency_overrides[escalation_routes.get_current_user] = lambda: User(id=user_id, display_name="Runner")
        app.dependency_overrides[profile_routes.get_db] = override_db
        app.dependency_overrides[profile_routes.get_current_user] = lambda: User(id=user_id, display_name="Runner")
        return TestClient(app)

    def test_migration_creates_privacy_safe_lifecycle_tables_and_constraints(self):
        with self.engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS safety_escalation_events, safety_escalations CASCADE"))
            connection.execute(text("CREATE TABLE IF NOT EXISTS schema_migrations (version VARCHAR(255) PRIMARY KEY, applied_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now())"))
            connection.execute(text("DELETE FROM schema_migrations WHERE version = '20260715_0032_safety_escalations'"))
        run_migrations(self.engine)
        run_migrations(self.engine)
        with self.engine.connect() as connection:
            tables = set(connection.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema() AND table_name LIKE 'safety_escalation%'" )).scalars())
            constraints = set(connection.execute(text("SELECT constraint_name FROM information_schema.table_constraints WHERE table_schema = current_schema() AND table_name LIKE 'safety_escalation%'" )).scalars())
            indexes = set(connection.execute(text("SELECT indexname FROM pg_indexes WHERE schemaname = current_schema() AND tablename LIKE 'safety_escalation%'" )).scalars())
            triggers = set(connection.execute(text("SELECT tgname FROM pg_trigger JOIN pg_class ON pg_class.oid = tgrelid JOIN pg_namespace ON pg_namespace.oid = pg_class.relnamespace WHERE pg_namespace.nspname = current_schema() AND NOT tgisinternal AND pg_class.relname LIKE 'safety_escalation%'" )).scalars())
            migrated = connection.execute(text("SELECT 1 FROM schema_migrations WHERE version = '20260715_0032_safety_escalations'")).scalar_one()
        self.assertEqual(tables, {"safety_escalations", "safety_escalation_events"})
        self.assertTrue({"ck_safety_escalation_lifecycle", "uq_safety_escalation_source", "fk_safety_escalation_event_owner", "uq_safety_escalation_event_type"}.issubset(constraints))
        self.assertIn("uq_safety_escalation_active_user", indexes)
        self.assertEqual(triggers, {"trg_safety_escalation_transition", "trg_safety_escalation_event", "trg_safety_escalation_event_presence"})
        self.assertEqual(migrated, 1)

        with self.SessionLocal() as db:
            escalation = SafetyEscalation(
                user_id=self.user_id,
                local_date=date.today(),
                trigger_kind="red_flag_stop",
                severity="critical",
                status="open",
                rule_version=safety_escalations.RULE_VERSION,
                source_rule_version="daily-readiness-v3",
                source_rule_id="pain_or_illness_stop",
                source_key="profile:trigger-test",
                source_fingerprint="c" * 64,
            )
            db.add(escalation)
            db.flush()
            db.add(SafetyEscalationEvent(escalation_id=escalation.id, user_id=self.user_id, event_type="opened", actor_kind="system", rule_version=safety_escalations.RULE_VERSION, metadata_json={}))
            db.commit()
            escalation.status = "acknowledged"
            escalation.acknowledgement_code = "understood_guidance"
            escalation.acknowledged_at = datetime.now(UTC)
            with self.assertRaises(DBAPIError):
                db.commit()

    def test_current_case_is_idempotent_private_and_has_no_plan_mutation_authority(self):
        with self.SessionLocal() as db:
            plan = TrainingPlan(user_id=self.user_id, title="Protected plan", goal_type="10k", target_date=date.today(), available_days_per_week=3, status="active")
            db.add(plan)
            db.flush()
            db.add(TrainingPlanVersion(plan_id=plan.id, user_id=self.user_id, version_number=1, reason="manual", snapshot_json={"private": "plan"}, summary="baseline"))
            db.commit()
            plan_id = plan.id

        with self.enabled():
            first = self.client_for(self.user_id).get("/api/safety-escalations/current")
            second = self.client_for(self.user_id).get("/api/safety-escalations/current")
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json(), second.json())
        payload = first.json()["escalation"]
        self.assertEqual(payload["trigger_kind"], "return_to_run_ambiguous")
        self.assertNotIn("injury", first.text.lower())
        self.assertNotIn("private", first.text.lower())
        self.assertNotIn("source_key", first.text)
        self.assertNotIn("source_fingerprint", first.text)
        with self.SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(SafetyEscalation)), 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(SafetyEscalationEvent).where(SafetyEscalationEvent.event_type == "opened")), 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(TrainingPlan).where(TrainingPlan.id == plan_id)), 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(TrainingPlanVersion).where(TrainingPlanVersion.plan_id == plan_id)), 1)

    def test_acknowledgement_is_owned_idempotent_and_not_clearance(self):
        with self.enabled():
            current = self.client_for(self.user_id).get("/api/safety-escalations/current").json()["escalation"]
            forbidden = self.client_for(self.other_user_id).post(f"/api/safety-escalations/{current['id']}/acknowledge", json={"acknowledgement": "understood_guidance"})
            first = self.client_for(self.user_id).post(f"/api/safety-escalations/{current['id']}/acknowledge", json={"acknowledgement": "understood_guidance"})
            duplicate = self.client_for(self.user_id).post(f"/api/safety-escalations/{current['id']}/acknowledge", json={"acknowledgement": "understood_guidance"})
        self.assertEqual(forbidden.status_code, 409, forbidden.text)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json(), duplicate.json())
        self.assertEqual(first.json()["escalation"]["status"], "acknowledged")
        self.assertIn("не подтверждает безопасность возврата", first.json()["escalation"]["disclaimer"])
        with self.SessionLocal() as db:
            escalation = db.get(SafetyEscalation, current["id"])
            self.assertEqual(escalation.status, "acknowledged")
            self.assertEqual(db.scalar(select(func.count()).select_from(SafetyEscalationEvent).where(SafetyEscalationEvent.escalation_id == current["id"], SafetyEscalationEvent.event_type == "acknowledged")), 1)

    def test_same_safety_classification_preserves_acknowledgement(self):
        with self.enabled():
            current = self.client_for(self.user_id).get("/api/safety-escalations/current").json()["escalation"]
            acknowledged = self.client_for(self.user_id).post(f"/api/safety-escalations/{current['id']}/acknowledge", json={"acknowledgement": "understood_guidance"})
            repeated = self.client_for(self.user_id).get("/api/safety-escalations/current")
        self.assertEqual(acknowledged.status_code, 200, acknowledged.text)
        self.assertEqual(repeated.json()["escalation"]["id"], current["id"])
        self.assertEqual(repeated.json()["escalation"]["status"], "acknowledged")
        self.assertEqual(repeated.json()["escalation"]["acknowledged_at"], acknowledged.json()["escalation"]["acknowledged_at"])

    def test_resolved_input_supersedes_case_and_recurrence_opens_new_case(self):
        with self.enabled():
            first = self.client_for(self.user_id).get("/api/safety-escalations/current").json()["escalation"]
            with self.SessionLocal() as db:
                profile = db.scalar(select(AthleteProfile).where(AthleteProfile.user_id == self.user_id))
                profile.recovery_status = "normal"
                db.commit()
            resolved = self.client_for(self.user_id).get("/api/safety-escalations/current")
            with self.SessionLocal() as db:
                profile = db.scalar(select(AthleteProfile).where(AthleteProfile.user_id == self.user_id))
                profile.recovery_status = "injured"
                db.commit()
            recurrent = self.client_for(self.user_id).get("/api/safety-escalations/current")
        self.assertIsNone(resolved.json()["escalation"])
        self.assertNotEqual(recurrent.json()["escalation"]["id"], first["id"])
        with self.SessionLocal() as db:
            old = db.get(SafetyEscalation, first["id"])
            self.assertEqual(old.status, "superseded")
            self.assertIsNotNone(old.superseded_at)
            self.assertEqual(db.scalar(select(func.count()).select_from(SafetyEscalation).where(SafetyEscalation.status.in_(("open", "acknowledged")))), 1)

    def test_profile_update_synchronizes_case_in_same_request(self):
        with self.SessionLocal() as db:
            profile = db.scalar(select(AthleteProfile).where(AthleteProfile.user_id == self.user_id))
            profile.recovery_status = "normal"
            db.commit()

        with self.enabled():
            injured = self.client_for(self.user_id).put("/api/profile", json={"recovery_status": "injured"})
            with self.SessionLocal() as db:
                active_after_injury = db.scalar(select(SafetyEscalation).where(SafetyEscalation.user_id == self.user_id, SafetyEscalation.status.in_(("open", "acknowledged"))))
                self.assertIsNotNone(active_after_injury)
                self.assertEqual(active_after_injury.trigger_kind, "return_to_run_ambiguous")
            normal = self.client_for(self.user_id).put("/api/profile", json={"recovery_status": "normal"})

        self.assertEqual(injured.status_code, 200, injured.text)
        self.assertEqual(normal.status_code, 200, normal.text)
        with self.SessionLocal() as db:
            escalation = db.scalar(select(SafetyEscalation).where(SafetyEscalation.user_id == self.user_id))
            self.assertEqual(escalation.status, "superseded")
            self.assertEqual(db.scalar(select(func.count()).select_from(SafetyEscalationEvent).where(SafetyEscalationEvent.escalation_id == escalation.id)), 2)

    def test_concurrent_materialization_creates_one_active_case(self):
        barrier = threading.Barrier(2)
        errors: list[BaseException] = []

        def load():
            try:
                barrier.wait(5)
                response = self.client_for(self.user_id).get("/api/safety-escalations/current")
                if response.status_code != 200:
                    raise AssertionError(response.text)
            except BaseException as exc:
                errors.append(exc)

        with self.enabled():
            threads = [threading.Thread(target=load) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(10)
        self.assertFalse(errors)
        with self.SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(SafetyEscalation)), 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(SafetyEscalationEvent)), 1)

    def test_export_is_user_scoped_bounded_and_delete_removes_lifecycle(self):
        with self.enabled():
            self.client_for(self.user_id).get("/api/safety-escalations/current")
        with self.SessionLocal() as db:
            exported = export_user_data(db, db.get(User, self.user_id))
            self.assertEqual(exported["version"], "2026-07-15.0034")
            self.assertEqual(len(exported["safety_escalations"]), 1)
            serialized = str({"cases": exported["safety_escalations"], "events": exported["safety_escalation_events"]})
            self.assertNotIn("source_key", serialized)
            self.assertNotIn("source_fingerprint", serialized)
            self.assertNotIn("private injury detail", serialized)
            counts = delete_user_data(db, self.user_id)
            db.commit()
            self.assertEqual(counts["safety_escalations"], 1)
            self.assertEqual(counts["safety_escalation_events"], 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(SafetyEscalation).where(SafetyEscalation.user_id == self.user_id)), 0)

    def test_database_rejects_invalid_lifecycle_and_cross_user_event(self):
        with self.SessionLocal() as db:
            db.add(SafetyEscalation(
                user_id=self.user_id,
                local_date=date.today(),
                trigger_kind="red_flag_stop",
                severity="critical",
                status="acknowledged",
                rule_version=safety_escalations.RULE_VERSION,
                source_rule_version="daily-readiness-v3",
                source_rule_id="pain_or_illness_stop",
                source_key="checkin:1",
                source_fingerprint="a" * 64,
            ))
            with self.assertRaises(IntegrityError):
                db.commit()

        with self.SessionLocal() as db:
            escalation = SafetyEscalation(
                user_id=self.user_id,
                local_date=date.today(),
                trigger_kind="red_flag_stop",
                severity="critical",
                status="open",
                rule_version=safety_escalations.RULE_VERSION,
                source_rule_version="daily-readiness-v3",
                source_rule_id="pain_or_illness_stop",
                source_key="checkin:1",
                source_fingerprint="b" * 64,
            )
            db.add(escalation)
            db.flush()
            db.add(SafetyEscalationEvent(escalation_id=escalation.id, user_id=self.other_user_id, event_type="opened", actor_kind="system", rule_version=safety_escalations.RULE_VERSION, metadata_json={}))
            with self.assertRaises(IntegrityError):
                db.commit()

    def test_closed_rollout_does_not_materialize_or_expose_case(self):
        with self.enabled(False):
            response = self.client_for(self.user_id).get("/api/safety-escalations/current")
        self.assertEqual(response.json(), {"available": False, "escalation": None})
        with self.SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(SafetyEscalation)), 0)


if __name__ == "__main__":
    unittest.main()
