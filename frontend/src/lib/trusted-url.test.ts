import { describe, expect, it } from "vitest"

import { trustedTelegramUrl } from "./trusted-url"

describe("trustedTelegramUrl", () => {
  it("accepts only Telegram HTTPS hosts", () => {
    expect(trustedTelegramUrl("https://t.me/runforfan_bot?start=abc")).toBe("https://t.me/runforfan_bot?start=abc")
    expect(trustedTelegramUrl("https://telegram.me/runforfan_bot")).toBe("https://telegram.me/runforfan_bot")
  })

  it("rejects executable, credential and lookalike URLs", () => {
    expect(trustedTelegramUrl("javascript:alert(1)")).toBe("")
    expect(trustedTelegramUrl("http://t.me/runforfan_bot")).toBe("")
    expect(trustedTelegramUrl("https://t.me.evil.example/runforfan_bot")).toBe("")
    expect(trustedTelegramUrl("https://user@t.me/runforfan_bot")).toBe("")
    expect(trustedTelegramUrl("https://user:secret@t.me/runforfan_bot")).toBe("")
    expect(trustedTelegramUrl("not a url")).toBe("")
  })
})
