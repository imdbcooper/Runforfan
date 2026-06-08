from __future__ import annotations

import unittest
from datetime import date

DEPENDENCY_SKIP_REASON = None

try:
    from app.models import TrainingPlanWorkout, TrainingPlanWorkoutBlock
    from app.services.planning import block_to_dict, planned_workout_blocks_for_preview, workout_to_dict
except ModuleNotFoundError as exc:
    if exc.name in {"pydantic", "sqlalchemy"}:
        DEPENDENCY_SKIP_REASON = "Backend dependencies are required for planned workout block tests"
    else:
        raise


@unittest.skipIf(DEPENDENCY_SKIP_REASON is not None, DEPENDENCY_SKIP_REASON or "")
class PlannedWorkoutBlockTests(unittest.TestCase):
    def test_interval_preview_gets_structured_blocks_with_targets(self):
        workout = {
            "week_index": 1,
            "day_index": 2,
            "scheduled_date": date(2026, 6, 10),
            "workout_type": "interval",
            "title": "Intervals",
            "distance_km": 8.0,
            "duration_seconds": 3000,
            "intensity": "threshold",
            "description": "Quality",
        }
        zones = {
            "pace": [{"zone_key": "interval", "lower_value": 230, "upper_value": 260}, {"zone_key": "easy", "lower_value": 360, "upper_value": 420}],
            "hr": [{"zone_key": "z4", "lower_value": 165, "upper_value": 178}, {"zone_key": "z2", "lower_value": 135, "upper_value": 150}],
            "rpe": [],
        }

        blocks = planned_workout_blocks_for_preview(workout, zones)

        self.assertEqual([block["block_type"] for block in blocks], ["warmup", "work", "recovery", "cooldown"])
        self.assertEqual(blocks[1]["repeat_count"], 4)
        self.assertEqual(blocks[1]["target_pace_min_seconds_per_km"], 230)
        self.assertEqual(blocks[1]["target_hr_max_bpm"], 178)

    def test_workout_to_dict_serializes_persisted_blocks(self):
        workout = TrainingPlanWorkout(
            id=10,
            plan_id=20,
            scheduled_date=date(2026, 6, 8),
            status="planned",
            week_index=1,
            day_index=1,
            workout_type="easy",
            title="Easy",
            distance_km=5.0,
            duration_seconds=1800,
            intensity="easy",
        )
        workout.blocks = [
            TrainingPlanWorkoutBlock(id=2, workout_id=10, block_index=2, block_type="cooldown", repeat_count=1, target_duration_seconds=300),
            TrainingPlanWorkoutBlock(id=1, workout_id=10, block_index=1, block_type="work", repeat_count=1, target_distance_km=5.0),
        ]

        result = workout_to_dict(workout)

        self.assertEqual([block["block_index"] for block in result["blocks"]], [1, 2])
        self.assertEqual(result["blocks"][0], block_to_dict(workout.blocks[1]))


if __name__ == "__main__":
    unittest.main()
