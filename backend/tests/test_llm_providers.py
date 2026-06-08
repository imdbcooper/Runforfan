from __future__ import annotations

import unittest
from datetime import UTC, datetime
from unittest.mock import patch

DEPENDENCY_SKIP_REASON = None

try:
    from app.api.routes.settings import delete_llm_provider, provider_out, test_provider_connection, update_llm_provider
    from app.models import LlmProviderSetting, User
    from app.schemas.common import LlmProviderUpdate
    from app.services.llm_providers import provider_endpoint_url, provider_supports_vision
except ModuleNotFoundError as exc:
    if exc.name in {"cryptography", "fastapi", "httpx", "pydantic", "sqlalchemy"}:
        DEPENDENCY_SKIP_REASON = "Backend dependencies are required for LLM provider tests"
    else:
        raise


class FakeDb:
    def __init__(self, provider: LlmProviderSetting, providers: list[LlmProviderSetting] | None = None):
        self.provider = provider
        self.providers = providers or [provider]
        self.committed = False

    def scalar(self, query):
        return self.provider

    def scalars(self, query):
        return self.providers

    def execute(self, query):
        return None

    def commit(self):
        self.committed = True

    def refresh(self, item):
        return None


class FakeResponse:
    def raise_for_status(self):
        return None


def make_provider(**kwargs) -> LlmProviderSetting:
    values = {
        "id": 10,
        "user_id": 1,
        "provider": "openai",
        "display_name": "Smoke OpenAI",
        "base_url": "https://example.test/v1/chat/completions",
        "model": "gpt-4o-mini",
        "encrypted_api_key": "encrypted-secret",
        "is_default": True,
        "is_active": True,
        "created_at": datetime(2026, 6, 8, tzinfo=UTC),
    }
    values.update(kwargs)
    return LlmProviderSetting(**values)


@unittest.skipIf(DEPENDENCY_SKIP_REASON is not None, DEPENDENCY_SKIP_REASON or "")
class LlmProviderTests(unittest.TestCase):
    def test_provider_out_masks_key_and_reports_vision_support(self):
        provider = make_provider()

        result = provider_out(provider).model_dump()

        self.assertTrue(result["has_api_key"])
        self.assertTrue(result["supports_vision"])
        self.assertNotIn("api_key", result)
        self.assertNotIn("encrypted_api_key", result)

    def test_provider_supports_vision_for_anthropic_claude_3(self):
        provider = make_provider(provider="anthropic", model="claude-3-5-sonnet-latest")

        self.assertTrue(provider_supports_vision(provider))

    def test_update_provider_keeps_or_clears_secret_intentionally(self):
        provider = make_provider(encrypted_api_key="existing")
        db = FakeDb(provider)

        update_llm_provider(provider.id, LlmProviderUpdate(display_name="Updated"), User(id=1, display_name="Runner"), db)

        self.assertEqual(provider.display_name, "Updated")
        self.assertEqual(provider.encrypted_api_key, "existing")
        self.assertTrue(db.committed)

        update_llm_provider(provider.id, LlmProviderUpdate(api_key=None), User(id=1, display_name="Runner"), db)

        self.assertIsNone(provider.encrypted_api_key)

    def test_update_provider_ignores_null_display_name(self):
        provider = make_provider(display_name="Original")
        db = FakeDb(provider)

        update_llm_provider(provider.id, LlmProviderUpdate(display_name=None), User(id=1, display_name="Runner"), db)

        self.assertEqual(provider.display_name, "Original")

    def test_default_provider_is_preserved_when_default_is_deleted(self):
        old_default = make_provider(id=1, display_name="Default", is_default=True)
        fallback = make_provider(id=2, display_name="Fallback", is_default=False)
        db = FakeDb(old_default, [old_default, fallback])

        delete_llm_provider(old_default.id, User(id=1, display_name="Runner"), db)

        self.assertFalse(old_default.is_active)
        self.assertFalse(old_default.is_default)
        self.assertTrue(fallback.is_default)

    def test_connection_test_uses_safe_prompt_without_returning_raw_response(self):
        provider = make_provider(base_url=None, encrypted_api_key=None)
        captured = {}

        def fake_post(*args, **kwargs):
            captured.update(kwargs)
            return FakeResponse()

        with patch("app.api.routes.settings.httpx.post", side_effect=fake_post):
            result = test_provider_connection(provider)

        self.assertTrue(result.ok)
        self.assertEqual(captured["json"]["messages"][0]["role"], "user")
        self.assertIn("Reply with exactly: ok", captured["json"]["messages"][0]["content"])
        self.assertEqual(result.message, "Safe prompt completed successfully.")

    def test_custom_provider_endpoint_rejects_private_http_urls(self):
        provider = make_provider(base_url="http://127.0.0.1:8080/api/not-a-llm")

        with self.assertRaises(ValueError):
            provider_endpoint_url(provider, type("Settings", (), {"allow_private_llm_base_urls": False})())


if __name__ == "__main__":
    unittest.main()
