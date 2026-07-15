import os
import threading
import unittest
import uuid
from datetime import UTC, datetime, timedelta

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, func, select, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import sessionmaker

    from app.api.errors import add_exception_handlers
    from app.api.routes import recovery_signals as recovery_routes
    from app.db.base import Base
    from app.db.migrations.runner import run_migrations
    from app.models import AuditLog, RecoverySignalObservation, User
    from app.services.athlete_state import materialize_athlete_state
    from app.services.data_management import delete_user_data, export_user_data
except ModuleNotFoundError as exc:
    if exc.name in {"fastapi", "httpx", "psycopg", "sqlalchemy"}:
        raise unittest.SkipTest("PostgreSQL dependencies are required for recovery signal integration tests") from exc
    raise


TEST_DATABASE_URL = os.getenv("RUNFORFAN_TEST_DATABASE_URL")


@unittest.skipUnless(TEST_DATABASE_URL, "RUNFORFAN_TEST_DATABASE_URL is required for PostgreSQL integration tests")
class RecoverySignalPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database_name = make_url(TEST_DATABASE_URL).database or ""
        if not database_name.endswith("_test"):
            raise RuntimeError("RUNFORFAN_TEST_DATABASE_URL must point to a database whose name ends with _test")
        cls.schema = f"recovery_signals_{uuid.uuid4().hex}"
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
            user = User(display_name="Recovery Runner", is_demo=False)
            other = User(display_name="Other Runner", is_demo=False)
            db.add_all([user, other])
            db.commit()
            self.user_id = user.id
            self.other_user_id = other.id

    def client_for(self, user_id: int) -> TestClient:
        app = FastAPI()
        add_exception_handlers(app)
        app.include_router(recovery_routes.router, prefix="/api")

        def override_db():
            with self.SessionLocal() as db:
                yield db

        app.dependency_overrides[recovery_routes.get_db] = override_db
        app.dependency_overrides[recovery_routes.get_current_user] = lambda: User(id=user_id, display_name="Runner")
        return TestClient(app)

    def payload(self, record_id: str = "record-1", *, value: float = 61.0, unit: str = "ms", observed_at: datetime | None = None):
        return {"observations": [{
            "metric_key": "hrv_rmssd_ms",
            "value": value,
            "unit": unit,
            "observed_at": (observed_at or datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
            "source_kind": "device_import",
            "source_system": "generic_wearable",
            "source_label": "Generic wearable",
            "source_record_id": record_id,
            "quality": "high",
            "quality_score": 0.9,
        }]}

    def test_import_is_user_scoped_idempotent_and_audited(self):
        payload = self.payload()
        first = self.client_for(self.user_id).post("/api/recovery-signals/imports", json=payload)
        duplicate = self.client_for(self.user_id).post("/api/recovery-signals/imports", json=payload)
        other = self.client_for(self.other_user_id).post("/api/recovery-signals/imports", json=payload)

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["accepted"], 1)
        self.assertEqual(duplicate.json(), {"accepted": 0, "duplicates": 1, "observations": []})
        self.assertEqual(other.json()["accepted"], 1)
        with self.SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(RecoverySignalObservation)), 2)
            self.assertEqual(db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "recovery_signals.imported")), 3)

    def test_source_record_identity_cannot_be_reused_with_different_data(self):
        client = self.client_for(self.user_id)
        original = self.payload(value=61.0)
        conflicting_payload = {"observations": [{**original["observations"][0], "value": 40.0}]}
        first = client.post("/api/recovery-signals/imports", json=original)
        conflicting = client.post("/api/recovery-signals/imports", json=conflicting_payload)

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(conflicting.status_code, 409, conflicting.text)
        with self.SessionLocal() as db:
            rows = list(db.scalars(select(RecoverySignalObservation).where(RecoverySignalObservation.user_id == self.user_id)))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].value_numeric, 61.0)

    def test_import_rejects_future_wrong_unit_and_out_of_range_atomically(self):
        client = self.client_for(self.user_id)
        future = client.post("/api/recovery-signals/imports", json=self.payload(observed_at=datetime.now(UTC) + timedelta(minutes=1)))
        wrong_unit = client.post("/api/recovery-signals/imports", json=self.payload(unit="bpm"))
        out_of_range = client.post("/api/recovery-signals/imports", json=self.payload(value=301.0))
        mixed = self.payload("valid")
        mixed["observations"].append({**self.payload("invalid", value=301.0)["observations"][0]})
        atomic = client.post("/api/recovery-signals/imports", json=mixed)

        self.assertEqual([future.status_code, wrong_unit.status_code, out_of_range.status_code, atomic.status_code], [422, 422, 422, 422])
        with self.SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(RecoverySignalObservation)), 0)

    def test_new_observation_changes_athlete_state_fingerprint(self):
        with self.SessionLocal() as db:
            first = materialize_athlete_state(db, db.get(User, self.user_id))
        response = self.client_for(self.user_id).post("/api/recovery-signals/imports", json=self.payload())
        self.assertEqual(response.status_code, 200, response.text)
        with self.SessionLocal() as db:
            second = materialize_athlete_state(db, db.get(User, self.user_id))
        self.assertNotEqual(first["snapshot_id"], second["snapshot_id"])
        self.assertNotEqual(first["input_fingerprint"], second["input_fingerprint"])

    def test_export_and_delete_are_scoped(self):
        self.client_for(self.user_id).post("/api/recovery-signals/imports", json=self.payload())
        self.client_for(self.other_user_id).post("/api/recovery-signals/imports", json=self.payload())
        with self.SessionLocal() as db:
            exported = export_user_data(db, db.get(User, self.user_id))
            self.assertEqual(exported["version"], "2026-07-15.0031")
            self.assertEqual(len(exported["recovery_signal_observations"]), 1)
            counts = delete_user_data(db, self.user_id)
            db.commit()
            self.assertEqual(counts["recovery_signal_observations"], 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(RecoverySignalObservation).where(RecoverySignalObservation.user_id == self.other_user_id)), 1)

    def test_migration_runner_creates_stage_five_constraints(self):
        with self.engine.begin() as connection:
            connection.execute(text("DROP TABLE recovery_signal_observations CASCADE"))
            connection.execute(text("CREATE TABLE IF NOT EXISTS schema_migrations (version VARCHAR(255) PRIMARY KEY, applied_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now())"))
            connection.execute(text("DELETE FROM schema_migrations WHERE version = '20260714_0028_recovery_signal_observations'"))
        run_migrations(self.engine)
        with self.engine.connect() as connection:
            constraints = set(connection.execute(text("SELECT constraint_name FROM information_schema.table_constraints WHERE table_schema = current_schema() AND table_name = 'recovery_signal_observations'" )).scalars())
        self.assertTrue({"uq_recovery_signal_source_record", "ck_recovery_signal_metric_key", "ck_recovery_signal_observed_received"}.issubset(constraints))

    def test_migration_runner_serializes_concurrent_startup(self):
        with self.engine.begin() as connection:
            connection.execute(text("DROP TABLE recovery_signal_observations CASCADE"))
            connection.execute(text("CREATE TABLE IF NOT EXISTS schema_migrations (version VARCHAR(255) PRIMARY KEY, applied_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now())"))
            for version, _ in __import__("app.db.migrations.runner", fromlist=["MIGRATIONS"]).MIGRATIONS[:-1]:
                connection.execute(text("INSERT INTO schema_migrations (version) VALUES (:version) ON CONFLICT DO NOTHING"), {"version": version})
            connection.execute(text("DELETE FROM schema_migrations WHERE version = '20260714_0028_recovery_signal_observations'"))
        barrier = threading.Barrier(2)
        errors = []

        def migrate():
            try:
                barrier.wait()
                run_migrations(self.engine)
            except Exception as error:
                errors.append(error)

        threads = [threading.Thread(target=migrate) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        with self.engine.connect() as connection:
            self.assertEqual(connection.execute(text("SELECT count(*) FROM schema_migrations WHERE version = '20260714_0028_recovery_signal_observations'" )).scalar_one(), 1)


if __name__ == "__main__":
    unittest.main()
