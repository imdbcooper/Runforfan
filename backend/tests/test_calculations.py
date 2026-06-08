import unittest
from datetime import date

from app.services.calculations import (
    ACSM_REF,
    BANISTER_REF,
    DANIELS_REF,
    FOSTER_REF,
    KARVONEN_REF,
    LTHR_REF,
    RIEGEL_REF,
    RPE_SCALE_REF,
    TANAKA_REF,
    age_from_birthdate,
    calculate_acsm_running_energy_kcal,
    calculate_ctl_atl_tsb,
    calculate_hrmax_zones,
    calculate_hr_trimp,
    calculate_hrr_zones,
    calculate_monotony_strain,
    calculate_pace_seconds_per_km,
    calculate_rpe_zones,
    calculate_speed_kmh,
    calculate_srpe_load,
    calculate_threshold_hr_zones,
    calculate_threshold_pace_zones,
    calculate_vdot,
    calculate_weighted_average_pace,
    estimate_hrmax_tanaka,
    predict_riegel_time,
)


class CalculationTests(unittest.TestCase):
    def assertZoneSource(self, zones, source_reference):
        self.assertTrue(zones)
        for zone in zones:
            self.assertEqual(zone["source_reference"], source_reference)

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
        self.assertEqual(zones[0]["confidence"], "medium")
        self.assertEqual(zones[-1]["upper_value"], 183)

    def test_threshold_pace_zones(self):
        zones = calculate_threshold_pace_zones(324)
        threshold = next(zone for zone in zones if zone["zone_key"] == "threshold")
        self.assertEqual(threshold["lower_value"], 319)
        self.assertEqual(threshold["upper_value"], 334)

    def test_threshold_hr_and_rpe_zones(self):
        hr_zones = calculate_threshold_hr_zones(170)
        self.assertEqual(hr_zones[0]["method"], "threshold_hr")
        self.assertIsNone(hr_zones[0]["lower_value"])
        self.assertEqual(hr_zones[2]["lower_value"], 152)
        self.assertEqual(hr_zones[-1]["lower_value"], 169)

        rpe_zones = calculate_rpe_zones()
        self.assertEqual(rpe_zones[0]["unit"], "rpe")
        self.assertEqual(rpe_zones[-1]["upper_value"], 10)

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
        self.assertEqual(result["tsb"].value, round(result["ctl"].value - result["atl"].value, 1))

    def test_srpe_load_and_monotony_strain(self):
        self.assertEqual(calculate_srpe_load(60, 5).value, 300)
        self.assertEqual(calculate_srpe_load(60, 5).method, "srpe")

        result = calculate_monotony_strain([100, 80, 120, 90, 110, 0, 60])
        self.assertIsNotNone(result["monotony"].value)
        self.assertIsNotNone(result["strain"].value)

        flat = calculate_monotony_strain([50, 50, 50])
        self.assertIsNone(flat["monotony"].value)
        self.assertIsNone(flat["strain"].value)

    def test_acsm_running_energy_estimate(self):
        flat = calculate_acsm_running_energy_kcal(distance_km=10, duration_seconds=3000, weight_kg=70)
        uphill = calculate_acsm_running_energy_kcal(distance_km=10, duration_seconds=3000, weight_kg=70, grade=0.01)

        self.assertEqual(flat.value, 761.2)
        self.assertEqual(flat.unit, "kcal")
        self.assertEqual(flat.method, "acsm_running_energy")
        self.assertEqual(flat.confidence, "low")
        self.assertEqual(uphill.value, 792.7)
        self.assertEqual(uphill.confidence, "medium")

    def test_acsm_running_energy_clamps_downhill_grade(self):
        downhill = calculate_acsm_running_energy_kcal(distance_km=10, duration_seconds=3000, weight_kg=70, grade=-0.5)

        self.assertEqual(downhill.value, 761.2)
        self.assertEqual(downhill.confidence, "low")

    def test_acsm_running_energy_requires_core_inputs(self):
        self.assertIsNone(calculate_acsm_running_energy_kcal(distance_km=None, duration_seconds=3000, weight_kg=70).value)
        self.assertIsNone(calculate_acsm_running_energy_kcal(distance_km=10, duration_seconds=0, weight_kg=70).value)
        self.assertIsNone(calculate_acsm_running_energy_kcal(distance_km=10, duration_seconds=3000, weight_kg=None).value)

    def test_hr_trimp_uses_banister_sex_specific_formula(self):
        male = calculate_hr_trimp(60, average_hr_bpm=160, resting_hr_bpm=50, max_hr_bpm=190, sex="male")
        female = calculate_hr_trimp(60, average_hr_bpm=160, resting_hr_bpm=50, max_hr_bpm=190, sex="female")

        self.assertEqual(male.value, 136.4)
        self.assertEqual(male.method, "hr_trimp")
        self.assertEqual(male.confidence, "medium")
        self.assertEqual(female.value, 150.6)

    def test_hr_trimp_requires_valid_sex_and_hr_reserve(self):
        self.assertIsNone(calculate_hr_trimp(60, 160, 50, 190, sex="unspecified").value)
        self.assertIsNone(calculate_hr_trimp(60, 160, 190, 190, sex="male").value)

    def test_public_calculations_have_source_references(self):
        self.assertEqual(calculate_pace_seconds_per_km(1800, 5).source_reference, ACSM_REF)
        self.assertEqual(calculate_speed_kmh(10, 3600).source_reference, ACSM_REF)
        self.assertEqual(calculate_weighted_average_pace([(5, 1500), (3, 960)]).source_reference, ACSM_REF)
        self.assertEqual(estimate_hrmax_tanaka(35).source_reference, TANAKA_REF)
        self.assertZoneSource(calculate_hrr_zones(50, 190), KARVONEN_REF)
        self.assertZoneSource(calculate_hrmax_zones(190), ACSM_REF)
        self.assertZoneSource(calculate_threshold_hr_zones(170), LTHR_REF)
        self.assertZoneSource(calculate_threshold_pace_zones(324), DANIELS_REF)
        self.assertZoneSource(calculate_rpe_zones(), RPE_SCALE_REF)
        self.assertEqual(calculate_vdot(5, 1200).source_reference, DANIELS_REF)
        self.assertEqual(predict_riegel_time(5, 1200, 10).source_reference, RIEGEL_REF)
        self.assertEqual(calculate_srpe_load(60, 5).source_reference, FOSTER_REF)
        self.assertEqual(calculate_acsm_running_energy_kcal(10, 3000, 70).source_reference, ACSM_REF)
        self.assertEqual(calculate_hr_trimp(60, 160, 50, 190, sex="male").source_reference, BANISTER_REF)
        self.assertEqual(calculate_ctl_atl_tsb([50])["ctl"].source_reference, BANISTER_REF)
        self.assertEqual(calculate_ctl_atl_tsb([50])["atl"].source_reference, BANISTER_REF)
        self.assertEqual(calculate_ctl_atl_tsb([50])["tsb"].source_reference, BANISTER_REF)
        self.assertEqual(calculate_monotony_strain([100, 80, 120])["monotony"].source_reference, FOSTER_REF)
        self.assertEqual(calculate_monotony_strain([100, 80, 120])["strain"].source_reference, FOSTER_REF)


if __name__ == "__main__":
    unittest.main()
