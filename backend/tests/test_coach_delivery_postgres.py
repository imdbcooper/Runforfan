import os
import threading
import unittest
import uuid
from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace
from unittest.mock import patch

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, func, select, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import sessionmaker

    from app.api.errors import add_exception_handlers
    from app.api.routes import coach_delivery as coach_delivery_routes
    from app.db.base import Base
    from app.db.migrations.runner import run_migrations
    from app.models import CoachDelivery, CoachDeliveryAttempt, CoachDeliveryPreference, User
    from app.services import coach_delivery, telegram_bot
    from app.services.data_management import delete_user_data, export_user_data
    from app.services.telegram_bot import TelegramDeliveryError, TelegramDeliveryResult
except ModuleNotFoundError as exc:
    if exc.name in {"fastapi", "httpx", "psycopg", "sqlalchemy"}:
        raise unittest.SkipTest("PostgreSQL dependencies are required for coach delivery integration tests") from exc
    raise


TEST_DATABASE_URL = os.getenv("RUNFORFAN_TEST_DATABASE_URL")


@unittest.skipUnless(TEST_DATABASE_URL, "RUNFORFAN_TEST_DATABASE_URL is required for PostgreSQL integration tests")
class CoachDeliveryPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database_name = make_url(TEST_DATABASE_URL).database or ""
        if not database_name.endswith("_test"):
            raise RuntimeError("RUNFORFAN_TEST_DATABASE_URL must point to a database whose name ends with _test")
        cls.schema = f"coach_delivery_{uuid.uuid4().hex}"
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
            user = User(display_name="Delivery Runner", telegram_id=101, is_demo=False)
            other = User(display_name="Other Runner", telegram_id=202, is_demo=False)
            db.add_all([user, other])
            db.commit()
            self.user_id = user.id
            self.other_user_id = other.id

    def settings(self, *, enabled=True, worker_enabled=True):
        return patch.object(
            coach_delivery,
            "get_settings",
            return_value=SimpleNamespace(
                coach_delivery_enabled=enabled,
                coach_delivery_worker_enabled=worker_enabled,
                coach_delivery_batch_size=25,
                coach_delivery_max_attempts=3,
                coach_delivery_retry_base_seconds=60,
            ),
        )

    def delivery(self, user_id=None, *, delivery_id="delivery-1", local_date=None, status="pending", scheduled_for=None, retry_at=None, attempt_count=0, max_attempts=3):
        now = datetime.now(UTC)
        return CoachDelivery(
            id=delivery_id,
            user_id=user_id or self.user_id,
            local_date=local_date or date.today(),
            timezone="Europe/Moscow",
            rule_version=coach_delivery.DAILY_BRIEF_RULE_VERSION,
            template_key="proceed",
            content_fingerprint="a" * 64,
            status=status,
            scheduled_for=scheduled_for or now - timedelta(minutes=1),
            retry_at=retry_at,
            attempt_count=attempt_count,
            max_attempts=max_attempts,
            locked_at=now if status == "sending" else None,
            locked_by="test-worker" if status == "sending" else None,
        )

    def enabled_preference(self, db, user_id=None, chat_id=101):
        preference = CoachDeliveryPreference(
            user_id=user_id or self.user_id,
            telegram_chat_id=chat_id,
            telegram_chat_verified_at=datetime.now(UTC),
            telegram_enabled=True,
            daily_brief_local_time=time(8),
        )
        db.add(preference)
        return preference

    def test_migration_creates_delivery_tables_constraints_and_indexes(self):
        with self.engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS coach_delivery_attempts, coach_deliveries, coach_delivery_preferences CASCADE"))
            connection.execute(text("CREATE TABLE IF NOT EXISTS schema_migrations (version VARCHAR(255) PRIMARY KEY, applied_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now())"))
            connection.execute(text("DELETE FROM schema_migrations WHERE version IN ('20260714_0029_coach_delivery', '20260714_0030_coach_delivery_constraints')"))
        run_migrations(self.engine)
        with self.engine.connect() as connection:
            tables = set(connection.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()")).scalars())
            constraints = set(connection.execute(text("SELECT constraint_name FROM information_schema.table_constraints WHERE table_schema = current_schema() AND table_name IN ('coach_delivery_preferences', 'coach_deliveries', 'coach_delivery_attempts')")).scalars())
            indexes = set(connection.execute(text("SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()")).scalars())
            migrations = set(connection.execute(text("SELECT version FROM schema_migrations WHERE version LIKE '20260714_00%_coach_delivery%'")).scalars())
        self.assertTrue({"coach_delivery_preferences", "coach_deliveries", "coach_delivery_attempts"}.issubset(tables))
        self.assertTrue({"ck_coach_delivery_preference_enabled_destination", "uq_coach_delivery_daily", "ck_coach_delivery_attempt_counts", "ck_coach_delivery_retry_scheduled_at", "ck_coach_delivery_attempt_number", "uq_coach_delivery_attempt"}.issubset(constraints))
        self.assertTrue({"ix_coach_delivery_due_queue", "ix_coach_delivery_user_history", "ix_coach_delivery_attempts_delivery_id"}.issubset(indexes))
        self.assertEqual(migrations, {"20260714_0029_coach_delivery", "20260714_0030_coach_delivery_constraints"})

    def test_database_enforces_preference_delivery_and_attempt_constraints(self):
        invalid = [
            CoachDeliveryPreference(user_id=self.user_id, telegram_enabled=True),
            self.delivery(delivery_id="bad-count", attempt_count=4, max_attempts=3),
            self.delivery(delivery_id="bad-retry", status="retry_scheduled"),
        ]
        for row in invalid:
            with self.subTest(model=type(row).__name__), self.SessionLocal() as db:
                db.add(row)
                with self.assertRaises(IntegrityError):
                    db.commit()

        with self.SessionLocal() as db:
            delivery = self.delivery(delivery_id="attempt-check")
            db.add(delivery)
            db.commit()
            db.add(CoachDeliveryAttempt(delivery_id=delivery.id, attempt_number=0, status="success", started_at=datetime.now(UTC), completed_at=datetime.now(UTC)))
            with self.assertRaises(IntegrityError):
                db.commit()

    def test_private_start_verifies_destination_without_enabling_and_group_or_mismatch_is_ignored(self):
        with self.SessionLocal() as db:
            user = db.get(User, self.user_id)
            coach_delivery.verify_private_telegram_chat(db, user, 101, 101)
            preference = db.scalar(select(CoachDeliveryPreference).where(CoachDeliveryPreference.user_id == self.user_id))
            self.assertEqual(preference.telegram_chat_id, 101)
            self.assertIsNotNone(preference.telegram_chat_verified_at)
            self.assertFalse(preference.telegram_enabled)

        update = {"message": {"from": {"id": 303}, "chat": {"id": 404, "type": "private"}, "text": "/start"}}
        with patch.object(telegram_bot, "get_or_create_telegram_user_from_profile") as create_user:
            telegram_bot.handle_telegram_webhook_update(object(), update)
        create_user.assert_not_called()

    def test_export_is_user_scoped_and_excludes_destination_and_message_bodies(self):
        with self.SessionLocal() as db:
            self.enabled_preference(db, chat_id=101)
            db.add(self.delivery(delivery_id="user-delivery"))
            db.add(self.delivery(self.other_user_id, delivery_id="other-delivery"))
            db.commit()
            exported = export_user_data(db, db.get(User, self.user_id))
            self.assertEqual([item["id"] for item in exported["coach_deliveries"]], ["user-delivery"])
            self.assertNotIn("telegram_chat_id", exported["coach_delivery_preference"])
            serialized = str({"preference": exported["coach_delivery_preference"], "deliveries": exported["coach_deliveries"], "attempts": exported["coach_delivery_attempts"]})
            self.assertNotIn("telegram_chat_id", serialized)
            self.assertNotIn("message_body", serialized)
            self.assertNotIn("raw_body", serialized)

    def test_delete_removes_delivery_preference_and_attempts(self):
        with self.SessionLocal() as db:
            self.enabled_preference(db)
            delivery = self.delivery(delivery_id="delete-me")
            db.add(delivery)
            db.flush()
            db.add(CoachDeliveryAttempt(delivery_id=delivery.id, attempt_number=1, status="success", started_at=datetime.now(UTC), completed_at=datetime.now(UTC)))
            db.commit()
            counts = delete_user_data(db, self.user_id)
            db.commit()
            self.assertEqual(counts["coach_delivery_preferences"], 1)
            self.assertEqual(counts["coach_deliveries"], 1)
            self.assertEqual(counts["coach_delivery_attempts"], 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(CoachDelivery)), 0)
            self.assertEqual(db.scalar(select(func.count()).select_from(CoachDeliveryAttempt)), 0)

    def test_same_day_delivery_is_unique_and_future_delivery_is_not_claimed(self):
        with self.SessionLocal() as db:
            first = self.delivery(delivery_id="first", scheduled_for=datetime.now(UTC) + timedelta(hours=1))
            duplicate = self.delivery(delivery_id="duplicate", scheduled_for=datetime.now(UTC) + timedelta(hours=1))
            db.add(first)
            db.commit()
            db.add(duplicate)
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()
            with self.settings():
                self.assertEqual(coach_delivery.claim_due_deliveries(db, "worker", datetime.now(UTC)), [])

    def test_claiming_due_retry_clears_retry_schedule(self):
        with self.SessionLocal() as db:
            db.add(self.delivery(delivery_id="retry-due", status="retry_scheduled", retry_at=datetime.now(UTC) - timedelta(seconds=1)))
            db.commit()
            with self.settings():
                claimed = coach_delivery.claim_due_deliveries(db, "worker", datetime.now(UTC))
            self.assertEqual([row.id for row in claimed], ["retry-due"])
            claimed_delivery = db.get(CoachDelivery, "retry-due")
            self.assertEqual(claimed_delivery.status, "sending")
            self.assertIsNone(claimed_delivery.retry_at)

    def test_concurrent_claims_do_not_claim_same_delivery(self):
        with self.SessionLocal() as db:
            db.add(self.delivery(delivery_id="race"))
            db.commit()

        barrier = threading.Barrier(2)
        claims: list[list[str]] = []
        errors: list[BaseException] = []

        def claim(worker_id):
            try:
                with self.SessionLocal() as db, self.settings():
                    barrier.wait(timeout=5)
                    claims.append([row.id for row in coach_delivery.claim_due_deliveries(db, worker_id, datetime.now(UTC))])
            except BaseException as exc:  # Propagate worker failures to the test thread.
                errors.append(exc)

        threads = [threading.Thread(target=claim, args=(f"worker-{index}",)) for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertFalse(errors)
        self.assertEqual(sum(len(items) for items in claims), 1)

    def test_success_safe_retry_permanent_failures_and_global_switch_never_send(self):
        with self.SessionLocal() as db:
            self.enabled_preference(db)
            db.add_all([
                self.delivery(delivery_id="success", status="sending"),
                self.delivery(delivery_id="retry", local_date=date.today() - timedelta(days=1), status="sending"),
                self.delivery(delivery_id="forbidden", local_date=date.today() - timedelta(days=2), status="sending"),
                self.delivery(delivery_id="disabled", local_date=date.today() - timedelta(days=3), status="sending"),
            ])
            db.commit()

        with self.SessionLocal() as db, self.settings():
            with patch.object(coach_delivery.TelegramDeliveryClient, "send", return_value=TelegramDeliveryResult(200)) as send:
                coach_delivery.process_delivery(db, "success")
            send.assert_called_once()
            success = db.get(CoachDelivery, "success")
            self.assertEqual(success.status, "sent")
            self.assertEqual(db.scalar(select(func.count()).select_from(CoachDeliveryAttempt).where(CoachDeliveryAttempt.delivery_id == "success")), 1)

            with patch.object(coach_delivery.TelegramDeliveryClient, "send", side_effect=TelegramDeliveryError("rate_limited", 429, 30)):
                coach_delivery.process_delivery(db, "retry")
            retry = db.get(CoachDelivery, "retry")
            self.assertEqual(retry.status, "retry_scheduled")
            self.assertIsNotNone(retry.retry_at)

            with patch.object(coach_delivery.TelegramDeliveryClient, "send", side_effect=TelegramDeliveryError("forbidden", 403)):
                coach_delivery.process_delivery(db, "forbidden")
            forbidden = db.get(CoachDelivery, "forbidden")
            preference = db.scalar(select(CoachDeliveryPreference).where(CoachDeliveryPreference.user_id == self.user_id))
            self.assertEqual(forbidden.status, "permanent_failure")
            self.assertFalse(preference.telegram_enabled)

        with self.SessionLocal() as db:
            preference = db.scalar(select(CoachDeliveryPreference).where(CoachDeliveryPreference.user_id == self.user_id))
            preference.telegram_enabled = True
            preference.disabled_at = None
            db.add_all([
                self.delivery(delivery_id="timeout", local_date=date.today() - timedelta(days=4), status="sending"),
                self.delivery(delivery_id="internal", local_date=date.today() - timedelta(days=5), status="sending"),
            ])
            db.commit()
            with self.settings(), patch.object(coach_delivery.TelegramDeliveryClient, "send", side_effect=TelegramDeliveryError("timeout")):
                coach_delivery.process_delivery(db, "timeout")
            timeout = db.get(CoachDelivery, "timeout")
            self.assertEqual(timeout.status, "permanent_failure")
            self.assertIsNone(timeout.retry_at)
            with self.settings(), patch.object(coach_delivery.TelegramDeliveryClient, "send", side_effect=RuntimeError("sensitive provider text")):
                coach_delivery.process_delivery(db, "internal")
            internal = db.get(CoachDelivery, "internal")
            self.assertEqual(internal.status, "permanent_failure")
            attempt = db.scalar(select(CoachDeliveryAttempt).where(CoachDeliveryAttempt.delivery_id == "internal"))
            self.assertEqual(attempt.failure_class, "internal")
            self.assertNotIn("sensitive provider text", str(attempt.__dict__))

        with self.SessionLocal() as db, self.settings(enabled=False):
            with patch.object(coach_delivery.TelegramDeliveryClient, "send") as send:
                coach_delivery.process_delivery(db, "disabled")
            send.assert_not_called()
            self.assertEqual(db.get(CoachDelivery, "disabled").status, "pending")
            self.assertEqual(coach_delivery.enqueue_due_deliveries(db), 0)
            self.assertEqual(coach_delivery.claim_due_deliveries(db, "worker"), [])
            self.assertEqual(coach_delivery.run_once(), 0)

    def test_stale_sending_delivery_fails_closed_without_retry(self):
        with self.SessionLocal() as db:
            delivery = self.delivery(delivery_id="ambiguous-send", status="sending")
            delivery.locked_at = datetime.now(UTC) - timedelta(minutes=11)
            db.add(delivery)
            db.commit()
            with self.settings():
                self.assertEqual(coach_delivery.claim_due_deliveries(db, "next-worker"), [])
            delivery = db.get(CoachDelivery, "ambiguous-send")
            self.assertEqual(delivery.status, "permanent_failure")
            self.assertIsNone(delivery.retry_at)
            self.assertIsNone(delivery.locked_at)
            self.assertIsNone(delivery.locked_by)

    def test_opt_out_waits_for_in_flight_authorization_then_disables(self):
        with self.SessionLocal() as db:
            self.enabled_preference(db)
            db.add(self.delivery(delivery_id="in-flight", status="sending"))
            db.commit()

        send_started = threading.Event()
        release_send = threading.Event()
        opt_out_done = threading.Event()
        errors: list[BaseException] = []

        def send():
            try:
                with self.SessionLocal() as db, self.settings(), patch.object(coach_delivery.TelegramDeliveryClient, "send", side_effect=lambda *_args: (send_started.set(), release_send.wait(5), TelegramDeliveryResult(200))[-1]):
                    coach_delivery.process_delivery(db, "in-flight")
            except BaseException as exc:
                errors.append(exc)

        def opt_out():
            try:
                with self.SessionLocal() as db, self.settings():
                    coach_delivery.update_preference(db, db.get(User, self.user_id), telegram_enabled=False, daily_brief_local_time=None)
                opt_out_done.set()
            except BaseException as exc:
                errors.append(exc)

        sender = threading.Thread(target=send)
        sender.start()
        self.assertTrue(send_started.wait(5))
        updater = threading.Thread(target=opt_out)
        updater.start()
        self.assertFalse(opt_out_done.wait(0.2))
        release_send.set()
        sender.join(10)
        updater.join(10)
        self.assertFalse(errors)
        self.assertTrue(opt_out_done.is_set())
        with self.SessionLocal() as db:
            preference = db.scalar(select(CoachDeliveryPreference).where(CoachDeliveryPreference.user_id == self.user_id))
            self.assertFalse(preference.telegram_enabled)
            self.assertEqual(db.get(CoachDelivery, "in-flight").status, "sent")

    def test_preferences_api_cannot_expose_another_users_destination(self):
        with self.SessionLocal() as db:
            self.enabled_preference(db, chat_id=101)
            db.commit()

        app = FastAPI()
        add_exception_handlers(app)
        app.include_router(coach_delivery_routes.router, prefix="/api")

        def override_db():
            with self.SessionLocal() as db:
                yield db

        app.dependency_overrides[coach_delivery_routes.get_db] = override_db
        app.dependency_overrides[coach_delivery_routes.get_current_user] = lambda: User(id=self.other_user_id, display_name="Other Runner")
        with patch.object(coach_delivery, "get_settings", return_value=SimpleNamespace(coach_delivery_enabled=False, telegram_bot_token=None)):
            response = TestClient(app).get("/api/coach-delivery/preferences")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["linked"], False)
        self.assertNotIn("telegram_chat_id", response.text)


if __name__ == "__main__":
    unittest.main()
