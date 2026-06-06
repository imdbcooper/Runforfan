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
  workout_blocks: {
    id: number
    block_index: number
    block_type: "warmup" | "work" | "recovery" | "cooldown" | string
    title: string
    distance_km: number | null
    duration_seconds: number
    pace_seconds_per_km: number | null
    average_heart_rate_bpm: number | null
  }[]
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

export type AthleteProfile = {
  id: number
  user_id: number
  date_of_birth: string | null
  sex: "male" | "female" | "other" | "unspecified"
  height_cm: number | null
  weight_kg: number | null
  timezone: string | null
  locale: string | null
  resting_heart_rate_bpm: number | null
  max_heart_rate_bpm: number | null
  max_hr_source: string | null
  lactate_threshold_hr_bpm: number | null
  lactate_threshold_pace_seconds_per_km: number | null
  conservative_mode: boolean
  injury_notes: string | null
  estimated_max_heart_rate: {
    value: number | null
    unit: string
    method: string
    confidence: string
    source_reference: string
  } | null
  created_at: string
  updated_at: string
}

export type AthleteMeasurement = {
  id: number
  user_id: number
  source_model: "athlete_measurement" | "lactate_threshold_measurement" | string
  measurement_type: "weight" | "resting_hr" | "max_hr" | "lactate_threshold" | "vo2max" | "note"
  measured_at: string | null
  value_numeric: number | null
  value_json: Record<string, unknown> | null
  source: "manual" | "screenshot" | "device" | "calculated"
  confidence: number | null
  notes: string | null
  created_at: string
  updated_at: string
}

export type ProfileCompleteness = {
  score: number
  missing: string[]
  can_calculate_hr_zones: boolean
  can_calculate_hrr_zones: boolean
  can_calculate_pace_zones: boolean
  confidence: string
}

export type SafetyCheck = {
  conservative_mode: boolean
  warnings: string[]
  message: string
}

export type Zone = {
  id: number | null
  zone_type: string
  method: string
  zone_key: string
  label: string | null
  lower_value: number | null
  upper_value: number | null
  unit: string
  confidence: string
  source_reference: string | null
  is_active: boolean
}

export type ZoneWrite = {
  zone_key: string
  lower_value: number | null
  upper_value: number | null
  unit: string
  label?: string | null
}

export type Zones = {
  hr: Zone[]
  pace: Zone[]
  rpe: Zone[]
  metadata: Record<string, unknown>
}

export type PlanWorkout = {
  week_index: number
  day_index: number
  workout_type: string
  title: string
  distance_km: number | null
  duration_seconds: number | null
  intensity: string | null
  description: string | null
}

export type Plan = {
  id: number
  title: string
  goal_type: string
  race_distance_km: number | null
  target_date: string | null
  available_days_per_week: number
  status: string
  explanation: string | null
  workouts: PlanWorkout[]
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
  profile: () => request<AthleteProfile>("/profile"),
  updateProfile: (payload: Record<string, unknown>) => request<AthleteProfile>("/profile", { method: "PUT", body: JSON.stringify(payload) }),
  profileCompleteness: () => request<ProfileCompleteness>("/profile/completeness"),
  safetyCheck: () => request<SafetyCheck>("/profile/safety-check", { method: "POST", body: "{}" }),
  measurements: (limit = 50, offset = 0) => request<AthleteMeasurement[]>(`/profile/measurements?limit=${limit}&offset=${offset}`),
  createMeasurement: (payload: Record<string, unknown>) => request<AthleteMeasurement>("/profile/measurements", { method: "POST", body: JSON.stringify(payload) }),
  zones: () => request<Zones>("/zones"),
  recalculateZones: () => request<Zones>("/zones/recalculate", { method: "POST", body: "{}" }),
  replaceHrZones: (payload: ZoneWrite[]) => request<Zones>("/zones/hr", { method: "PUT", body: JSON.stringify(payload) }),
  replacePaceZones: (payload: ZoneWrite[]) => request<Zones>("/zones/pace", { method: "PUT", body: JSON.stringify(payload) }),
  providers: () => request<LlmProvider[]>("/settings/llm-providers"),
  createProvider: (payload: Record<string, unknown>) => request<LlmProvider>("/settings/llm-providers", { method: "POST", body: JSON.stringify(payload) }),
  deleteProvider: (id: number) => request(`/settings/llm-providers/${id}`, { method: "DELETE" }),
  generatePlan: (payload: Record<string, unknown>) => request<Plan>("/planning/generate", { method: "POST", body: JSON.stringify(payload) }),
}
