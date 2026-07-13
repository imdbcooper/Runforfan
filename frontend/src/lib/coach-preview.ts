import type { CoachPreviewResult } from "@/lib/api"

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

export function coachPreviewExpired(expiresAt: string, now = Date.now()) {
  const timestamp = Date.parse(expiresAt)
  return !Number.isFinite(timestamp) || timestamp <= now
}

export function parseCoachPreviewResult(value: unknown): CoachPreviewResult {
  if (!isRecord(value) || !["readiness_action", "coach_action", "weekly_strategy"].includes(String(value.kind)) || !isRecord(value.payload)) {
    throw new Error("Coach preview response does not match the supported contract")
  }
  const payload = value.payload
  if (
    typeof payload.preview_id !== "string"
    || typeof payload.expires_at !== "string"
    || typeof payload.summary !== "string"
    || !Array.isArray(payload.changes)
    || !isRecord(payload.weekly_effect)
  ) {
    throw new Error("Coach preview payload is incomplete")
  }
  if ("constraint_facts" in payload && !Array.isArray(payload.constraint_facts)) {
    throw new Error("Coach preview constraints are malformed")
  }
  return value as CoachPreviewResult
}
