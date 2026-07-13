import os
import threading
import unittest
import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

try:
    from sqlalchemy import create_engine, func, select, text, update
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import sessionmaker

    from app.db.base import Base
    from app.db.migrations.runner import run_migrations
    from app.models import AuditLog, AthleteProfile, CoachingEvent, DailyReadinessCheckIn, TrainingPlan, TrainingPlanRecommendationAudit, TrainingPlanVersion, TrainingPlanWorkout, User, WeeklyReview, WeeklyStrategyPreview
    from app.services.plan_rollbacks import apply_plan_rollback_preview, create_plan_rollback_preview
    from app.services.plan_versions import plan_snapshot
    from app.services.historical_state import resolve_historical_week, utc_week_interval
    from app.services.weekly_review import WeeklyReviewConflict, apply_weekly_strategy_preview, create_weekly_strategy_preview, materialize_weekly_review
except ModuleNotFoundError as exc:
    if exc.name in {"psycopg", "sqlalchemy"}:
        raise unittest.SkipTest("PostgreSQL dependencies are required for Weekly Review integration tests") from exc
    raise


TEST_DATABASE_URL = os.getenv("RUNFORFAN_TEST_DATABASE_URL")


@unittest.skipUnless(TEST_DATABASE_URL, "RUNFORFAN_TEST_DATABASE_URL is required for PostgreSQL integration tests")
class WeeklyReviewPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database_name = make_url(TEST_DATABASE_URL).database or ""
        if not database_name.endswith("_test"):
            raise RuntimeError("RUNFORFAN_TEST_DATABASE_URL must point to a database whose name ends with _test")
        cls.schema = f"weekly_review_{uuid.uuid4().hex}"
        cls.admin_engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
        with cls.admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{cls.schema}"'))
        cls.engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True, connect_args={"options": f"-csearch_path={cls.schema}"})
        cls.SessionLocal = sessionmaker(bind=cls.engine, autoflush=False, autocommit=False)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()
        with cls.admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{cls.schema}" CASCADE'))
        cls.admin_engine.dispose()

    def setUp(self):
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        timezone = ZoneInfo("Europe/Moscow")
        local_today = datetime.now(UTC).astimezone(timezone).date()
        current_week_start = local_today - timedelta(days=local_today.weekday())
        self.review_week_start = current_week_start - timedelta(days=7)
        self.review_week_end = current_week_start - timedelta(days=1)
        self.target_week_end = current_week_start + timedelta(days=6)
        target_easy_date = max(local_today, self.target_week_end - timedelta(days=2))
        target_hard_date = self.target_week_end
        historical_time = datetime.combine(self.review_week_start - timedelta(days=2), time(8), tzinfo=timezone).astimezone(UTC)
        with self.SessionLocal() as db:
            user = User(display_name="Weekly Review Runner", is_demo=False)
            db.add(user)
            db.flush()
            profile = AthleteProfile(user_id=user.id, sex="unspecified", timezone="Europe/Moscow", locale="ru-RU", unit_system="metric", recovery_status="normal", max_run_duration_minutes=120)
            plan = TrainingPlan(user_id=user.id, title="Stage 3 Plan", goal_type="10k", target_date=self.target_week_end + timedelta(days=30), available_days_per_week=4, status="active")
            plan.workouts = [
                TrainingPlanWorkout(scheduled_date=self.review_week_start + timedelta(days=1), status="planned", week_index=1, day_index=1, workout_type="easy", title="Previous easy", distance_km=8.0, duration_seconds=3000, intensity="easy"),
                TrainingPlanWorkout(scheduled_date=self.review_week_start + timedelta(days=4), status="planned", week_index=1, day_index=2, workout_type="tempo", title="Previous tempo", distance_km=6.0, duration_seconds=2400, intensity="threshold"),
                TrainingPlanWorkout(scheduled_date=target_easy_date, status="planned", week_index=2, day_index=1, workout_type="easy", title="Next easy", distance_km=10.0, duration_seconds=3600, intensity="easy"),
                TrainingPlanWorkout(scheduled_date=target_hard_date, status="planned", week_index=2, day_index=2, workout_type="tempo", title="Next tempo", distance_km=8.0, duration_seconds=3000, intensity="threshold"),
            ]
            db.add_all([profile, plan])
            db.flush()
            version = TrainingPlanVersion(user_id=user.id, plan_id=plan.id, version_number=1, reason="initial", summary="Historical initial plan", snapshot_json=plan_snapshot(plan), post_snapshot_json=plan_snapshot(plan), created_at=historical_time)
            db.add(version)
            db.flush()
            db.execute(update(AthleteProfile).where(AthleteProfile.id == profile.id).values(created_at=historical_time, updated_at=historical_time))
            db.execute(update(TrainingPlan).where(TrainingPlan.id == plan.id).values(created_at=historical_time, updated_at=historical_time))
            db.commit()
            self.user_id = user.id
            self.plan_id = plan.id
            self.initial_version_id = version.id
            self.review_workout_ids = [workout.id for workout in plan.workouts if self.review_week_start <= workout.scheduled_date <= self.review_week_end]
            self.target_workout_ids = [workout.id for workout in plan.workouts if current_week_start <= workout.scheduled_date <= self.target_week_end]

    def add_pain_event(self, *, recorded_at: datetime | None = None):
        timezone = ZoneInfo("Europe/Moscow")
        occurred_at = datetime.combine(self.review_week_end, time(9), tzinfo=timezone).astimezone(UTC)
        with self.SessionLocal() as db:
            event = CoachingEvent(
                user_id=self.user_id,
                event_type="pain_reported",
                category="user_input",
                source="post_workout_feedback",
                occurred_at=occurred_at,
                plan_id=self.plan_id,
                payload_json={"pain_level_0_10": 4},
            )
            if recorded_at is not None:
                event.created_at = recorded_at
            db.add(event)
            db.commit()
            return event.id

    def materialize(self):
        with self.SessionLocal() as db:
            return materialize_weekly_review(db, db.get(User, self.user_id), week_start=self.review_week_start)

    def add_completed_week_evidence(self, *, readiness_days: int = 3, prior_deload: bool = False):
        timezone = ZoneInfo("Europe/Moscow")
        with self.SessionLocal() as db:
            db.add(DailyReadinessCheckIn(
                user_id=self.user_id,
                checkin_date=datetime.now(UTC).astimezone(timezone).date(),
                sleep_quality_0_10=8,
                fatigue_0_10=2,
                soreness_0_10=2,
                stress_0_10=2,
                pain=False,
                illness_symptoms=False,
            ))
            for index, workout_id in enumerate(self.review_workout_ids):
                db.add(CoachingEvent(
                    user_id=self.user_id,
                    event_type="workout_completed",
                    category="outcome",
                    source="manual_completion",
                    occurred_at=datetime.combine(self.review_week_start + timedelta(days=1 + index * 3), time(9), tzinfo=timezone).astimezone(UTC),
                    plan_id=self.plan_id,
                    workout_id=workout_id,
                    payload_json={"actual_distance_km": 8.0 if index == 0 else 6.0, "actual_duration_seconds": 3000 if index == 0 else 2400},
                ))
            for index in range(readiness_days):
                checkin_date = self.review_week_start + timedelta(days=index * 2)
                db.add(CoachingEvent(
                    user_id=self.user_id,
                    event_type="readiness_checkin_saved",
                    category="user_input",
                    source="readiness_checkin",
                    occurred_at=datetime.now(UTC),
                    payload_json={
                        "checkin_date": checkin_date.isoformat(),
                        "signals": {"sleep_quality_0_10": 8, "fatigue_0_10": 2, "soreness_0_10": 2, "stress_0_10": 2, "pain": False, "illness_symptoms": False},
                    },
                ))
            if prior_deload:
                db.add(CoachingEvent(
                    user_id=self.user_id,
                    event_type="weekly_strategy_applied",
                    category="outcome",
                    source="weekly_strategy_preview",
                    occurred_at=datetime.combine(self.review_week_start, time(8), tzinfo=timezone).astimezone(UTC),
                    plan_id=self.plan_id,
                    payload_json={
                        "strategy": "deload",
                        "changes": [
                            {"field": "distance_km", "before": 11.0, "after": 8.8},
                            {"field": "distance_km", "before": 9.0, "after": 6.3},
                            {"field": "duration_seconds", "before": 3900, "after": 3120},
                            {"field": "duration_seconds", "before": 3300, "after": 2310},
                        ],
                    },
                ))
            db.commit()

    def side_effect_counts(self):
        with self.SessionLocal() as db:
            return {
                "versions": db.scalar(select(func.count()).select_from(TrainingPlanVersion)),
                "recommendation_audits": db.scalar(select(func.count()).select_from(TrainingPlanRecommendationAudit).where(TrainingPlanRecommendationAudit.action == "apply_weekly_strategy")),
                "audit_logs": db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "weekly_strategy_applied")),
                "events": db.scalar(select(func.count()).select_from(CoachingEvent).where(CoachingEvent.event_type == "weekly_strategy_applied")),
            }

    def test_review_is_immutable_reused_and_late_record_changes_fingerprint(self):
        first = self.materialize()
        second = self.materialize()

        self.assertEqual(first["review_id"], second["review_id"])
        self.assertEqual(first["recommended_strategy"], "hold")
        self.assertEqual(first["resolution_status"], "complete")
        self.add_pain_event()
        changed = self.materialize()

        self.assertNotEqual(changed["review_id"], first["review_id"])
        self.assertNotEqual(changed["input_fingerprint"], first["input_fingerprint"])
        self.assertEqual(changed["recommended_strategy"], "deload")
        with self.SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(WeeklyReview)), 2)

    def test_concurrent_materialization_reuses_one_immutable_review(self):
        barrier = threading.Barrier(2)
        review_ids: list[int] = []
        errors: list[Exception] = []

        def materialize_in_session():
            try:
                with self.SessionLocal() as db:
                    barrier.wait(timeout=5)
                    review_ids.append(materialize_weekly_review(db, db.get(User, self.user_id), week_start=self.review_week_start)["review_id"])
            except Exception as error:
                errors.append(error)

        threads = [threading.Thread(target=materialize_in_session) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(errors, [])
        self.assertEqual(len(set(review_ids)), 1)
        with self.SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(WeeklyReview)), 1)

    def test_plan_version_boundaries_are_start_inclusive_and_end_exclusive(self):
        timezone = ZoneInfo("Europe/Moscow")
        interval_start, interval_end = utc_week_interval(self.review_week_start, self.review_week_end, timezone)
        with self.SessionLocal() as db:
            plan = db.get(TrainingPlan, self.plan_id)
            start_version = TrainingPlanVersion(
                user_id=self.user_id,
                plan_id=self.plan_id,
                version_number=2,
                reason="manual",
                summary="Start boundary",
                snapshot_json=plan_snapshot(plan),
                post_snapshot_json=plan_snapshot(plan),
                created_at=interval_start,
            )
            db.add(start_version)
            db.flush()
            end_snapshot = plan_snapshot(plan)
            end_snapshot["title"] = "Must not leak into completed week"
            end_version = TrainingPlanVersion(
                user_id=self.user_id,
                plan_id=self.plan_id,
                version_number=3,
                reason="manual",
                summary="End boundary",
                snapshot_json=end_snapshot,
                post_snapshot_json=end_snapshot,
                created_at=interval_end,
            )
            db.add(end_version)
            db.commit()
            start_version_id = start_version.id
            context = resolve_historical_week(db, db.get(User, self.user_id), as_of_at=datetime.now(UTC), requested_week_start=self.review_week_start)

        self.assertEqual(context["resolution"]["week_start_plan_version_id"], start_version_id)
        self.assertEqual(context["resolution"]["week_end_plan_version_id"], start_version_id)
        self.assertEqual(context["plan"]["title"], "Stage 3 Plan")

    def test_hold_records_audit_without_plan_version(self):
        review = self.materialize()
        with self.SessionLocal() as db:
            user = db.get(User, self.user_id)
            preview = create_weekly_strategy_preview(db, user, review["review_id"], "hold")
            applied = apply_weekly_strategy_preview(db, user, preview["preview_id"])
            retried = apply_weekly_strategy_preview(db, user, preview["preview_id"])

        self.assertEqual(applied["status"], "applied")
        self.assertEqual(retried["status"], "already_applied")
        self.assertIsNone(applied["plan_version_id"])
        self.assertEqual(applied["changes"], [])
        with self.SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(TrainingPlanVersion)), 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(TrainingPlanRecommendationAudit).where(TrainingPlanRecommendationAudit.action == "apply_weekly_strategy")), 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "weekly_strategy_applied")), 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(CoachingEvent).where(CoachingEvent.event_type == "weekly_strategy_applied")), 1)

    def test_conservative_progression_is_capped_and_idempotent(self):
        self.add_completed_week_evidence(readiness_days=3)
        review = self.materialize()
        self.assertEqual(review["recommended_strategy"], "conservative_progression")
        with self.SessionLocal() as db:
            user = db.get(User, self.user_id)
            preview = create_weekly_strategy_preview(db, user, review["review_id"], "conservative_progression")
            applied = apply_weekly_strategy_preview(db, user, preview["preview_id"])
            retried = apply_weekly_strategy_preview(db, user, preview["preview_id"])

        self.assertEqual(applied["status"], "applied")
        self.assertEqual(retried["status"], "already_applied")
        self.assertEqual(applied["plan_version_id"], retried["plan_version_id"])
        with self.SessionLocal() as db:
            workouts = {item.id: item for item in db.scalars(select(TrainingPlanWorkout).where(TrainingPlanWorkout.id.in_(self.target_workout_ids)))}
            distances = sorted(round(item.distance_km, 2) for item in workouts.values())
            self.assertEqual(distances, [8.4, 10.5])
            self.assertTrue(all(item.workout_type in {"easy", "tempo"} for item in workouts.values()))
        self.assertEqual(self.side_effect_counts(), {"versions": 2, "recommendation_audits": 1, "audit_logs": 1, "events": 1})

    def test_resume_is_limited_by_prior_safe_baseline_and_idempotent(self):
        self.add_completed_week_evidence(readiness_days=2, prior_deload=True)
        review = self.materialize()
        self.assertEqual(review["recommended_strategy"], "resume")
        self.assertEqual(review["metrics"]["prior_safe_baseline"]["planned_distance_km"], 20.0)
        with self.SessionLocal() as db:
            user = db.get(User, self.user_id)
            preview = create_weekly_strategy_preview(db, user, review["review_id"], "resume")
            applied = apply_weekly_strategy_preview(db, user, preview["preview_id"])
            retried = apply_weekly_strategy_preview(db, user, preview["preview_id"])

        self.assertEqual(applied["status"], "applied")
        self.assertEqual(retried["status"], "already_applied")
        self.assertLessEqual(applied["weekly_effect"]["planned_distance_km_after"], 20.0)
        self.assertEqual(self.side_effect_counts(), {"versions": 2, "recommendation_audits": 1, "audit_logs": 1, "events": 2})

    def test_late_historical_input_makes_review_and_preview_stale(self):
        review = self.materialize()
        with self.SessionLocal() as db:
            preview_id = create_weekly_strategy_preview(db, db.get(User, self.user_id), review["review_id"], "hold")["preview_id"]
        self.add_pain_event()

        with self.SessionLocal() as db:
            user = db.get(User, self.user_id)
            with self.assertRaisesRegex(WeeklyReviewConflict, "new historical inputs") as caught:
                apply_weekly_strategy_preview(db, user, preview_id)
            db.rollback()

        self.assertEqual(caught.exception.reason, "review_stale")
        self.assertEqual(self.side_effect_counts(), {"versions": 1, "recommendation_audits": 0, "audit_logs": 0, "events": 0})

    def test_current_fatigue_blocks_progression_apply_without_side_effects(self):
        self.add_completed_week_evidence(readiness_days=3)
        review = self.materialize()
        with self.SessionLocal() as db:
            preview_id = create_weekly_strategy_preview(db, db.get(User, self.user_id), review["review_id"], "conservative_progression")["preview_id"]
            checkin = db.scalar(select(DailyReadinessCheckIn).where(DailyReadinessCheckIn.user_id == self.user_id))
            checkin.fatigue_0_10 = 9
            db.commit()

        with self.SessionLocal() as db:
            with self.assertRaises(WeeklyReviewConflict) as caught:
                apply_weekly_strategy_preview(db, db.get(User, self.user_id), preview_id)
            db.rollback()

        self.assertEqual(caught.exception.reason, "safety_blocks_strategy")
        self.assertEqual(self.side_effect_counts(), {"versions": 1, "recommendation_audits": 0, "audit_logs": 0, "events": 0})

    def test_late_checkin_safety_event_is_linked_to_historical_date(self):
        timezone = ZoneInfo("Europe/Moscow")
        with self.SessionLocal() as db:
            checkin = DailyReadinessCheckIn(
                user_id=self.user_id,
                checkin_date=self.review_week_end,
                sleep_quality_0_10=8,
                fatigue_0_10=2,
                soreness_0_10=2,
                stress_0_10=2,
                pain=True,
                pain_level_0_10=4,
                illness_symptoms=False,
            )
            db.add(checkin)
            db.flush()
            checkin_id = checkin.id
            recorded_at = datetime.now(UTC)
            db.add_all([
                CoachingEvent(user_id=self.user_id, event_type="readiness_checkin_saved", category="user_input", source="daily_readiness", occurred_at=recorded_at, checkin_id=checkin.id, payload_json={"checkin_date": self.review_week_end.isoformat(), "signals": {"sleep_quality_0_10": 8, "fatigue_0_10": 2, "soreness_0_10": 2, "stress_0_10": 2, "pain": True, "illness_symptoms": False}}),
                CoachingEvent(user_id=self.user_id, event_type="pain_reported", category="user_input", source="daily_readiness", occurred_at=recorded_at, checkin_id=checkin.id, payload_json={"pain_level_0_10": 4}),
            ])
            db.commit()

        review = self.materialize()

        self.assertEqual(review["recommended_strategy"], "deload")
        with self.SessionLocal() as db:
            pain_event = db.scalar(select(CoachingEvent).where(CoachingEvent.checkin_id == checkin_id, CoachingEvent.event_type == "pain_reported"))
        self.assertIn({"model": "coaching_events", "id": pain_event.id}, review["evidence"])

    def test_late_workout_linked_illness_is_included(self):
        with self.SessionLocal() as db:
            illness_event = CoachingEvent(
                user_id=self.user_id,
                event_type="illness_reported",
                category="user_input",
                source="user",
                occurred_at=datetime.now(UTC),
                plan_id=self.plan_id,
                workout_id=self.review_workout_ids[0],
                payload_json={"reason": "illness"},
            )
            db.add(illness_event)
            db.commit()
            illness_event_id = illness_event.id

        review = self.materialize()

        self.assertEqual(review["recommended_strategy"], "deload")
        self.assertIn({"model": "coaching_events", "id": illness_event_id}, review["evidence"])

    def test_plan_mutation_makes_preview_stale_without_side_effects(self):
        review = self.materialize()
        with self.SessionLocal() as db:
            preview_id = create_weekly_strategy_preview(db, db.get(User, self.user_id), review["review_id"], "hold")["preview_id"]
            workout = db.get(TrainingPlanWorkout, self.target_workout_ids[0])
            workout.distance_km += 1.0
            db.commit()

        with self.SessionLocal() as db:
            with self.assertRaises(WeeklyReviewConflict) as caught:
                apply_weekly_strategy_preview(db, db.get(User, self.user_id), preview_id)
            db.rollback()

        self.assertEqual(caught.exception.reason, "preview_stale")
        self.assertEqual(self.side_effect_counts(), {"versions": 1, "recommendation_audits": 0, "audit_logs": 0, "events": 0})

    def test_expired_and_cross_user_previews_fail_closed(self):
        review = self.materialize()
        with self.SessionLocal() as db:
            preview_id = create_weekly_strategy_preview(db, db.get(User, self.user_id), review["review_id"], "hold")["preview_id"]
            preview = db.get(WeeklyStrategyPreview, preview_id)
            preview.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            other = User(display_name="Other runner", is_demo=False)
            db.add(other)
            db.commit()
            other_id = other.id

        with self.SessionLocal() as db:
            with self.assertRaises(WeeklyReviewConflict) as expired:
                apply_weekly_strategy_preview(db, db.get(User, self.user_id), preview_id)
            db.rollback()
        self.assertEqual(expired.exception.reason, "preview_invalid_or_expired")
        with self.SessionLocal() as db:
            with self.assertRaises(WeeklyReviewConflict) as foreign:
                apply_weekly_strategy_preview(db, db.get(User, other_id), preview_id)
            db.rollback()
        self.assertEqual(foreign.exception.reason, "preview_invalid_or_expired")
        self.assertEqual(self.side_effect_counts(), {"versions": 1, "recommendation_audits": 0, "audit_logs": 0, "events": 0})

    def test_recording_cutoff_excludes_then_includes_late_evidence(self):
        recorded_at = datetime.now(UTC)
        self.add_pain_event(recorded_at=recorded_at)
        with self.SessionLocal() as db:
            user = db.get(User, self.user_id)
            before = materialize_weekly_review(db, user, week_start=self.review_week_start, as_of_at=recorded_at - timedelta(seconds=1))
            after = materialize_weekly_review(db, user, week_start=self.review_week_start, as_of_at=recorded_at + timedelta(seconds=1))

        self.assertEqual(before["recommended_strategy"], "hold")
        self.assertEqual(after["recommended_strategy"], "deload")
        self.assertNotEqual(before["input_fingerprint"], after["input_fingerprint"])

    def test_profile_changed_after_week_start_fails_closed(self):
        timezone = ZoneInfo("Europe/Moscow")
        interval_start, _interval_end = utc_week_interval(self.review_week_start, self.review_week_end, timezone)
        with self.SessionLocal() as db:
            profile = db.scalar(select(AthleteProfile).where(AthleteProfile.user_id == self.user_id))
            db.execute(update(AthleteProfile).where(AthleteProfile.id == profile.id).values(updated_at=interval_start + timedelta(hours=1)))
            db.commit()

        with self.SessionLocal() as db:
            with self.assertRaisesRegex(ValueError, "timezone and safety profile cannot be reconstructed"):
                materialize_weekly_review(db, db.get(User, self.user_id), week_start=self.review_week_start)

    def test_concurrent_deload_apply_creates_one_version_and_can_be_rolled_back(self):
        self.add_pain_event()
        review = self.materialize()
        with self.SessionLocal() as db:
            preview_id = create_weekly_strategy_preview(db, db.get(User, self.user_id), review["review_id"], "deload")["preview_id"]
        barrier = threading.Barrier(2)
        statuses: list[str] = []
        errors: list[Exception] = []

        def apply_in_session():
            try:
                with self.SessionLocal() as db:
                    barrier.wait(timeout=5)
                    statuses.append(apply_weekly_strategy_preview(db, db.get(User, self.user_id), preview_id)["status"])
            except Exception as error:
                errors.append(error)

        threads = [threading.Thread(target=apply_in_session) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(errors, [])
        self.assertEqual(sorted(statuses), ["already_applied", "applied"])
        with self.SessionLocal() as db:
            preview = db.get(WeeklyStrategyPreview, preview_id)
            version_id = preview.plan_version_id
            self.assertIsNotNone(version_id)
            self.assertEqual(db.scalar(select(func.count()).select_from(TrainingPlanVersion)), 2)
            self.assertEqual(db.scalar(select(func.count()).select_from(CoachingEvent).where(CoachingEvent.event_type == "weekly_strategy_applied")), 1)
            workouts = list(db.scalars(select(TrainingPlanWorkout).where(TrainingPlanWorkout.plan_id == self.plan_id, TrainingPlanWorkout.scheduled_date >= date.today())))
            self.assertTrue(any(workout.workout_type == "easy" and "Weekly strategy: deload" in (workout.description or "") for workout in workouts))
            rollback_preview = create_plan_rollback_preview(db, db.get(User, self.user_id), self.plan_id, version_id)
            rolled_back = apply_plan_rollback_preview(db, db.get(User, self.user_id), rollback_preview["preview_id"])

        self.assertEqual(rolled_back["status"], "applied")
        with self.SessionLocal() as db:
            versions = list(db.scalars(select(TrainingPlanVersion).order_by(TrainingPlanVersion.version_number)))
            self.assertEqual(len(versions), 3)
            self.assertEqual(versions[-1].rollback_of_version_id, version_id)

    def test_migration_runner_applies_stage_three_schema(self):
        run_migrations(self.engine)
        with self.engine.connect() as connection:
            tables = set(connection.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()")).scalars())
            unique_constraints = set(connection.execute(text("SELECT constraint_name FROM information_schema.table_constraints WHERE table_schema = current_schema() AND table_name = 'weekly_reviews'")).scalars())
        self.assertIn("weekly_reviews", tables)
        self.assertIn("weekly_strategy_previews", tables)
        self.assertIn("uq_weekly_review_input", unique_constraints)


if __name__ == "__main__":
    unittest.main()
