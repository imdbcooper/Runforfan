from __future__ import annotations

import json
import os
import unittest
import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

try:
    import httpx
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, func, select, text
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import sessionmaker

    from app.api.errors import add_exception_handlers
    from app.api.routes import coach as coach_routes
    from app.db.base import Base
    from app.db.migrations.runner import run_migrations
    from app.models import (
        AthleteProfile,
        AuditLog,
        CoachActionPreview,
        CoachConversation,
        CoachLlmAttempt,
        CoachMemory,
        CoachMessage,
        LlmProviderSetting,
        TrainingPlan,
        TrainingPlanVersion,
        TrainingPlanWorkout,
        User,
    )
    from app.schemas.coach import CoachAssistantResponse, CoachTurnCreate, MemoryUpdate, ProviderCoachOutput
    from app.services.conversational_coach import (
        CoachConflict,
        create_conversation,
        delete_memory,
        get_conversation,
        memory_out,
        submit_turn,
        update_memory,
    )
    from app.services.data_management import delete_user_data, export_user_data
    from app.services.secrets import encrypt_secret
except ModuleNotFoundError as exc:
    if exc.name in {"fastapi", "httpx", "psycopg", "sqlalchemy"}:
        raise unittest.SkipTest("PostgreSQL dependencies are required for conversational coach integration tests") from exc
    raise


TEST_DATABASE_URL = os.getenv("RUNFORFAN_TEST_DATABASE_URL")
SAFE_CONTEXT = {
    "sources": ["athlete_state"],
    "athlete_state": {"status": "ok"},
    "today_readiness": {"recommendation": {"status": "proceed"}},
    "weekly_review": {"review_id": None, "recommended_strategy": None},
    "upcoming_workouts": [],
    "coaching_events": [],
    "memory": {},
    "history": [],
    "limitations": [],
}


def provider_output(**overrides) -> dict[str, object]:
    data: dict[str, object] = {
        "intent": "inform",
        "answer": "Deterministic guidance remains authoritative.",
        "citations": [{"source_key": "athlete_state"}],
        "safety_status": "normal",
    }
    data.update(overrides)
    return data


