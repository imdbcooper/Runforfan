import unittest
from datetime import date

try:
    from app.services.constraint_engine import HardWorkoutPolicy, dates_within_days, is_hard_workout, validate_readiness_action_target
except ModuleNotFoundError as exc:
    if exc.name == "sqlalchemy":
        raise unittest.SkipTest("Backend dependencies are required for constraint engine tests") from exc
    raise


class ConstraintEngineTests(unittest.TestCase):
    def test_hard_classification_preserves_policy_specific_overrides(self):
        planning = HardWorkoutPolicy(frozenset({"interval"}), frozenset({"hard"}), frozenset({"easy"}))
        calendar = HardWorkoutPolicy(frozenset({"long"}), frozenset({"hard"}))
        readiness = HardWorkoutPolicy(frozenset({"fartlek"}), frozenset({"vo2max"}), normalize_case=True)

        self.assertFalse(is_hard_workout("interval", "easy", policy=planning))
        self.assertTrue(is_hard_workout("long", "easy", policy=calendar))
        self.assertTrue(is_hard_workout("FARTLEK", None, policy=readiness))

    def test_date_windows_preserve_forward_and_absolute_semantics(self):
        first = date(2026, 6, 3)

        self.assertTrue(dates_within_days(first, date(2026, 6, 5), max_days=2))
        self.assertFalse(dates_within_days(first, date(2026, 6, 6), max_days=2))
        self.assertTrue(dates_within_days(first, date(2026, 6, 1), max_days=2, absolute=True))
        self.assertFalse(dates_within_days(first, date(2026, 6, 1), max_days=2))

    def test_readiness_validation_preserves_failure_priority(self):
        not_applicable = validate_readiness_action_target(
            action="proceed_as_planned",
            prescription=None,
            applicable_actions={"shorten_easy", "easy_replacement"},
            completed_activity_id=9,
            status="done",
            workout_is_hard=True,
            block_target_rpe_maxes=[8],
        )

        self.assertEqual(not_applicable.reason, "action_not_applicable")
        self.assertEqual(not_applicable.decision, "blocked")

    def test_readiness_validation_blocks_mutation_and_unsafe_shortening(self):
        immutable = validate_readiness_action_target(
            action="easy_replacement",
            prescription={"duration_seconds": 1800},
            applicable_actions={"shorten_easy", "easy_replacement"},
            completed_activity_id=9,
            status="done",
            workout_is_hard=False,
            block_target_rpe_maxes=[],
        )
        unsafe = validate_readiness_action_target(
            action="shorten_easy",
            prescription={"distance_km": 5.0},
            applicable_actions={"shorten_easy", "easy_replacement"},
            completed_activity_id=None,
            status="planned",
            workout_is_hard=False,
            block_target_rpe_maxes=[6],
        )

        self.assertEqual(immutable.reason, "workout_not_mutable")
        self.assertEqual(unsafe.reason, "safety_blocks_action")

    def test_readiness_validation_requires_measurable_shorten_target(self):
        missing = validate_readiness_action_target(
            action="shorten_easy",
            prescription={"distance_km": None, "duration_seconds": None},
            applicable_actions={"shorten_easy", "easy_replacement"},
            completed_activity_id=None,
            status="planned",
            workout_is_hard=False,
            block_target_rpe_maxes=[4],
        )
        allowed = validate_readiness_action_target(
            action="shorten_easy",
            prescription={"duration_seconds": 1800},
            applicable_actions={"shorten_easy", "easy_replacement"},
            completed_activity_id=None,
            status="rescheduled",
            workout_is_hard=False,
            block_target_rpe_maxes=[4],
        )

        self.assertEqual(missing.reason, "safety_blocks_action")
        self.assertTrue(allowed.allowed)


if __name__ == "__main__":
    unittest.main()
