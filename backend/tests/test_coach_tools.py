from __future__ import annotations

import unittest
from pathlib import Path

from app.services.coach_tools import _safe_state, authoritative_safety, build_coach_context


class CoachToolsTests(unittest.TestCase):
    def test_medical_language_cannot_be_downgraded(self):
        context = {"today_readiness": {"recommendation": {"status": "proceed"}}, "athlete_state": {"status": "ok"}}
        self.assertEqual(authoritative_safety(context, "I have pain but want to run"), "medical_boundary")

    def test_medical_classifier_covers_common_symptoms_without_substring_collisions(self):
        context = {"today_readiness": {"recommendation": {"status": "proceed"}}, "athlete_state": {"status": "ok"}}
        medical = (
            "I have fever and nausea",
            "I feel dizzy after running",
            "There is swelling around my ankle",
            "I have chest pain and shortness of breath",
            "У меня температура и тошнота",
            "После бега головокружение",
            "Боль в груди и трудно дышать",
            "Кажется, я растянул связку",
        )
        for message in medical:
            with self.subTest(message=message):
                self.assertEqual(authoritative_safety(context, message), "medical_boundary")
        for message in ("Use the monkey bars", "Хочу бегать больше", "Я болельщик марафона"):
            with self.subTest(message=message):
                self.assertEqual(authoritative_safety(context, message), "normal")

    def test_context_omits_raw_payloads_and_notes(self):
        # The DTO construction is field-selective: these sensitive fields never appear in it.
        source = (Path(__file__).resolve().parents[1] / "app/services/coach_tools.py").read_text(encoding="utf-8")
        self.assertNotIn("payload_json", source)
        self.assertNotIn("injury_notes", source)
        self.assertNotIn("activity.title", source)

    def test_recovery_context_omits_vendor_labels_and_operational_fields(self):
        state = _safe_state({
            "signals": [{
                "key": "recovery_signals",
                "value": {"metrics": [{
                    "id": 4,
                    "metric_key": "hrv_rmssd_ms",
                    "value": 52.0,
                    "unit": "ms",
                    "observed_at": "2026-07-14T06:00:00+00:00",
                    "quality": "high",
                    "freshness": "fresh",
                    "baseline": 61.0,
                    "baseline_samples": 7,
                    "anomaly": False,
                    "source_system": "vendor-private",
                    "source_label": "Private Device Name",
                    "received_at": "2026-07-14T06:01:00+00:00",
                }]},
            }],
        })
        metric = state["signals"][0]["value"]["metrics"][0]
        self.assertNotIn("source_system", metric)
        self.assertNotIn("source_label", metric)
        self.assertNotIn("received_at", metric)


if __name__ == "__main__":
    unittest.main()
