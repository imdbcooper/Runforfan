from __future__ import annotations

import unittest
from datetime import UTC, datetime

DEPENDENCY_SKIP_REASON = None

try:
    from app.models import Activity, LlmProviderSetting, User
    from app.services.csv_imports import activity_payload_from_csv_row, iter_csv_rows
    from app.services.data_management import activity_export, llm_provider_export, model_to_dict
except ModuleNotFoundError as exc:
    if exc.name in {"pydantic", "sqlalchemy"}:
        DEPENDENCY_SKIP_REASON = "Backend dependencies are required for data management tests"
    else:
        raise


@unittest.skipIf(DEPENDENCY_SKIP_REASON is not None, DEPENDENCY_SKIP_REASON or "")
class DataManagementTests(unittest.TestCase):
    def test_csv_row_parses_common_activity_columns(self):
        row = {
            "Activity Date": "2026-06-08 07:30:00",
            "Activity Name": "Morning 5K",
            "Distance (km)": "5,02",
            "Moving Time": "00:25:10",
            "Average Heart Rate": "151",
            "Elevation Gain": "43",
        }

        payload = activity_payload_from_csv_row(row, 2, "activities.csv")

        self.assertEqual(payload["title"], "Morning 5K")
        self.assertEqual(payload["duration_seconds"], 1510)
        self.assertEqual(payload["distance_km"], 5.02)
        self.assertEqual(payload["average_heart_rate_bpm"], 151)
        self.assertEqual(payload["elevation_gain_m"], 43.0)

    def test_csv_reader_supports_semicolon_delimiter(self):
        rows = iter_csv_rows("date;distance_km;duration_seconds\n2026-06-08;10;2700\n".encode("utf-8"))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["distance_km"], "10")

    def test_provider_export_masks_encrypted_key(self):
        provider = LlmProviderSetting(
            id=1,
            user_id=2,
            provider="openai",
            display_name="Provider",
            model="gpt-4o-mini",
            encrypted_api_key="secret-ciphertext",
            is_default=True,
            is_active=True,
            created_at=datetime(2026, 6, 8, tzinfo=UTC),
        )

        exported = llm_provider_export(provider)

        self.assertTrue(exported["has_api_key"])
        self.assertNotIn("encrypted_api_key", exported)

    def test_model_to_dict_serializes_datetime(self):
        user = User(id=1, display_name="Runner", is_demo=True, created_at=datetime(2026, 6, 8, tzinfo=UTC), updated_at=datetime(2026, 6, 8, tzinfo=UTC))

        exported = model_to_dict(user)

        self.assertEqual(exported["created_at"], "2026-06-08T00:00:00+00:00")

    def test_activity_export_includes_nested_blocks(self):
        activity = Activity(id=5, user_id=1, title="Run", duration_seconds=600, created_at=datetime(2026, 6, 8, tzinfo=UTC), updated_at=datetime(2026, 6, 8, tzinfo=UTC))
        activity.segments = []
        activity.split_blocks = []
        activity.workout_blocks = []

        exported = activity_export(activity)

        self.assertEqual(exported["id"], 5)
        self.assertEqual(exported["segments"], [])


if __name__ == "__main__":
    unittest.main()
