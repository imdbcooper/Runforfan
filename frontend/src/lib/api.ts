const API_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8080/api"
const DEV_LOGIN_ENABLED = import.meta.env.DEV || import.meta.env.VITE_ENABLE_DEV_LOGIN === "true"
const TELEGRAM_BOT_USERNAME = import.meta.env.VITE_TELEGRAM_BOT_USERNAME || ""
const AUTH_EXPIRED_EVENT = "runforfan-auth-expired"

function safeStorageGet(key: string) {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function safeStorageSet(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    // Auth still works for the current tab even if persistent storage is blocked.
  }
}

function safeStorageRemove(key: string) {
  try {
    localStorage.removeItem(key)
  } catch {
    // Ignore storage failures; in-memory token state is still cleared.
  }
}

export type Activity = {
  id: number
  activity_type: string
  title: string
  started_at: string | null
  distance_km: number | null
  duration_seconds: number
  calories_kcal: number | null
  average_pace_seconds_per_km: number | null
  fastest_pace_seconds_per_km: number | null
  average_speed_kmh: number | null
  average_cadence_spm: number | null
  average_stride_cm: number | null
  steps_count: number | null
  average_heart_rate_bpm: number | null
  elevation_gain_m: number | null
  elevation_loss_m: number | null
  aerobic_training_stress: number | null
  aerobic_training_effect: string | null
  source_note: string | null
  segments: ActivitySegment[]
  split_blocks: ActivitySplitBlock[]
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
  derived_metrics: DerivedActivityMetric[]
  sources: ActivitySource[]
}

export type ActivitySource = {
  source_id: number
  file_name: string | null
  screen_type: string | null
  source_app: string | null
  captured_at: string | null
  uploaded_at: string | null
  notes: string | null
}

export type ActivitySegment = {
  id: number
  segment_index: number
  distance_km: number
  duration_seconds: number
  pace_seconds_per_km: number
  average_heart_rate_bpm: number | null
  average_cadence_spm: number | null
}

export type ActivitySplitBlock = {
  id: number
  block_index: number
  start_km: number
  end_km: number
  distance_km: number
  duration_seconds: number
  cumulative_duration_seconds: number | null
  notes: string | null
}

export type ActivityValidationIssue = {
  code: string
  severity: "info" | "warning" | string
  message: string
  metric: string | null
  expected: number | null
  actual: number | null
  unit: string | null
}

export type ActivityValidation = {
  activity_id: number
  status: "ok" | "warning" | string
  weighted_pace_seconds_per_km: number | null
  source_counts: Record<string, number>
  checks: ActivityValidationIssue[]
  issues: ActivityValidationIssue[]
}

export type DerivedActivityMetric = {
  activity_id: number
  metric_key: string
  metric_value: number
  unit: string
  method: string
  source_reference: string | null
  input_hash: string
  computed_at: string
}

export type LlmProvider = {
  id: number
  provider: "openai" | "anthropic"
  display_name: string
  base_url: string | null
  model: string
  is_default: boolean
  has_api_key: boolean
  supports_vision: boolean
  created_at: string
}

export type LlmProviderTest = {
  ok: boolean
  status: string
  provider: string
  model: string
  response_ms: number | null
  supports_vision: boolean
  message: string
}

export type Integration = {
  id: string
  name: string
  category: string
  status: string
  configured: boolean
  description: string
  details: Record<string, unknown>
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
  requires_confirmation: boolean
  candidate: ImportCandidate | null
  created_at: string
}

export type ImportCandidate = {
  activity: {
    title: string | null
    started_at: string | null
    distance_km: number | null
    duration_seconds: number | null
    average_pace_seconds_per_km: number | null
    average_heart_rate_bpm: number | null
  }
  confidence: "low" | "medium" | "high" | string | null
  uncertainty_notes: string[]
  estimated_fields: string[]
  segments_count: number
  workout_blocks_count: number
}

export type ImportUploadResult = Omit<ImportBatch, "source_app" | "created_at"> & {
  source_app?: string | null
  created_at?: string
}

export type CsvImportResult = {
  id: number
  status: string
  source_app: string
  created_activities: number
  skipped_duplicates: number
  failed_rows: number
  matched_workouts: number
  created_activity_ids: number[]
  errors: string[]
  recognition_message: string | null
}

