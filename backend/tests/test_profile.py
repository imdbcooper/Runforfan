import unittest
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

DEPENDENCY_SKIP_REASON = None

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.routes import profile as profile_routes
    from pydantic import ValidationError

    from app.api.routes.profile import apply_measurement_to_profile
    from app.models import AthleteProfile
    from app.services import zones as zones_service
    from app.schemas.common import AthleteMeasurementCreate, AthleteProfileUpdate
    from app.services.profile import profile_completeness, safety_check
except ModuleNotFoundError as exc:
    if exc.name in {"fastapi", "httpx", "pydantic", "pydantic_core", "sqlalchemy", "starlette"}:
        DEPENDENCY_SKIP_REASON = "Backend dependencies are required for profile tests"
    else:
        raise


@unittest.skipIf(DEPENDENCY_SKIP_REASON is not None, DEPENDENCY_SKIP_REASON or "")
class ProfileServiceTests(unittest.TestCase):
    def test_profile_update_validates_training_days_and_long_run_day(self):
        with self.assertRaises(ValidationError):
            AthleteProfileUpdate(preferred_weekdays=[1, 1, 3])

        with self.assertRaises(ValidationError):
            AthleteProfileUpdate(preferred_weekdays=[1, 3], long_run_weekday=6)

        payload = AthleteProfileUpdate(preferred_weekdays=[1, 3, 6], long_run_weekday=6)
        self.assertEqual(payload.preferred_weekdays, [1, 3, 6])

    def test_profile_completeness_tracks_preferences_that_affect_calculations(self):
        complete = AthleteProfile(
            user_id=1,
            date_of_birth=date(1990, 1, 1),
            resting_heart_rate_bpm=48,
            max_heart_rate_bpm=188,
            lactate_threshold_pace_seconds_per_km=300,
            lactate_threshold_hr_bpm=170,
            weight_kg=72,
            height_cm=180,
            preferred_weekdays=[1, 3, 6],
            max_run_duration_minutes=120,
        )

        result = profile_completeness(complete)

        self.assertEqual(result["score"], 1.0)
        self.assertEqual(result["missing"], [])

        partial = AthleteProfile(user_id=1, max_heart_rate_bpm=188)
        missing = set(profile_completeness(partial)["missing"])
        self.assertIn("preferred_weekdays", missing)
        self.assertIn("max_run_duration_minutes", missing)

    def test_safety_check_uses_health_conditions_and_recovery_status(self):
        profile = AthleteProfile(user_id=1, health_conditions="asthma", recovery_status="tired")

        result = safety_check(profile)

        self.assertTrue(result["conservative_mode"])
        self.assertTrue(any("медицинские состояния" in warning for warning in result["warnings"]))
        self.assertTrue(any("Recovery status: tired" in warning for warning in result["warnings"]))

    def test_vo2max_measurement_updates_profile_current_value(self):
        profile = AthleteProfile(user_id=1)
        payload = AthleteMeasurementCreate(measurement_type="vo2max", value_numeric=52.4, source="device")

        changed_zones = apply_measurement_to_profile(profile, payload)

        self.assertFalse(changed_zones)
        self.assertEqual(profile.vo2max, 52.4)

    def test_weight_measurement_validates_profile_range(self):
        with self.assertRaises(ValidationError):
            AthleteMeasurementCreate(measurement_type="weight", value_numeric=-1, source="manual")

        with self.assertRaises(ValidationError):
            AthleteMeasurementCreate(measurement_type="weight", value_numeric=251, source="manual")

    def test_profile_weight_update_repairs_profile_dependent_metrics(self):
        profile = AthleteProfile(id=10, user_id=42, weight_kg=70, sex="unspecified", conservative_mode=False)
        profile.created_at = datetime(2026, 6, 8, tzinfo=UTC)
        profile.updated_at = datetime(2026, 6, 8, tzinfo=UTC)
        db = SimpleNamespace(commit=Mock(), refresh=Mock())
        app = FastAPI()
        app.include_router(profile_routes.router, prefix="/api")

        def override_db():
            yield db

        app.dependency_overrides[profile_routes.get_current_user] = lambda: SimpleNamespace(id=42)
        app.dependency_overrides[profile_routes.get_db] = override_db

        with (
            patch.object(profile_routes, "get_or_create_profile", return_value=profile),
            patch.object(profile_routes, "refresh_user_profile_dependent_activity_metrics") as refresh_metrics,
        ):
            response = TestClient(app).put("/api/profile", json={"weight_kg": 72})

        self.assertEqual(response.status_code, 200)
        refresh_metrics.assert_called_once_with(db, 42)

    def test_weight_measurement_repairs_profile_dependent_metrics(self):
        profile = AthleteProfile(id=10, user_id=42, weight_kg=70)
        db = SimpleNamespace(add=Mock(), commit=Mock(), refresh=Mock())
        payload = AthleteMeasurementCreate(measurement_type="weight", value_numeric=72, source="manual")

        with (
            patch.object(profile_routes, "get_or_create_profile", return_value=profile),
            patch.object(profile_routes, "refresh_user_profile_dependent_activity_metrics") as refresh_metrics,
        ):
            profile_routes.create_measurement(payload, SimpleNamespace(id=42), db)

        self.assertEqual(profile.weight_kg, 72)
        refresh_metrics.assert_called_once_with(db, 42)

    def test_zone_recalculation_preserves_manual_zone_types(self):
        class ScalarResult:
            def all(self):
                return ["hr"]

        class ZoneDb:
            def __init__(self):
                self.added = []
                self.committed = False

            def scalars(self, query):
                return ScalarResult()

            def execute(self, query):
                return None

            def add(self, item):
                self.added.append(item)

            def commit(self):
                self.committed = True

        profile = AthleteProfile(user_id=42, max_heart_rate_bpm=190, lactate_threshold_pace_seconds_per_km=300)
        db = ZoneDb()

        with (
            patch.object(zones_service, "get_or_create_profile", return_value=profile),
            patch.object(zones_service, "vdot_threshold_pace", return_value=(None, "low")),
            patch.object(zones_service, "zones_response", return_value={"hr": [], "pace": [], "rpe": [], "metadata": {}}),
        ):
            zones_service.recalculate_and_store_zones(db, SimpleNamespace(id=42))

        self.assertTrue(db.committed)
        self.assertTrue(db.added)
        self.assertTrue(all(zone.zone_type != "hr" for zone in db.added))
        self.assertTrue(any(zone.zone_type == "pace" for zone in db.added))
        self.assertTrue(any(zone.zone_type == "rpe" for zone in db.added))


if __name__ == "__main__":
    unittest.main()
