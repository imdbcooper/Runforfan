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
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.orm import sessionmaker

    from app.api.errors import add_exception_handlers
    from app.api.routes import safety_escalations as escalation_routes
    from app.api.routes import safety_reviews as review_routes
    from app.db.base import Base
    from app.db.migrations.runner import run_migrations
    from app.models import AthleteProfile, SafetyEscalation, SafetyEscalationEvent, SafetyReviewConsent, SafetyReviewEvent, SafetyReviewerGrant, SafetyReviewRequest, TrainingPlan, TrainingPlanVersion, User
    from app.services import safety_escalations, safety_reviews
    from app.services.data_management import delete_user_data, export_user_data
except ModuleNotFoundError as exc:
    if exc.name in {"fastapi", "httpx", "psycopg", "sqlalchemy"}:
        raise unittest.SkipTest("PostgreSQL dependencies are required for safety review integration tests") from exc
    raise


TEST_DATABASE_URL = os.getenv("RUNFORFAN_TEST_DATABASE_URL")


@unittest.skipUnless(TEST_DATABASE_URL, "RUNFORFAN_TEST_DATABASE_URL is required for PostgreSQL integration tests")
class SafetyReviewPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database_name = make_url(TEST_DATABASE_URL).database or ""
        if not database_name.endswith("_test"):
            raise RuntimeError("RUNFORFAN_TEST_DATABASE_URL must point to a database whose name ends with _test")
        cls.schema = f"safety_review_{uuid.uuid4().hex}"
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
            athlete = User(display_name="Safety Runner", is_demo=False, is_active=True)
            other = User(display_name="Other Runner", is_demo=False, is_active=True)
            reviewer = User(display_name="Reviewer One", is_demo=False, is_active=True)
            second_reviewer = User(display_name="Reviewer Two", is_demo=False, is_active=True)
            demo_reviewer = User(display_name="Demo Reviewer", is_demo=True, is_active=True)
            db.add_all([athlete, other, reviewer, second_reviewer, demo_reviewer])
            db.flush()
            db.add_all([
                AthleteProfile(user_id=athlete.id, timezone="Europe/Moscow", recovery_status="injured", injury_notes="private injury detail", health_conditions="private condition"),
                AthleteProfile(user_id=other.id, timezone="Europe/Moscow", recovery_status="normal"),
                SafetyReviewerGrant(user_id=reviewer.id, status="active"),
                SafetyReviewerGrant(user_id=second_reviewer.id, status="active"),
            ])
            db.commit()
            self.athlete_id = athlete.id
            self.other_id = other.id
            self.reviewer_id = reviewer.id
            self.second_reviewer_id = second_reviewer.id
            self.demo_reviewer_id = demo_reviewer.id

    def enabled(self, *, escalation=True, review=True, reviewer_api=True):
        settings = SimpleNamespace(
            safety_escalation_enabled=escalation,
            safety_review_enabled=review,
            safety_review_reviewer_api_enabled=reviewer_api,
        )
        return patch.object(safety_reviews, "get_settings", return_value=settings)

    def client_for(self, user_id: int) -> TestClient:
        app = FastAPI()
        add_exception_handlers(app)
        app.include_router(escalation_routes.router, prefix="/api")
        app.include_router(review_routes.router, prefix="/api")

        def override_db():
            with self.SessionLocal() as db:
                yield db

        def current_user():
            with self.SessionLocal() as db:
                user = db.get(User, user_id)
                db.expunge(user)
                return user

        app.dependency_overrides[escalation_routes.get_db] = override_db
        app.dependency_overrides[escalation_routes.get_current_user] = current_user
        app.dependency_overrides[review_routes.get_db] = override_db
        app.dependency_overrides[review_routes.get_current_user] = current_user
        return TestClient(app)

    def open_case(self) -> int:
        with self.SessionLocal() as db:
            escalation = SafetyEscalation(
                user_id=self.athlete_id,
                local_date=date.today(),
                trigger_kind="return_to_run_ambiguous",
                severity="critical",
                status="open",
                rule_version=safety_escalations.RULE_VERSION,
                source_rule_version="daily-readiness-v3",
                source_rule_id="profile_injured",
                source_key="profile:private",
                source_fingerprint=uuid.uuid4().hex + uuid.uuid4().hex,
            )
            db.add(escalation)
            db.flush()
            db.add(SafetyEscalationEvent(escalation_id=escalation.id, user_id=self.athlete_id, event_type="opened", actor_kind="system", rule_version=safety_escalations.RULE_VERSION, metadata_json={}))
            db.commit()
            return escalation.id

    def request_case(self, escalation_id: int) -> int:
        with self.enabled():
            consent = self.client_for(self.athlete_id).post(f"/api/safety-escalations/{escalation_id}/review-consent", json={"policy_version": safety_reviews.POLICY_VERSION})
            requested = self.client_for(self.athlete_id).post(f"/api/safety-escalations/{escalation_id}/review-request", json={"request": "human_review"})
        self.assertEqual(consent.status_code, 200, consent.text)
        self.assertEqual(requested.status_code, 200, requested.text)
        with self.SessionLocal() as db:
            return db.scalar(select(SafetyReviewRequest.id).where(SafetyReviewRequest.escalation_id == escalation_id))

    def test_migration_creates_reviewer_workflow_constraints_and_triggers(self):
        with self.engine.connect() as connection:
            tables = set(connection.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema() AND table_name LIKE 'safety_review%'" )).scalars())
            constraints = set(connection.execute(text("SELECT constraint_name FROM information_schema.table_constraints WHERE table_schema = current_schema() AND table_name LIKE 'safety_review%'" )).scalars())
            triggers = set(connection.execute(text("SELECT tgname FROM pg_trigger JOIN pg_class ON pg_class.oid = tgrelid JOIN pg_namespace ON pg_namespace.oid = pg_class.relnamespace WHERE pg_namespace.nspname = current_schema() AND NOT tgisinternal AND pg_class.relname LIKE 'safety_review%'" )).scalars())
            migrated = connection.execute(text("SELECT 1 FROM schema_migrations WHERE version = '20260715_0033_safety_review_workflow'")).scalar_one()
        self.assertEqual(tables, {"safety_reviewer_grants", "safety_review_consents", "safety_review_requests", "safety_review_events"})
        self.assertTrue({"fk_safety_review_request_owner", "fk_safety_review_request_consent_owner", "ck_safety_review_request_lifecycle", "ck_safety_review_event_pair"}.issubset(constraints))
        self.assertEqual(triggers, {"trg_safety_reviewer_grant", "trg_safety_review_consent", "trg_safety_review_request", "trg_safety_review_event", "trg_safety_review_request_event_presence"})
        self.assertEqual(migrated, 1)

    def test_database_rejects_demo_reviewer_grant(self):
        with self.SessionLocal() as db:
            db.add(SafetyReviewerGrant(user_id=self.demo_reviewer_id, status="active"))
            with self.assertRaises(DBAPIError):
                db.commit()

    def test_consent_and_request_are_owned_explicit_and_idempotent(self):
        escalation_id = self.open_case()
        with self.enabled():
            wrong_owner = self.client_for(self.other_id).post(f"/api/safety-escalations/{escalation_id}/review-consent", json={"policy_version": safety_reviews.POLICY_VERSION})
            malformed = self.client_for(self.athlete_id).post(f"/api/safety-escalations/{escalation_id}/review-consent", json={"policy_version": safety_reviews.POLICY_VERSION, "notes": "private"})
            consent = self.client_for(self.athlete_id).post(f"/api/safety-escalations/{escalation_id}/review-consent", json={"policy_version": safety_reviews.POLICY_VERSION})
            duplicate = self.client_for(self.athlete_id).post(f"/api/safety-escalations/{escalation_id}/review-consent", json={"policy_version": safety_reviews.POLICY_VERSION})
            requested = self.client_for(self.athlete_id).post(f"/api/safety-escalations/{escalation_id}/review-request", json={"request": "human_review"})
            repeated = self.client_for(self.athlete_id).post(f"/api/safety-escalations/{escalation_id}/review-request", json={"request": "human_review"})
        self.assertEqual(wrong_owner.status_code, 409)
        self.assertEqual(malformed.status_code, 422)
        self.assertEqual(consent.json(), duplicate.json())
        self.assertEqual(requested.json(), repeated.json())
        self.assertEqual(requested.json()["request_status"], "requested")
        self.assertIn("no guaranteed response time", requested.json()["disclaimer"])
        with self.SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(SafetyReviewConsent)), 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(SafetyReviewRequest)), 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(SafetyReviewEvent).where(SafetyReviewEvent.event_type == "requested")), 1)

    def test_reviewer_queue_requires_grant_and_context_is_bounded(self):
        escalation_id = self.open_case()
        request_id = self.request_case(escalation_id)
        with self.enabled():
            denied = self.client_for(self.other_id).get("/api/safety-reviewer/requests")
            queue = self.client_for(self.reviewer_id).get("/api/safety-reviewer/requests")
            claimed = self.client_for(self.reviewer_id).post(f"/api/safety-reviewer/requests/{request_id}/claim")
            context = self.client_for(self.reviewer_id).get(f"/api/safety-reviewer/requests/{request_id}/context")
            other_context = self.client_for(self.second_reviewer_id).get(f"/api/safety-reviewer/requests/{request_id}/context")
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(queue.status_code, 200, queue.text)
        self.assertNotIn("trigger_kind", queue.text)
        self.assertEqual(claimed.status_code, 200, claimed.text)
        self.assertEqual(context.status_code, 200, context.text)
        self.assertEqual(other_context.status_code, 409)
        serialized = context.text.lower()
        for forbidden in ("user_id", "display_name", "telegram", "profile:private", "injury_notes", "private injury detail", "health_conditions"):
            self.assertNotIn(forbidden, serialized)
        self.assertIn("return_to_run_ambiguous", serialized)
        with self.SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(SafetyReviewEvent).where(SafetyReviewEvent.event_type == "viewed")), 2)

    def test_concurrent_claim_has_single_winner(self):
        escalation_id = self.open_case()
        request_id = self.request_case(escalation_id)
        barrier = threading.Barrier(2)
        statuses: list[int] = []

        def claim(reviewer_id: int):
            barrier.wait(5)
            statuses.append(self.client_for(reviewer_id).post(f"/api/safety-reviewer/requests/{request_id}/claim").status_code)

        with self.enabled():
            threads = [threading.Thread(target=claim, args=(reviewer_id,)) for reviewer_id in (self.reviewer_id, self.second_reviewer_id)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(10)
        self.assertEqual(sorted(statuses), [200, 409])
        with self.SessionLocal() as db:
            request = db.get(SafetyReviewRequest, request_id)
            self.assertIn(request.reviewer_user_id, {self.reviewer_id, self.second_reviewer_id})
            self.assertEqual(db.scalar(select(func.count()).select_from(SafetyReviewEvent).where(SafetyReviewEvent.event_type == "claimed")), 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(SafetyReviewEvent).where(SafetyReviewEvent.event_type == "viewed")), 1)

    def test_concurrent_claim_and_withdrawal_are_fail_closed_without_server_error(self):
        escalation_id = self.open_case()
        request_id = self.request_case(escalation_id)
        barrier = threading.Barrier(2)
        statuses: list[int] = []

        def claim():
            barrier.wait(5)
            statuses.append(self.client_for(self.reviewer_id).post(f"/api/safety-reviewer/requests/{request_id}/claim").status_code)

        def withdraw():
            barrier.wait(5)
            statuses.append(self.client_for(self.athlete_id).delete(f"/api/safety-escalations/{escalation_id}/review-consent").status_code)

        with self.enabled():
            threads = [threading.Thread(target=claim), threading.Thread(target=withdraw)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(10)
        self.assertEqual(len(statuses), 2)
        self.assertNotIn(500, statuses)
        self.assertIn(200, statuses)
        with self.SessionLocal() as db:
            consent = db.scalar(select(SafetyReviewConsent).where(SafetyReviewConsent.escalation_id == escalation_id))
            request = db.get(SafetyReviewRequest, request_id)
            self.assertEqual(consent.status, "withdrawn")
            self.assertEqual(request.status, "withdrawn")

    def test_reviewer_cannot_see_or_claim_own_request(self):
        with self.SessionLocal() as db:
            profile = db.scalar(select(AthleteProfile).where(AthleteProfile.user_id == self.reviewer_id))
            if profile is None:
                db.add(AthleteProfile(user_id=self.reviewer_id, timezone="Europe/Moscow", recovery_status="injured"))
            escalation = SafetyEscalation(
                user_id=self.reviewer_id,
                local_date=date.today(),
                trigger_kind="return_to_run_ambiguous",
                severity="critical",
                status="open",
                rule_version=safety_escalations.RULE_VERSION,
                source_rule_version="daily-readiness-v3",
                source_rule_id="profile_injured",
                source_key="profile:self-review",
                source_fingerprint=uuid.uuid4().hex + uuid.uuid4().hex,
            )
            db.add(escalation)
            db.flush()
            db.add(SafetyEscalationEvent(escalation_id=escalation.id, user_id=self.reviewer_id, event_type="opened", actor_kind="system", rule_version=safety_escalations.RULE_VERSION, metadata_json={}))
            db.commit()
            self_escalation_id = escalation.id
        with self.enabled():
            self.client_for(self.reviewer_id).post(f"/api/safety-escalations/{self_escalation_id}/review-consent", json={"policy_version": safety_reviews.POLICY_VERSION})
            self.client_for(self.reviewer_id).post(f"/api/safety-escalations/{self_escalation_id}/review-request", json={"request": "human_review"})
            with self.SessionLocal() as db:
                request_id = db.scalar(select(SafetyReviewRequest.id).where(SafetyReviewRequest.escalation_id == self_escalation_id))
            queue = self.client_for(self.reviewer_id).get("/api/safety-reviewer/requests")
            claim = self.client_for(self.reviewer_id).post(f"/api/safety-reviewer/requests/{request_id}/claim")
        self.assertNotIn(request_id, [item["id"] for item in queue.json()])
        self.assertEqual(claim.status_code, 409)

    def test_request_requires_an_eligible_reviewer_other_than_athlete(self):
        escalation_id = self.open_case()
        with self.SessionLocal() as db:
            grants = list(db.scalars(select(SafetyReviewerGrant).where(SafetyReviewerGrant.status == "active").with_for_update()))
            now = datetime.now(UTC)
            for grant in grants:
                grant.status = "revoked"
                grant.revoked_at = now
            db.add(SafetyReviewerGrant(user_id=self.athlete_id, status="active"))
            db.commit()
        with self.enabled():
            consent = self.client_for(self.athlete_id).post(f"/api/safety-escalations/{escalation_id}/review-consent", json={"policy_version": safety_reviews.POLICY_VERSION})
            requested = self.client_for(self.athlete_id).post(f"/api/safety-escalations/{escalation_id}/review-request", json={"request": "human_review"})
        self.assertEqual(consent.status_code, 200)
        self.assertEqual(requested.status_code, 409)
        with self.SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(SafetyReviewRequest)), 0)

    def test_withdrawal_cuts_reviewer_access_and_cannot_be_reopened(self):
        escalation_id = self.open_case()
        request_id = self.request_case(escalation_id)
        with self.enabled():
            claimed = self.client_for(self.reviewer_id).post(f"/api/safety-reviewer/requests/{request_id}/claim")
            withdrawn = self.client_for(self.athlete_id).delete(f"/api/safety-escalations/{escalation_id}/review-consent")
            denied = self.client_for(self.reviewer_id).get(f"/api/safety-reviewer/requests/{request_id}/context")
            reopen = self.client_for(self.athlete_id).post(f"/api/safety-escalations/{escalation_id}/review-consent", json={"policy_version": safety_reviews.POLICY_VERSION})
        self.assertEqual(claimed.status_code, 200)
        self.assertEqual(withdrawn.json()["request_status"], "withdrawn")
        self.assertEqual(denied.status_code, 409)
        self.assertEqual(reopen.status_code, 409)

    def test_reviewer_revocation_releases_claim_and_blocks_access(self):
        escalation_id = self.open_case()
        request_id = self.request_case(escalation_id)
        with self.enabled():
            self.client_for(self.reviewer_id).post(f"/api/safety-reviewer/requests/{request_id}/claim")
            with self.SessionLocal() as db:
                grant, released = safety_reviews.revoke_reviewer(db, self.reviewer_id)
                self.assertEqual(grant.status, "revoked")
                self.assertEqual(released, 1)
            denied = self.client_for(self.reviewer_id).get(f"/api/safety-reviewer/requests/{request_id}/context")
            queue = self.client_for(self.second_reviewer_id).get("/api/safety-reviewer/requests")
        self.assertEqual(denied.status_code, 403)
        self.assertEqual([item["id"] for item in queue.json()], [request_id])
        with self.SessionLocal() as db:
            request = db.get(SafetyReviewRequest, request_id)
            self.assertEqual(request.status, "requested")
            self.assertIsNone(request.reviewer_user_id)
            self.assertEqual(db.scalar(select(func.count()).select_from(SafetyReviewEvent).where(SafetyReviewEvent.event_type == "released")), 1)

    def test_assigned_reviewer_can_release_request_to_opaque_queue(self):
        escalation_id = self.open_case()
        request_id = self.request_case(escalation_id)
        with self.enabled():
            claimed = self.client_for(self.reviewer_id).post(f"/api/safety-reviewer/requests/{request_id}/claim")
            released = self.client_for(self.reviewer_id).post(f"/api/safety-reviewer/requests/{request_id}/release")
            denied = self.client_for(self.reviewer_id).get(f"/api/safety-reviewer/requests/{request_id}/context")
            queue = self.client_for(self.second_reviewer_id).get("/api/safety-reviewer/requests")
        self.assertEqual(claimed.status_code, 200)
        self.assertEqual(released.status_code, 200, released.text)
        self.assertEqual(released.json()["status"], "requested")
        self.assertEqual(denied.status_code, 409)
        self.assertEqual([item["id"] for item in queue.json()], [request_id])
        with self.SessionLocal() as db:
            request = db.get(SafetyReviewRequest, request_id)
            self.assertIsNone(request.reviewer_user_id)
            self.assertEqual(db.scalar(select(func.count()).select_from(SafetyReviewEvent).where(SafetyReviewEvent.event_type == "released")), 1)

    def test_concurrent_claim_and_revoke_leave_reviewer_access_closed(self):
        escalation_id = self.open_case()
        request_id = self.request_case(escalation_id)
        barrier = threading.Barrier(2)
        outcomes: list[str] = []

        def claim():
            barrier.wait(5)
            outcomes.append(f"claim:{self.client_for(self.reviewer_id).post(f'/api/safety-reviewer/requests/{request_id}/claim').status_code}")

        def revoke():
            barrier.wait(5)
            with self.SessionLocal() as db:
                grant, released = safety_reviews.revoke_reviewer(db, self.reviewer_id)
                outcomes.append(f"revoke:{grant.status}:{released}")

        with self.enabled():
            threads = [threading.Thread(target=claim), threading.Thread(target=revoke)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(10)
            denied = self.client_for(self.reviewer_id).get(f"/api/safety-reviewer/requests/{request_id}/context")
        self.assertEqual(len(outcomes), 2)
        self.assertEqual(denied.status_code, 403)
        with self.SessionLocal() as db:
            grant = db.scalar(select(SafetyReviewerGrant).where(SafetyReviewerGrant.user_id == self.reviewer_id))
            request = db.get(SafetyReviewRequest, request_id)
            self.assertEqual(grant.status, "revoked")
            self.assertEqual(request.status, "requested")
            self.assertIsNone(request.reviewer_user_id)

    def test_database_blocks_direct_event_and_grant_deletion(self):
        escalation_id = self.open_case()
        request_id = self.request_case(escalation_id)
        with self.SessionLocal() as db:
            event_id = db.scalar(select(SafetyReviewEvent.id).where(SafetyReviewEvent.request_id == request_id))
            with self.assertRaises(DBAPIError):
                db.execute(text("DELETE FROM safety_review_events WHERE user_id = :user_id"), {"user_id": self.athlete_id})
                db.commit()
            db.rollback()
            with self.assertRaises(DBAPIError):
                db.execute(text("DELETE FROM safety_review_requests WHERE user_id = :user_id"), {"user_id": self.athlete_id})
                db.commit()
            db.rollback()
            with self.assertRaises(DBAPIError):
                db.execute(text("DELETE FROM safety_review_consents WHERE user_id = :user_id"), {"user_id": self.athlete_id})
                db.commit()
            db.rollback()
            with self.assertRaises(DBAPIError):
                db.execute(text("DELETE FROM safety_reviewer_grants WHERE user_id = :user_id"), {"user_id": self.reviewer_id})
                db.commit()
            db.rollback()
            self.assertIsNotNone(db.get(SafetyReviewEvent, event_id))
            self.assertIsNotNone(db.scalar(select(SafetyReviewerGrant).where(SafetyReviewerGrant.user_id == self.reviewer_id)))

    def test_database_blocks_same_status_transition_fact_mutation(self):
        escalation_id = self.open_case()
        request_id = self.request_case(escalation_id)
        with self.enabled():
            self.client_for(self.reviewer_id).post(f"/api/safety-reviewer/requests/{request_id}/claim")
            self.client_for(self.reviewer_id).post(f"/api/safety-reviewer/requests/{request_id}/complete", json={"disposition_code": "seek_local_professional_support"})
        with self.SessionLocal() as db:
            for column, value in (
                ("reviewer_user_id", str(self.second_reviewer_id)),
                ("claimed_at", "now() + interval '1 hour'"),
                ("completed_at", "now() + interval '1 hour'"),
                ("closed_at", "now()"),
                ("disposition_code", "'insufficient_information'"),
            ):
                with self.assertRaises(DBAPIError):
                    db.execute(text(f"UPDATE safety_review_requests SET {column} = {value} WHERE id = :id"), {"id": request_id})
                    db.commit()
                db.rollback()
            request = db.get(SafetyReviewRequest, request_id)
            self.assertEqual(request.reviewer_user_id, self.reviewer_id)
            self.assertEqual(request.disposition_code, "seek_local_professional_support")

    def test_database_requires_event_for_legal_status_transition(self):
        escalation_id = self.open_case()
        request_id = self.request_case(escalation_id)
        with self.SessionLocal() as db:
            with self.assertRaises(DBAPIError):
                db.execute(
                    text("UPDATE safety_review_requests SET status = 'claimed', reviewer_user_id = :reviewer_id, claimed_at = now() WHERE id = :id"),
                    {"reviewer_id": self.reviewer_id, "id": request_id},
                )
                db.commit()
            db.rollback()
            request = db.get(SafetyReviewRequest, request_id)
            self.assertEqual(request.status, "requested")
            self.assertIsNone(request.reviewer_user_id)

    def test_case_supersession_cancels_active_review(self):
        escalation_id = self.open_case()
        request_id = self.request_case(escalation_id)
        with self.enabled():
            self.client_for(self.reviewer_id).post(f"/api/safety-reviewer/requests/{request_id}/claim")
            with self.SessionLocal() as db:
                escalation = db.get(SafetyEscalation, escalation_id)
                safety_escalations._supersede(db, escalation, datetime.now(UTC))
                db.commit()
            denied = self.client_for(self.reviewer_id).get(f"/api/safety-reviewer/requests/{request_id}/context")
        self.assertEqual(denied.status_code, 409)
        with self.SessionLocal() as db:
            self.assertEqual(db.get(SafetyReviewConsent, db.scalar(select(SafetyReviewConsent.id))).status, "case_superseded")
            self.assertEqual(db.get(SafetyReviewRequest, request_id).status, "cancelled_case_superseded")

    def test_bounded_completion_export_delete_and_no_plan_mutation(self):
        escalation_id = self.open_case()
        request_id = self.request_case(escalation_id)
        with self.SessionLocal() as db:
            plan = TrainingPlan(user_id=self.athlete_id, title="Protected", goal_type="10k", target_date=date.today(), available_days_per_week=3, status="active")
            db.add(plan)
            db.flush()
            db.add(TrainingPlanVersion(plan_id=plan.id, user_id=self.athlete_id, version_number=1, reason="manual", snapshot_json={}, summary="baseline"))
            db.commit()
        with self.enabled():
            self.client_for(self.reviewer_id).post(f"/api/safety-reviewer/requests/{request_id}/claim")
            completed = self.client_for(self.reviewer_id).post(f"/api/safety-reviewer/requests/{request_id}/complete", json={"disposition_code": "seek_local_professional_support"})
            malformed = self.client_for(self.reviewer_id).post(f"/api/safety-reviewer/requests/{request_id}/complete", json={"disposition_code": "medical_clearance", "notes": "unsafe"})
        self.assertEqual(completed.status_code, 200, completed.text)
        self.assertEqual(malformed.status_code, 422)
        with self.SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(TrainingPlanVersion).where(TrainingPlanVersion.user_id == self.athlete_id)), 1)
            exported = export_user_data(db, db.get(User, self.athlete_id))
            self.assertEqual(exported["version"], "2026-07-15.0033")
            serialized = str({"consents": exported["safety_review_consents"], "requests": exported["safety_review_requests"], "events": exported["safety_review_events"]})
            self.assertNotIn("reviewer_user_id", serialized)
            self.assertNotIn("actor_user_id", serialized)
            self.assertNotIn("private injury detail", serialized)
            counts = delete_user_data(db, self.athlete_id)
            db.commit()
            self.assertEqual(counts["safety_review_requests"], 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(SafetyReviewRequest).where(SafetyReviewRequest.user_id == self.athlete_id)), 0)

    def test_closed_rollout_hides_athlete_and_reviewer_apis(self):
        escalation_id = self.open_case()
        with self.enabled(review=False, reviewer_api=False):
            athlete = self.client_for(self.athlete_id).get(f"/api/safety-escalations/{escalation_id}/review")
            reviewer = self.client_for(self.reviewer_id).get("/api/safety-reviewer/requests")
        self.assertEqual(athlete.status_code, 200)
        self.assertFalse(athlete.json()["available"])
        self.assertEqual(reviewer.status_code, 404)


if __name__ == "__main__":
    unittest.main()
