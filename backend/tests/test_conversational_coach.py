from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from app.models import LlmProviderSetting, User
from app.schemas.coach import CoachAssistantResponse, CoachTurnCreate, ProviderCoachOutput
from app.services.coach_provider import active_providers
from app.services.coach_tools import authoritative_safety
from app.services.conversational_coach import _fallback, _prompt, _valid_output, submit_turn


ROOT = Path(__file__).resolve().parents[1]


class FakeScalars:
    def __init__(self, rows): self.rows = rows
    def __iter__(self): return iter(self.rows)


class FakeDb:
    def __init__(self, rows=()): self.rows = rows
    def scalars(self, _query): return FakeScalars(self.rows)


def output(**overrides):
    data = {"intent": "inform", "answer": "Use the deterministic guidance.", "citations": [{"source_key": "athlete_state"}], "safety_status": "normal"}
    data.update(overrides)
    return ProviderCoachOutput.model_validate(data)


class ConversationalCoachTests(unittest.TestCase):
    def test_strict_schema_trim_wrapper_and_invalid_union(self):
        self.assertEqual(CoachTurnCreate(message="  hello  ", context="general").message, "hello")
        with self.assertRaises(ValidationError): CoachTurnCreate(message="   ", context="general")
        with self.assertRaises(ValidationError): ProviderCoachOutput.model_validate({"intent": "inform", "answer": "ok", "citations": [], "safety_status": "normal", "apply": True})
        with self.assertRaises(ValidationError): ProviderCoachOutput.model_validate({"intent": "request_preview", "answer": "ok", "citations": [], "safety_status": "normal", "preview_request": {"kind": "coach_action", "workout_id": 1, "action": "skip", "reason": "fatigue", "target_date": "2026-07-14"}})
        with self.assertRaises(ValidationError): ProviderCoachOutput.model_validate({"intent": "inform", "answer": "ok", "citations": [{"source_key": "athlete_state"}], "safety_status": "normal", "memory_candidate": {"communication_style": None}})
        wrapped = CoachAssistantResponse(output=output(), mode="deterministic_fallback", attempt_count=0, authoritative_safety_status="caution")
        self.assertEqual(wrapped.mode, "deterministic_fallback")

    def test_fixture_adversarial_cases_have_safe_classification_or_rejectable_output(self):
        rows = json.loads((ROOT / "tests/fixtures/coach_evals/v1.json").read_text())
        context = {"today_readiness": {"recommendation": {"status": "proceed"}}, "athlete_state": {"status": "ok"}, "sources": ["athlete_state"]}
        rank = {"normal": 0, "caution": 1, "medical_boundary": 2}
        for row in rows:
            if "message" in row:
                self.assertGreaterEqual(rank[authoritative_safety(context, row["message"])], rank[row["expected_safety"]], row["id"])
            if isinstance(row.get("provider_output"), dict):
                try:
                    candidate = ProviderCoachOutput.model_validate(row["provider_output"])
                except ValidationError:
                    self.assertEqual(row["expected"], "reject", row["id"])
                else:
                    self.assertFalse(_valid_output(None, None, candidate, context, "caution"), row["id"])
            elif "provider_output" in row:
                with self.assertRaises((ValidationError, ValueError), msg=row["id"]):
                    ProviderCoachOutput.model_validate_json(row["provider_output"])

    def test_output_filter_rejects_citation_downgrade_quantity_and_disclosure(self):
        context = {"sources": ["athlete_state"], "today_readiness": {"recommendation": {"status": "proceed"}}, "athlete_state": {"status": "ok"}, "upcoming_workouts": []}
        self.assertFalse(_valid_output(None, None, output(citations=[{"source_key": "invented"}]), context, "normal"))
        self.assertFalse(_valid_output(None, None, output(answer="Run 30 km today."), context, "normal"))
        self.assertFalse(_valid_output(None, None, output(answer="Here is the API key."), context, "normal"))
        self.assertFalse(_valid_output(None, None, output(answer="I cannot diagnose, but you definitely have an injury and should train through pain."), context, "normal"))
        self.assertFalse(_valid_output(None, None, output(safety_status="normal"), context, "caution"))

    def test_prompt_serializes_context_as_an_untrusted_envelope(self):
        prompt = _prompt({"sources": ["athlete_state"], "athlete_state": {"status": "ok"}}, CoachTurnCreate(message="Объясни решение", context="general"))

        self.assertIn("<UNTRUSTED_USER_ENVELOPE>", prompt["user"])
        self.assertIn('"message":"Объясни решение"', prompt["user"])

    def test_provider_ordering_is_user_scoped_by_query_contract(self):
        providers = [LlmProviderSetting(id=2, user_id=1, provider="openai", display_name="new", model="b", is_default=False, is_active=True), LlmProviderSetting(id=1, user_id=1, provider="openai", display_name="default", model="a", is_default=True, is_active=True)]
        # Ordering happens in SQL; FakeDb preserves already ordered query results.
        self.assertEqual([item.id for item in active_providers(FakeDb([providers[1], providers[0]]), User(id=1, display_name="Runner"))], [1, 2])
        source = (ROOT / "app/services/coach_provider.py").read_text()
        self.assertIn("LlmProviderSetting.user_id == user.id", source)

    def test_migration_contract_and_no_follow_on_migration(self):
        source = (ROOT / "app/db/migrations/runner.py").read_text()
        self.assertIn("response_json JSONB", source)
        self.assertIn("surface VARCHAR(64) NOT NULL", source)
        self.assertIn("last_message_at TIMESTAMP", source)
        self.assertIn("value_json JSONB NOT NULL", source)
        self.assertIn("status VARCHAR(32) NOT NULL DEFAULT 'confirmed'", source)
        self.assertIn("provider_id INTEGER", source)
        self.assertIn("attempt_number INTEGER NOT NULL", source)
        self.assertNotIn("20260713_0028", source)

    def test_no_mutation_or_preview_creation_imports_in_restricted_modules(self):
        for filename in ("conversational_coach.py", "coach_tools.py", "coach_provider.py"):
            tree = ast.parse((ROOT / "app/services" / filename).read_text())
            names = {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) for alias in node.names}
            self.assertFalse(any(name.startswith("apply_") or (name.startswith("create_") and name.endswith("_preview")) for name in names), filename)

    def test_no_provider_uses_deterministic_fallback(self):
        fallback = _fallback("caution")
        self.assertEqual(fallback.safety_status, "caution")
        self.assertIn("Не удалось безопасно", fallback.answer)

    def test_medical_boundary_does_not_call_provider(self):
        class TurnDb:
            def __init__(self):
                self.scalars_calls = 0
                self.messages = []
            def scalar(self, query):
                description = str(query)
                if "count(coach_messages.id)" in description:
                    return 0
                if "coach_conversations" in description:
                    return type("Conversation", (), {"id": "conversation", "user_id": 1, "status": "active", "last_message_at": None})()
                return User(id=1, display_name="Runner")
            def scalars(self, _query):
                return FakeScalars([])
            def add(self, value):
                self.messages.append(value)
                if getattr(value, "role", None) == "user": value.id = 1
            def commit(self): pass
            def refresh(self, value):
                if getattr(value, "role", None) == "assistant": value.id = 2
            def rollback(self): pass
            def get(self, _model, _identifier): return None

        context = {"sources": ["athlete_state", "today_readiness"], "today_readiness": {"recommendation": {"status": "proceed"}}, "athlete_state": {"status": "ok"}}
        with patch("app.services.conversational_coach.get_settings", return_value=type("Settings", (), {"coach_turn_window_minutes": 10, "coach_turn_limit": 10, "coach_pending_turn_limit": 3})()), patch("app.services.conversational_coach.build_coach_context", return_value=context), patch("app.services.conversational_coach.request_coach_output") as provider:
            result = submit_turn(TurnDb(), User(id=1, display_name="Runner"), "conversation", CoachTurnCreate(message="У меня боль в колене", context="general"))

        provider.assert_not_called()
        self.assertEqual(result["response"].authoritative_safety_status, "medical_boundary")


if __name__ == "__main__":
    unittest.main()