export type AuditLogEntry = {
  id: number
  action: string
  entity_type: string
  entity_id: number | null
  metadata_json: Record<string, unknown> | null
  created_at: string
}

export type GoalProgress = {
  metric: string
  value: number | null
  target: number | null
  percentage: number
  readiness: string
}

export type GoalMilestone = {
  title: string
  due_date: string | null
  status: string
  target: unknown
  value?: number | null
}

export type GoalPredictedRange = {
  target_distance_km: number
  predicted_duration_seconds: number
  lower_seconds: number
  upper_seconds: number
  confidence: string
  source: string | null
  target_delta_seconds: number | null
  warnings: string[]
}

export type RunningGoal = {
  id: number
  title: string
  goal_type: "race" | "weekly_consistency" | "monthly_distance" | "long_run" | "custom_habit" | "health" | string
  target_value: number | null
  unit: string | null
  period_start: string | null
  period_end: string | null
  race_distance_km: number | null
  target_date: string | null
  target_time_seconds: number | null
  priority: string | null
  course_notes: string | null
  training_plan_id: number | null
  reason: string | null
  status: "active" | "paused" | "completed" | "missed" | "archived" | string
  created_at: string
  updated_at: string
  progress: GoalProgress
  milestones: GoalMilestone[]
  plan: { id: number; title: string; status: string; goal_type: string; race_distance_km: number | null; target_date: string | null; adherence: PlanAdherence } | null
  current_fitness: PerformanceVdot | null
  predicted_time_range: GoalPredictedRange | null
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
  unit_system: "metric" | "imperial" | string
  preferred_weekdays: number[] | null
  long_run_weekday: number | null
  max_run_duration_minutes: number | null
  resting_heart_rate_bpm: number | null
  max_heart_rate_bpm: number | null
  max_hr_source: string | null
  lactate_threshold_hr_bpm: number | null
  lactate_threshold_pace_seconds_per_km: number | null
  vo2max: number | null
  conservative_mode: boolean
  injury_notes: string | null
  health_conditions: string | null
  recovery_status: "fresh" | "normal" | "tired" | "strained" | "injured" | "unknown" | string
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
  source: "manual" | "screenshot" | "device" | "calculated" | "lab"
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
  blocks: PlannedWorkoutBlock[]
  feedback: PlanWorkoutFeedback | null
  execution_score: PlanWorkoutExecutionScore | null
}

export type PlannedWorkoutBlock = {
  id: number | null
  workout_id: number | null
  block_index: number
  block_type: string
  repeat_count: number
  target_distance_km: number | null
  target_duration_seconds: number | null
  target_pace_min_seconds_per_km: number | null
  target_pace_max_seconds_per_km: number | null
  target_hr_min_bpm: number | null
  target_hr_max_bpm: number | null
  target_rpe_min: number | null
  target_rpe_max: number | null
  description: string | null
}

export type PlanWorkoutFeedback = {
  id: number
  workout_id: number
  activity_id: number | null
  completion_status: string | null
  rpe: number | null
  soreness_0_10: number | null
  fatigue: number | null
  pain: boolean
  pain_level: number | null
  sleep_quality_0_10: number | null
  sleep_quality: number | null
  pain_notes: string | null
  user_notes: string | null
  weather_notes: string | null
  notes: string | null
  created_at: string
  updated_at: string
}

export type PlanWorkoutExecutionScore = {
  score: number | null
  status: string
  volume_score: number | null
  intensity_score: number | null
  adherence_status: string
  subjective_risk: string
  flags: string[]
}

export type PlanAdherence = {
  total_workouts: number
  planned_sessions: number
  done_workouts: number
  completed_sessions: number
  missed_workouts: number
  skipped_workouts: number
  linked_workouts: number
  unlinked_done_workouts: number
  planned_distance_km: number
  completed_distance_km: number
  planned_duration_seconds: number
  completed_duration_seconds: number
  completion_rate: number
  session_adherence: number
  distance_completion_rate: number
  distance_adherence: number
  duration_completion_rate: number
  duration_adherence: number
  support_workouts: number
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
  duration_delta_seconds: number | null
}

export type PlanWorkoutMatchCandidate = {
  workout: PlanWorkout
  score: number
  confidence: "high" | "medium" | "low" | string
  reasons: string[]
  date_delta_days: number | null
  distance_delta_km: number | null
  duration_delta_seconds: number | null
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
  elapsed_workouts: number
  recent_completed_distance_km: number
  upcoming_planned_distance_km: number
  low_adherence_weeks: number
  upcoming_hard_workouts: number
}

