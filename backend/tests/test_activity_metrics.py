from __future__ import annotations

import unittest
from datetime import UTC, datetime

DEPENDENCY_SKIP_REASON = None

try:
    from sqlalchemy import create_engine, func, select
    from sqlalchemy.orm import selectinload, sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.db.base import Base
    from app.models import Activity, ActivitySegment, ActivityWorkoutBlock, DerivedActivityMetric, User
    from app.services.activity_metrics import backfill_derived_activity_metrics, compute_derived_activity_metrics, sync_derived_activity_metrics
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
        self.assertFalse(db.executed)
        self.assertEqual(activity.derived_metrics, rows)
        self.assertTrue(any(row.metric_key == "average_pace_seconds_per_km" for row in rows))
        self.assertEqual(db.added, rows)

    def test_sync_replaces_loaded_relationship_rows_in_real_session(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine, tables=[User.__table__, Activity.__table__, ActivitySegment.__table__, ActivityWorkoutBlock.__table__, DerivedActivityMetric.__table__])
        SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

        with SessionLocal() as db:
            user = User(id=1, display_name="Runner")
            activity = Activity(id=7, user_id=1, title="Run", distance_km=5.0, duration_seconds=1500)
            db.add_all([user, activity])
            db.commit()

            loaded = db.scalar(select(Activity).where(Activity.id == 7).options(selectinload(Activity.derived_metrics)))
            self.assertIsNotNone(loaded)
            first_rows = sync_derived_activity_metrics(db, loaded)
            db.commit()

            self.assertEqual(len(first_rows), 4)
            self.assertEqual(db.scalar(select(func.count()).select_from(DerivedActivityMetric).where(DerivedActivityMetric.activity_id == 7)), 4)

            loaded_again = db.scalar(select(Activity).where(Activity.id == 7).options(selectinload(Activity.derived_metrics)))
            self.assertIsNotNone(loaded_again)
            self.assertEqual(len(loaded_again.derived_metrics), 4)
            loaded_again.duration_seconds = 1800
            second_rows = sync_derived_activity_metrics(db, loaded_again)
            db.commit()

            metrics = {metric.metric_key: metric.metric_value for metric in second_rows}
            self.assertEqual(db.scalar(select(func.count()).select_from(DerivedActivityMetric).where(DerivedActivityMetric.activity_id == 7)), 4)
            self.assertEqual(metrics["duration_minutes"], 30.0)
            self.assertEqual(metrics["average_pace_seconds_per_km"], 360)

    def test_backfill_syncs_missing_metrics(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine, tables=[User.__table__, Activity.__table__, ActivitySegment.__table__, ActivityWorkoutBlock.__table__, DerivedActivityMetric.__table__])
        SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

        with SessionLocal() as db:
            user = User(id=1, display_name="Runner")
            activity = Activity(id=7, user_id=1, title="Run", distance_km=5.0, duration_seconds=1500)
            db.add_all([user, activity])
            db.commit()

            synced_count = backfill_derived_activity_metrics(db)
            db.commit()

            rows = list(db.scalars(select(DerivedActivityMetric).where(DerivedActivityMetric.activity_id == 7)))
            hashes = {row.input_hash for row in rows}
            metrics = {row.metric_key: row.metric_value for row in rows}

            self.assertEqual(synced_count, 1)
            self.assertEqual(len(rows), 4)
            self.assertEqual(len(hashes), 1)
            self.assertEqual(metrics["duration_minutes"], 25.0)

    def test_backfill_repair_mode_updates_stale_metrics(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine, tables=[User.__table__, Activity.__table__, ActivitySegment.__table__, ActivityWorkoutBlock.__table__, DerivedActivityMetric.__table__])
        SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

        with SessionLocal() as db:
            user = User(id=1, display_name="Runner")
            activity = Activity(id=7, user_id=1, title="Run", distance_km=5.0, duration_seconds=1500)
            stale = DerivedActivityMetric(activity_id=7, metric_key="duration_minutes", metric_value=1, unit="minutes", method="old", source_reference="old", input_hash="stale", computed_at=datetime(2026, 6, 8, tzinfo=UTC))
            db.add_all([user, activity, stale])
            db.commit()

            synced_count = backfill_derived_activity_metrics(db, repair_existing=True)
            db.commit()

            rows = list(db.scalars(select(DerivedActivityMetric).where(DerivedActivityMetric.activity_id == 7)))
            hashes = {row.input_hash for row in rows}
            metrics = {row.metric_key: row.metric_value for row in rows}

            self.assertEqual(synced_count, 1)
            self.assertEqual(len(rows), 4)
            self.assertEqual(len(hashes), 1)
            self.assertNotIn("stale", hashes)
            self.assertEqual(metrics["duration_minutes"], 25.0)


if __name__ == "__main__":
    unittest.main()
