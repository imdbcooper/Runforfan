from __future__ import annotations

import unittest
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

DEPENDENCY_SKIP_REASON = None

try:
    from fastapi import HTTPException

    from app.api.routes.settings import delete_llm_provider, normalized_base_url, provider_out, test_provider_connection, update_llm_provider
    from app.models import LlmProviderSetting, User
    from app.schemas.common import LlmProviderUpdate
    from app.services.llm_providers import pinned_provider_request, provider_endpoint_url, provider_supports_vision
except ModuleNotFoundError as exc:
    if exc.name in {"cryptography", "fastapi", "httpx", "pydantic", "sqlalchemy"}:
        DEPENDENCY_SKIP_REASON = "Backend dependencies are required for LLM provider tests"
    else:
        raise


class FakeDb:
    def __init__(self, provider: LlmProviderSetting, providers: list[LlmProviderSetting] | None = None):
        self.provider = provider
        self.providers = providers or [provider]
        self.added = []
        self.committed = False

    def scalar(self, query):
        return self.provider

    def scalars(self, query):
        return self.providers

    def execute(self, query):
        return None

    def add(self, item):
        self.added.append(item)

    def flush(self):
        return None

    def commit(self):
        self.committed = True

    def refresh(self, item):
        return None


class FakeResponse:
    def __init__(self, payload=None, json_error: Exception | None = None):
        self.payload = payload or {"choices": [{"message": {"content": "ok"}}]}
        self.json_error = json_error

    def raise_for_status(self):
        return None

    def json(self):
        if self.json_error:
            raise self.json_error
        return self.payload


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

    def test_openai_provider_endpoint_normalizes_base_urls(self):
        settings = type("Settings", (), {"allow_private_llm_base_urls": True})()

        self.assertEqual(
            provider_endpoint_url(make_provider(base_url="https://byesu.com"), settings),
            "https://byesu.com/v1/chat/completions",
        )
        self.assertEqual(
            provider_endpoint_url(make_provider(base_url="https://byesu.com/v1"), settings),
            "https://byesu.com/v1/chat/completions",
        )
        self.assertEqual(
            provider_endpoint_url(make_provider(base_url="https://byesu.com/v1/chat/completions"), settings),
            "https://byesu.com/v1/chat/completions",
        )
        self.assertEqual(
            provider_endpoint_url(make_provider(base_url="https://gateway.example/openai"), settings),
            "https://gateway.example/openai/chat/completions",
        )

    def test_connection_test_rejects_non_json_openai_response(self):
        provider = make_provider(base_url=None, encrypted_api_key=None)

        def fake_post(*args, **kwargs):
            return FakeResponse(json_error=ValueError("html"))

        with patch("app.api.routes.settings.httpx.post", side_effect=fake_post):
            result = test_provider_connection(provider)

        self.assertFalse(result.ok)
        self.assertIn("non-JSON", result.message)

    def test_connection_test_rejects_non_chat_completion_json(self):
        provider = make_provider(base_url=None, encrypted_api_key=None)

        def fake_post(*args, **kwargs):
            return FakeResponse({"ok": True})

        with patch("app.api.routes.settings.httpx.post", side_effect=fake_post):
            result = test_provider_connection(provider)

        self.assertFalse(result.ok)
        self.assertIn("chat completions", result.message)

    def test_custom_provider_endpoint_rejects_private_http_urls(self):
        provider = make_provider(base_url="http://127.0.0.1:8080/api/not-a-llm")

        with self.assertRaises(ValueError):
            provider_endpoint_url(provider, type("Settings", (), {"allow_private_llm_base_urls": False})())

    def test_pinned_request_revalidates_dns_and_rejects_private_answers(self):
        private_record = [(None, None, None, None, ("127.0.0.1", 443))]

        with patch("app.services.llm_providers.socket.getaddrinfo", return_value=private_record), patch("app.services.llm_providers.httpx.Client") as client:
            with self.assertRaises(ValueError):
                pinned_provider_request(
                    "https://provider.example/v1/chat/completions",
                    allow_private=False,
                    json={"safe": True},
                    headers={"Authorization": "Bearer secret"},
                    timeout=20,
                )

        client.assert_not_called()

    def test_pinned_request_connects_to_vetted_ip_with_original_sni_and_host(self):
        public_record = [(None, None, None, None, ("8.8.8.8", 443))]
        response = FakeResponse()
        client = MagicMock()
        client.__enter__.return_value = client
        client.build_request.return_value = object()
        client.send.return_value = response

        with patch("app.services.llm_providers.socket.getaddrinfo", return_value=public_record), patch("app.services.llm_providers.httpx.Client", return_value=client):
            result = pinned_provider_request(
                "https://provider.example/v1/chat/completions",
                allow_private=False,
                json={"safe": True},
                headers={"Authorization": "Bearer secret"},
                timeout=20,
            )

        self.assertIs(result, response)
        request_call = client.build_request.call_args
        self.assertEqual(str(request_call.args[1]), "https://8.8.8.8/v1/chat/completions")
        self.assertEqual(request_call.kwargs["headers"]["Host"], "provider.example")
        self.assertEqual(request_call.kwargs["extensions"], {"sni_hostname": "provider.example"})
        client.send.assert_called_once_with(client.build_request.return_value)

    def test_provider_base_url_is_rejected_before_storage(self):
        with self.assertRaises(HTTPException) as ctx:
            normalized_base_url("http://127.0.0.1:8080/api/not-a-llm")

        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
