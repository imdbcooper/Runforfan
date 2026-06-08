from __future__ import annotations

from datetime import UTC, datetime
import unittest
from unittest.mock import Mock, patch

DEPENDENCY_SKIP_REASON = None

try:
    from sqlalchemy import create_engine, func, select
    from sqlalchemy.orm import selectinload, sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.db.base import Base
    from app.models import Activity, ActivitySegment, ActivityWorkoutBlock, AthleteProfile, DerivedActivityMetric, User
    from app.services import activity_metrics as activity_metrics_service
    from app.services.activity_metrics import _backfill_activity_ids, backfill_derived_activity_metrics, compute_derived_activity_metrics, refresh_user_profile_dependent_activity_metrics, sync_derived_activity_metrics
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


class QueryCaptureDb:
    def __init__(self):
        self.scalars_queries = []

    def scalars(self, query):
        self.scalars_queries.append(query)
        return []


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

    def test_compute_metrics_adds_estimated_energy_when_weight_is_available(self):
        activity = Activity(id=5, user_id=1, title="Run", distance_km=10.0, duration_seconds=3000, elevation_gain_m=80, elevation_loss_m=50)
        profile = AthleteProfile(user_id=1, weight_kg=70)

        metrics = {metric["metric_key"]: metric for metric in compute_derived_activity_metrics(activity, profile)}

        self.assertEqual(metrics["estimated_energy_kcal"]["metric_value"], 770.7)
        self.assertEqual(metrics["estimated_energy_kcal"]["unit"], "kcal")
        self.assertEqual(metrics["estimated_energy_kcal"]["method"], "acsm_running_energy")

    def test_compute_metrics_does_not_override_imported_calories(self):
        activity = Activity(id=5, user_id=1, title="Run", distance_km=10.0, duration_seconds=3000, calories_kcal=700)
        profile = AthleteProfile(user_id=1, weight_kg=70)

        metrics = {metric["metric_key"]: metric for metric in compute_derived_activity_metrics(activity, profile)}

        self.assertNotIn("estimated_energy_kcal", metrics)

    def test_compute_metrics_only_estimates_running_energy_for_run_like_activities(self):
        cycling = Activity(id=5, user_id=1, activity_type="cycling", title="Ride", distance_km=10.0, duration_seconds=3000)
        manual_run = Activity(id=6, user_id=1, activity_type="manual_workout", title="Planned run", distance_km=10.0, duration_seconds=3000)
        profile = AthleteProfile(user_id=1, weight_kg=70)

        cycling_metrics = {metric["metric_key"]: metric for metric in compute_derived_activity_metrics(cycling, profile)}
        manual_run_metrics = {metric["metric_key"]: metric for metric in compute_derived_activity_metrics(manual_run, profile)}

        self.assertNotIn("estimated_energy_kcal", cycling_metrics)
        self.assertIn("estimated_energy_kcal", manual_run_metrics)

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
            profile = AthleteProfile(user_id=1, weight_kg=70)
            db.add_all([user, activity])
            db.commit()

            loaded = db.scalar(select(Activity).where(Activity.id == 7).options(selectinload(Activity.derived_metrics)))
            self.assertIsNotNone(loaded)
            first_rows = sync_derived_activity_metrics(db, loaded, profile)
            db.commit()

            self.assertEqual(len(first_rows), 5)
            self.assertEqual(db.scalar(select(func.count()).select_from(DerivedActivityMetric).where(DerivedActivityMetric.activity_id == 7)), 5)

            loaded_again = db.scalar(select(Activity).where(Activity.id == 7).options(selectinload(Activity.derived_metrics)))
            self.assertIsNotNone(loaded_again)
            self.assertEqual(len(loaded_again.derived_metrics), 5)
            loaded_again.duration_seconds = 1800
            second_rows = sync_derived_activity_metrics(db, loaded_again, profile)
            db.commit()

            metrics = {metric.metric_key: metric.metric_value for metric in second_rows}
            self.assertEqual(db.scalar(select(func.count()).select_from(DerivedActivityMetric).where(DerivedActivityMetric.activity_id == 7)), 5)
            self.assertEqual(metrics["duration_minutes"], 30.0)
            self.assertEqual(metrics["average_pace_seconds_per_km"], 360)
            self.assertIn("estimated_energy_kcal", metrics)

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

            synced_count = backfill_derived_activity_metrics(db, include_profile_metrics=False)
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

            synced_count = backfill_derived_activity_metrics(db, repair_existing=True, include_profile_metrics=False)
            db.commit()

            rows = list(db.scalars(select(DerivedActivityMetric).where(DerivedActivityMetric.activity_id == 7)))
            hashes = {row.input_hash for row in rows}
            metrics = {row.metric_key: row.metric_value for row in rows}

            self.assertEqual(synced_count, 1)
            self.assertEqual(len(rows), 4)
            self.assertEqual(len(hashes), 1)
            self.assertNotIn("stale", hashes)
            self.assertEqual(metrics["duration_minutes"], 25.0)

    def test_backfill_profile_metric_candidate_query_uses_composite_key(self):
        db = QueryCaptureDb()

        activity_ids = _backfill_activity_ids(db, limit=10, repair_existing=False, include_profile_metrics=True, user_id=42)

        self.assertEqual(activity_ids, [])
        self.assertEqual(len(db.scalars_queries), 2)
        profile_query = str(db.scalars_queries[1].compile(compile_kwargs={"literal_binds": True}))
        self.assertIn("derived_activity_metrics.metric_key IS NULL", profile_query)
        self.assertIn("activities.distance_km > 0", profile_query)
        self.assertIn("activities.duration_seconds > 0", profile_query)
        self.assertIn("athlete_profiles.weight_kg > 0", profile_query)
        self.assertIn("replace(replace(lower(coalesce(activities.activity_type, 'outdoor_run')), '-', '_'), ' ', '_') = 'manual_workout'", profile_query)
        self.assertIn("activities.user_id = 42", profile_query)

    def test_refresh_profile_dependent_metrics_drains_missing_candidates(self):
        profile = AthleteProfile(user_id=42, weight_kg=70)
        activities = {
            1: Activity(id=1, user_id=42, activity_type="outdoor_run", title="Run 1", distance_km=5, duration_seconds=1500),
            2: Activity(id=2, user_id=42, activity_type="manual workout", title="Run 2", distance_km=6, duration_seconds=1800),
            3: Activity(id=3, user_id=42, activity_type="treadmill", title="Run 3", distance_km=7, duration_seconds=2100),
        }
        db = QueryCaptureDb()
        db.scalar = Mock(return_value=profile)

        def load_candidates(_db, ids):
            return [activities[activity_id] for activity_id in ids]

        with (
            patch.object(activity_metrics_service, "invalidate_user_profile_dependent_activity_metrics", return_value=3),
            patch.object(activity_metrics_service, "_missing_profile_metric_activity_ids", side_effect=[[1, 2], [3], []]) as missing_ids,
            patch.object(activity_metrics_service, "_load_backfill_candidates", side_effect=load_candidates),
            patch.object(activity_metrics_service, "_metric_rows_are_current", return_value=False),
            patch.object(activity_metrics_service, "sync_derived_activity_metrics") as sync,
        ):
            synced_count = refresh_user_profile_dependent_activity_metrics(db, 42, batch_size=2)

        self.assertEqual(synced_count, 3)
        self.assertEqual(missing_ids.call_count, 3)
        self.assertEqual(sync.call_count, 3)


if __name__ == "__main__":
    unittest.main()