export type PlanRecommendations = {
  plan_id: number
  status: "ok" | "watch" | "adjust" | string
  generated_at: string
  summary: string
  adaptation_summary: string | null
  risk_before: Record<string, unknown> | null
  risk_after: Record<string, unknown> | null
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
  adaptation_summary: string | null
  risk_before: Record<string, unknown> | null
  risk_after: Record<string, unknown> | null
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

export type PlanVersion = {
  id: number
  plan_id: number
  version_number: number
  reason: "initial" | "manual_edit" | "auto_adaptation" | "user_request" | string
  summary: string | null
  snapshot_json: Record<string, unknown> | null
  created_at: string
}

export type Plan = {
  id: number
  title: string
  goal_type: string
  race_distance_km: number | null
  target_date: string | null
  target_time_seconds: number | null
  available_days_per_week: number
  status: string
  explanation: string | null
  workouts: PlanWorkout[]
  adherence: PlanAdherence | null
  weekly_adherence: PlanWeeklyAdherence[]
  created_at: string | null
  updated_at: string | null
}

export type PlanWeekSummary = {
  week_index: number
  planned_distance_km: number
  planned_duration_seconds: number | null
  completed_distance_km: number
  completed_duration_seconds: number
  completion_rate: number
  distance_completion_rate: number
  planned_time_label: string
  hard_sessions: number
  support_workouts: number
  support_duration_seconds: number
  long_run_km: number | null
  deload: boolean
  workouts: PlanWorkout[]
  warnings: string[]
}

export type PlanBuilderBaseline = {
  observed_weekly_volume_km: number[]
  current_weekly_volume_km: number
  current_weekly_volume_source: string
  recent_long_run_km: number | null
  history_span_days: number
  consistent_weeks: number
  activity_count: number
  training_age_level: string
  detected_training_age_level: string | null
  quality_sessions_8w: number
  confidence: string
}

export type PlanBuilderWeeklyVolume = {
  week_index: number
  phase: string
  is_taper: boolean
  taper_week_index: number | null
  planned_distance_km: number
  long_run_km: number
  hard_sessions: number
  support_sessions: number
  support_duration_seconds: number
}

export type PlanBuilderRiskFlag = {
  code: string
  severity: "info" | "warning" | "critical" | string
  message: string
  reasons: string[]
}

export type PlanBuilderPreviewWorkout = {
  week_index: number
  day_index: number
  scheduled_date: string
  phase: string
  workout_type: string
  title: string
  distance_km: number | null
  duration_seconds: number | null
  intensity: string | null
  description: string | null
  blocks: PlannedWorkoutBlock[]
}

export type PlanBuilderPreview = {
  title: string
  goal_type: string
  race_distance_km: number | null
  target_date: string | null
  target_time_seconds: number | null
  priority: string
  weeks: number
  available_days_per_week: number
  preferred_weekdays: number[]
  intensity_mode: string
  start_date: string
  current_weekly_distance_km: number
  peak_weekly_distance_km: number
  constraints: Record<string, unknown>
  baseline: PlanBuilderBaseline
  weekly_volume_curve: PlanBuilderWeeklyVolume[]
  intensity_split: Record<string, number>
  risk_flags: PlanBuilderRiskFlag[]
  workouts: PlanBuilderPreviewWorkout[]
  explanation: string
}

export type PlanRecommendationApplyResult = {
  plan_id: number
  audit_id: number
  plan_version_id: number | null
  plan_version_number: number | null
  adaptation_summary: string | null
  risk_before: Record<string, unknown> | null
  risk_after: Record<string, unknown> | null
  changes: PlanRecommendationChange[]
  skipped: Record<string, unknown>[]
  plan: Plan
}

export type CurrentWeek = {
  plan_id: number | null
  plan_title: string | null
  plan_status: string | null
  week_index: number | null
  week_start: string
  week_end: string
  today: string
  status: string
  message: string
  workouts: PlanWorkout[]
  adherence: PlanAdherence | null
  today_workout: PlanWorkout | null
  next_workout: PlanWorkout | null
}

export type DashboardPlanSummary = {
  id: number
  title: string
  status: string
  goal_type: string
  race_distance_km: number | null
  target_date: string | null
  adherence: PlanAdherence | null
}

export type DashboardReadiness = {
  status: "ok" | "watch" | "risk" | string
  message: string
  factors: string[]
}

export type DashboardAlert = {
  severity: "info" | "warning" | "critical" | string
  title: string
  message: string
  action: string | null
}

export type DashboardRecommendationSummary = {
  status: "ok" | "watch" | "adjust" | string
  summary: string
  recommendations: PlanRecommendation[]
}

export type CalculationResult = {
  value: number | null
  unit: string
  method: string
  confidence: string
  source_reference: string
}

export type AnalyticsPeriod = {
  from_date: string | null
  to_date: string | null
  label: string
}

export type AnalyticsActivityHighlight = {
  id: number
  title: string
  started_at: string | null
  distance_km: number | null
  duration_seconds: number | null
  average_pace_seconds_per_km: number | null
  average_heart_rate_bpm: number | null
}

export type AnalyticsBestEffort = {
  target_distance_km: number
  activity_id: number
  title: string
  started_at: string | null
  source: string
  confidence: string
  distance_km: number
  duration_seconds: number
  pace_seconds_per_km: number
  estimated_vdot: CalculationResult | null
}

export type AnalyticsConsistency = {
  training_days: number
  training_days_per_week: number
  missed_planned_sessions: number
}

export type AnalyticsMonth = {
  month: string
  distance_km: number
  duration_seconds: number
  count: number
}

export type AnalyticsSummary = {
  period: AnalyticsPeriod
  activity_count: number
  total_distance_km: number
  total_duration_seconds: number
  weighted_average_pace_seconds_per_km: number | null
  average_heart_rate_bpm: number | null
  training_load: number | null
  load_method: string
  longest_activity_id: number | null
  longest_distance_km: number | null
  fastest_activity_id: number | null
  fastest_average_pace_seconds_per_km: number | null
  longest_activity: AnalyticsActivityHighlight | null
  fastest_activity: AnalyticsActivityHighlight | null
  adherence: PlanAdherence | null
  consistency: AnalyticsConsistency
  best_efforts: AnalyticsBestEffort[]
  estimated_vdot: CalculationResult | null
  estimated_vdot_activity_id: number | null
  manual_vo2max: CalculationResult | null
  months: AnalyticsMonth[]
}

export type AnalyticsTimeseriesPoint = {
  period_start: string
  period_label: string
  value: number | null
  distance_km: number
  duration_seconds: number
  count: number
  weighted_average_pace_seconds_per_km: number | null
  average_heart_rate_bpm: number | null
  training_load: number | null
}

export type AnalyticsTimeseries = {
  metric: string
  granularity: string
  points: AnalyticsTimeseriesPoint[]
}

export type AnalyticsInsight = {
  severity: "info" | "warning" | "critical" | string
  title: string
  message: string
  confidence: "low" | "medium" | "high" | string
  evidence: Record<string, unknown>[]
  reasons: string[]
}

export type TrainingLoadDailyPoint = {
  date: string
  load: number
  load_method: string
  load_methods: string[]
  distance_km: number
  duration_seconds: number
  duration_minutes: number
  activity_ids: number[]
  activity_count: number
  srpe_count: number
  hard_session: boolean
  hard_reasons: string[]
  recovery_day: boolean
  ctl: number | null
  atl: number | null
  tsb: number | null
  monotony_window_value: number | null
  strain_window_value: number | null
}

export type TrainingLoadDaily = {
  period: AnalyticsPeriod
  method: string
  points: TrainingLoadDailyPoint[]
}

export type TrainingLoadWeeklyPoint = {
  week_start: string
  week_label: string
  load: number
  load_method: string
  distance_km: number
  duration_seconds: number
  activity_count: number
  hard_sessions: number
  recovery_days: number
  long_run_share: number | null
  monotony: number | null
  strain: number | null
}

export type TrainingLoadWeekly = {
  period: AnalyticsPeriod
  method: string
  points: TrainingLoadWeeklyPoint[]
}

export type TrainingLoadFitnessPoint = {
  date: string
  load: number
  ctl: number
  atl: number
  tsb: number
}

export type TrainingLoadFitnessFatigue = {
  period: AnalyticsPeriod
  method: string
  explanation: string
  current: {
    ctl: CalculationResult
    atl: CalculationResult
    tsb: CalculationResult
  }
  points: TrainingLoadFitnessPoint[]
}

export type TrainingLoadWarning = {
  severity: "info" | "warning" | "critical" | string
  title: string
  message: string
  reasons: string[]
  metric: string | null
  value: number | null
  threshold: number | null
}

export type TrainingLoadMaterializationStatus = {
  period: AnalyticsPeriod
  expected_days: number
  persisted_days: number
  missing_dates: string[]
  stale_dates: string[]
  fresh: boolean
}

export type TrainingLoadBackfill = {
  synced_rows: number
  status: TrainingLoadMaterializationStatus
}

export type ZoneDistributionItem = {
  zone_key: string
  label: string
  duration_seconds: number
  percentage: number
  source_count: number
}

export type ZoneDistributionBucket = {
  period_start: string
  period_label: string
  total_duration_seconds: number
  items: ZoneDistributionItem[]
  seiler_three_zone: ZoneDistributionItem[]
}

export type LowIntensityCompliance = {
  target: Record<string, unknown>
  period_label: string | null
  low_percentage: number | null
  status: "below" | "within" | "above" | "unknown" | string
}

export type ZonePlannedActual = {
  zone_key: string
  label: string
  planned_duration_seconds: number
  planned_percentage: number
  actual_duration_seconds: number
  actual_percentage: number
  diff_percentage: number
}

export type ZoneDistribution = {
  period: AnalyticsPeriod
  granularity: "week" | "month" | string
  zones: Zones
  actual_hr: ZoneDistributionItem[]
  actual_pace: ZoneDistributionItem[]
  actual_rpe: ZoneDistributionItem[]
  actual_five_zone: ZoneDistributionItem[]
  seiler_three_zone: ZoneDistributionItem[]
  planned_five_zone: ZoneDistributionItem[]
  planned_vs_actual: ZonePlannedActual[]
  time_buckets: ZoneDistributionBucket[]
  low_intensity_compliance: LowIntensityCompliance | null
  metadata: Record<string, unknown>
}

export type PerformanceResult = {
  id: number
  user_id: number
  activity_id: number | null
  result_type: "race" | "time_trial" | string
  name: string
  result_date: string
  distance_km: number
  duration_seconds: number
  pace_seconds_per_km: number
  source: string
  terrain: string
  weather: string | null
  elevation_gain_m: number | null
  temperature_c: number | null
  is_noisy: boolean
  noisy_reasons: string[]
  age_days: number | null
  estimated_vdot: CalculationResult | null
  notes: string | null
  created_at: string
  updated_at: string
}

export type PerformanceThresholdTrendPoint = {
  result_id: number
  result_date: string
  distance_km: number
  duration_seconds: number
  threshold_pace_seconds_per_km: number
  source: string
  confidence: string
}

export type PerformancePaceZone = {
  zone_key: string
  label: string | null
  lower_value: number | null
  upper_value: number | null
  unit: string
  method: string
  confidence: string
  source_reference: string | null
}

export type PerformanceVdot = {
  estimate: CalculationResult | null
  source: PerformanceResult | null
  confidence: string
  warnings: string[]
  threshold_trend: PerformanceThresholdTrendPoint[]
  pace_zones: PerformancePaceZone[]
}

export type PerformancePrediction = {
  target_distance_km: number
  label: string
  predicted_duration_seconds: number | null
  predicted_pace_seconds_per_km: number | null
  source_result_id: number | null
  source_result_name: string | null
  source_distance_km: number | null
  source_duration_seconds: number | null
  method: string
  confidence: string
  extrapolation_ratio: number | null
  extrapolation_limited: boolean
  noisy: boolean
  warnings: string[]
  source_reference: string
}

export type PerformancePb = {
  target_distance_km: number
  label: string
  result_id: number
  name: string
  result_type: string
  result_date: string
  distance_km: number
  duration_seconds: number
  normalized_duration_seconds: number
  pace_seconds_per_km: number
  estimated_vdot: CalculationResult | null
  is_noisy: boolean
  noisy_reasons: string[]
}

export type DashboardSummary = {
  generated_at: string
  today: string
  analytics: AnalyticsSummary
  active_plan: DashboardPlanSummary | null
  current_week: CurrentWeek
  weekly_snapshot: PlanAdherence | null
  today_workout: PlanWorkout | null
  next_workout: PlanWorkout | null
  profile_completeness: ProfileCompleteness
  safety: SafetyCheck
  readiness: DashboardReadiness
  alerts: DashboardAlert[]
  recommendations: DashboardRecommendationSummary | null
  pending_imports_count: number
  provider_count: number
  recent_activities: Activity[]
}

export type CalendarEvent = {
  id: string
  kind: "planned_workout" | "activity" | string
  date: string
  title: string
  status: string | null
  planned_workout_id: number | null
  linked_activity_id: number | null
  plan_id: number | null
  plan_title: string | null
  workout_type: string | null
  distance_km: number | null
  duration_seconds: number | null
  execution_score: PlanWorkoutExecutionScore | null
  workout: PlanWorkout | null
  activity: Activity | null
}

export type CalendarWarning = {
  severity: "info" | "warning" | "critical" | string
  title: string
  message: string
  date: string | null
  planned_workout_ids: number[]
}

export type CalendarSummary = {
  planned_workouts: number
  done_workouts: number
  missed_workouts: number
  skipped_workouts: number
  activities: number
  linked_activities: number
  unlinked_activities: number
  planned_distance_km: number
  activity_distance_km: number
}

export type CalendarResponse = {
  from_date: string
  to_date: string
  events: CalendarEvent[]
  warnings: CalendarWarning[]
  summary: CalendarSummary
}

export type TelegramLoginPayload = {
  id: string | number
  first_name?: string
  last_name?: string
  username?: string
  photo_url?: string
  auth_date: string | number
  hash: string
}

export type AuthToken = {
  access_token: string
  user: {
    id: number
    telegram_id: number | null
    username: string | null
    display_name: string
    is_demo: boolean
  }
}

let token = safeStorageGet("runforfan_token")

export const authConfig = {
  devLoginEnabled: DEV_LOGIN_ENABLED,
  telegramBotUsername: TELEGRAM_BOT_USERNAME,
}

export function hasAuthToken() {
  return Boolean(token)
}

export function clearAuthToken() {
  token = null
  safeStorageRemove("runforfan_token")
}

export function onAuthExpired(listener: () => void) {
  window.addEventListener(AUTH_EXPIRED_EVENT, listener)
  return () => window.removeEventListener(AUTH_EXPIRED_EVENT, listener)
}

function notifyAuthExpired() {
  window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT))
}

