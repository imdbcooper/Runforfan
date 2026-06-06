import unittest
from datetime import date

from app.services.calculations import (
    age_from_birthdate,
    calculate_ctl_atl_tsb,
    calculate_hrr_zones,
    calculate_pace_seconds_per_km,
    calculate_speed_kmh,
    calculate_threshold_pace_zones,
    calculate_vdot,
    estimate_hrmax_tanaka,
    predict_riegel_time,
)


class CalculationTests(unittest.TestCase):
    def test_pace_and_speed(self):
        self.assertEqual(calculate_pace_seconds_per_km(1800, 5).value, 360)
        self.assertEqual(calculate_speed_kmh(10, 3600).value, 10.0)

    def test_age_and_tanaka_hrmax(self):
        self.assertEqual(age_from_birthdate(date(1990, 6, 7), date(2026, 6, 6)), 35)
        self.assertEqual(estimate_hrmax_tanaka(35).value, 184)

    def test_hrr_zones(self):
        zones = calculate_hrr_zones(resting_hr=50, max_hr=190)
        self.assertEqual(zones[0]["zone_key"], "z1")
        self.assertEqual(zones[0]["lower_value"], 92)
        self.assertEqual(zones[-1]["upper_value"], 183)

    def test_threshold_pace_zones(self):
        zones = calculate_threshold_pace_zones(324)
        threshold = next(zone for zone in zones if zone["zone_key"] == "threshold")
        self.assertEqual(threshold["lower_value"], 319)
        self.assertEqual(threshold["upper_value"], 334)

    def test_vdot_and_riegel(self):
        vdot = calculate_vdot(5, 1200)
        self.assertGreater(vdot.value, 45)
        self.assertLess(vdot.value, 55)
        prediction = predict_riegel_time(5, 1200, 10)
        self.assertEqual(prediction.unit, "seconds")
        self.assertGreater(prediction.value, 2400)

    def test_ctl_atl_tsb(self):
        result = calculate_ctl_atl_tsb([50, 60, 40, 0, 70, 30, 20])
        self.assertIn("ctl", result)
        self.assertIn("atl", result)
        self.assertIn("tsb", result)


if __name__ == "__main__":
    unittest.main()
