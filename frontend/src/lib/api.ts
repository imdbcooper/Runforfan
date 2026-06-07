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

export type ImportBatch = {
  id: number
  status: string
  source_app: string | null
  recognition_engine: string | null
  recognition_message: string | null
  created_activity_id: number | null
  matched_workout_id: number | null
  match_status: "auto_matched" | "already_matched" | "matched" | "unmatched" | string
  auto_matched: boolean
  created_at: string
}

export type ImportUploadResult = Omit<ImportBatch, "source_app" | "created_at"> & {
  source_app?: string | null
  created_at?: string
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
  id: number
  plan_id: number
  week_index: number
  day_index: number
  scheduled_date: string | null
  status: "planned" | "done" | "missed" | "skipped" | "rescheduled" | string
  completed_activity_id: number | null
  actual_distance_km: number | null
  actual_duration_seconds: number | null
  workout_type: string
  title: string
  distance_km: number | null
  duration_seconds: number | null
  intensity: string | null
  description: string | null
  feedback: PlanWorkoutFeedback | null
  execution_score: PlanWorkoutExecutionScore | null
}

export type PlanWorkoutFeedback = {
  id: number
  workout_id: number
  rpe: number | null
  fatigue: number | null
  pain: boolean
  pain_level: number | null
  sleep_quality: number | null
  notes: string | null
  created_at: string
  updated_at: string
}

export type PlanWorkoutExecutionScore = {
  score: number | null
  status: string
  volume_score: number | null
  subjective_risk: string
  flags: string[]
}

export type PlanAdherence = {
  total_workouts: number
  done_workouts: number
  missed_workouts: number
  skipped_workouts: number
  linked_workouts: number
  unlinked_done_workouts: number
  planned_distance_km: number
  completed_distance_km: number
  completion_rate: number
  distance_completion_rate: number
  warnings: string[]
}

export type PlanWeeklyAdherence = PlanAdherence & {
  week_index: number
  planned_workouts: number
  total_workouts: number | null
}

export type PlanActivityMatchCandidate = {
  activity: Activity
  score: number
  confidence: "high" | "medium" | "low" | string
  reasons: string[]
  date_delta_days: number | null
  distance_delta_km: number | null
}

export type PlanWorkoutMatchCandidate = {
  workout: PlanWorkout
  score: number
  confidence: "high" | "medium" | "low" | string
  reasons: string[]
  date_delta_days: number | null
  distance_delta_km: number | null
}

export type PlanRecommendation = {
  type: string
  severity: "info" | "warning" | "critical" | string
  title: string
  message: string
  workout_id: number | null
  week_index: number | null
  reasons: string[]
  suggested_payload: Record<string, unknown> | null
}

export type PlanRecommendationsMetrics = {
  completion_rate: number
  distance_completion_rate: number
  missed_recent_workouts: number
  unlinked_done_workouts: number
  planned_distance_km: number
  completed_distance_km: number
  recent_completed_distance_km: number
  upcoming_planned_distance_km: number
}

export type PlanRecommendations = {
  plan_id: number
  status: "ok" | "watch" | "adjust" | string
  generated_at: string
  summary: string
  metrics: PlanRecommendationsMetrics
  recommendations: PlanRecommendation[]
}

export type PlanRecommendationChange = {
  workout_id: number | null
  field: string
  before: unknown
  after: unknown
  reason: string | null
}

export type PlanRecommendationPreview = {
  plan_id: number
  generated_at: string
  changes: PlanRecommendationChange[]
  skipped: Record<string, unknown>[]
  recommendations: PlanRecommendation[]
}

export type PlanRecommendationAudit = {
  id: number
  plan_id: number
  action: string
  status: string
  recommendations_snapshot: Record<string, unknown> | null
  preview_changes: Record<string, unknown> | null
  applied_changes: Record<string, unknown> | null
  created_at: string
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
  adherence: PlanAdherence | null
  weekly_adherence: PlanWeeklyAdherence[]
}

export type PlanRecommendationApplyResult = {
  plan_id: number
  audit_id: number
  changes: PlanRecommendationChange[]
  skipped: Record<string, unknown>[]
  plan: Plan
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
  imports: () => request<ImportBatch[]>("/imports"),
  uploadScreenshots: (files: File[]) => {
    const data = new FormData()
    files.forEach((file) => data.append("screenshots", file))
    return request<ImportUploadResult>("/imports/screenshots", { method: "POST", body: data })
  },
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
  plans: () => request<Plan[]>("/planning/plans"),
  plan: (id: number) => request<Plan>(`/planning/plans/${id}`),
  planAdherence: (id: number) => request<{ adherence: PlanAdherence; weekly_adherence: PlanWeeklyAdherence[] }>(`/planning/plans/${id}/adherence`),
  planRecommendations: (id: number) => request<PlanRecommendations>(`/planning/plans/${id}/recommendations`),
  previewPlanRecommendations: (id: number) => request<PlanRecommendationPreview>(`/planning/plans/${id}/recommendations/preview`, { method: "POST", body: "{}" }),
  applyPlanRecommendations: (id: number, changes: PlanRecommendationChange[]) => request<PlanRecommendationApplyResult>(`/planning/plans/${id}/recommendations/apply`, { method: "POST", body: JSON.stringify({ changes }) }),
  planRecommendationAudit: (id: number) => request<PlanRecommendationAudit[]>(`/planning/plans/${id}/recommendations/audit`),
  activatePlan: (id: number) => request<Plan>(`/planning/plans/${id}/activate`, { method: "POST", body: "{}" }),
  updatePlanWorkout: (id: number, payload: Record<string, unknown>) => request<PlanWorkout>(`/planning/workouts/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  workoutFeedback: (id: number) => request<PlanWorkoutFeedback | null>(`/planning/workouts/${id}/feedback`),
  saveWorkoutFeedback: (id: number, payload: Record<string, unknown>) => request<PlanWorkoutFeedback>(`/planning/workouts/${id}/feedback`, { method: "PUT", body: JSON.stringify(payload) }),
  workoutMatchCandidates: (id: number) => request<PlanActivityMatchCandidate[]>(`/planning/workouts/${id}/match-candidates`),
  activityMatchCandidates: (id: number, activeOnly = false) => request<PlanWorkoutMatchCandidate[]>(`/planning/activities/${id}/match-candidates?active_only=${activeOnly}`),
  linkPlanWorkoutActivity: (workoutId: number, activityId: number) => request<PlanWorkout>(`/planning/workouts/${workoutId}/link-activity`, { method: "POST", body: JSON.stringify({ activity_id: activityId }) }),
  providers: () => request<LlmProvider[]>("/settings/llm-providers"),
  createProvider: (payload: Record<string, unknown>) => request<LlmProvider>("/settings/llm-providers", { method: "POST", body: JSON.stringify(payload) }),
  deleteProvider: (id: number) => request(`/settings/llm-providers/${id}`, { method: "DELETE" }),
  generatePlan: (payload: Record<string, unknown>) => request<Plan>("/planning/generate", { method: "POST", body: JSON.stringify(payload) }),
}
