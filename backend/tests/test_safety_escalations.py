import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

try:
    from app.models import AthleteProfile, DailyReadinessCheckIn, SafetyEscalation
    from app.services import safety_escalations
except ModuleNotFoundError as exc:
    if exc.name in {"pydantic", "sqlalchemy"}:
        raise unittest.SkipTest("Backend dependencies are required for safety escalation tests") from exc
    raise


class SafetyEscalationTests(unittest.TestCase):
    def profile(self, recovery_status="normal"):
        return AthleteProfile(id=1, user_id=1, recovery_status=recovery_status)

    def checkin(self, *, pain=False):
        return DailyReadinessCheckIn(id=2, user_id=1, checkin_date=date(2026, 7, 15), pain=pain, illness_symptoms=False)

    def test_injured_profile_is_ambiguous_return_to_run_boundary(self):
        result = safety_escalations.classify_escalation(
            self.profile("injured"),
            None,
            {"rule_id": "profile_injured"},
        )
        self.assertEqual(result, {"trigger_kind": "return_to_run_ambiguous", "severity": "critical"})

    def test_stop_rule_has_priority_over_pain_rest(self):
        result = safety_escalations.classify_escalation(
            self.profile(),
            self.checkin(pain=True),
            {"rule_id": "pain_or_illness_stop"},
        )
        self.assertEqual(result, {"trigger_kind": "red_flag_stop", "severity": "critical"})

    def test_low_pain_rest_is_high_severity_without_medical_claim(self):
        result = safety_escalations.classify_escalation(
            self.profile(),
            self.checkin(pain=True),
            {"rule_id": "rest_required"},
        )
        self.assertEqual(result, {"trigger_kind": "pain_requires_rest", "severity": "high"})

    def test_non_qualifying_guidance_does_not_escalate(self):
        result = safety_escalations.classify_escalation(
            self.profile(),
            self.checkin(),
            {"rule_id": "proceed_as_planned"},
        )
        self.assertIsNone(result)

    def test_response_projection_excludes_source_identity_and_health_values(self):
        escalation = SafetyEscalation(
            id=3,
            user_id=1,
            local_date=date(2026, 7, 15),
            trigger_kind="red_flag_stop",
            severity="critical",
            status="open",
            rule_version=safety_escalations.RULE_VERSION,
            source_rule_version="daily-readiness-v3",
            source_rule_id="pain_or_illness_stop",
            source_key="checkin:private",
            source_fingerprint="f" * 64,
        )
        with patch.object(safety_escalations, "get_settings", return_value=SimpleNamespace(safety_escalation_enabled=True)):
            result = safety_escalations.escalation_response(escalation)
        serialized = str(result)
        self.assertNotIn("checkin:private", serialized)
        self.assertNotIn("source_fingerprint", serialized)
        self.assertNotIn("source_rule_version", serialized)
        self.assertIn("не является медицинским устройством", result["escalation"]["disclaimer"])


if __name__ == "__main__":
    unittest.main()
