import unittest
from datetime import UTC, date, datetime, time
from types import SimpleNamespace
from unittest.mock import patch

try:
    from fastapi import HTTPException
    from app.models import AthleteProfile, CoachDelivery, CoachDeliveryPreference, User
    from app.schemas.common import CoachDeliveryPreferenceUpdate
    from app.services import coach_delivery
    from app.services import telegram_bot
except ModuleNotFoundError as exc:
    if exc.name in {"fastapi", "sqlalchemy", "pydantic"}:
        raise unittest.SkipTest("Backend dependencies are required for coach delivery tests") from exc
    raise


class CoachDeliveryTests(unittest.TestCase):
    def test_preference_update_forbids_destination_fields(self):
        with self.assertRaises(Exception):
            CoachDeliveryPreferenceUpdate.model_validate({"telegram_chat_id": 123})

    def test_preference_response_hides_chat_id(self):
        user = User(id=1, display_name="Runner", is_demo=False)
        user.athlete_profile = AthleteProfile(user_id=1, timezone="Europe/Moscow")
        preference = CoachDeliveryPreference(user_id=1, telegram_chat_id=123, telegram_chat_verified_at=datetime.now(UTC), telegram_enabled=False, daily_brief_local_time=time(8))
        with patch.object(coach_delivery, "get_settings", return_value=SimpleNamespace(coach_delivery_enabled=False)), patch.object(coach_delivery, "telegram_bot_start_url", return_value="https://t.me/bot"):
            response = coach_delivery.preference_response(user, preference)
        self.assertTrue(response["linked"])
        self.assertNotIn("telegram_chat_id", response)
        self.assertIsNone(response["bot_url"])

    def test_preference_response_tolerates_live_bot_api_failure(self):
        user = User(id=1, display_name="Runner", is_demo=False)
        user.athlete_profile = AthleteProfile(user_id=1, timezone="Europe/Moscow")
        with patch.object(coach_delivery, "get_settings", return_value=SimpleNamespace(coach_delivery_enabled=True)), patch.object(coach_delivery, "telegram_bot_start_url", side_effect=HTTPException(status_code=502)):
            response = coach_delivery.preference_response(user, None)
        self.assertIsNone(response["bot_url"])

    def test_unknown_action_does_not_select_a_delivery_template(self):
        self.assertIsNone(coach_delivery._template_key("unrecognized"))

    def test_enabling_requires_global_kill_switch(self):
        db = SimpleNamespace(scalar=lambda *_args, **_kwargs: CoachDeliveryPreference(user_id=1, telegram_chat_id=123, telegram_chat_verified_at=datetime.now(UTC)))
        user = User(id=1, display_name="Runner", is_demo=False)
        with patch.object(coach_delivery, "get_settings", return_value=SimpleNamespace(coach_delivery_enabled=False)):
            with self.assertRaises(HTTPException) as caught:
                coach_delivery.update_preference(db, user, telegram_enabled=True, daily_brief_local_time=None)
        self.assertEqual(caught.exception.status_code, 403)

    def test_closed_rollout_rejects_schedule_only_update(self):
        db = SimpleNamespace()
        user = User(id=1, display_name="Runner", is_demo=False)
        with patch.object(coach_delivery, "get_settings", return_value=SimpleNamespace(coach_delivery_enabled=False)):
            with self.assertRaises(HTTPException) as caught:
                coach_delivery.update_preference(db, user, telegram_enabled=None, daily_brief_local_time=time(9))
        self.assertEqual(caught.exception.status_code, 403)

    def test_safe_message_does_not_use_workout_notes(self):
        delivery = CoachDelivery(id="delivery", user_id=1, local_date=date(2026, 7, 14), timezone="Europe/Moscow", rule_version=coach_delivery.DAILY_BRIEF_RULE_VERSION, template_key="rest", content_fingerprint="fingerprint", scheduled_for=datetime.now(UTC))
        self.assertNotIn("secret note", coach_delivery._message(delivery))
        self.assertIn("не медицинская", coach_delivery._message(delivery))

    def test_telegram_delivery_classifies_forbidden_without_body(self):
        response = SimpleNamespace(status_code=403, is_success=False, json=lambda: {"ok": False, "description": "secret"})
        with patch.object(telegram_bot, "_bot_api_url", return_value="https://example.invalid"), patch.object(telegram_bot, "get_settings", return_value=SimpleNamespace(telegram_bot_proxy_url=None, frontend_url="https://run.slavx.ru/app/")), patch.object(telegram_bot.httpx, "post", return_value=response):
            with self.assertRaises(telegram_bot.TelegramDeliveryError) as caught:
                telegram_bot.TelegramDeliveryClient().send(1, "brief")
        self.assertEqual(caught.exception.failure_class, "forbidden")

    def test_telegram_delivery_classifies_missing_token_as_configuration(self):
        settings = SimpleNamespace(telegram_bot_token=None, telegram_bot_proxy_url=None, frontend_url="https://run.slavx.ru/app/")
        with patch.object(telegram_bot, "get_settings", return_value=settings):
            with self.assertRaises(telegram_bot.TelegramDeliveryError) as caught:
                telegram_bot.TelegramDeliveryClient().send(1, "brief")
        self.assertEqual(caught.exception.failure_class, "configuration")

    def test_group_start_does_not_create_user_or_destination(self):
        db = SimpleNamespace()
        update = {"message": {"from": {"id": 3}, "chat": {"id": -10, "type": "group"}, "text": "/start"}}
        with patch.object(telegram_bot, "get_or_create_telegram_user_from_profile") as create_user:
            telegram_bot.handle_telegram_webhook_update(db, update)
        create_user.assert_not_called()

    def test_private_start_does_not_collect_destination_during_closed_rollout(self):
        db = SimpleNamespace()
        user = User(id=1, display_name="Runner", telegram_id=3, is_demo=False)
        update = {"message": {"from": {"id": 3}, "chat": {"id": 3, "type": "private"}, "text": "/start"}}
        settings = SimpleNamespace(coach_delivery_enabled=False)
        with patch.object(telegram_bot, "get_settings", return_value=settings), patch.object(telegram_bot, "get_or_create_telegram_user_from_profile", return_value=user), patch.object(telegram_bot, "create_telegram_login_code", return_value="code"), patch.object(telegram_bot, "build_frontend_login_url", return_value="https://run.slavx.ru/app/?telegram_login_code=code"), patch.object(telegram_bot, "_send_message") as send, patch("app.services.coach_delivery.verify_private_telegram_chat") as verify:
            telegram_bot.handle_telegram_webhook_update(db, update)
        verify.assert_not_called()
        send.assert_called_once()


if __name__ == "__main__":
    unittest.main()