function storeAuthToken(data: AuthToken) {
  token = data.access_token
  safeStorageSet("runforfan_token", token)
  return data
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  })
  if (!response.ok) {
    const body = await response.text()
    if (response.status === 401 && !DEV_LOGIN_ENABLED) {
      clearAuthToken()
      notifyAuthExpired()
    }
    throw new Error(`${response.status}: ${body}`)
  }
  return response.json()
}

export async function devLogin() {
  if (!DEV_LOGIN_ENABLED) {
    if (token) return { access_token: token, user: null }
    throw new Error("Production login requires Telegram authentication")
  }
  const data = await request<AuthToken>("/auth/dev-login", { method: "POST", body: "{}" })
  return storeAuthToken(data)
}

export async function telegramLogin(payload: TelegramLoginPayload) {
  const data = await request<AuthToken>("/auth/telegram", {
    method: "POST",
    body: JSON.stringify({ ...payload, id: String(payload.id), auth_date: String(payload.auth_date) }),
  })
  return storeAuthToken(data)
}

export const api = {
  activities: () => request<Activity[]>("/activities"),
  activity: (id: number) => request<Activity>(`/activities/${id}`),
  createActivity: (payload: Record<string, unknown>) => request<Activity>("/activities", { method: "POST", body: JSON.stringify(payload) }),
  updateActivity: (id: number, payload: Record<string, unknown>) => request<Activity>(`/activities/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  activityValidation: (id: number) => request<ActivityValidation>(`/activities/${id}/validation`),
  imports: () => request<ImportBatch[]>("/imports"),
  uploadScreenshots: (files: File[]) => {
    const data = new FormData()
    files.forEach((file) => data.append("screenshots", file))
    return request<ImportUploadResult>("/imports/screenshots", { method: "POST", body: data })
  },
  confirmImport: (id: number) => request<ImportUploadResult>(`/imports/${id}/confirm`, { method: "POST", body: "{}" }),
  rejectImport: (id: number) => request<ImportUploadResult>(`/imports/${id}/reject`, { method: "POST", body: "{}" }),
  updateImportCandidate: (id: number, payload: Record<string, unknown>) => request<ImportUploadResult>(`/imports/${id}/candidate`, { method: "PATCH", body: JSON.stringify(payload) }),
  uploadCsv: (file: File, sourceApp = "csv") => {
    const data = new FormData()
    data.append("csv_file", file)
    data.append("source_app", sourceApp)
    return request<CsvImportResult>("/imports/csv", { method: "POST", body: data })
  },
  analytics: (params = "") => request<AnalyticsSummary>(`/analytics/summary${params}`),
  analyticsTimeseries: (params = "") => request<AnalyticsTimeseries>(`/analytics/timeseries${params}`),
  analyticsInsights: (params = "") => request<AnalyticsInsight[]>(`/analytics/insights${params}`),
  trainingLoadDaily: (params = "") => request<TrainingLoadDaily>(`/analytics/load/daily${params}`),
  trainingLoadWeekly: (params = "") => request<TrainingLoadWeekly>(`/analytics/load/weekly${params}`),
  trainingLoadFitnessFatigue: (params = "") => request<TrainingLoadFitnessFatigue>(`/analytics/load/fitness-fatigue${params}`),
  trainingLoadWarnings: (params = "") => request<TrainingLoadWarning[]>(`/analytics/load/warnings${params}`),
  trainingLoadMaterialization: (params = "") => request<TrainingLoadMaterializationStatus>(`/analytics/load/materialization${params}`),
  backfillTrainingLoad: (params = "") => request<TrainingLoadBackfill>(`/analytics/load/backfill${params}`, { method: "POST", body: "{}" }),
  zoneDistribution: (params = "") => request<ZoneDistribution>(`/analytics/zones/distribution${params}`),
  performanceResults: (params = "") => request<PerformanceResult[]>(`/performance/results${params}`),
  createPerformanceResult: (payload: Record<string, unknown>) => request<PerformanceResult>("/performance/results", { method: "POST", body: JSON.stringify(payload) }),
  performanceVdot: () => request<PerformanceVdot>("/performance/vdot"),
  performancePredictions: () => request<PerformancePrediction[]>("/performance/predictions"),
  performancePbs: () => request<PerformancePb[]>("/performance/pbs"),
  goals: () => request<RunningGoal[]>("/goals"),
  createGoal: (payload: Record<string, unknown>) => request<RunningGoal>("/goals", { method: "POST", body: JSON.stringify(payload) }),
  updateGoal: (id: number, payload: Record<string, unknown>) => request<RunningGoal>(`/goals/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  completeGoal: (id: number, payload: Record<string, unknown> = {}) => request<RunningGoal>(`/goals/${id}/complete`, { method: "POST", body: JSON.stringify(payload) }),
  deleteGoal: (id: number) => request<{ deleted: boolean; id: number }>(`/goals/${id}`, { method: "DELETE" }),
  dashboardSummary: () => request<DashboardSummary>("/dashboard/summary"),
  calendar: (fromDate: string, toDate: string) => request<CalendarResponse>(`/calendar?from=${fromDate}&to=${toDate}`),
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
  replaceRpeZones: (payload: ZoneWrite[]) => request<Zones>("/zones/rpe", { method: "PUT", body: JSON.stringify(payload) }),
  plans: () => request<Plan[]>("/planning/plans"),
  currentWeek: () => request<CurrentWeek>("/planning/current-week"),
  plan: (id: number) => request<Plan>(`/planning/plans/${id}`),
  planWeeks: (id: number) => request<PlanWeekSummary[]>(`/planning/plans/${id}/weeks`),
  planAdherence: (id: number) => request<{ adherence: PlanAdherence; weekly_adherence: PlanWeeklyAdherence[] }>(`/planning/plans/${id}/adherence`),
  planRecommendations: (id: number) => request<PlanRecommendations>(`/planning/plans/${id}/recommendations`),
  previewPlanRecommendations: (id: number) => request<PlanRecommendationPreview>(`/planning/plans/${id}/recommendations/preview`, { method: "POST", body: "{}" }),
  applyPlanRecommendations: (id: number, changes: PlanRecommendationChange[]) => request<PlanRecommendationApplyResult>(`/planning/plans/${id}/recommendations/apply`, { method: "POST", body: JSON.stringify({ changes }) }),
  planRecommendationAudit: (id: number) => request<PlanRecommendationAudit[]>(`/planning/plans/${id}/recommendations/audit`),
  planVersions: (id: number) => request<PlanVersion[]>(`/planning/plans/${id}/versions`),
  activatePlan: (id: number) => request<Plan>(`/planning/plans/${id}/activate`, { method: "POST", body: "{}" }),
  updatePlan: (id: number, payload: Record<string, unknown>) => request<Plan>(`/planning/plans/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  duplicatePlan: (id: number) => request<Plan>(`/planning/plans/${id}/duplicate`, { method: "POST", body: "{}" }),
  deletePlan: (id: number) => request<{ deleted: boolean; id: number }>(`/planning/plans/${id}`, { method: "DELETE" }),
  workout: (id: number) => request<PlanWorkout>(`/planning/workouts/${id}`),
  completeWorkout: (id: number, payload: Record<string, unknown>) => request<PlanWorkout>(`/planning/workouts/${id}/complete`, { method: "POST", body: JSON.stringify(payload) }),
  updatePlanWorkout: (id: number, payload: Record<string, unknown>) => request<PlanWorkout>(`/planning/workouts/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  workoutFeedback: (id: number) => request<PlanWorkoutFeedback | null>(`/planning/workouts/${id}/feedback`),
  patchWorkoutFeedback: (id: number, payload: Record<string, unknown>) => request<PlanWorkoutFeedback>(`/planning/workouts/${id}/feedback`, { method: "PATCH", body: JSON.stringify(payload) }),
  saveWorkoutFeedback: (id: number, payload: Record<string, unknown>) => request<PlanWorkoutFeedback>(`/planning/workouts/${id}/feedback`, { method: "PUT", body: JSON.stringify(payload) }),
  workoutMatchCandidates: (id: number) => request<PlanActivityMatchCandidate[]>(`/planning/workouts/${id}/match-candidates`),
  activityMatchCandidates: (id: number, activeOnly = false) => request<PlanWorkoutMatchCandidate[]>(`/planning/activities/${id}/match-candidates?active_only=${activeOnly}`),
  linkPlanWorkoutActivity: (workoutId: number, activityId: number) => request<PlanWorkout>(`/planning/workouts/${workoutId}/link-activity`, { method: "POST", body: JSON.stringify({ activity_id: activityId }) }),
  attachWorkoutActivity: (workoutId: number, activityId: number) => request<PlanWorkout>(`/planning/workouts/${workoutId}/attach-activity`, { method: "POST", body: JSON.stringify({ activity_id: activityId }) }),
  providers: () => request<LlmProvider[]>("/settings/llm-providers"),
  createProvider: (payload: Record<string, unknown>) => request<LlmProvider>("/settings/llm-providers", { method: "POST", body: JSON.stringify(payload) }),
  updateProvider: (id: number, payload: Record<string, unknown>) => request<LlmProvider>(`/settings/llm-providers/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  setDefaultProvider: (id: number) => request<LlmProvider>(`/settings/llm-providers/${id}/default`, { method: "POST", body: "{}" }),
  testProvider: (id: number) => request<LlmProviderTest>(`/settings/llm-providers/${id}/test`, { method: "POST", body: "{}" }),
  deleteProvider: (id: number) => request(`/settings/llm-providers/${id}`, { method: "DELETE" }),
  integrations: () => request<Integration[]>("/settings/integrations"),
  exportData: () => request<Record<string, unknown>>("/export"),
  deleteAccountData: (confirmation: "DELETE") => request<{ deleted: boolean; counts: Record<string, number>; audit_id: number | null }>("/account/data", { method: "DELETE", body: JSON.stringify({ confirmation }) }),
  auditLog: (limit = 100, offset = 0) => request<AuditLogEntry[]>(`/audit-log?limit=${limit}&offset=${offset}`),
  previewPlan: (payload: Record<string, unknown>) => request<PlanBuilderPreview>("/planning/preview", { method: "POST", body: JSON.stringify(payload) }),
  generatePlan: (payload: Record<string, unknown>) => request<Plan>("/planning/generate", { method: "POST", body: JSON.stringify(payload) }),
}
