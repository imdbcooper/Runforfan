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


def block_duration_total(blocks: list[dict[str, object]]) -> int:
    return sum(int(block["target_duration_seconds"] or 0) * int(block.get("repeat_count") or 1) for block in blocks)


def block_distance_total(blocks: list[dict[str, object]]) -> float:
    return round(sum(float(block["target_distance_km"] or 0) * int(block.get("repeat_count") or 1) for block in blocks), 2)


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
        self.assertEqual(block_duration_total(blocks), workout["duration_seconds"])
        self.assertAlmostEqual(block_distance_total(blocks), workout["distance_km"], places=1)

    def test_quality_work_blocks_are_capped_by_workout_type(self):
        zones = {"pace": [], "hr": [], "rpe": []}
        interval = {"workout_type": "interval", "distance_km": 18.0, "duration_seconds": 7200, "training_age_level": "advanced"}
        tempo = {"workout_type": "tempo", "distance_km": 18.0, "duration_seconds": 7200, "training_age_level": "advanced"}
        beginner_tempo = {"workout_type": "tempo", "distance_km": 10.0, "duration_seconds": 3600, "training_age_level": "beginner"}

        interval_blocks = planned_workout_blocks_for_preview(interval, zones)
        tempo_blocks = planned_workout_blocks_for_preview(tempo, zones)
        beginner_blocks = planned_workout_blocks_for_preview(beginner_tempo, zones)

        self.assertLessEqual(interval_blocks[1]["target_duration_seconds"] * interval_blocks[1]["repeat_count"], 25 * 60)
        self.assertLessEqual(tempo_blocks[1]["target_duration_seconds"], 40 * 60)
        self.assertLessEqual(beginner_blocks[1]["target_duration_seconds"], 20 * 60)
        self.assertLessEqual(interval_blocks[1]["target_distance_km"] * interval_blocks[1]["repeat_count"], 5.0)
        self.assertLessEqual(tempo_blocks[1]["target_distance_km"], 7.0)
        self.assertEqual(block_duration_total(interval_blocks), interval["duration_seconds"])
        self.assertEqual(block_duration_total(tempo_blocks), tempo["duration_seconds"])
        self.assertEqual(block_duration_total(beginner_blocks), beginner_tempo["duration_seconds"])
        self.assertAlmostEqual(block_distance_total(interval_blocks), interval["distance_km"], places=1)
        self.assertAlmostEqual(block_distance_total(tempo_blocks), tempo["distance_km"], places=1)
        self.assertAlmostEqual(block_distance_total(beginner_blocks), beginner_tempo["distance_km"], places=1)

    def test_repeated_block_rounding_keeps_parent_targets(self):
        zones = {"pace": [], "hr": [], "rpe": []}
        interval = {"workout_type": "interval", "distance_km": 8.1, "duration_seconds": 3001, "training_age_level": "intermediate"}
        hills = {"workout_type": "hill", "distance_km": 7.1, "duration_seconds": 3601, "training_age_level": "intermediate"}
        strides = {"workout_type": "strides", "distance_km": 5.1, "duration_seconds": 2401}

        for workout in (interval, hills, strides):
            blocks = planned_workout_blocks_for_preview(workout, zones)
            self.assertEqual(block_duration_total(blocks), workout["duration_seconds"])
            self.assertAlmostEqual(block_distance_total(blocks), workout["distance_km"], places=1)

    def test_short_strides_fall_back_to_easy_block(self):
        zones = {"pace": [], "hr": [], "rpe": []}
        blocks = planned_workout_blocks_for_preview({"workout_type": "strides", "distance_km": 0.2, "duration_seconds": 60}, zones)

        self.assertEqual([block["block_type"] for block in blocks], ["work"])
        self.assertEqual(block_duration_total(blocks), 60)
        self.assertAlmostEqual(block_distance_total(blocks), 0.2, places=1)

    def test_short_quality_workouts_fall_back_to_easy_block(self):
        zones = {"pace": [], "hr": [], "rpe": []}
        for workout_type in ("interval", "hill", "race_pace"):
            blocks = planned_workout_blocks_for_preview({"workout_type": workout_type, "distance_km": 0.5, "duration_seconds": 120}, zones)
            self.assertEqual([block["block_type"] for block in blocks], ["work"])
            self.assertEqual(block_duration_total(blocks), 120)
            self.assertAlmostEqual(block_distance_total(blocks), 0.5, places=1)

    def test_recovery_strides_and_hills_get_specific_blocks(self):
        zones = {"pace": [], "hr": [], "rpe": []}
        recovery = planned_workout_blocks_for_preview({"workout_type": "recovery", "distance_km": 4.0, "duration_seconds": 1800}, zones)
        strides = planned_workout_blocks_for_preview({"workout_type": "strides", "distance_km": 5.0, "duration_seconds": 2400}, zones)
        hills = planned_workout_blocks_for_preview({"workout_type": "hill", "distance_km": 7.0, "duration_seconds": 3600, "training_age_level": "intermediate"}, zones)

        self.assertEqual(recovery[0]["block_type"], "recovery")
        self.assertIn("strides", [block["block_type"] for block in strides])
        self.assertEqual(hills[1]["block_type"], "work")
        self.assertLessEqual(hills[1]["target_duration_seconds"] * hills[1]["repeat_count"], 16 * 60)
        self.assertEqual(block_duration_total(strides), 2400)
        self.assertAlmostEqual(block_distance_total(strides), 5.0, places=1)
        self.assertEqual(block_duration_total(hills), 3600)
        self.assertAlmostEqual(block_distance_total(hills), 7.0, places=1)

    def test_race_pace_blocks_use_target_race_pace(self):
        zones = {"pace": [{"zone_key": "threshold", "lower_value": 300, "upper_value": 310}], "hr": [], "rpe": []}
        blocks = planned_workout_blocks_for_preview(
            {
                "workout_type": "race_pace",
                "distance_km": 8.0,
                "duration_seconds": 3000,
                "training_age_level": "intermediate",
                "target_race_pace_seconds_per_km": 240,
            },
            zones,
        )

        self.assertEqual(blocks[1]["target_pace_min_seconds_per_km"], 235)
        self.assertEqual(blocks[1]["target_pace_max_seconds_per_km"], 245)
        self.assertNotEqual(blocks[1]["target_pace_min_seconds_per_km"], 300)

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
