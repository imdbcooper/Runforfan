from __future__ import annotations

import unittest
from pathlib import Path

from app.services.coach_tools import authoritative_safety, build_coach_context


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


if __name__ == "__main__":
    unittest.main()
