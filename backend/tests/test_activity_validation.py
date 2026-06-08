from __future__ import annotations

import unittest
from datetime import UTC, datetime

DEPENDENCY_SKIP_REASON = None

try:
    from app.api.routes.activities import activity_validation_report
    from app.models import Activity, ActivityScreenshot, ActivitySegment, ActivityWorkoutBlock, ScreenshotSource
    from app.schemas.common import ActivityOut
except ModuleNotFoundError as exc:
    if exc.name in {"fastapi", "pydantic", "sqlalchemy", "starlette"}:
        DEPENDENCY_SKIP_REASON = "Backend dependencies are required for activity validation tests"
    else:
        raise


@unittest.skipIf(DEPENDENCY_SKIP_REASON is not None, DEPENDENCY_SKIP_REASON or "")
class ActivityValidationTests(unittest.TestCase):
    def test_validation_reports_segment_weighted_pace_and_sum_mismatches(self):
        activity = Activity(
            id=5,
            user_id=1,
            title="Intervals",
            started_at=datetime(2026, 6, 8, 7, tzinfo=UTC),
            distance_km=5.0,
            duration_seconds=1500,
            average_pace_seconds_per_km=280,
            average_heart_rate_bpm=150,
        )
        activity.segments = [
            ActivitySegment(id=1, activity_id=5, segment_index=1, distance_km=2.0, duration_seconds=600, pace_seconds_per_km=300),
            ActivitySegment(id=2, activity_id=5, segment_index=2, distance_km=2.0, duration_seconds=620, pace_seconds_per_km=310),
        ]

        report = activity_validation_report(activity)
        codes = {issue["code"] for issue in report["issues"]}

        self.assertEqual(report["status"], "warning")
        self.assertEqual(report["weighted_pace_seconds_per_km"], 305)
        self.assertIn("pace_distance_duration_mismatch", codes)
        self.assertIn("weighted_pace_mismatch", codes)
        self.assertIn("segment_distance_mismatch", codes)
        self.assertIn("segment_duration_mismatch", codes)
        self.assertEqual(report["source_counts"]["segments"], 2)

    def test_validation_marks_short_fast_final_segment_as_info_not_warning(self):
        activity = Activity(
            id=6,
            user_id=1,
            title="Easy finish",
            started_at=datetime(2026, 6, 8, 7, tzinfo=UTC),
            distance_km=2.2,
            duration_seconds=630,
            average_pace_seconds_per_km=286,
        )
        activity.segments = [
            ActivitySegment(id=3, activity_id=6, segment_index=3, distance_km=0.2, duration_seconds=30, pace_seconds_per_km=150),
            ActivitySegment(id=1, activity_id=6, segment_index=1, distance_km=1.0, duration_seconds=300, pace_seconds_per_km=300),
            ActivitySegment(id=2, activity_id=6, segment_index=2, distance_km=1.0, duration_seconds=300, pace_seconds_per_km=300),
        ]

        report = activity_validation_report(activity)
        check = next(item for item in report["checks"] if item["code"] == "short_fast_final_segment")

        self.assertEqual(report["status"], "ok")
        self.assertEqual(check["severity"], "info")

    def test_validation_reports_workout_block_mismatches(self):
        activity = Activity(
            id=7,
            user_id=1,
            title="Blocks",
            started_at=datetime(2026, 6, 8, 7, tzinfo=UTC),
            distance_km=5.0,
            duration_seconds=1500,
            average_pace_seconds_per_km=300,
        )
        activity.workout_blocks = [
            ActivityWorkoutBlock(id=1, activity_id=7, block_index=1, block_type="warmup", title="Warmup", distance_km=1.0, duration_seconds=300),
            ActivityWorkoutBlock(id=2, activity_id=7, block_index=2, block_type="work", title="Work", distance_km=2.0, duration_seconds=600),
        ]

        report = activity_validation_report(activity)
        codes = {issue["code"] for issue in report["issues"]}

        self.assertIn("workout_block_distance_mismatch", codes)
        self.assertIn("workout_block_duration_mismatch", codes)

    def test_activity_detail_sources_expose_safe_screenshot_metadata(self):
        activity = Activity(id=8, user_id=1, activity_type="outdoor_run", title="Screenshot run", distance_km=5.0, duration_seconds=1500)
        source = ScreenshotSource(id=99, user_id=1, file_path="/private/uploads/user-1/run.png", screen_type="summary", source_app="Huawei Health", notes="Uploaded screenshot run.png")
        activity.screenshots = [ActivityScreenshot(activity_id=8, source_id=99, source=source)]

        dumped = ActivityOut.model_validate(activity).model_dump(mode="json")

        self.assertEqual(dumped["sources"], [{
            "source_id": 99,
            "file_name": "run.png",
            "screen_type": "summary",
            "source_app": "Huawei Health",
            "captured_at": None,
            "uploaded_at": None,
            "notes": "Uploaded screenshot run.png",
        }])
        self.assertNotIn("file_path", dumped["sources"][0])


if __name__ == "__main__":
    unittest.main()
