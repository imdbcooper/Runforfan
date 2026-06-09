import hashlib
import hmac
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

try:
    from fastapi import HTTPException

    from app.api.routes import auth as auth_routes
    from app.services import auth as auth_service
except ModuleNotFoundError as exc:
    if exc.name in {"fastapi", "sqlalchemy"}:
        raise unittest.SkipTest("Backend dependencies are required for auth tests") from exc
    raise


def signed_telegram_payload(bot_token: str, auth_date: int) -> dict[str, str]:
    payload = {
        "id": "12345",
        "first_name": "Runner",
        "username": "runner",
        "auth_date": str(auth_date),
    }
    data_check = "\n".join(f"{key}={value}" for key, value in sorted(payload.items()))
    secret = hashlib.sha256(bot_token.encode("utf-8")).digest()
    payload["hash"] = hmac.new(secret, data_check.encode("utf-8"), hashlib.sha256).hexdigest()
    return payload


class AuthTests(unittest.TestCase):
    def test_dev_login_is_disabled_outside_development(self):
        with patch.object(auth_routes, "get_settings", return_value=SimpleNamespace(app_env="production")):
            with self.assertRaises(HTTPException) as caught:
                auth_routes.dev_login(SimpleNamespace())

        self.assertEqual(caught.exception.status_code, 403)

    def test_telegram_login_rejects_stale_payloads(self):
        bot_token = "test-token"
        now = datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc)
        payload = signed_telegram_payload(bot_token, int((now - timedelta(days=2)).timestamp()))

        with patch.object(auth_service, "get_settings", return_value=SimpleNamespace(telegram_bot_token=bot_token)):
            self.assertFalse(auth_service.validate_telegram_login(payload, now=now))

    def test_telegram_login_accepts_fresh_signed_payloads(self):
        bot_token = "test-token"
        now = datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc)
        payload = signed_telegram_payload(bot_token, int((now - timedelta(minutes=5)).timestamp()))

        with patch.object(auth_service, "get_settings", return_value=SimpleNamespace(telegram_bot_token=bot_token)):
            self.assertTrue(auth_service.validate_telegram_login(payload, now=now))

    def test_telegram_display_name_uses_full_name(self):
        self.assertEqual(
            auth_service.telegram_display_name("  Ivan ", " Petrov  ", "runner"),
            "Ivan Petrov",
        )

    def test_telegram_display_name_falls_back_to_username(self):
        self.assertEqual(auth_service.telegram_display_name(None, None, " runner "), "runner")

    def test_telegram_display_name_keeps_existing_fallback(self):
        self.assertEqual(auth_service.telegram_display_name(None, None, None, "Old Runner"), "Old Runner")

    def test_telegram_bot_login_url_preserves_frontend_query(self):
        from app.services import telegram_bot

        settings = SimpleNamespace(frontend_url="https://run.slavx.ru/app/?lang=ru")
        with patch.object(telegram_bot, "get_settings", return_value=settings):
            self.assertEqual(
                telegram_bot.build_frontend_login_url("one-time-code"),
                "https://run.slavx.ru/app/?lang=ru&telegram_login_code=one-time-code",
            )

    def test_telegram_bot_start_url_is_disabled_without_token(self):
        from app.services import telegram_bot

        settings = SimpleNamespace(telegram_bot_token=None)
        with patch.object(telegram_bot, "get_settings", return_value=settings):
            self.assertIsNone(telegram_bot.telegram_bot_start_url())


if __name__ == "__main__":
    unittest.main()
