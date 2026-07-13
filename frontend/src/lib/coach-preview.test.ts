import { describe, expect, it } from "vitest"

import { coachPreviewExpired, parseCoachPreviewResult } from "./coach-preview"

const preview = {
  kind: "coach_action",
  payload: {
    preview_id: "preview-1",
    expires_at: "2026-07-14T00:10:00Z",
    summary: "Skip the selected workout",
    changes: [],
    weekly_effect: {},
    constraint_facts: [],
  },
}

describe("Coach preview contract", () => {
  it("accepts a supported server preview and rejects malformed payloads", () => {
    expect(parseCoachPreviewResult(preview)).toEqual(preview)
    expect(() => parseCoachPreviewResult({ ...preview, kind: "direct_apply" })).toThrow(/supported contract/)
    expect(() => parseCoachPreviewResult({ ...preview, payload: { ...preview.payload, changes: null } })).toThrow(/incomplete/)
    expect(() => parseCoachPreviewResult({ ...preview, payload: { ...preview.payload, constraint_facts: "unsafe" } })).toThrow(/constraints/)
  })

  it("fails closed for invalid timestamps and expires at the boundary", () => {
    expect(coachPreviewExpired("invalid", 0)).toBe(true)
    expect(coachPreviewExpired("2026-07-14T00:10:00Z", Date.parse("2026-07-14T00:09:59Z"))).toBe(false)
    expect(coachPreviewExpired("2026-07-14T00:10:00Z", Date.parse("2026-07-14T00:10:00Z"))).toBe(true)
  })
})
