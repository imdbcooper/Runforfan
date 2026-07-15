import os
import unittest
import threading
import uuid
from datetime import UTC, date, datetime, timedelta

try:
    from sqlalchemy import create_engine, select, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.orm import sessionmaker

    from app.db.base import Base
    from app.db.migrations.runner import run_migrations
    from app.models import CoachEvaluationRun, SafetyEscalation, SafetyEscalationEvent, TrainingPlan, TrainingPlanVersion, User, WeeklyReview
    from app.services.coach_evaluation import EVALUATION_VERSION, THRESHOLD_VERSION, evaluate_window, materialize_evaluation, run_to_dict
except ModuleNotFoundError as exc:
    if exc.name in {"psycopg", "sqlalchemy"}:
        raise unittest.SkipTest("PostgreSQL dependencies are required for coach evaluation tests") from exc
    raise


TEST_DATABASE_URL = os.getenv("RUNFORFAN_TEST_DATABASE_URL")


@unittest.skipUnless(TEST_DATABASE_URL, "RUNFORFAN_TEST_DATABASE_URL is required for PostgreSQL integration tests")
class CoachEvaluationPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database_name = make_url(TEST_DATABASE_URL).database or ""
        if not database_name.endswith("_test"):
            raise RuntimeError("RUNFORFAN_TEST_DATABASE_URL must point to a database whose name ends with _test")
        cls.schema = f"coach_evaluation_{uuid.uuid4().hex}"
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
        self.start = datetime(2026, 6, 1, tzinfo=UTC)
        self.end = datetime(2026, 7, 1, tzinfo=UTC)
        with self.SessionLocal() as db:
            user = User(display_name="Evaluation Runner", is_demo=False, is_active=True)
            db.add(user)
            db.flush()
            self.user_id = user.id
            db.commit()

    def add_reviews(self, count: int = 20, *, pain: int = 0, overload: int = 0, execution: float = 0.9, adherence: float = 0.9):
        with self.SessionLocal() as db:
            for index in range(count):
                user_id = self.user_id
                if index:
                    user = User(display_name=f"Evaluation Runner {index}", is_demo=False, is_active=True)
                    db.add(user)
                    db.flush()
                    user_id = user.id
                week_start = date(2026, 6, 1)
                snapshot = {
                    "metrics": {"session_adherence": adherence, "execution_average": execution, "overdone_sessions": 1 if index < overload else 0, "high_risk_feedback": 0},
                    "readiness_trends": {"pain_days": 1 if index < pain else 0},
                }
                db.add(WeeklyReview(user_id=user_id, week_start=week_start, week_end=week_start + timedelta(days=6), timezone="UTC", review_version="weekly-review-v3", rule_version="weekly-review-rules-v3", input_fingerprint=f"{index:064x}", resolution_status="complete", snapshot_json=snapshot, as_of_at=self.start, computed_at=self.start + timedelta(hours=index + 1), trigger_type="on_read"))
            db.commit()

    def test_migration_creates_immutable_evaluation_runs(self):
        with self.engine.connect() as connection:
            migrated = connection.execute(text("SELECT 1 FROM schema_migrations WHERE version = '20260715_0035_coach_evaluation_runs'")).scalar_one()
            trigger = connection.execute(text("SELECT 1 FROM pg_trigger JOIN pg_class ON pg_class.oid = tgrelid WHERE pg_class.relname = 'coach_evaluation_runs' AND tgname = 'trg_coach_evaluation_run_immutable'")).scalar_one()
        self.assertEqual(migrated, 1)
        self.assertEqual(trigger, 1)

    def test_empty_window_is_insufficient_not_pass(self):
        with self.SessionLocal() as db:
            report = evaluate_window(db, self.start, self.end)
        self.assertEqual(report["status"], "insufficient_data")
        self.assertEqual(report["gates"]["review_coverage"]["status"], "insufficient_data")
        self.assertEqual(report["gates"]["retention"]["reason"], "not_measured")
        self.assertIn("Insufficient data is not a pass", report["disclaimer"])

    def test_partial_day_window_is_rejected(self):
        with self.SessionLocal() as db:
            with self.assertRaisesRegex(ValueError, "UTC midnight"):
                evaluate_window(db, self.start + timedelta(hours=1), self.end)

    def test_review_window_uses_reviewed_week_not_materialization_time(self):
        with self.SessionLocal() as db:
            db.add_all([
                WeeklyReview(user_id=self.user_id, week_start=date(2026, 5, 18), week_end=date(2026, 5, 24), timezone="UTC", review_version="weekly-review-v3", rule_version="weekly-review-rules-v3", input_fingerprint="a" * 64, resolution_status="complete", snapshot_json={"metrics": {}, "readiness_trends": {}}, as_of_at=self.start, computed_at=self.start + timedelta(days=1), trigger_type="on_read"),
                WeeklyReview(user_id=self.user_id, week_start=date(2026, 6, 1), week_end=date(2026, 6, 7), timezone="UTC", review_version="weekly-review-v3", rule_version="weekly-review-rules-v3", input_fingerprint="b" * 64, resolution_status="complete", snapshot_json={"metrics": {}, "readiness_trends": {}}, as_of_at=self.end, computed_at=self.start - timedelta(days=1), trigger_type="on_read"),
            ])
            db.commit()
        with self.SessionLocal() as db:
            report = evaluate_window(db, self.start, self.end)
        self.assertEqual(report["metrics"]["weekly_review_samples"], 1)
        self.assertEqual(report["incidents"]["weekly_review_rule_versions"], {"weekly-review-rules-v3": 1})

    def test_complete_evidence_keeps_unmeasured_product_outcomes_truthful(self):
        self.add_reviews()
        with self.SessionLocal() as db:
            report = evaluate_window(db, self.start, self.end)
        self.assertEqual(report["gates"]["session_adherence"]["status"], "pass")
        self.assertEqual(report["gates"]["completion_quality"]["status"], "pass")
        self.assertEqual(report["gates"]["pain_flags"]["status"], "pass")
        self.assertEqual(report["gates"]["summary"]["product_evidence_status"], "insufficient_data")
        self.assertEqual(report["status"], "insufficient_data")

    def test_unsafe_progression_during_active_case_blocks_release(self):
        self.add_reviews()
        with self.SessionLocal() as db:
            plan = TrainingPlan(user_id=self.user_id, title="Protected", goal_type="10k", target_date=date(2026, 9, 1), available_days_per_week=3, status="active")
            db.add(plan)
            db.flush()
            escalation = SafetyEscalation(user_id=self.user_id, local_date=date(2026, 6, 10), trigger_kind="red_flag_stop", severity="critical", status="open", rule_version="safety-escalation-v1", source_rule_version="daily-readiness-v3", source_rule_id="pain_or_illness_stop", source_key="test", source_fingerprint="a" * 64, created_at=self.start + timedelta(days=5), updated_at=self.start + timedelta(days=5))
            db.add(escalation)
            db.flush()
            db.add(SafetyEscalationEvent(escalation_id=escalation.id, user_id=self.user_id, event_type="opened", actor_kind="system", rule_version="safety-escalation-v1", occurred_at=self.start + timedelta(days=5), metadata_json={}))
            db.add(TrainingPlanVersion(user_id=self.user_id, plan_id=plan.id, version_number=1, reason="weekly_strategy_conservative_progression", snapshot_json={}, created_at=self.start + timedelta(days=10)))
            db.commit()
        with self.SessionLocal() as db:
            report = evaluate_window(db, self.start, self.end)
        self.assertEqual(report["metrics"]["unsafe_progression_mutations"], 1)
        self.assertEqual(report["gates"]["unsafe_suggestion"]["status"], "block")
        self.assertEqual(report["gates"]["summary"]["safety_release_status"], "block")
        self.assertEqual(report["status"], "block")

    def test_materialization_is_idempotent_private_and_immutable(self):
        self.add_reviews()
        with self.SessionLocal() as db:
            first = materialize_evaluation(db, self.start, self.end)
            second = materialize_evaluation(db, self.start, self.end)
            self.assertEqual(first.id, second.id)
            serialized = str(run_to_dict(first)).lower()
            for forbidden in ("user_id", "plan_id", "request_id", "display_name", "pain_notes", "health_conditions"):
                self.assertNotIn(forbidden, serialized)
            with self.assertRaises(DBAPIError):
                db.execute(text("UPDATE coach_evaluation_runs SET status = 'pass' WHERE id = :id"), {"id": first.id})
                db.commit()
            db.rollback()
            self.assertEqual(db.scalar(select(CoachEvaluationRun.status).where(CoachEvaluationRun.id == first.id)), "insufficient_data")

    def test_concurrent_materialization_returns_one_run(self):
        barrier = threading.Barrier(2)
        ids: list[str] = []
        errors: list[str] = []

        def materialize():
            try:
                with self.SessionLocal() as db:
                    barrier.wait(5)
                    ids.append(materialize_evaluation(db, self.start, self.end).id)
            except Exception as error:
                errors.append(str(error))

        threads = [threading.Thread(target=materialize) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        self.assertEqual(errors, [])
        self.assertEqual(len(set(ids)), 1)
        with self.SessionLocal() as db:
            self.assertEqual(len(list(db.scalars(select(CoachEvaluationRun)))), 1)


if __name__ == "__main__":
    unittest.main()
