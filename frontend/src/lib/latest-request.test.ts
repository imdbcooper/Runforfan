import { describe, expect, it } from "vitest"

import { createLatestRequestGate } from "./latest-request"

describe("createLatestRequestGate", () => {
  it("accepts only the latest started request", () => {
    const gate = createLatestRequestGate()
    const first = gate.begin()
    const second = gate.begin()

    expect(gate.isLatest(first)).toBe(false)
    expect(gate.isLatest(second)).toBe(true)
  })

  it("invalidates the current request when a newer request starts", () => {
    const gate = createLatestRequestGate()
    const current = gate.begin()

    expect(gate.isLatest(current)).toBe(true)
    gate.begin()
    expect(gate.isLatest(current)).toBe(false)
  })
})
