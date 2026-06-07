import unittest
from datetime import UTC, date, datetime

try:
    from app.models import AthleteProfile, PerformanceResult, User
    from app.services.performance import (
        noisy_reasons,
        performance_pbs,
        performance_predictions,
        performance_vdot,
        select_vdot_source,
        vdot_confidence,
    )
except ModuleNotFoundError as exc:
    if exc.name in {"pydantic", "sqlalchemy"}:
        raise unittest.SkipTest("Backend dependencies are required for performance tests") from exc
    raise


def make_user() -> User:
    return User(id=1, display_name="Runner", is_demo=True, is_active=True)


def make_result(result_id: int, distance_km: float, duration_seconds: int, result_type: str = "race", result_date: datetime | None = None) -> PerformanceResult:
    return PerformanceResult(
        id=result_id,
        user_id=1,
        result_type=result_type,
        name=f"Result {result_id}",
        result_date=result_date or datetime(2026, 6, 1, 8, tzinfo=UTC),
        distance_km=distance_km,
        duration_seconds=duration_seconds,
        source="manual",
        terrain="road",
        is_noisy=False,
        created_at=datetime(2026, 6, 1, 9, tzinfo=UTC),
        updated_at=datetime(2026, 6, 1, 9, tzinfo=UTC),
    )


class FakeDb:
    def __init__(self, results: list[PerformanceResult], profile: AthleteProfile | None = None):
        self.results = results
        self.profile = profile

    def scalars(self, _query):
        return self.results

    def scalar(self, _query):
        return self.profile


class PerformanceTests(unittest.TestCase):
    def test_vdot_source_ignores_short_results_and_selects_eligible_race(self):
        short = make_result(1, 1.0, 210, "time_trial")
        race = make_result(2, 5.0, 1200, "race")

        selected = select_vdot_source([short, race], today=date(2026, 6, 2))

        self.assertEqual(selected.id, 2)

    def test_vdot_source_prefers_more_recent_source_within_same_confidence(self):
        older_faster = make_result(1, 5.0, 1180, "race", datetime(2026, 5, 1, 8, tzinfo=UTC))
        newer = make_result(2, 5.0, 1220, "race", datetime(2026, 6, 1, 8, tzinfo=UTC))

        selected = select_vdot_source([older_faster, newer], today=date(2026, 6, 2))

        self.assertEqual(selected.id, 2)

    def test_vdot_confidence_degrades_for_stale_or_noisy_sources(self):
        recent = make_result(1, 5.0, 1200, "race", datetime(2026, 6, 1, 8, tzinfo=UTC))
        old = make_result(2, 5.0, 1200, "race", datetime(2026, 1, 1, 8, tzinfo=UTC))
        trail = make_result(3, 5.0, 1200, "race", datetime(2026, 6, 1, 8, tzinfo=UTC))
        trail.terrain = "trail"

        self.assertEqual(vdot_confidence(recent, today=date(2026, 6, 2)), "high")
        self.assertEqual(vdot_confidence(old, today=date(2026, 6, 2)), "medium")
        self.assertEqual(vdot_confidence(trail, today=date(2026, 6, 2)), "medium")
        self.assertIn("trail terrain", noisy_reasons(trail))

    def test_predictions_include_confidence_and_extrapolation_limits(self):
        db = FakeDb([make_result(1, 5.0, 1200, "race")])

        predictions = performance_predictions(db, make_user())
        marathon = next(prediction for prediction in predictions if prediction["label"] == "Marathon")

        self.assertTrue(marathon["extrapolation_limited"])
        self.assertEqual(marathon["confidence"], "low")
        self.assertTrue(any("extrapolation" in warning.lower() for warning in marathon["warnings"]))

    def test_pbs_choose_best_near_exact_result(self):
        slower = make_result(1, 5.0, 1500, "race")
        faster = make_result(2, 5.0, 1200, "time_trial")
        ten_k = make_result(3, 10.0, 2700, "race")

        pbs = performance_pbs(FakeDb([slower, faster, ten_k]), make_user())
        five_k = next(pb for pb in pbs if pb["label"] == "5K")

        self.assertEqual(five_k["result_id"], 2)
        self.assertEqual(five_k["normalized_duration_seconds"], 1200)

    def test_pbs_ignore_non_race_time_trial_results(self):
        workout = make_result(1, 5.0, 1100, "workout")
        race = make_result(2, 5.0, 1250, "race")

        pbs = performance_pbs(FakeDb([workout, race]), make_user())
        five_k = next(pb for pb in pbs if pb["label"] == "5K")

        self.assertEqual(five_k["result_id"], 2)

    def test_vdot_response_includes_threshold_trend_and_derived_pace_zones(self):
        db = FakeDb([make_result(1, 10.0, 2700, "race")])

        response = performance_vdot(db, make_user())

        self.assertIsNotNone(response["estimate"])
        self.assertEqual(len(response["threshold_trend"]), 1)
        self.assertTrue(response["pace_zones"])
        self.assertEqual(response["pace_zones"][0]["method"], "vdot_threshold_estimate")

    def test_profile_threshold_pace_overrides_result_derived_zones(self):
        profile = AthleteProfile(user_id=1, lactate_threshold_pace_seconds_per_km=250, sex="unspecified", conservative_mode=False)
        db = FakeDb([make_result(1, 10.0, 2700, "race")], profile)

        response = performance_vdot(db, make_user())

        self.assertEqual(response["pace_zones"][0]["method"], "threshold_pace")


if __name__ == "__main__":
    unittest.main()
