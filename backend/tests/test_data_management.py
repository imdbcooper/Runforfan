from __future__ import annotations

import unittest
from datetime import UTC, datetime

DEPENDENCY_SKIP_REASON = None

try:
    from app.models import Activity, CoachLlmAttempt, CoachMessage, DailyTrainingLoad, DerivedActivityMetric, LlmProviderSetting, TrainingPlan, TrainingPlanWorkout, TrainingPlanWorkoutBlock, User
    from app.db.migrations.runner import MIGRATIONS
    from app.services.csv_imports import activity_payload_from_csv_row, iter_csv_rows
    from app.services.data_management import DELETE_MODELS, activities_csv_content, activity_export, coach_message_export, csv_safe_value, llm_provider_export, model_to_dict, training_plan_export
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
        activity.derived_metrics = [DerivedActivityMetric(activity_id=5, metric_key="training_load_proxy", metric_value=10.0, unit="au", method="duration_proxy", source_reference="test", input_hash="hash", computed_at=datetime(2026, 6, 8, tzinfo=UTC))]

        exported = activity_export(activity)

        self.assertEqual(exported["id"], 5)
        self.assertEqual(exported["segments"], [])
        self.assertEqual(exported["derived_metrics"][0]["metric_key"], "training_load_proxy")

    def test_activities_csv_export_includes_core_activity_fields(self):
        activity = Activity(
            id=5,
            user_id=1,
            activity_type="run",
            title="Morning, run",
            started_at=datetime(2026, 6, 8, 7, 30, tzinfo=UTC),
            distance_km=5.0,
            duration_seconds=1500,
            average_pace_seconds_per_km=300,
            average_heart_rate_bpm=145,
        )

        exported = activities_csv_content([activity])

        self.assertIn("id,activity_type,title,started_at,distance_km", exported)
        self.assertIn('5,run,"Morning, run",2026-06-08T07:30:00+00:00,5.0', exported)

    def test_activities_csv_export_escapes_spreadsheet_formulas(self):
        activity = Activity(id=5, user_id=1, title="=cmd", source_note=" @risk", duration_seconds=60)

        exported = activities_csv_content([activity])

        self.assertIn("'=cmd", exported)
        self.assertIn("' @risk", exported)
        self.assertEqual(csv_safe_value("normal"), "normal")

    def test_training_plan_export_includes_workout_blocks(self):
        workout = TrainingPlanWorkout(id=3, plan_id=9, week_index=1, day_index=1, workout_type="easy", title="Easy", status="planned")
        workout.blocks = [TrainingPlanWorkoutBlock(id=4, workout_id=3, block_index=1, block_type="work", repeat_count=1, target_distance_km=5.0)]
        workout.feedback = None
        plan = TrainingPlan(id=9, user_id=1, title="Plan", goal_type="10k", available_days_per_week=3, status="draft", workouts=[workout])

        exported = training_plan_export(plan)

        self.assertEqual(exported["workouts"][0]["blocks"][0]["block_type"], "work")

    def test_daily_training_load_model_to_dict_serializes_date(self):
        load = DailyTrainingLoad(user_id=1, date=datetime(2026, 6, 8, tzinfo=UTC).date(), load_value=42.0, method="manual", duration_minutes=60.0, activity_ids=[5], ctl=1.0, atl=2.0, tsb=-1.0, computed_at=datetime(2026, 6, 8, tzinfo=UTC))

        exported = model_to_dict(load)

        self.assertEqual(exported["date"], "2026-06-08")
        self.assertEqual(exported["activity_ids"], [5])

    def test_coach_message_export_redacts_content(self):
        message = CoachMessage(id=1, user_id=2, conversation_id="conversation_opaque_id", role="assistant", content="sensitive training detail", content_redacted=True, response_json={"output": {"answer": "sensitive training detail"}}, created_at=datetime(2026, 7, 13, tzinfo=UTC))

        exported = coach_message_export(message)

        self.assertTrue(exported["content_redacted"])
        self.assertIsNone(exported["content"])
        self.assertIsNone(exported["response_json"])

    def test_coach_llm_attempt_model_has_no_raw_payload_columns(self):
        column_names = set(CoachLlmAttempt.__table__.columns.keys())

        self.assertTrue({"provider", "model", "status", "failure_class", "started_at", "completed_at", "duration_ms", "request_fingerprint", "output_fingerprint", "validation_errors"}.issubset(column_names))
        self.assertFalse({"raw_request", "raw_response", "request_payload", "response_payload"} & column_names)

    def test_coach_migration_creates_required_tables_and_integrity_checks(self):
        statements = dict(MIGRATIONS)["20260713_0027_conversational_coach"]
        migration_sql = "\n".join(statements).lower()

        for table_name in ("coach_conversations", "coach_messages", "coach_memory", "coach_llm_attempts"):
            self.assertIn(f"create table if not exists {table_name}", migration_sql)
        self.assertIn("on delete cascade", migration_sql)
        self.assertIn("foreign key (source_message_id, user_id)", migration_sql)
        self.assertIn("foreign key (message_id, user_id, conversation_id)", migration_sql)
        self.assertIn("check (role", migration_sql)
        self.assertIn("check (status", migration_sql)
        self.assertIn("foreign key (conversation_id, user_id)", migration_sql)

    def test_coach_delete_order_removes_dependents_before_conversations(self):
        names = [name for name, _ in DELETE_MODELS]

        self.assertLess(names.index("coach_llm_attempts"), names.index("coach_messages"))
        self.assertLess(names.index("coach_memory"), names.index("coach_messages"))
        self.assertLess(names.index("coach_messages"), names.index("coach_conversations"))


if __name__ == "__main__":
    unittest.main()
