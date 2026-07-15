import copy
import hashlib
import json
from pathlib import Path

from app.core.settings import Settings
from app.services.weekly_review import WEEKLY_REVIEW_RULE_VERSION, WEEKLY_STRATEGIES, compute_weekly_review


REPLAY_VERSION = "stage6-strategy-replay-v1"
RELEASE_GATE_VERSION = "stage6-software-release-gate-v1"
EXPECTED_MANIFEST_FINGERPRINT = "95f5ddadaa8d310c0689684ca316f92d61e9ffb88ff0318c02e9c713452e5d98"
FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "stage6" / "weekly_review_healthy.json"
SCENARIOS = (
    {"id": "healthy_progression", "expected": "conservative_progression", "mutation": "none", "safety": "normal"},
    {"id": "pain_deload", "expected": "deload", "mutation": "pain", "safety": "safety_override"},
    {"id": "partial_hold", "expected": "hold", "mutation": "partial", "safety": "conservative_fallback"},
    {"id": "prior_deload_resume", "expected": "resume", "mutation": "prior_deload", "safety": "bounded_resume"},
    {"id": "overdone_hold", "expected": "hold", "mutation": "overdone", "safety": "conservative_fallback"},
    {"id": "illness_deload", "expected": "deload", "mutation": "illness", "safety": "safety_override"},
    {"id": "profile_restriction_deload", "expected": "deload", "mutation": "profile_restriction", "safety": "safety_override"},
    {"id": "high_risk_feedback_deload", "expected": "deload", "mutation": "high_risk_feedback", "safety": "safety_override"},
    {"id": "severe_fatigue_deload", "expected": "deload", "mutation": "severe_fatigue", "safety": "safety_override"},
    {"id": "reduced_readiness_hold", "expected": "hold", "mutation": "reduced_readiness", "safety": "conservative_fallback"},
    {"id": "unlinked_completion_hold", "expected": "hold", "mutation": "unlinked", "safety": "conservative_fallback"},
    {"id": "low_adherence_hold", "expected": "hold", "mutation": "low_adherence", "safety": "conservative_fallback"},
    {"id": "missing_checkins_hold", "expected": "hold", "mutation": "missing_checkins", "safety": "conservative_fallback"},
    {"id": "missing_workouts_hold", "expected": "hold", "mutation": "missing_workouts", "safety": "conservative_fallback"},
    {"id": "wearable_anomaly_hold", "expected": "hold", "mutation": "wearable_anomaly", "safety": "conservative_fallback"},
    {"id": "same_day_correction_deload", "expected": "deload", "mutation": "same_day_correction", "safety": "safety_override"},
)


