from __future__ import annotations

import unittest
from datetime import UTC, datetime

DEPENDENCY_SKIP_REASON = None

try:
    from app.models import Activity, ActivitySegment, ActivityWorkoutBlock, User
    from app.services.activity_metrics import compute_derived_activity_metrics, sync_derived_activity_metrics
except ModuleNotFoundError as exc:
    if exc.name in {"pydantic", "sqlalchemy"}:
        DEPENDENCY_SKIP_REASON = "Backend dependencies are required for activity metrics tests"
    else:
        raise


class FakeDb:
    def __init__(self):
        self.added = []
        self.flushed = False
        self.executed = []

    def add(self, item):
        self.added.append(item)

    def flush(self):
        self.flushed = True

    def execute(self, query):
        self.executed.append(query)


@unittest.skipIf(DEPENDENCY_SKIP_REASON is not None, DEPENDENCY_SKIP_REASON or "")
class ActivityMetricsTests(unittest.TestCase):
    def test_compute_metrics_derives_pace_speed_load_and_structure(self):
        activity = Activity(
            id=5,
            user_id=1,
            title="Intervals",
            started_at=datetime(2026, 6, 8, 7, tzinfo=UTC),
            distance_km=10.0,
            duration_seconds=3000,
            average_heart_rate_bpm=150,
            elevation_gain_m=80,
            elevation_loss_m=50,
        )
        activity.segments = [
            ActivitySegment(id=1, activity_id=5, segment_index=1, distance_km=1.0, duration_seconds=290, pace_seconds_per_km=290),
            ActivitySegment(id=2, activity_id=5, segment_index=2, distance_km=1.0, duration_seconds=310, pace_seconds_per_km=310),
        ]
        activity.workout_blocks = [
            ActivityWorkoutBlock(id=1, activity_id=5, block_index=1, block_type="warmup", title="Warmup", distance_km=2.0, duration_seconds=700),
            ActivityWorkoutBlock(id=2, activity_id=5, block_index=2, block_type="work", title="Work", distance_km=1.0, duration_seconds=250),
        ]

        metrics = {metric["metric_key"]: metric for metric in compute_derived_activity_metrics(activity)}

        self.assertEqual(metrics["average_pace_seconds_per_km"]["metric_value"], 300)
        self.assertEqual(metrics["average_speed_kmh"]["metric_value"], 12.0)
        self.assertEqual(metrics["training_load_proxy"]["method"], "hr_duration_proxy")
        self.assertEqual(metrics["work_block_count"]["metric_value"], 1.0)
        self.assertEqual(metrics["vertical_balance_m"]["metric_value"], 30.0)
        self.assertIn("input_hash", metrics["duration_minutes"])

    def test_sync_replaces_existing_rows_and_attaches_metrics(self):
        activity = Activity(id=7, user_id=1, title="Run", distance_km=5.0, duration_seconds=1500)
        activity.segments = []
        activity.workout_blocks = []
        db = FakeDb()

        rows = sync_derived_activity_metrics(db, activity)

        self.assertTrue(db.flushed)
        self.assertTrue(db.executed)
        self.assertEqual(activity.derived_metrics, rows)
        self.assertTrue(any(row.metric_key == "average_pace_seconds_per_km" for row in rows))
        self.assertEqual(db.added, rows)


if __name__ == "__main__":
    unittest.main()
