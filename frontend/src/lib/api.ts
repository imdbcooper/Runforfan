const API_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8080/api"

export type Activity = {
  id: number
  title: string
  started_at: string | null
  distance_km: number | null
  duration_seconds: number
  average_pace_seconds_per_km: number | null
  average_heart_rate_bpm: number | null
  segments: unknown[]
}

export type LlmProvider = {
  id: number
  provider: "openai" | "anthropic"
  display_name: string
  base_url: string | null
  model: string
  is_default: boolean
  has_api_key: boolean
  created_at: string
}

let token = localStorage.getItem("runforfan_token")

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  })
  if (!response.ok) throw new Error(`${response.status}: ${await response.text()}`)
  return response.json()
}

export async function devLogin() {
  const data = await request<{ access_token: string }>("/auth/dev-login", { method: "POST", body: "{}" })
  token = data.access_token
  localStorage.setItem("runforfan_token", token)
  return data
}

export const api = {
  activities: () => request<Activity[]>("/activities"),
  analytics: () => request<Record<string, any>>("/analytics/summary"),
  providers: () => request<LlmProvider[]>("/settings/llm-providers"),
  createProvider: (payload: Record<string, unknown>) => request<LlmProvider>("/settings/llm-providers", { method: "POST", body: JSON.stringify(payload) }),
  deleteProvider: (id: number) => request(`/settings/llm-providers/${id}`, { method: "DELETE" }),
  generatePlan: (payload: Record<string, unknown>) => request<Record<string, any>>("/planning/generate", { method: "POST", body: JSON.stringify(payload) }),
}
