export function trustedTelegramUrl(rawUrl: string) {
  try {
    const parsed = new URL(rawUrl)
    if (parsed.protocol !== "https:") return ""
    if (parsed.username || parsed.password) return ""
    if (!["t.me", "telegram.me", "www.telegram.me"].includes(parsed.hostname.toLowerCase())) return ""
    return parsed.toString()
  } catch {
    return ""
  }
}