@unittest.skipUnless(TEST_DATABASE_URL, "RUNFORFAN_TEST_DATABASE_URL is required for PostgreSQL integration tests")
class ConversationalCoachPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database_name = make_url(TEST_DATABASE_URL).database or ""
        if not database_name.endswith("_test"):
            raise RuntimeError("RUNFORFAN_TEST_DATABASE_URL must point to a database whose name ends with _test")
        cls.schema = f"conversational_coach_{uuid.uuid4().hex}"
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
            user = User(display_name="Coach Runner", is_demo=False)
            other = User(display_name="Other Runner", is_demo=False)
            db.add_all([user, other])
            db.flush()
            db.add(AthleteProfile(user_id=user.id, sex="unspecified", timezone="Europe/Moscow", locale="ru-RU", unit_system="metric", recovery_status="normal"))
            plan = TrainingPlan(user_id=user.id, title="Coach Plan", goal_type="10k", target_date=date.today() + timedelta(days=30), available_days_per_week=3, status="active")
            plan.workouts = [TrainingPlanWorkout(scheduled_date=date.today() + timedelta(days=1), status="planned", week_index=1, day_index=1, workout_type="easy", title="Easy", distance_km=8.0, duration_seconds=3000, intensity="easy")]
            db.add(plan)
            db.commit()
            self.user_id = user.id
            self.other_user_id = other.id
            self.workout_id = plan.workouts[0].id

    def seed_provider(self, db, *, model: str = "primary", is_default: bool = True) -> LlmProviderSetting:
        provider = LlmProviderSetting(
            user_id=self.user_id,
            provider="openai",
            display_name=model,
            model=model,
            encrypted_api_key=encrypt_secret("test-key"),
            is_default=is_default,
            is_active=True,
        )
        db.add(provider)
        db.commit()
        db.refresh(provider)
        return provider

    def conversation_id(self, db) -> str:
        return create_conversation(db, db.get(User, self.user_id), "overview")["id"]

    def settings(self, *, turn_limit: int = 10, pending_limit: int = 3):
        return patch(
            "app.services.conversational_coach.get_settings",
            return_value=SimpleNamespace(coach_turn_limit=turn_limit, coach_turn_window_minutes=10, coach_pending_turn_limit=pending_limit),
        )

    def submit(self, db, conversation_id: str, message: str = "Explain today's decision"):
        with self.settings(), patch("app.services.conversational_coach.build_coach_context", return_value=SAFE_CONTEXT):
            return submit_turn(db, db.get(User, self.user_id), conversation_id, CoachTurnCreate(message=message, context="general"))

    def client_for(self, user_id: int, *, enabled: bool = True) -> TestClient:
        app = FastAPI()
        add_exception_handlers(app)
        app.include_router(coach_routes.router, prefix="/api")

        def override_db():
            with self.SessionLocal() as db:
                yield db

        app.dependency_overrides[coach_routes.get_db] = override_db
        app.dependency_overrides[coach_routes.get_current_user] = lambda: User(id=user_id, display_name="Runner")
        settings_patch = patch.object(coach_routes, "get_settings", return_value=SimpleNamespace(coach_enabled=enabled))
        settings_patch.start()
        self.addCleanup(settings_patch.stop)
        return TestClient(app)

    def test_turn_persists_ordered_messages_attempt_and_audit(self):
        with self.SessionLocal() as db:
            conversation_id = self.conversation_id(db)
            provider = self.seed_provider(db)
            provider_id = provider.id
            with patch("app.services.coach_provider._request", return_value=json.dumps(provider_output())) as request:
                assistant = self.submit(db, conversation_id)

        self.assertEqual(assistant["response"].mode, "llm")
        self.assertEqual(assistant["response"].provider_model, "primary")
        request.assert_called_once()
        with self.SessionLocal() as db:
            messages = list(db.scalars(select(CoachMessage).where(CoachMessage.conversation_id == conversation_id).order_by(CoachMessage.created_at, CoachMessage.id)))
            attempt = db.scalar(select(CoachLlmAttempt).where(CoachLlmAttempt.conversation_id == conversation_id))
            self.assertEqual([message.role for message in messages], ["user", "assistant"])
            self.assertEqual(attempt.message_id, messages[0].id)
            self.assertEqual(attempt.provider_id, provider_id)
            self.assertEqual(attempt.status, "success")
            self.assertTrue(attempt.request_fingerprint)
            self.assertTrue(attempt.output_fingerprint)
            self.assertEqual(db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "coach.turn_completed")), 1)

    def test_schema_repair_safety_rejection_and_next_provider_fallback(self):
        with self.SessionLocal() as db:
            conversation_id = self.conversation_id(db)
            self.seed_provider(db, model="primary", is_default=True)
            self.seed_provider(db, model="secondary", is_default=False)
            calls: list[str] = []

            def response(provider, _prompt):
                calls.append(provider.model)
                if provider.model == "primary" and calls.count("primary") == 1:
                    return "not-json"
                if provider.model == "primary":
                    return json.dumps(provider_output(answer="Here is the API key."))
                return json.dumps(provider_output(answer="Use the cited server guidance."))

            with patch("app.services.coach_provider._request", side_effect=response):
                assistant = self.submit(db, conversation_id)

        self.assertEqual(calls, ["primary", "primary", "secondary"])
        self.assertEqual(assistant["response"].provider_model, "secondary")
        self.assertEqual(assistant["response"].attempt_count, 3)
        with self.SessionLocal() as db:
            attempts = list(db.scalars(select(CoachLlmAttempt).where(CoachLlmAttempt.conversation_id == conversation_id).order_by(CoachLlmAttempt.attempt_number)))
            self.assertEqual([(item.request_phase, item.status, item.failure_class) for item in attempts], [("initial", "failed", "schema"), ("repair", "failed", "safety"), ("initial", "success", None)])
            self.assertTrue(attempts[0].validation_errors)

    def test_provider_timeout_and_no_provider_use_persisted_fallback(self):
        with self.SessionLocal() as db:
            timeout_conversation = self.conversation_id(db)
            self.seed_provider(db)
            with patch("app.services.coach_provider._request", side_effect=httpx.TimeoutException("timeout")):
                timeout_assistant = self.submit(db, timeout_conversation)
            no_provider_conversation = self.conversation_id(db)
            db.query(LlmProviderSetting).delete()
            db.commit()
            no_provider_assistant = self.submit(db, no_provider_conversation)

        self.assertEqual(timeout_assistant["response"].mode, "deterministic_fallback")
        self.assertEqual(timeout_assistant["response"].attempt_count, 1)
        self.assertEqual(no_provider_assistant["response"].mode, "deterministic_fallback")
        self.assertEqual(no_provider_assistant["response"].attempt_count, 0)
        with self.SessionLocal() as db:
            attempt = db.scalar(select(CoachLlmAttempt).where(CoachLlmAttempt.conversation_id == timeout_conversation))
            self.assertEqual((attempt.status, attempt.failure_class), ("failed", "timeout"))
            self.assertEqual(db.scalar(select(func.count()).select_from(CoachMessage).where(CoachMessage.conversation_id == timeout_conversation)), 2)
            self.assertEqual(db.scalar(select(func.count()).select_from(CoachMessage).where(CoachMessage.conversation_id == no_provider_conversation)), 2)

    def test_ownership_rate_and_pending_limits_fail_before_insert(self):
        with self.SessionLocal() as db:
            conversation_id = self.conversation_id(db)
            other = db.get(User, self.other_user_id)
            self.assertIsNone(get_conversation(db, other, conversation_id))
            with self.assertRaises(CoachConflict) as foreign:
                submit_turn(db, other, conversation_id, CoachTurnCreate(message="foreign", context="general"))
            self.assertEqual(foreign.exception.reason, "not_found")
            db.rollback()
            db.add(CoachMessage(user_id=self.user_id, conversation_id=conversation_id, role="user", turn_status="pending", content="pending"))
            db.commit()
            before = db.scalar(select(func.count()).select_from(CoachMessage).where(CoachMessage.conversation_id == conversation_id))
            with self.settings(turn_limit=10, pending_limit=3):
                with self.assertRaises(CoachConflict) as pending:
                    submit_turn(db, db.get(User, self.user_id), conversation_id, CoachTurnCreate(message="second", context="general"))
            self.assertEqual(pending.exception.reason, "turn_pending")
            db.rollback()
            after = db.scalar(select(func.count()).select_from(CoachMessage).where(CoachMessage.conversation_id == conversation_id))
            self.assertEqual(after, before)

        with self.SessionLocal() as db:
            limited_conversation_id = self.conversation_id(db)
        client = self.client_for(self.user_id)
        with self.settings(turn_limit=0):
            response = client.post(f"/api/coach/conversations/{limited_conversation_id}/turns", json={"message": "limited", "context": "general"})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["code"], "rate_limited")

    def test_memory_requires_owned_matching_candidate_and_deletes_explicitly(self):
        candidate = {"communication_style": "brief", "coaching_focus": "recovery"}
        with self.SessionLocal() as db:
            conversation_id = self.conversation_id(db)
            response = CoachAssistantResponse(
                output=ProviderCoachOutput.model_validate(provider_output(memory_candidate=candidate)),
                mode="llm",
                provider="openai",
                provider_model="test",
                attempt_count=1,
                authoritative_safety_status="normal",
            )
            message = CoachMessage(user_id=self.user_id, conversation_id=conversation_id, role="assistant", content="Confirm preferences", response_json=response.model_dump(mode="json"))
            db.add(message)
            db.commit()
            db.refresh(message)
            source_id = message.id
            saved = update_memory(db, db.get(User, self.user_id), MemoryUpdate(**candidate, source_message_id=source_id))
            self.assertEqual(saved, candidate)
            rows = list(db.scalars(select(CoachMemory).where(CoachMemory.user_id == self.user_id)))
            self.assertTrue(all(row.status == "confirmed" and row.source_message_id == source_id for row in rows))
            with self.assertRaises(CoachConflict) as foreign:
                update_memory(db, db.get(User, self.other_user_id), MemoryUpdate(communication_style="brief", source_message_id=source_id))
            self.assertEqual(foreign.exception.reason, "memory_source_not_found")
            db.rollback()
            delete_memory(db, db.get(User, self.user_id))
            self.assertEqual(memory_out(db, db.get(User, self.user_id)), {})

        client = self.client_for(self.other_user_id)
        response = client.put("/api/coach/memory", json={"communication_style": "brief", "source_message_id": source_id})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["details"]["reason"], "memory_source_not_found")

    def test_stale_pending_turn_is_recovered_before_new_turn(self):
        with self.SessionLocal() as db:
            conversation_id = self.conversation_id(db)
            stale = CoachMessage(user_id=self.user_id, conversation_id=conversation_id, role="user", turn_status="pending", content="orphaned", created_at=datetime.now(UTC) - timedelta(minutes=11))
            db.add(stale)
            db.commit()
            stale_id = stale.id
            result = self.submit(db, conversation_id, "new turn")

        self.assertEqual(result["response"].mode, "deterministic_fallback")
        with self.SessionLocal() as db:
            recovered = db.get(CoachMessage, stale_id)
            messages = list(db.scalars(select(CoachMessage).where(CoachMessage.conversation_id == conversation_id).order_by(CoachMessage.created_at, CoachMessage.id)))
            self.assertEqual(recovered.turn_status, "completed")
            self.assertEqual([item.role for item in messages], ["user", "assistant", "user", "assistant"])
            self.assertEqual(db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "coach.turn_recovered")), 1)

    def test_turn_handoff_needs_separate_owner_preview_and_never_applies(self):
        with self.SessionLocal() as db:
            conversation_id = self.conversation_id(db)
            output = provider_output(
                intent="request_preview",
                answer="A server preview can be prepared.",
                citations=[{"source_key": f"workout:{self.workout_id}"}],
                preview_request={"kind": "coach_action", "workout_id": self.workout_id, "action": "skip", "reason": "fatigue", "target_date": None},
            )
            response = CoachAssistantResponse(output=ProviderCoachOutput.model_validate(output), mode="llm", provider="openai", provider_model="test", attempt_count=1, authoritative_safety_status="normal")
            message = CoachMessage(user_id=self.user_id, conversation_id=conversation_id, role="assistant", content=str(output["answer"]), response_json=response.model_dump(mode="json"))
            db.add(message)
            db.commit()
            db.refresh(message)
            message_id = message.id
            self.assertEqual(db.scalar(select(func.count()).select_from(CoachActionPreview)), 0)
            self.assertEqual(db.get(TrainingPlanWorkout, self.workout_id).status, "planned")

        foreign = self.client_for(self.other_user_id).post(f"/api/coach/conversations/{conversation_id}/previews", json={"assistant_message_id": message_id})
        self.assertEqual(foreign.status_code, 404)
        client = self.client_for(self.user_id)
        context = {**SAFE_CONTEXT, "sources": ["athlete_state", f"workout:{self.workout_id}"]}
        with patch.object(coach_routes, "build_coach_context", return_value=context), patch.object(coach_routes, "authoritative_safety", return_value="normal"):
            created = client.post(f"/api/coach/conversations/{conversation_id}/previews", json={"assistant_message_id": message_id})
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(created.json()["kind"], "coach_action")
        with self.SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(CoachActionPreview)), 1)
            self.assertEqual(db.get(TrainingPlanWorkout, self.workout_id).status, "planned")
            self.assertEqual(db.scalar(select(func.count()).select_from(TrainingPlanVersion)), 0)

    def test_export_and_delete_are_scoped_and_dependency_safe(self):
        with self.SessionLocal() as db:
            conversation_id = self.conversation_id(db)
            message = CoachMessage(user_id=self.user_id, conversation_id=conversation_id, role="user", content="private", content_redacted=True)
            db.add(message)
            db.commit()
            exported = export_user_data(db, db.get(User, self.user_id))
            self.assertEqual(exported["version"], "2026-07-14.0028")
            self.assertEqual(exported["coach_conversations"][0]["id"], conversation_id)
            self.assertIsNone(exported["coach_messages"][0]["content"])
            counts = delete_user_data(db, self.user_id)
            db.commit()
            self.assertEqual(counts["coach_conversations"], 1)
            self.assertEqual(counts["coach_messages"], 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(CoachConversation).where(CoachConversation.user_id == self.user_id)), 0)
            self.assertIsNotNone(db.get(User, self.other_user_id))

    def test_migration_runner_applies_stage_four_constraints(self):
        with self.engine.begin() as connection:
            connection.execute(text("DROP TABLE coach_llm_attempts, coach_memory, coach_messages, coach_conversations CASCADE"))
            connection.execute(text("CREATE TABLE IF NOT EXISTS schema_migrations (version VARCHAR(255) PRIMARY KEY, applied_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now())"))
            connection.execute(text("DELETE FROM schema_migrations WHERE version = '20260713_0027_conversational_coach'"))
        run_migrations(self.engine)
        with self.engine.connect() as connection:
            tables = set(connection.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()" )).scalars())
            constraints = set(connection.execute(text("SELECT constraint_name FROM information_schema.table_constraints WHERE table_schema = current_schema() AND table_name IN ('coach_conversations', 'coach_messages', 'coach_memory', 'coach_llm_attempts')" )).scalars())
        self.assertTrue({"coach_conversations", "coach_messages", "coach_memory", "coach_llm_attempts"}.issubset(tables))
        self.assertTrue({"ck_coach_conversations_status", "ck_coach_messages_role", "fk_coach_messages_conversation_owner", "uq_coach_memory_user_key", "ck_coach_llm_attempt_status"}.issubset(constraints))

    def test_database_rejects_cross_user_message_memory_and_attempt_links(self):
        with self.SessionLocal() as db:
            conversation_id = self.conversation_id(db)
            assistant = CoachMessage(user_id=self.user_id, conversation_id=conversation_id, role="assistant", content="owned")
            db.add(assistant)
            db.commit()
            assistant_id = assistant.id

        invalid_rows = [
            CoachMessage(user_id=self.other_user_id, conversation_id=conversation_id, role="user", content="foreign"),
            CoachMemory(user_id=self.other_user_id, memory_key="communication_style", value_json="brief", status="confirmed", source_message_id=assistant_id),
            CoachLlmAttempt(user_id=self.other_user_id, conversation_id=conversation_id, message_id=assistant_id, provider="openai", model="test", attempt_number=1, request_phase="initial", status="success"),
        ]
        for row in invalid_rows:
            with self.subTest(model=type(row).__name__), self.SessionLocal() as db:
                db.add(row)
                with self.assertRaises(IntegrityError):
                    db.commit()


if __name__ == "__main__":
    unittest.main()