def _context(mutation: str) -> dict[str, object]:
    context = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    if mutation == "pain":
        context["events"].append({"id": 9001, "event_type": "pain_reported", "occurred_at": "2026-07-12T10:00:00+00:00", "payload": {"pain_level_0_10": 4}})
    elif mutation == "partial":
        context["resolution"]["status"] = "partial_legacy"
        context["resolution"]["limitations"] = ["replay coverage gap"]
    elif mutation == "prior_deload":
        context["events"].append({"id": 9002, "event_type": "weekly_strategy_applied", "occurred_at": "2026-07-06T04:00:00+00:00", "payload": {"strategy": "deload", "changes": [{"field": "distance_km", "before": 14.0, "after": 11.0}, {"field": "duration_seconds", "before": 5400, "after": 4300}]}})
    elif mutation == "overdone":
        context["review_workouts"][0]["execution"]["adherence_status"] = "overdone"
    elif mutation == "illness":
        context["events"].append({"id": 9003, "event_type": "illness_reported", "occurred_at": "2026-07-12T10:00:00+00:00", "payload": {}})
    elif mutation == "profile_restriction":
        context["profile"]["recovery_status"] = "injured"
    elif mutation == "high_risk_feedback":
        context["review_workouts"][0]["execution"]["subjective_risk"] = "high"
    elif mutation in {"severe_fatigue", "reduced_readiness"}:
        for event in context["events"]:
            if event["event_type"] == "readiness_checkin_saved":
                signals = event["payload"]["signals"]
                signals["fatigue_0_10"] = 9 if mutation == "severe_fatigue" else 6
    elif mutation == "unlinked":
        context["review_workouts"][0]["actual"] = None
        context["review_workouts"][0]["completed_activity_id"] = None
    elif mutation == "low_adherence":
        context["review_workouts"][0]["status"] = "missed"
        context["review_workouts"][0]["actual"] = None
        context["review_workouts"][0]["completed_activity_id"] = None
    elif mutation == "missing_checkins":
        context["events"] = [event for event in context["events"] if event["event_type"] != "readiness_checkin_saved"]
    elif mutation == "missing_workouts":
        context["review_workouts"] = []
    elif mutation == "wearable_anomaly":
        context["recovery_observations"] = [
            {
                "id": index,
                "metric_key": "hrv_rmssd_ms",
                "value": 60.0 if index < 8 else 40.0,
                "unit": "ms",
                "observed_at": f"2026-07-{4 + index:02d}T08:00:00+00:00" if index < 8 else "2026-07-13T07:00:00+00:00",
                "received_at": "2026-07-13T08:00:00+00:00",
                "source_kind": "device_import",
                "source_system": "synthetic_replay",
                "source_label": "Synthetic replay",
                "quality": "high",
                "quality_score": 0.9,
                "normalization_version": "recovery-signals-v1",
            }
            for index in range(1, 9)
        ]
    elif mutation == "same_day_correction":
        corrected = copy.deepcopy(next(event for event in context["events"] if event["event_type"] == "readiness_checkin_saved"))
        corrected["id"] = 9004
        corrected["occurred_at"] = "2026-07-12T20:00:00+00:00"
        corrected["payload"]["checkin_date"] = "2026-07-07"
        corrected["payload"]["signals"]["fatigue_0_10"] = 9
        context["events"].append(corrected)
    elif mutation != "none":
        raise ValueError(f"Unsupported replay mutation: {mutation}")
    return context


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def run_strategy_replay() -> dict[str, object]:
    results: list[dict[str, object]] = []
    for scenario in SCENARIOS:
        context = _context(str(scenario["mutation"]))
        first = compute_weekly_review(context)
        perturbed = copy.deepcopy(context)
        perturbed["events"] = list(reversed(perturbed["events"]))
        perturbed["review_workouts"] = list(reversed(perturbed["review_workouts"]))
        second = compute_weekly_review(perturbed)
        output = _canonical(first)
        actual = str(first["recommended_strategy"])
        passed = output == _canonical(second) and actual == scenario["expected"] and actual in WEEKLY_STRATEGIES
        results.append({"id": scenario["id"], "expected_strategy": scenario["expected"], "actual_strategy": actual, "safety_class": scenario["safety"], "output_fingerprint": hashlib.sha256(output.encode()).hexdigest(), "status": "pass" if passed else "block"})
    manifest = {"replay_version": REPLAY_VERSION, "rule_version": WEEKLY_REVIEW_RULE_VERSION, "strategy_allowlist": sorted(WEEKLY_STRATEGIES), "scenarios": results}
    fingerprint = hashlib.sha256(_canonical(manifest).encode()).hexdigest()
    return {**manifest, "manifest_fingerprint": fingerprint, "expected_manifest_fingerprint": EXPECTED_MANIFEST_FINGERPRINT, "status": "pass" if all(item["status"] == "pass" for item in results) and fingerprint == EXPECTED_MANIFEST_FINGERPRINT else "block"}


def software_release_gate(settings: Settings) -> dict[str, object]:
    replay = run_strategy_replay()
    closed_flags = {
        "coach_delivery_enabled": not settings.coach_delivery_enabled,
        "coach_delivery_worker_enabled": not settings.coach_delivery_worker_enabled,
        "coach_post_workout_delivery_enabled": not settings.coach_post_workout_delivery_enabled,
        "coach_weekly_review_delivery_enabled": not settings.coach_weekly_review_delivery_enabled,
        "safety_escalation_enabled": not settings.safety_escalation_enabled,
        "safety_review_enabled": not settings.safety_review_enabled,
        "safety_review_reviewer_api_enabled": not settings.safety_review_reviewer_api_enabled,
    }
    gates = {"strategy_replay": replay["status"], "default_off_rollout": "pass" if all(closed_flags.values()) else "block"}
    status = "pass" if all(value == "pass" for value in gates.values()) else "block"
    return {"release_gate_version": RELEASE_GATE_VERSION, "status": status, "gates": gates, "closed_rollout_flags": closed_flags, "replay": replay, "operational_staffed_review": "blocked_pending_human_checklist", "product_outcome_claims": "insufficient_data_pending_retention_and_trust_measurement", "disclaimer": "Software baseline only. Passing does not enable delivery or staffed review and does not prove retention, trust, clinical safety, staffing, monitoring, or response time."}
