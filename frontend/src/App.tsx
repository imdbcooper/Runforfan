import { Activity, BatteryCharging, Bot, CalendarDays, ChartSpline, Goal, HeartPulse, Menu, Moon, Settings, Shield, Trophy, Upload, X, Zap } from "lucide-react"
import { type FormEvent, type ReactNode, useEffect, useRef, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardHeader, CardTitle } from "@/components/ui/card"
import { CalculationExplainer } from "@/components/ui/calculation-explainer"
import { DataTable, type DataTableColumn } from "@/components/ui/data-table"
import { Input } from "@/components/ui/input"
import { MetricCard } from "@/components/ui/metric-card"
import { Select } from "@/components/ui/select"
import { api, type Activity as ActivityType, type AnalyticsInsight, type AnalyticsSummary, type AnalyticsTimeseries, type AthleteMeasurement, type AthleteProfile, type AuditLogEntry, type CalendarEvent, type CalendarResponse, type CsvImportResult, type DashboardSummary, devLogin, type ImportBatch, type ImportUploadResult, type Integration, type LlmProvider, type LlmProviderTest, type PerformancePaceZone, type PerformancePb, type PerformancePrediction, type PerformanceResult, type PerformanceVdot, type Plan, type PlanActivityMatchCandidate, type PlanBuilderPreview, type PlanRecommendationAudit, type PlanRecommendationPreview, type PlanRecommendations, type PlanVersion, type PlanWeekSummary, type PlanWorkout, type PlanWorkoutMatchCandidate, type ProfileCompleteness, type RunningGoal, type SafetyCheck, type TrainingLoadDaily, type TrainingLoadDailyPoint, type TrainingLoadFitnessFatigue, type TrainingLoadMaterializationStatus, type TrainingLoadWarning, type TrainingLoadWeekly, type Zone, type ZoneDistribution, type ZoneDistributionItem, type ZonePlannedActual, type Zones } from "@/lib/api"
import { cn } from "@/lib/utils"

type Page = "overview" | "activities" | "imports" | "calendar" | "analytics" | "load" | "zones" | "performance" | "goals" | "profile" | "planning" | "settings"
type FeedbackDraft = { rpe: string; soreness_0_10: string; fatigue: string; pain: boolean; pain_level: string; sleep_quality_0_10: string; sleep_quality: string; pain_notes: string; user_notes: string; weather_notes: string; notes: string }
type CompletionDraft = FeedbackDraft & { actual_distance_km: string; actual_duration_minutes: string; average_heart_rate_bpm: string; completed_at: string }
type CalendarMatchState =
  | { mode: "workout_to_activity"; candidates: PlanActivityMatchCandidate[] }
  | { mode: "activity_to_workout"; candidates: PlanWorkoutMatchCandidate[] }

type CalendarDayProps = {
  day: string
  events: CalendarEvent[]
  load: number
  maxLoad: number
  busyEvent: string
  loadingMatchEvent: string
  matchesByEvent: Record<string, CalendarMatchState>
  matchErrors: Record<string, string>
  rescheduleDrafts: Record<string, string>
  onFindMatches: (event: CalendarEvent) => Promise<void>
  onLinkMatch: (event: CalendarEvent, workoutId: number, activityId: number) => Promise<void>
  onReschedule: (event: CalendarEvent, scheduledDate: string) => Promise<void>
  onRescheduleDraft: (eventId: string, value: string) => void
  onUpdate: (event: CalendarEvent, status: string) => Promise<void>
}

type CalendarEventCardProps = Omit<CalendarDayProps, "day" | "events" | "load" | "maxLoad"> & {
  event: CalendarEvent
}

const SUPPORT_WORKOUT_TYPES = new Set(["strength", "ofp", "mobility", "prehab", "core", "cross_training"])
const WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

const nav = [
  ["overview", "Dashboard", Zap],
  ["activities", "Activities", Activity],
  ["imports", "Imports", Upload],
  ["calendar", "Calendar", CalendarDays],
  ["analytics", "Analytics", ChartSpline],
  ["load", "Load & Recovery", BatteryCharging],
  ["zones", "Zones Analytics", Shield],
  ["performance", "Performance", Trophy],
  ["goals", "Goals & races", Goal],
  ["profile", "Profile & zones", HeartPulse],
  ["planning", "Plans", Goal],
  ["settings", "Settings & data", Settings],
] as const

function formatPace(seconds?: number | null) {
  if (!seconds) return "--"
  return `${Math.floor(seconds / 60)}'${String(seconds % 60).padStart(2, "0")}`
}

function formatDistance(km?: number | null) {
  return km ? `${km.toFixed(2)} км` : "--"
}

function formatChangeValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "--"
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(1)
  if (typeof value === "string") return value
  return JSON.stringify(value)
}

function formatDuration(seconds?: number | null) {
  if (!seconds) return "--"
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const rest = seconds % 60
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}` : `${minutes}:${String(rest).padStart(2, "0")}`
}

function isSupportWorkoutType(type?: string | null) {
  return SUPPORT_WORKOUT_TYPES.has(type || "")
}

function formatWorkoutTarget(target: { distance_km?: number | null; duration_seconds?: number | null; workout_type?: string | null }) {
  const duration = formatDuration(target.duration_seconds)
  const distance = formatDistance(target.distance_km)
  if (isSupportWorkoutType(target.workout_type)) return duration !== "--" ? duration : "support"
  if (distance !== "--" && duration !== "--") return `${distance} · ${duration}`
  if (distance !== "--") return distance
  return duration
}

function formatWorkoutActual(workout: { actual_distance_km?: number | null; actual_duration_seconds?: number | null; workout_type?: string | null }) {
  const duration = formatDuration(workout.actual_duration_seconds)
  const distance = formatDistance(workout.actual_distance_km)
  if (isSupportWorkoutType(workout.workout_type)) return duration !== "--" ? duration : "--"
  if (distance !== "--" && duration !== "--") return `${distance} · ${duration}`
  if (distance !== "--") return distance
  return duration
}

function calendarEventLoad(event: CalendarEvent) {
  if (event.distance_km) return event.distance_km
  if (event.duration_seconds) return Math.max(1, event.duration_seconds / 600)
  return 1
}

function numberOrNull(value: FormDataEntryValue | null) {
  if (value === null || value === "") return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function stringOrNull(value: FormDataEntryValue | null) {
  return value === null || value === "" ? null : String(value)
}

function apiErrorMessage(caught: unknown, fallback: string) {
  if (!(caught instanceof Error)) return fallback
  const body = caught.message.replace(/^\d+:\s*/, "")
  try {
    const parsed = JSON.parse(body) as { detail?: unknown; message?: unknown }
    if (typeof parsed.message === "string") return parsed.message
    if (typeof parsed.detail === "string") return parsed.detail
  } catch {
    return caught.message || fallback
  }
  return caught.message || fallback
}

function csvNumbers(value: FormDataEntryValue | null) {
  return String(value || "").split(",").map((item) => item.trim()).filter(Boolean).map((item) => Number(item)).filter((item) => Number.isFinite(item))
}

function planBuilderPayload(form: HTMLFormElement, activate = false) {
  const data = new FormData(form)
  const targetTimeMinutes = numberOrNull(data.get("target_time_minutes"))
  const recentRaceTimeMinutes = numberOrNull(data.get("recent_race_time_minutes"))
  return {
    title: stringOrNull(data.get("title")) || "Марафонская программа",
    goal_type: stringOrNull(data.get("goal_type")) || "marathon",
    race_distance_km: numberOrNull(data.get("race_distance_km")) || 42.2,
    target_date: stringOrNull(data.get("target_date")),
    plan_length_weeks: numberOrNull(data.get("plan_length_weeks")),
    target_time_seconds: targetTimeMinutes ? Math.round(targetTimeMinutes * 60) : null,
    priority: stringOrNull(data.get("priority")) || "b",
    aggressiveness: stringOrNull(data.get("aggressiveness")) || "auto",
    available_days_per_week: numberOrNull(data.get("available_days_per_week")) || 4,
    current_weekly_distance_km: numberOrNull(data.get("current_weekly_distance_km")),
    longest_recent_run_km: numberOrNull(data.get("longest_recent_run_km")),
    recent_race_distance_km: numberOrNull(data.get("recent_race_distance_km")),
    recent_race_time_seconds: recentRaceTimeMinutes ? Math.round(recentRaceTimeMinutes * 60) : null,
    preferred_weekdays: csvNumbers(data.get("preferred_weekdays")),
    time_budget_minutes_per_week: numberOrNull(data.get("time_budget_minutes_per_week")),
    intensity_mode: stringOrNull(data.get("intensity_mode")) || "mixed",
    injury: data.get("injury") === "on",
    no_hard_workouts: data.get("no_hard_workouts") === "on",
    max_long_run_km: numberOrNull(data.get("max_long_run_km")),
    max_long_run_duration_minutes: numberOrNull(data.get("max_long_run_duration_minutes")),
    terrain: stringOrNull(data.get("terrain")),
    include_strength: data.get("include_strength") === "on",
    strength_sessions_per_week: numberOrNull(data.get("strength_sessions_per_week")),
    include_mobility: data.get("include_mobility") === "on",
    mobility_sessions_per_week: numberOrNull(data.get("mobility_sessions_per_week")),
    strength_equipment: stringOrNull(data.get("strength_equipment")),
    activate,
  }
}

function feedbackDraftFromWorkout(workout: PlanWorkout): FeedbackDraft {
  const soreness = workout.feedback?.soreness_0_10 ?? workout.feedback?.fatigue
  const sleep = workout.feedback?.sleep_quality_0_10 ?? workout.feedback?.sleep_quality
  const userNotes = workout.feedback?.user_notes || workout.feedback?.notes || ""
  return {
    rpe: workout.feedback?.rpe?.toString() || "",
    soreness_0_10: soreness?.toString() || "",
    fatigue: soreness?.toString() || "",
    pain: workout.feedback?.pain || false,
    pain_level: workout.feedback?.pain_level?.toString() || "",
    sleep_quality_0_10: sleep?.toString() || "",
    sleep_quality: sleep?.toString() || "",
    pain_notes: workout.feedback?.pain_notes || "",
    user_notes: userNotes,
    weather_notes: workout.feedback?.weather_notes || "",
    notes: userNotes,
  }
}

function completionDraftFromWorkout(workout: PlanWorkout): CompletionDraft {
  return {
    ...feedbackDraftFromWorkout(workout),
    actual_distance_km: workout.actual_distance_km?.toString() || workout.distance_km?.toString() || "",
    actual_duration_minutes: workout.actual_duration_seconds ? String(Math.round(workout.actual_duration_seconds / 60)) : workout.duration_seconds ? String(Math.round(workout.duration_seconds / 60)) : "",
    average_heart_rate_bpm: "",
    completed_at: "",
  }
}

function feedbackNumber(value: string) {
  if (value.trim() === "") return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : NaN
}

function feedbackValidationError(draft: FeedbackDraft) {
  const fields: [keyof FeedbackDraft, string][] = [["rpe", "RPE"], ["soreness_0_10", "soreness"], ["pain_level", "pain"], ["sleep_quality_0_10", "sleep"]]
  for (const [field, label] of fields) {
    const value = feedbackNumber(String(draft[field]))
    if (value !== null && (!Number.isFinite(value) || !Number.isInteger(value) || value < 0 || value > 10)) return `${label} должен быть целым числом 0-10`
  }
  return ""
}

function feedbackPayload(draft: FeedbackDraft) {
  const soreness = feedbackNumber(draft.soreness_0_10 || draft.fatigue)
  const sleep = feedbackNumber(draft.sleep_quality_0_10 || draft.sleep_quality)
  const userNotes = draft.user_notes || draft.notes || null
  return {
    rpe: feedbackNumber(draft.rpe),
    soreness_0_10: soreness,
    fatigue: soreness,
    pain: draft.pain,
    pain_level: feedbackNumber(draft.pain_level),
    sleep_quality_0_10: sleep,
    sleep_quality: sleep,
    pain_notes: draft.pain_notes || null,
    user_notes: userNotes,
    weather_notes: draft.weather_notes || null,
    notes: userNotes,
  }
}

function completionValidationError(draft: CompletionDraft) {
  const distance = feedbackNumber(draft.actual_distance_km)
  const duration = feedbackNumber(draft.actual_duration_minutes)
  if (distance !== null && (!Number.isFinite(distance) || distance < 0 || distance > 250)) return "Фактическая дистанция должна быть 0-250 км"
  if (duration === null || !Number.isFinite(duration) || duration <= 0 || duration > 2880) return "Фактическое время должно быть 1-2880 минут"
  const hr = feedbackNumber(draft.average_heart_rate_bpm)
  if (hr !== null && (!Number.isFinite(hr) || !Number.isInteger(hr) || hr < 30 || hr > 240)) return "Средний HR должен быть целым числом 30-240"
  return feedbackValidationError(draft)
}

function completionPayload(draft: CompletionDraft) {
  const distance = feedbackNumber(draft.actual_distance_km)
  const duration = feedbackNumber(draft.actual_duration_minutes)
  return {
    actual_distance_km: distance,
    actual_duration_seconds: duration === null ? null : Math.round(duration * 60),
    completed_at: draft.completed_at ? new Date(draft.completed_at).toISOString() : null,
    average_heart_rate_bpm: feedbackNumber(draft.average_heart_rate_bpm),
    ...feedbackPayload(draft),
  }
}

function formatZoneValue(zone: Zone, value: number | null) {
  if (value === null) return "--"
  if (zone.unit === "seconds_per_km") return `${formatPace(Math.round(value))}/км`
  if (zone.unit === "bpm") return `${Math.round(value)} bpm`
  return `${value}`
}

function formatZoneRange(zone: Zone) {
  return `${formatZoneValue(zone, zone.lower_value)} - ${formatZoneValue(zone, zone.upper_value)}`
}

function missingLabel(field: string) {
  const labels: Record<string, string> = {
    date_of_birth: "дата рождения",
    resting_heart_rate_bpm: "пульс покоя",
    max_heart_rate_bpm_or_birthdate: "HRmax или дата рождения",
    lactate_threshold_pace_seconds_per_km: "пороговый темп",
    lactate_threshold_hr_bpm: "пороговый пульс",
    weight_kg: "вес",
    height_cm: "рост",
    preferred_weekdays: "тренировочные дни",
    max_run_duration_minutes: "макс. длительность",
  }
  return labels[field] || field
}

function weekdayLabel(value?: number | null) {
  if (!value) return "--"
  return WEEKDAY_LABELS[value - 1] || String(value)
}

function weekdayListLabel(values?: number[] | null) {
  return values?.length ? values.map(weekdayLabel).join(", ") : "--"
}

function measurementValueLabel(measurement: AthleteMeasurement) {
  const value = measurement.value_numeric
  if (value === null || value === undefined) return "--"
  if (measurement.measurement_type === "weight") return `${value.toFixed(1)} кг`
  if (measurement.measurement_type === "vo2max") return `${value.toFixed(1)} ml/kg/min`
  if (["resting_hr", "max_hr", "lactate_threshold"].includes(measurement.measurement_type)) return `${Math.round(value)} bpm`
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}

function workoutBlockSummary(activity: ActivityType) {
  const workBlocks = activity.workout_blocks?.filter((block) => block.block_type === "work") || []
  if (!workBlocks.length) return null
  const distance = workBlocks[0]?.distance_km
  const sameDistance = distance && workBlocks.every((block) => block.distance_km === distance)
  return sameDistance ? `${workBlocks.length} x ${distance.toFixed(2)} км` : `${workBlocks.length} рабочих блока`
}

function activityMetricLabel(key: string) {
  const labels: Record<string, string> = {
    average_pace_seconds_per_km: "pace",
    average_speed_kmh: "speed",
    duration_minutes: "minutes",
    estimated_energy_kcal: "energy est.",
    pace_variability_seconds_per_km: "variability",
    training_load_proxy: "load",
    vertical_balance_m: "vertical",
    work_block_count: "work blocks",
    work_block_distance_km: "work km",
    work_block_duration_seconds: "work time",
  }
  return labels[key] || key.replace(/_/g, " ")
}

function formatActivityMetric(metric: ActivityType["derived_metrics"][number]) {
  if (metric.unit === "seconds_per_km") return `${formatPace(metric.metric_value)}/км`
  if (metric.unit === "seconds") return formatDuration(metric.metric_value)
  if (metric.unit === "minutes") return `${metric.metric_value.toFixed(1)} min`
  if (metric.unit === "kcal") return `${metric.metric_value.toFixed(0)} kcal`
  if (metric.unit === "kmh") return `${metric.metric_value.toFixed(2)} km/h`
  if (metric.unit === "km") return `${metric.metric_value.toFixed(2)} km`
  if (metric.unit === "count") return String(Math.round(metric.metric_value))
  return `${Number.isInteger(metric.metric_value) ? Math.round(metric.metric_value) : metric.metric_value.toFixed(1)} ${metric.unit}`
}

function primaryActivityMetrics(activity: ActivityType) {
  const priority = ["average_pace_seconds_per_km", "average_speed_kmh", "training_load_proxy", "estimated_energy_kcal", "pace_variability_seconds_per_km"]
  const metrics = activity.derived_metrics || []
  return priority.map((key) => metrics.find((metric) => metric.metric_key === key)).filter(Boolean) as ActivityType["derived_metrics"]
}

function loadMethodLabel(method: string) {
  const labels: Record<string, string> = {
    aerobic_training_stress: "ATS",
    hr_trimp: "HR TRIMP",
    mixed: "mixed",
    pace_based_fallback: "pace fallback",
    srpe: "sRPE",
    support_duration_fallback: "support duration",
    unavailable: "unavailable",
  }
  return labels[method] || method.replace(/_/g, " ")
}

function App() {
  const [page, setPage] = useState<Page>("overview")
  const [mobileOpen, setMobileOpen] = useState(false)
  const [activities, setActivities] = useState<ActivityType[]>([])
  const [analytics, setAnalytics] = useState<AnalyticsSummary | null>(null)
  const [dashboard, setDashboard] = useState<DashboardSummary | null>(null)
  const [providers, setProviders] = useState<LlmProvider[]>([])
  const [profile, setProfile] = useState<AthleteProfile | null>(null)
  const [completeness, setCompleteness] = useState<ProfileCompleteness | null>(null)
  const [safety, setSafety] = useState<SafetyCheck | null>(null)
  const [zones, setZones] = useState<Zones | null>(null)
  const [measurements, setMeasurements] = useState<AthleteMeasurement[]>([])
  const [status, setStatus] = useState("LOADING")

  async function refreshGlobal() {
    try {
      await devLogin()
      const [nextActivities, nextAnalytics, nextDashboard, nextProviders] = await Promise.all([
        api.activities(),
        api.analytics(),
        api.dashboardSummary(),
        api.providers(),
      ])
      setActivities(nextActivities)
      setAnalytics(nextAnalytics)
      setDashboard(nextDashboard)
      setProviders(nextProviders)
      setStatus("DEMO USER")
    } catch (error) {
      setStatus("API ERROR")
      console.error(error)
    }
  }

  async function refreshProfileData() {
    try {
      await devLogin()
      const nextProfile = await api.profile()
      const [nextCompleteness, nextSafety, nextZones, nextMeasurements] = await Promise.all([
        api.profileCompleteness(),
        api.safetyCheck(),
        api.zones(),
        api.measurements(50, 0),
      ])
      setProfile(nextProfile)
      setCompleteness(nextCompleteness)
      setSafety(nextSafety)
      setZones(nextZones)
      setMeasurements(nextMeasurements)
      setStatus("DEMO USER")
    } catch (error) {
      setStatus("API ERROR")
      console.error(error)
    }
  }

  useEffect(() => { void refreshGlobal() }, [])
  useEffect(() => {
    if (page === "profile") void refreshProfileData()
  }, [page])

  return (
    <div className="min-h-screen bg-[#090909] text-zinc-100">
      <div className="grid min-h-screen lg:grid-cols-[14rem_1fr]">
        <Sidebar page={page} setPage={setPage} className="hidden lg:block" />
        {mobileOpen && <>
          <button aria-label="Close menu overlay" className="fixed inset-0 z-40 bg-black/70" onClick={() => setMobileOpen(false)} />
          <aside className="fixed inset-y-0 left-0 z-50 w-56 border-r border-zinc-800 bg-[#111] lg:hidden">
            <div className="flex h-12 items-center justify-end border-b border-zinc-800 px-2"><Button variant="ghost" size="icon" onClick={() => setMobileOpen(false)}><X /></Button></div>
            <Sidebar page={page} setPage={(next) => { setPage(next); setMobileOpen(false) }} />
          </aside>
        </>}

        <div className="min-w-0 max-w-full">
          <Topbar status={status} onMenu={() => setMobileOpen(true)} />
          <main className="min-w-0 max-w-full overflow-hidden p-4 md:p-6">
            {page === "overview" && <Overview activities={activities} analytics={analytics} dashboard={dashboard} providers={providers} onImport={() => setPage("imports")} onPlans={() => setPage("planning")} />}
            {page === "activities" && <Activities activities={activities} onImport={() => setPage("imports")} />}
            {page === "imports" && <ImportsPage onChanged={refreshGlobal} />}
            {page === "calendar" && <CalendarPage onImport={() => setPage("imports")} onPlans={() => setPage("planning")} />}
            {page === "analytics" && <Analytics analytics={analytics} />}
            {page === "load" && <TrainingLoadRecovery />}
            {page === "zones" && <ZonesAnalytics />}
            {page === "performance" && <PerformanceAnalytics />}
            {page === "goals" && <GoalsRaces />}
            {page === "profile" && <ProfileZones profile={profile} completeness={completeness} safety={safety} zones={zones} measurements={measurements} onChanged={refreshProfileData} />}
            {page === "planning" && <Planning />}
            {page === "settings" && <SettingsPage providers={providers} onChanged={refreshGlobal} />}
          </main>
        </div>
      </div>
    </div>
  )
}

function Sidebar({ page, setPage, className }: { page: Page; setPage: (page: Page) => void; className?: string }) {
  return <div className={cn("sticky top-0 h-screen border-r border-zinc-800 bg-[#111] text-zinc-300", className)}>
    <div className="border-b border-zinc-800 px-3 py-3">
      <p className="font-mono text-[10px] uppercase tracking-[0.24em] text-zinc-500">RUNFORFAN · ADMIN</p>
      <h1 className="mt-1 text-sm font-semibold text-white">Training Lab</h1>
    </div>
    <nav className="space-y-1 p-2">
      {nav.map(([key, label, Icon]) => {
        const active = page === key
        return <button key={key} onClick={() => setPage(key)} className={cn("relative flex h-7 w-full items-center gap-2 rounded-md px-2 text-left text-xs font-medium transition-colors", active ? "bg-zinc-800 text-white before:absolute before:left-0 before:top-1 before:h-5 before:w-0.5 before:bg-orange-400" : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-100")}><Icon className="h-4 w-4" />{label}</button>
      })}
    </nav>
    <div className="mt-4 border-t border-zinc-800 p-2">
      <div className="flex h-7 items-center gap-2 rounded-md px-2 text-xs text-zinc-500"><Shield className="h-4 w-4" /> Telegram later</div>
      <div className="flex h-7 items-center gap-2 rounded-md px-2 text-xs text-zinc-500"><Bot className="h-4 w-4" /> User LLM keys</div>
    </div>
  </div>
}

function Topbar({ status, onMenu }: { status: string; onMenu: () => void }) {
  return <header className="sticky top-0 z-30 flex h-12 items-center justify-between border-b border-zinc-800 bg-[#090909]/95 px-3 backdrop-blur">
    <div className="flex items-center gap-2">
      <Button variant="ghost" size="icon" className="lg:hidden" onClick={onMenu}><Menu /></Button>
      <p className="font-mono text-[10px] uppercase tracking-[0.24em] text-zinc-500">RUNFORFAN · ADMIN</p>
    </div>
    <div className="flex items-center gap-2">
      <Badge>{status}</Badge>
      <Button variant="secondary" size="sm">LEGACY</Button>
      <Button variant="ghost" size="icon"><Moon /></Button>
    </div>
  </header>
}

function Overview({ activities, analytics, dashboard, providers, onImport, onPlans }: { activities: ActivityType[]; analytics: AnalyticsSummary | null; dashboard: DashboardSummary | null; providers: LlmProvider[]; onImport: () => void; onPlans: () => void }) {
  const metrics = dashboard?.analytics || analytics
  const currentWeek = dashboard?.current_week
  const weekly = dashboard?.weekly_snapshot
  const plan = dashboard?.active_plan
  const recentActivities = dashboard?.recent_activities?.length ? dashboard.recent_activities : activities
  const readiness = dashboard?.readiness
  const providerCount = dashboard?.provider_count ?? providers.length
  return <div className="grid gap-4">
    <div className="grid min-w-0 gap-4 xl:grid-cols-[1fr_1.35fr]">
      <Card className="min-w-0 overflow-hidden p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-zinc-500">Dashboard</p>
            <h2 className="mt-2 text-lg font-semibold text-white">Today, plan and readiness</h2>
            <p className="mt-2 max-w-2xl text-xs leading-5 text-zinc-500">{currentWeek?.message || "Loading the active plan, weekly adherence and import alerts."}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge className={cn("border-zinc-700 bg-zinc-900 text-zinc-300", signalClass(readiness?.status))}>{readiness?.status || "loading"}</Badge>
            {plan ? <Badge>{plan.title}</Badge> : <Badge className="border-orange-400/30 bg-orange-400/10 text-orange-200">no active plan</Badge>}
          </div>
        </div>
        <div className="mt-4 flex flex-wrap gap-2"><Button size="sm" onClick={onImport}>+ Add screenshots</Button><Button size="sm" variant="secondary" onClick={onPlans}>Open plans</Button></div>
      </Card>
      <Card className="grid grid-cols-4 divide-x divide-zinc-800 p-3 max-md:grid-cols-2 max-md:divide-x-0 max-md:divide-y">
        <Stat label="activities" value={metrics?.activity_count ?? activities.length} />
        <Stat label="distance" value={Number(metrics?.total_distance_km || 0).toFixed(1)} suffix="km" />
        <Stat label="week done" value={`${Math.round((weekly?.completion_rate || 0) * 100)}%`} />
        <Stat label="providers" value={providerCount} />
      </Card>
    </div>

    <div className="grid min-w-0 gap-4 xl:grid-cols-[1.15fr_0.85fr]">
      <WorkoutFocus todayWorkout={dashboard?.today_workout || null} nextWorkout={dashboard?.next_workout || null} currentWeek={currentWeek || null} onPlans={onPlans} />
      <DashboardSignals dashboard={dashboard} />
    </div>

    {currentWeek ? <CurrentWeekCard currentWeek={currentWeek} onPlans={onPlans} /> : null}
    <Activities activities={recentActivities} compact onImport={onImport} />
  </div>
}

function signalClass(status?: string) {
  if (status === "risk" || status === "adjust" || status === "critical" || status === "at_risk" || status === "missed" || status === "strained" || status === "injured") return "border-rose-400/30 bg-rose-500/10 text-rose-200"
  if (status === "watch" || status === "warning" || status === "tired" || status === "below" || status === "above") return "border-orange-400/30 bg-orange-400/10 text-orange-200"
  if (status === "ok" || status === "active" || status === "done" || status === "on_track" || status === "completed" || status === "fresh" || status === "normal" || status === "within") return "border-zinc-700 bg-zinc-900 text-zinc-200"
  return "border-zinc-700 bg-zinc-900 text-zinc-400"
}

function formatDate(value?: string | null) {
  if (!value) return "--"
  return new Date(`${value}T00:00:00`).toLocaleDateString("ru-RU", { day: "2-digit", month: "short" })
}

function dateFromISO(value: string) {
  return new Date(`${value}T00:00:00`)
}

function toISODate(value: Date) {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`
}

function addDays(value: string, days: number) {
  const date = dateFromISO(value)
  date.setDate(date.getDate() + days)
  return toISODate(date)
}

function startOfWeekISO(value = toISODate(new Date())) {
  const date = dateFromISO(value)
  const weekday = (date.getDay() + 6) % 7
  date.setDate(date.getDate() - weekday)
  return toISODate(date)
}

function monthRangeISO(value = toISODate(new Date())) {
  const date = dateFromISO(value)
  const start = new Date(date.getFullYear(), date.getMonth(), 1)
  const end = new Date(date.getFullYear(), date.getMonth() + 1, 0)
  return [toISODate(start), toISODate(end)] as const
}

const MAX_CALENDAR_DAYS = 42

function calendarRangeDayCount(fromDate: string, toDate: string) {
  if (!fromDate || !toDate || fromDate > toDate) return 0
  let count = 0
  let cursor = fromDate
  while (cursor <= toDate && count <= MAX_CALENDAR_DAYS) {
    count += 1
    cursor = addDays(cursor, 1)
  }
  return cursor <= toDate ? MAX_CALENDAR_DAYS + 1 : count
}

function dateRange(fromDate: string, toDate: string) {
  const days: string[] = []
  let cursor = fromDate
  for (let index = 0; index < MAX_CALENDAR_DAYS && cursor <= toDate; index += 1) {
    days.push(cursor)
    cursor = addDays(cursor, 1)
  }
  return days
}

function WorkoutFocus({ todayWorkout, nextWorkout, currentWeek, onPlans }: { todayWorkout: PlanWorkout | null; nextWorkout: PlanWorkout | null; currentWeek: DashboardSummary["current_week"] | null; onPlans: () => void }) {
  const focus = todayWorkout || nextWorkout
  return <Card>
    <CardHeader><div><CardTitle>{todayWorkout ? "Today workout" : "Next workout"}</CardTitle><p className="text-xs text-zinc-500">{currentWeek ? `${formatDate(currentWeek.week_start)} - ${formatDate(currentWeek.week_end)}` : "Active plan focus"}</p></div>{focus ? <Badge className={signalClass(focus.status)}>{focus.status}</Badge> : null}</CardHeader>
    {focus ? <div className="grid gap-3 p-4 text-xs md:grid-cols-[1fr_auto] md:items-end">
      <div className="min-w-0">
        <p className="text-base font-semibold text-white">{focus.title}</p>
        <p className="mt-1 text-zinc-500">{formatDate(focus.scheduled_date)} · week {focus.week_index} · {focus.workout_type} · {formatWorkoutTarget(focus)}</p>
        <p className="mt-2 max-w-3xl leading-5 text-zinc-400">{focus.description || "No target description"}</p>
        {focus.execution_score?.flags?.length ? <p className="mt-2 text-orange-200">{focus.execution_score.flags.slice(0, 2).join(" · ")}</p> : null}
      </div>
      <div className="grid grid-cols-3 gap-2 md:w-64">
        <Stat label="score" value={focus.execution_score?.score === null || focus.execution_score?.score === undefined ? "--" : `${Math.round(focus.execution_score.score * 100)}%`} />
        <Stat label="risk" value={focus.execution_score?.subjective_risk || "--"} />
        <Stat label="actual" value={formatWorkoutActual(focus)} />
      </div>
    </div> : <div className="p-4 text-xs text-zinc-500"><p>No active workout is scheduled yet.</p><Button className="mt-3" size="sm" variant="secondary" onClick={onPlans}>Create or activate plan</Button></div>}
  </Card>
}

function DashboardSignals({ dashboard }: { dashboard: DashboardSummary | null }) {
  const alerts = dashboard?.alerts || []
  const factors = dashboard?.readiness.factors || []
  return <Card>
    <CardHeader><div><CardTitle>Readiness signals</CardTitle><p className="text-xs text-zinc-500">Profile, imports, feedback and coach alerts.</p></div><Badge className={signalClass(dashboard?.readiness.status)}>{dashboard?.readiness.status || "loading"}</Badge></CardHeader>
    <div className="grid gap-3 p-4 text-xs">
      <p className="leading-5 text-zinc-400">{dashboard?.readiness.message || "Summary is loading."}</p>
      {factors.length ? <div className="grid gap-1">{factors.map((factor) => <p key={factor} className="rounded-md border border-zinc-800 bg-zinc-950 px-3 py-2 text-zinc-300">{factor}</p>)}</div> : null}
      <div className="grid gap-2">
        {alerts.length ? alerts.map((alert) => <div key={`${alert.title}-${alert.message}`} className={cn("rounded-md border px-3 py-2", signalClass(alert.severity))}><p className="font-medium">{alert.title}</p><p className="mt-1 leading-5 text-zinc-300/90">{alert.message}</p></div>) : <p className="rounded-md border border-zinc-800 bg-zinc-950 px-3 py-2 text-zinc-500">No dashboard alerts.</p>}
      </div>
    </div>
  </Card>
}

function CurrentWeekCard({ currentWeek, onPlans }: { currentWeek: DashboardSummary["current_week"]; onPlans: () => void }) {
  const adherence = currentWeek.adherence
  return <Card>
    <CardHeader><div><CardTitle>Current week</CardTitle><p className="text-xs text-zinc-500">{currentWeek.plan_title || "No active plan"} · {formatDate(currentWeek.week_start)} - {formatDate(currentWeek.week_end)}</p></div><div className="flex items-center gap-2"><Badge className={signalClass(currentWeek.status)}>{currentWeek.status}</Badge><Button size="sm" variant="secondary" onClick={onPlans}>Plans</Button></div></CardHeader>
    <div className="grid gap-3 border-t border-zinc-800 p-4 text-xs md:grid-cols-4">
      <Stat label="workouts" value={adherence?.total_workouts ?? 0} />
      <Stat label="done" value={adherence?.done_workouts ?? 0} />
      <Stat label="planned" value={formatDistance(adherence?.planned_distance_km)} />
      <Stat label="actual" value={formatDistance(adherence?.completed_distance_km)} />
    </div>
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] text-left text-xs">
        <thead className="border-b border-zinc-800 text-[10px] uppercase tracking-[0.14em] text-zinc-500"><tr><th className="px-4 py-2">Workout</th><th>Date</th><th>Type</th><th>Plan</th><th>Actual</th><th>Score</th><th>Status</th></tr></thead>
        <tbody>{currentWeek.workouts.map((workout) => <tr key={workout.id} className="border-b border-zinc-900 last:border-0 align-top hover:bg-zinc-900/60"><td className="px-4 py-3 font-medium text-white">{workout.title}<div className="text-[11px] text-zinc-500">#{workout.id} · week {workout.week_index}</div></td><td>{formatDate(workout.scheduled_date)}</td><td>{workout.workout_type}<div className="text-[11px] text-zinc-500">{workout.intensity || "--"}</div></td><td>{formatWorkoutTarget(workout)}</td><td>{formatWorkoutActual(workout)}</td><td>{workout.execution_score?.score === null || workout.execution_score?.score === undefined ? "--" : `${Math.round(workout.execution_score.score * 100)}%`}<div className="text-[11px] text-zinc-500">{workout.execution_score?.subjective_risk || "--"}</div></td><td><Badge className={signalClass(workout.status)}>{workout.status}</Badge></td></tr>)}</tbody>
      </table>
      {!currentWeek.workouts.length && <p className="p-4 text-xs text-zinc-500">No workouts in the current calendar week.</p>}
    </div>
  </Card>
}

function Stat({ label, value, suffix }: { label: string; value: string | number; suffix?: string }) {
  return <div className="px-4 py-3 text-center"><strong className="block text-lg text-white">{value}{suffix ? ` ${suffix}` : ""}</strong><span className="font-mono text-[10px] uppercase tracking-[0.16em] text-zinc-500">{label}</span></div>
}

function Activities({ activities, compact = false, onImport }: { activities: ActivityType[]; compact?: boolean; onImport?: () => void }) {
  if (!compact) {
    const activityColumns: DataTableColumn<ActivityType>[] = [
      { key: "name", header: "Name", sortValue: (activity) => activity.started_at ? Date.parse(activity.started_at) : 0, cell: (activity) => {
        const summary = workoutBlockSummary(activity)
        return <div className="font-medium text-white">{activity.title}<div className="text-[11px] text-zinc-500">{activity.started_at ? new Date(activity.started_at).toLocaleString("ru-RU") : "без даты"}</div>{summary && <div className="mt-1 flex items-center gap-2"><Badge>interval</Badge><span className="text-[11px] text-orange-300">{summary}</span></div>}</div>
      } },
      { key: "distance", header: "Distance", sortValue: (activity) => activity.distance_km || 0, cell: (activity) => <>{formatDistance(activity.distance_km)}<div className="text-[11px] text-zinc-500">{formatDuration(activity.duration_seconds)}</div></> },
      { key: "pace", header: "Pace", sortValue: (activity) => activity.average_pace_seconds_per_km || 99999, cell: (activity) => {
        const derived = primaryActivityMetrics(activity)
        return <>{formatPace(activity.average_pace_seconds_per_km)}/км{derived.length ? <div className="mt-1 flex flex-wrap gap-1">{derived.slice(0, 2).map((metric) => <Badge key={metric.metric_key} className="border-zinc-700 bg-zinc-900 text-zinc-300">{activityMetricLabel(metric.metric_key)} {formatActivityMetric(metric)}</Badge>)}</div> : null}</>
      } },
      { key: "hr", header: "HR", sortValue: (activity) => activity.average_heart_rate_bpm || 0, cell: (activity) => activity.average_heart_rate_bpm || "--" },
      { key: "structure", header: "Structure", sortValue: (activity) => activity.workout_blocks?.length || activity.segments.length || 0, cell: (activity) => {
        const summary = workoutBlockSummary(activity)
        return <>{summary || `${activity.segments.length} km splits`}{activity.workout_blocks?.length ? <div className="mt-1 text-[11px] text-zinc-500">{activity.workout_blocks.length} blocks</div> : null}{activity.derived_metrics?.length ? <div className="mt-1 text-[11px] text-orange-300">{activity.derived_metrics.length} derived metrics</div> : null}</>
      } },
      { key: "id", header: "ID", sortValue: (activity) => activity.id, cell: (activity) => <span className="font-mono text-zinc-500">#{activity.id}</span> },
    ]
    return <Card>
      <CardHeader><div><CardTitle>Activities</CardTitle><p className="text-xs text-zinc-500">{activities.length} total · sortable, filterable, paginated</p></div><Button size="sm" onClick={onImport}>+ Import</Button></CardHeader>
      <DataTable
        rows={activities}
        columns={activityColumns}
        getRowKey={(activity) => activity.id}
        getSearchText={(activity) => `${activity.title} ${activity.id} ${activity.started_at || ""}`}
        filterPlaceholder="Filter by title, date, id"
        emptyState={<div className="flex flex-wrap items-center gap-3"><span>No activities match this filter.</span><Button size="sm" variant="secondary" onClick={onImport}>Import activity</Button></div>}
      />
      {activities.some((activity) => activity.workout_blocks?.length) && <div className="grid gap-3 border-t border-zinc-800 p-4 lg:grid-cols-2">
        {activities.filter((activity) => activity.workout_blocks?.length).map((activity) => <div key={`blocks-${activity.id}`} className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-3">
          <div className="mb-2 flex items-center justify-between gap-3"><div><p className="text-sm font-medium text-white">{activity.title}</p><p className="text-[11px] text-zinc-500">Интервальная структура</p></div><Badge>{workoutBlockSummary(activity) || "blocks"}</Badge></div>
          <div className="grid gap-1">{activity.workout_blocks.map((block) => <div key={block.id} className="grid grid-cols-[5rem_1fr_4rem_4rem] gap-2 rounded-md bg-zinc-900/60 px-2 py-1.5 text-[11px]"><span className={cn("font-medium", block.block_type === "work" ? "text-orange-300" : "text-zinc-400")}>{block.title}</span><span className="text-zinc-500">{formatDuration(block.duration_seconds)}</span><span>{formatDistance(block.distance_km)}</span><span>{formatPace(block.pace_seconds_per_km)}/км</span></div>)}</div>
        </div>)}
      </div>}
    </Card>
  }
  return <Card>
    <CardHeader><div><CardTitle>Activities</CardTitle><p className="text-xs text-zinc-500">{activities.length} total</p></div><Button size="sm" onClick={onImport}>+ Import</Button></CardHeader>
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-left text-xs">
        <thead className="border-b border-zinc-800 text-[10px] uppercase tracking-[0.14em] text-zinc-500"><tr><th className="px-4 py-2">Name</th><th>Distance</th><th>Pace</th><th>HR</th><th>Structure</th><th>ID</th></tr></thead>
        <tbody>{activities.slice(0, compact ? 6 : undefined).map((activity) => {
          const summary = workoutBlockSummary(activity)
          const derived = primaryActivityMetrics(activity)
          return <tr key={activity.id} className="border-b border-zinc-900 last:border-0 align-top hover:bg-zinc-900/60"><td className="px-4 py-3 font-medium text-white">{activity.title}<div className="text-[11px] text-zinc-500">{activity.started_at ? new Date(activity.started_at).toLocaleString("ru-RU") : "без даты"}</div>{summary && <div className="mt-1 flex items-center gap-2"><Badge>interval</Badge><span className="text-[11px] text-orange-300">{summary}</span></div>}</td><td>{formatDistance(activity.distance_km)}<div className="text-[11px] text-zinc-500">{formatDuration(activity.duration_seconds)}</div></td><td>{formatPace(activity.average_pace_seconds_per_km)}/км{derived.length ? <div className="mt-1 flex flex-wrap gap-1">{derived.slice(0, 2).map((metric) => <Badge key={metric.metric_key} className="border-zinc-700 bg-zinc-900 text-zinc-300">{activityMetricLabel(metric.metric_key)} {formatActivityMetric(metric)}</Badge>)}</div> : null}</td><td>{activity.average_heart_rate_bpm || "--"}</td><td>{summary || `${activity.segments.length} km splits`}{activity.workout_blocks?.length ? <div className="mt-1 text-[11px] text-zinc-500">{activity.workout_blocks.length} blocks</div> : null}{activity.derived_metrics?.length ? <div className="mt-1 text-[11px] text-orange-300">{activity.derived_metrics.length} derived metrics</div> : null}</td><td className="font-mono text-zinc-500">#{activity.id}</td></tr>
        })}</tbody>
      </table>
    </div>
    {!compact && activities.some((activity) => activity.workout_blocks?.length) && <div className="grid gap-3 border-t border-zinc-800 p-4 lg:grid-cols-2">
      {activities.filter((activity) => activity.workout_blocks?.length).map((activity) => <div key={`blocks-${activity.id}`} className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-3">
        <div className="mb-2 flex items-center justify-between gap-3"><div><p className="text-sm font-medium text-white">{activity.title}</p><p className="text-[11px] text-zinc-500">Интервальная структура</p></div><Badge>{workoutBlockSummary(activity) || "blocks"}</Badge></div>
        <div className="grid gap-1">{activity.workout_blocks.map((block) => <div key={block.id} className="grid grid-cols-[5rem_1fr_4rem_4rem] gap-2 rounded-md bg-zinc-900/60 px-2 py-1.5 text-[11px]"><span className={cn("font-medium", block.block_type === "work" ? "text-orange-300" : "text-zinc-400")}>{block.title}</span><span className="text-zinc-500">{formatDuration(block.duration_seconds)}</span><span>{formatDistance(block.distance_km)}</span><span>{formatPace(block.pace_seconds_per_km)}/км</span></div>)}</div>
      </div>)}
    </div>}
  </Card>
}

function ImportsPage({ onChanged }: { onChanged: () => Promise<void> }) {
  const [imports, setImports] = useState<ImportBatch[]>([])
  const [uploadResult, setUploadResult] = useState<ImportUploadResult | null>(null)
  const [csvResult, setCsvResult] = useState<CsvImportResult | null>(null)
  const [matchCandidates, setMatchCandidates] = useState<PlanWorkoutMatchCandidate[]>([])
  const [candidateError, setCandidateError] = useState("")
  const [linkError, setLinkError] = useState("")
  const [importHistoryError, setImportHistoryError] = useState("")
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState("Upload screenshots from the same workout. Up to 6 files per batch.")

  async function loadImports() {
    setImportHistoryError("")
    try {
      await devLogin()
      setImports(await api.imports())
    } catch (error) {
      console.error(error)
      setImportHistoryError("Не удалось загрузить историю импортов")
    }
  }

  async function loadCandidatesForResult(result: ImportUploadResult) {
    setMatchCandidates([])
    setCandidateError("")
    if (!result.created_activity_id || result.matched_workout_id) {
      return
    }
    try {
      setMatchCandidates(await api.activityMatchCandidates(result.created_activity_id, true))
    } catch (error) {
      console.error(error)
      setCandidateError("Не удалось загрузить кандидатов плана. Позже можно сопоставить вручную в Plans.")
    }
  }

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const input = form.elements.namedItem("screenshots") as HTMLInputElement | null
    const files = Array.from(input?.files || [])
    if (!files.length) {
      setMessage("Выберите хотя бы один скриншот.")
      return
    }
    if (files.length > 6) {
      setMessage("Загрузите не больше 6 скриншотов за один batch.")
      return
    }
    setBusy(true)
    setMessage("Recognition is running...")
    setMatchCandidates([])
    setCandidateError("")
    setLinkError("")
    try {
      await devLogin()
      const result = await api.uploadScreenshots(files)
      setUploadResult(result)
      setMessage(result.recognition_message || "Import completed")
      await loadCandidatesForResult(result)
      await loadImports()
      await onChanged()
      form.reset()
    } catch (error) {
      console.error(error)
      setMessage(error instanceof Error ? error.message : "Import failed")
    } finally {
      setBusy(false)
    }
  }

  async function uploadCsv(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const input = form.elements.namedItem("csv_file") as HTMLInputElement | null
    const file = input?.files?.[0]
    if (!file) {
      setMessage("Выберите CSV файл.")
      return
    }
    setBusy(true)
    setMessage("CSV import is running...")
    try {
      await devLogin()
      const result = await api.uploadCsv(file, stringOrNull(new FormData(form).get("source_app")) || "csv")
      setCsvResult(result)
      setMessage(result.recognition_message || "CSV import completed")
      await loadImports()
      await onChanged()
      form.reset()
    } catch (error) {
      console.error(error)
      setMessage(error instanceof Error ? error.message : "CSV import failed")
    } finally {
      setBusy(false)
    }
  }

  async function linkCandidate(candidate: PlanWorkoutMatchCandidate) {
    if (!uploadResult?.created_activity_id) return
    setBusy(true)
    setLinkError("")
    try {
      await api.linkPlanWorkoutActivity(candidate.workout.id, uploadResult.created_activity_id)
      setUploadResult({ ...uploadResult, matched_workout_id: candidate.workout.id, match_status: "manual", auto_matched: false })
      setMatchCandidates([])
      await loadImports()
      await onChanged()
    } catch (error) {
      console.error(error)
      setLinkError("Не удалось привязать workout. Обновите candidates или сопоставьте из Plans.")
    } finally {
      setBusy(false)
    }
  }

  async function confirmImport(batchId: number) {
    setBusy(true)
    setLinkError("")
    try {
      await devLogin()
      const result = await api.confirmImport(batchId)
      setUploadResult(result)
      setMessage(result.recognition_message || "Import confirmed")
      await loadCandidatesForResult(result)
      await loadImports()
      await onChanged()
    } catch (error) {
      console.error(error)
      setMessage(error instanceof Error ? error.message : "Не удалось подтвердить import candidate")
    } finally {
      setBusy(false)
    }
  }

  async function rejectImport(batchId: number) {
    setBusy(true)
    try {
      await devLogin()
      const result = await api.rejectImport(batchId)
      setUploadResult(result)
      setMatchCandidates([])
      setMessage(result.recognition_message || "Import rejected")
      await loadImports()
      await onChanged()
    } catch (error) {
      console.error(error)
      setMessage(error instanceof Error ? error.message : "Не удалось отклонить import candidate")
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => { void loadImports() }, [])

  return <div className="grid gap-4 xl:grid-cols-[24rem_1fr]">
    <div className="grid gap-4">
      <Card>
        <CardHeader><div><CardTitle>Import screenshots</CardTitle><p className="text-xs text-zinc-500">LLM recognition or supported template fallback.</p></div><Badge>{imports.length} batches</Badge></CardHeader>
        <form onSubmit={upload} className="grid gap-3 p-4 text-xs">
          <Field label="Screenshots"><Input name="screenshots" type="file" accept="image/png,image/jpeg,image/webp" multiple required /></Field>
          <Button type="submit" disabled={busy}>{busy ? "Processing..." : "Upload and recognize"}</Button>
        </form>
        <div className="border-t border-zinc-800 p-4 text-xs text-zinc-400">
          <p className="leading-5">{message}</p>
          <p className="mt-2 text-zinc-600">Unknown screenshots require a configured vision LLM. Supported templates remain deterministic.</p>
        </div>
      </Card>
      <Card>
        <CardHeader><div><CardTitle>CSV import</CardTitle><p className="text-xs text-zinc-500">Import date, distance, duration, pace and HR columns.</p></div><Badge>6.18</Badge></CardHeader>
        <form onSubmit={uploadCsv} className="grid gap-3 p-4 text-xs">
          <Field label="CSV file"><Input name="csv_file" type="file" accept=".csv,text/csv" required /></Field>
          <Field label="Source app"><Input name="source_app" defaultValue="csv" placeholder="garmin, strava, manual" /></Field>
          <Button type="submit" disabled={busy}>{busy ? "Importing..." : "Import CSV"}</Button>
        </form>
        {csvResult ? <div className="grid grid-cols-2 gap-2 border-t border-zinc-800 p-4 text-xs md:grid-cols-4">
          <Stat label="created" value={csvResult.created_activities} />
          <Stat label="duplicates" value={csvResult.skipped_duplicates} />
          <Stat label="matched" value={csvResult.matched_workouts} />
          <Stat label="failed" value={csvResult.failed_rows} />
          {csvResult.errors.length ? <p className="col-span-full rounded-md border border-orange-400/20 bg-orange-400/10 px-3 py-2 text-orange-100">{csvResult.errors.slice(0, 3).join(" · ")}</p> : null}
        </div> : null}
      </Card>
    </div>

    <div className="grid gap-4">
      <Card>
        <CardHeader><div><CardTitle>Last import result</CardTitle><p className="text-xs text-zinc-500">Recognition output and plan match state.</p></div>{uploadResult && <Badge>{uploadResult.status}</Badge>}</CardHeader>
        {uploadResult ? <div className="grid gap-3 p-4 text-xs">
          <div className="grid gap-2 md:grid-cols-4">
            <Stat label="batch" value={`#${uploadResult.id}`} />
            <Stat label="activity" value={uploadResult.created_activity_id ? `#${uploadResult.created_activity_id}` : "--"} />
            <Stat label="matched" value={uploadResult.matched_workout_id ? `#${uploadResult.matched_workout_id}` : "--"} />
            <Stat label="engine" value={uploadResult.recognition_engine || "--"} />
          </div>
          <div className="rounded-md border border-zinc-800 bg-zinc-950 p-3 text-zinc-400">{uploadResult.recognition_message || "No recognition message"}</div>
          {uploadResult.requires_confirmation && uploadResult.candidate ? <ImportCandidateReview batch={uploadResult} busy={busy} onConfirm={confirmImport} onReject={rejectImport} /> : null}
          {uploadResult.matched_workout_id ? <div className="rounded-md border border-orange-400/20 bg-orange-400/10 px-3 py-2 text-orange-100">{uploadResult.auto_matched ? "Auto-linked by import matching" : "Currently matched"} to planned workout #{uploadResult.matched_workout_id}.</div> : null}
          {uploadResult.created_activity_id && !uploadResult.matched_workout_id ? <MatchReview candidates={matchCandidates} busy={busy} candidateError={candidateError} linkError={linkError} onLink={linkCandidate} /> : null}
        </div> : <p className="p-4 text-xs text-zinc-500">Upload a screenshot batch to see recognition and matching feedback.</p>}
      </Card>

      <Card>
        <CardHeader><div><CardTitle>Import history</CardTitle><p className="text-xs text-zinc-500">Recent recognition batches for current user.</p></div><Button size="sm" variant="secondary" onClick={loadImports}>Refresh</Button></CardHeader>
        {importHistoryError ? <p className="px-4 pb-2 text-xs text-orange-200">{importHistoryError}</p> : null}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-left text-xs">
            <thead className="border-b border-zinc-800 text-[10px] uppercase tracking-[0.14em] text-zinc-500"><tr><th className="px-4 py-2">Batch</th><th>Status</th><th>Activity</th><th>Match</th><th>Engine</th><th>Message</th><th>Action</th><th>Date</th></tr></thead>
            <tbody>{imports.map((batch) => <tr key={batch.id} className="border-b border-zinc-900 last:border-0 align-top"><td className="px-4 py-2 font-mono text-zinc-500">#{batch.id}</td><td><Badge className={batch.requires_confirmation ? "border-orange-400/40 bg-orange-400/15 text-orange-100" : "border-zinc-700 bg-zinc-900 text-zinc-300"}>{batch.status}</Badge></td><td>{batch.created_activity_id ? `#${batch.created_activity_id}` : "--"}</td><td>{batch.matched_workout_id ? `#${batch.matched_workout_id}` : "--"}</td><td>{batch.recognition_engine || "--"}</td><td className="max-w-[18rem] text-zinc-500">{batch.recognition_message || "--"}</td><td>{batch.requires_confirmation ? <div className="flex flex-wrap gap-1"><Button size="sm" disabled={busy} onClick={() => confirmImport(batch.id)}>Confirm</Button><Button size="sm" variant="secondary" disabled={busy} onClick={() => rejectImport(batch.id)}>Reject</Button></div> : <span className="text-zinc-600">--</span>}</td><td className="text-zinc-500">{batch.created_at ? new Date(batch.created_at).toLocaleString("ru-RU") : "--"}</td></tr>)}</tbody>
          </table>
          {!imports.length && <p className="p-4 text-xs text-zinc-500">История импортов пока пуста.</p>}
        </div>
      </Card>
    </div>
  </div>
}

function ImportCandidateReview({ batch, busy, onConfirm, onReject }: { batch: ImportUploadResult; busy: boolean; onConfirm: (batchId: number) => Promise<void>; onReject: (batchId: number) => Promise<void> }) {
  const candidate = batch.candidate
  if (!candidate) return null
  return <div className="grid gap-3 rounded-md border border-orange-400/25 bg-orange-400/10 p-3 text-xs">
    <div className="flex flex-wrap items-center justify-between gap-2"><div><p className="font-semibold text-orange-50">Review required before analytics</p><p className="mt-1 text-orange-100/70">LLM output passed validation but will not create an activity until confirmed.</p></div><Badge className="border-orange-400/40 bg-orange-400/15 text-orange-100">{candidate.confidence || "unknown"} confidence</Badge></div>
    <div className="grid gap-2 md:grid-cols-4"><Stat label="title" value={candidate.activity.title || "--"} /><Stat label="distance" value={candidate.activity.distance_km ? `${candidate.activity.distance_km} км` : "--"} /><Stat label="duration" value={candidate.activity.duration_seconds ? formatDuration(candidate.activity.duration_seconds) : "--"} /><Stat label="pace" value={candidate.activity.average_pace_seconds_per_km ? formatPace(candidate.activity.average_pace_seconds_per_km) : "--"} /></div>
    {candidate.uncertainty_notes.length ? <p className="text-[11px] text-orange-100/70">uncertainty: {candidate.uncertainty_notes.slice(0, 3).join(" · ")}</p> : null}
    {candidate.estimated_fields.length ? <p className="text-[11px] text-orange-100/70">estimated: {candidate.estimated_fields.slice(0, 4).join(" · ")}</p> : null}
    <div className="flex flex-wrap gap-2"><Button size="sm" disabled={busy} onClick={() => onConfirm(batch.id)}>Confirm and create activity</Button><Button size="sm" variant="secondary" disabled={busy} onClick={() => onReject(batch.id)}>Reject candidate</Button></div>
  </div>
}

function MatchReview({ candidates, busy, candidateError, linkError, onLink }: { candidates: PlanWorkoutMatchCandidate[]; busy: boolean; candidateError: string; linkError: string; onLink: (candidate: PlanWorkoutMatchCandidate) => Promise<void> }) {
  if (candidateError) return <div className="rounded-md border border-orange-400/20 bg-orange-400/10 px-3 py-2 text-xs text-orange-100">{candidateError}</div>
  if (!candidates.length) return <div className="rounded-md border border-zinc-800 bg-zinc-950 px-3 py-2 text-xs text-zinc-500">No confident active-plan candidates. Open Plans to match manually later.</div>
  return <div className="grid gap-2">
    <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-zinc-500">Plan match candidates</p>
    {linkError ? <p className="rounded-md border border-orange-400/20 bg-orange-400/10 px-3 py-2 text-xs text-orange-100">{linkError}</p> : null}
    {candidates.slice(0, 4).map((candidate) => <div key={candidate.workout.id} className="grid gap-2 rounded-md border border-zinc-800 bg-zinc-950 p-3 text-xs md:grid-cols-[1fr_auto] md:items-center">
      <div><p className="font-medium text-white">{candidate.workout.title}<span className="ml-2 font-mono text-[10px] text-zinc-500">#{candidate.workout.id}</span></p><p className="mt-1 text-zinc-500">Week {candidate.workout.week_index} · {candidate.workout.scheduled_date ? new Date(candidate.workout.scheduled_date).toLocaleDateString("ru-RU") : "no date"} · {candidate.workout.distance_km?.toFixed(1) || "--"} км</p><p className="mt-1 text-[11px] text-zinc-500">{candidate.reasons.slice(0, 2).join(" · ")}</p></div>
      <div className="flex flex-wrap items-center gap-2 md:justify-end"><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{Math.round(candidate.score * 100)}% {candidate.confidence}</Badge><Button size="sm" disabled={busy} aria-label={`Link uploaded activity to planned workout ${candidate.workout.title} #${candidate.workout.id}`} onClick={() => onLink(candidate)}>Link</Button></div>
    </div>)}
  </div>
}

function CalendarPage({ onImport, onPlans }: { onImport: () => void; onPlans: () => void }) {
  const initialStart = startOfWeekISO()
  const [fromDate, setFromDate] = useState(initialStart)
  const [toDate, setToDate] = useState(addDays(initialStart, 6))
  const [calendar, setCalendar] = useState<CalendarResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [busyEvent, setBusyEvent] = useState("")
  const [loadingMatchEvent, setLoadingMatchEvent] = useState("")
  const [calendarMatches, setCalendarMatches] = useState<Record<string, CalendarMatchState>>({})
  const [calendarMatchErrors, setCalendarMatchErrors] = useState<Record<string, string>>({})
  const [rescheduleDrafts, setRescheduleDrafts] = useState<Record<string, string>>({})

  async function loadRange(fromValue = fromDate, toValue = toDate) {
    setError("")
    setCalendarMatches({})
    setCalendarMatchErrors({})
    if (fromValue > toValue) {
      setError("Дата начала должна быть раньше или равна дате окончания")
      return
    }
    if (calendarRangeDayCount(fromValue, toValue) > MAX_CALENDAR_DAYS) {
      setError(`Диапазон календаря не может превышать ${MAX_CALENDAR_DAYS} дней`)
      return
    }
    setLoading(true)
    try {
      await devLogin()
      setCalendar(await api.calendar(fromValue, toValue))
      setRescheduleDrafts({})
    } catch (loadError) {
      console.error(loadError)
      setError(loadError instanceof Error ? loadError.message : "Не удалось загрузить календарь")
    } finally {
      setLoading(false)
    }
  }

  async function submitRange(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    await loadRange()
  }

  async function applyQuickRange(range: "week" | "next" | "month") {
    let nextFrom = startOfWeekISO()
    let nextTo = addDays(nextFrom, 6)
    if (range === "next") {
      nextFrom = addDays(nextFrom, 7)
      nextTo = addDays(nextFrom, 6)
    } else if (range === "month") {
      const [monthStart, monthEnd] = monthRangeISO()
      nextFrom = monthStart
      nextTo = monthEnd
    }
    setFromDate(nextFrom)
    setToDate(nextTo)
    await loadRange(nextFrom, nextTo)
  }

  async function updateCalendarWorkout(event: CalendarEvent, status: string) {
    if (!event.planned_workout_id) return
    setBusyEvent(event.id)
    setError("")
    try {
      await api.updatePlanWorkout(event.planned_workout_id, { status })
      await loadRange(calendar?.from_date || fromDate, calendar?.to_date || toDate)
    } catch (updateError) {
      console.error(updateError)
      setError("Не удалось обновить workout из календаря")
    } finally {
      setBusyEvent("")
    }
  }

  async function rescheduleCalendarWorkout(event: CalendarEvent, scheduledDate: string) {
    if (!event.planned_workout_id) return
    setCalendarMatchErrors((current) => ({ ...current, [event.id]: "" }))
    if (!scheduledDate) {
      setCalendarMatchErrors((current) => ({ ...current, [event.id]: "Выберите новую дату" }))
      return
    }
    setBusyEvent(event.id)
    try {
      await api.updatePlanWorkout(event.planned_workout_id, { scheduled_date: scheduledDate })
      await loadRange(calendar?.from_date || fromDate, calendar?.to_date || toDate)
    } catch (updateError) {
      console.error(updateError)
      setCalendarMatchErrors((current) => ({ ...current, [event.id]: "Не удалось перенести workout" }))
    } finally {
      setBusyEvent("")
    }
  }

  async function loadCalendarMatches(event: CalendarEvent) {
    setLoadingMatchEvent(event.id)
    setCalendarMatchErrors((current) => ({ ...current, [event.id]: "" }))
    try {
      if (event.kind === "planned_workout" && event.planned_workout_id) {
        const candidates = await api.workoutMatchCandidates(event.planned_workout_id)
        setCalendarMatches((current) => ({ ...current, [event.id]: { mode: "workout_to_activity", candidates } }))
      } else if (event.linked_activity_id) {
        const candidates = await api.activityMatchCandidates(event.linked_activity_id, true)
        setCalendarMatches((current) => ({ ...current, [event.id]: { mode: "activity_to_workout", candidates } }))
      }
    } catch (matchError) {
      console.error(matchError)
      setCalendarMatchErrors((current) => ({ ...current, [event.id]: "Не удалось загрузить кандидатов" }))
    } finally {
      setLoadingMatchEvent("")
    }
  }

  async function linkCalendarMatch(event: CalendarEvent, workoutId: number, activityId: number) {
    setBusyEvent(event.id)
    setCalendarMatchErrors((current) => ({ ...current, [event.id]: "" }))
    try {
      await api.linkPlanWorkoutActivity(workoutId, activityId)
      setCalendarMatches((current) => {
        const next = { ...current }
        delete next[event.id]
        return next
      })
      await loadRange(calendar?.from_date || fromDate, calendar?.to_date || toDate)
    } catch (linkError) {
      console.error(linkError)
      setCalendarMatchErrors((current) => ({ ...current, [event.id]: "Не удалось привязать активность" }))
    } finally {
      setBusyEvent("")
    }
  }

  useEffect(() => { void loadRange(initialStart, addDays(initialStart, 6)) }, [])

  const shownFrom = calendar?.from_date || fromDate
  const shownTo = calendar?.to_date || toDate
  const days = dateRange(shownFrom, shownTo)
  const eventsByDate = new Map<string, CalendarEvent[]>()
  for (const event of calendar?.events || []) {
    eventsByDate.set(event.date, [...(eventsByDate.get(event.date) || []), event])
  }
  const dailyLoads = days.map((day) => (eventsByDate.get(day) || []).reduce((sum, event) => sum + calendarEventLoad(event), 0))
  const maxDailyLoad = Math.max(1, ...dailyLoads)

  return <div className="grid gap-4">
    <div className="grid gap-4 xl:grid-cols-[1fr_1.2fr]">
      <Card className="min-w-0 overflow-hidden p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-zinc-500">Calendar</p>
            <h2 className="mt-2 text-lg font-semibold text-white">Plan and actual by day</h2>
            <p className="mt-2 max-w-2xl text-xs leading-5 text-zinc-500">Planned workouts from the active plan, completed activities, linked/unlinked state and conflict warnings.</p>
          </div>
          <div className="flex flex-wrap gap-2"><Badge>{formatDate(shownFrom)} - {formatDate(shownTo)}</Badge><Badge className={signalClass(calendar?.warnings.length ? "warning" : "ok")}>{calendar?.warnings.length || 0} warnings</Badge></div>
        </div>
        <form onSubmit={submitRange} className="mt-4 grid gap-2 text-xs md:grid-cols-[1fr_1fr_auto]">
          <Input type="date" value={fromDate} onChange={(event) => setFromDate(event.target.value)} />
          <Input type="date" value={toDate} onChange={(event) => setToDate(event.target.value)} />
          <Button type="submit" disabled={loading}>{loading ? "Loading..." : "Load range"}</Button>
        </form>
        <div className="mt-3 flex flex-wrap gap-2"><Button size="sm" variant="secondary" onClick={() => applyQuickRange("week")}>This week</Button><Button size="sm" variant="secondary" onClick={() => applyQuickRange("next")}>Next week</Button><Button size="sm" variant="secondary" onClick={() => applyQuickRange("month")}>This month</Button><Button size="sm" variant="ghost" onClick={onImport}>+ Import</Button><Button size="sm" variant="ghost" onClick={onPlans}>Open plans</Button></div>
        {error ? <p className="mt-3 rounded-md border border-orange-400/20 bg-orange-400/10 px-3 py-2 text-xs text-orange-100">{error}</p> : null}
      </Card>
      <Card className="grid grid-cols-4 divide-x divide-zinc-800 p-3 max-md:grid-cols-2 max-md:divide-x-0 max-md:divide-y">
        <Stat label="planned" value={calendar?.summary.planned_workouts || 0} />
        <Stat label="done" value={calendar?.summary.done_workouts || 0} />
        <Stat label="activities" value={calendar?.summary.activities || 0} />
        <Stat label="unlinked" value={calendar?.summary.unlinked_activities || 0} />
      </Card>
    </div>

    {calendar?.warnings.length ? <Card>
      <CardHeader><div><CardTitle>Schedule warnings</CardTitle><p className="text-xs text-zinc-500">Conflict detection for hard sessions and long runs.</p></div><Badge className="border-orange-400/40 bg-orange-400/15 text-orange-100">{calendar.warnings.length}</Badge></CardHeader>
      <div className="grid gap-2 p-4 text-xs md:grid-cols-2">{calendar.warnings.map((warning) => <div key={`${warning.title}-${warning.date}-${warning.planned_workout_ids.join("-")}`} className="rounded-md border border-orange-400/20 bg-orange-400/10 p-3 text-orange-100"><p className="font-medium">{warning.title}</p><p className="mt-1 leading-5 text-orange-100/80">{warning.message}</p><p className="mt-1 font-mono text-[10px] uppercase tracking-[0.14em] text-orange-200/70">{formatDate(warning.date)} · workouts {warning.planned_workout_ids.map((id) => `#${id}`).join(", ")}</p></div>)}</div>
    </Card> : null}

    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-7">
      {days.map((day, index) => {
        const events = eventsByDate.get(day) || []
        const load = dailyLoads[index] || 0
        return <CalendarDay key={day} day={day} events={events} load={load} maxLoad={maxDailyLoad} busyEvent={busyEvent} loadingMatchEvent={loadingMatchEvent} matchesByEvent={calendarMatches} matchErrors={calendarMatchErrors} rescheduleDrafts={rescheduleDrafts} onFindMatches={loadCalendarMatches} onLinkMatch={linkCalendarMatch} onReschedule={rescheduleCalendarWorkout} onRescheduleDraft={(eventId, value) => setRescheduleDrafts((current) => ({ ...current, [eventId]: value }))} onUpdate={updateCalendarWorkout} />
      })}
    </div>
  </div>
}

function CalendarDay({ day, events, load, maxLoad, ...cardProps }: CalendarDayProps) {
  const today = toISODate(new Date())
  const width = Math.max(6, Math.round(load / maxLoad * 100))
  return <div className={cn("min-h-48 rounded-lg border bg-zinc-950/60 p-3 text-xs", day === today ? "border-orange-400/40" : "border-zinc-800")}>
    <div className="flex items-start justify-between gap-2"><div><p className="font-medium text-white">{formatDate(day)}</p><p className="mt-1 font-mono text-[10px] uppercase tracking-[0.14em] text-zinc-500">{dateFromISO(day).toLocaleDateString("ru-RU", { weekday: "short" })}</p></div>{events.length ? <Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{events.length}</Badge> : null}</div>
    <div className="mt-3 h-1.5 overflow-hidden rounded bg-zinc-900"><div className="h-full rounded bg-orange-400" style={{ width: `${width}%` }} /></div>
    <div className="mt-3 grid gap-2">{events.length ? events.map((event) => <CalendarEventCard key={event.id} event={event} {...cardProps} />) : <p className="rounded-md border border-zinc-900 bg-zinc-950 px-2 py-2 text-zinc-600">No plan or activity.</p>}</div>
  </div>
}

function CalendarEventCard({ event, busyEvent, loadingMatchEvent, matchesByEvent, matchErrors, rescheduleDrafts, onFindMatches, onLinkMatch, onReschedule, onRescheduleDraft, onUpdate }: CalendarEventCardProps) {
  const isWorkout = event.kind === "planned_workout"
  const isLinked = Boolean(event.planned_workout_id && event.linked_activity_id)
  const score = event.execution_score?.score
  const busy = busyEvent === event.id
  const matchState = matchesByEvent[event.id]
  const matchError = matchErrors[event.id]
  const loadingMatches = loadingMatchEvent === event.id
  const canFindWorkoutActivity = isWorkout && Boolean(event.planned_workout_id) && !event.linked_activity_id && ["planned", "rescheduled"].includes(event.status || "")
  const canFindActivityWorkout = !isWorkout && Boolean(event.linked_activity_id) && !event.planned_workout_id
  const canReschedule = isWorkout && Boolean(event.planned_workout_id) && !event.linked_activity_id && ["planned", "rescheduled"].includes(event.status || "")
  const rescheduleDraft = rescheduleDrafts[event.id] ?? event.date
  return <div className={cn("rounded-md border p-2", isWorkout ? "border-zinc-800 bg-zinc-950" : isLinked ? "border-orange-400/20 bg-orange-400/10" : "border-zinc-800 bg-zinc-900/70")}>
    <div className="flex flex-wrap items-start justify-between gap-2"><div className="min-w-0"><p className="truncate font-medium text-white">{event.title}</p><p className="mt-1 text-[11px] text-zinc-500">{isWorkout ? event.workout_type || "workout" : event.workout_type || "activity"} · {formatWorkoutTarget(event)}</p></div><Badge className={signalClass(event.status || undefined)}>{event.status || event.kind}</Badge></div>
    {score !== null && score !== undefined ? <p className="mt-2 text-[11px] text-zinc-500">Score {Math.round(score * 100)}% · {event.execution_score?.subjective_risk}</p> : null}
    {event.linked_activity_id && isWorkout ? <p className="mt-2 rounded border border-orange-400/20 bg-orange-400/10 px-2 py-1 text-[11px] text-orange-100">Linked activity #{event.linked_activity_id}</p> : null}
    {event.planned_workout_id && !isWorkout ? <p className="mt-2 rounded border border-orange-400/20 bg-orange-400/10 px-2 py-1 text-[11px] text-orange-100">Matched to workout #{event.planned_workout_id}</p> : null}
    {canReschedule ? <div className="mt-2 grid gap-1.5 rounded-md border border-zinc-800 bg-zinc-950/70 p-2">
      <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-zinc-500">Reschedule</p>
      <div className="grid gap-1.5 sm:grid-cols-[1fr_auto]"><Input type="date" value={rescheduleDraft} onChange={(change) => onRescheduleDraft(event.id, change.target.value)} /><Button size="sm" variant="ghost" disabled={busy || !rescheduleDraft || rescheduleDraft === event.date} onClick={() => onReschedule(event, rescheduleDraft)}>Move</Button></div>
    </div> : null}
    <div className="mt-2 flex flex-wrap gap-1.5">
      {isWorkout ? <>
        <Button size="sm" variant="ghost" disabled={busy || event.status === "missed" || Boolean(event.linked_activity_id)} onClick={() => onUpdate(event, "missed")}>Missed</Button>
        <Button size="sm" variant="ghost" disabled={busy || event.status === "skipped" || Boolean(event.linked_activity_id)} onClick={() => onUpdate(event, "skipped")}>Skipped</Button>
        {event.status !== "planned" && !event.linked_activity_id ? <Button size="sm" variant="ghost" disabled={busy} onClick={() => onUpdate(event, "planned")}>Restore</Button> : null}
      </> : null}
      {canFindWorkoutActivity || canFindActivityWorkout ? <Button size="sm" variant="ghost" disabled={busy || loadingMatches} onClick={() => onFindMatches(event)}>{loadingMatches ? "Matching..." : canFindWorkoutActivity ? "Find activity" : "Find workout"}</Button> : null}
    </div>
    {matchError ? <p className="mt-2 rounded-md border border-orange-400/20 bg-orange-400/10 px-2 py-1.5 text-[11px] text-orange-100">{matchError}</p> : null}
    {matchState ? <CalendarMatchCandidates event={event} state={matchState} busy={busy} onLinkMatch={onLinkMatch} /> : null}
  </div>
}

function CalendarMatchCandidates({ event, state, busy, onLinkMatch }: { event: CalendarEvent; state: CalendarMatchState; busy: boolean; onLinkMatch: (event: CalendarEvent, workoutId: number, activityId: number) => Promise<void> }) {
  if (state.mode === "workout_to_activity") {
    const workoutId = event.planned_workout_id
    if (!workoutId) return null
    if (!state.candidates.length) return <p className="mt-2 rounded-md border border-zinc-800 bg-zinc-950 px-2 py-1.5 text-[11px] text-zinc-500">No activity candidates in the matching window.</p>
    return <div className="mt-2 grid gap-1.5 rounded-md border border-zinc-800 bg-zinc-950/70 p-2">
      <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-zinc-500">Activity candidates</p>
      {state.candidates.slice(0, 4).map((candidate) => <div key={candidate.activity.id} className="grid gap-2 rounded-md bg-zinc-900/70 p-2 md:grid-cols-[1fr_auto] md:items-center">
        <div><p className="font-medium text-white">{candidate.activity.title}<span className="ml-2 font-mono text-[10px] text-zinc-500">#{candidate.activity.id}</span></p><p className="mt-1 text-zinc-500">{candidate.activity.started_at ? new Date(candidate.activity.started_at).toLocaleDateString("ru-RU") : "без даты"} · {formatDistance(candidate.activity.distance_km)} · {formatDuration(candidate.activity.duration_seconds)}</p><p className="mt-1 text-[11px] text-zinc-500">{candidate.reasons.slice(0, 2).join(" · ")}</p></div>
        <div className="flex flex-wrap items-center gap-2 md:justify-end"><Badge className="border-zinc-700 bg-zinc-950 text-zinc-300">{Math.round(candidate.score * 100)}% {candidate.confidence}</Badge><Button size="sm" disabled={busy} onClick={() => onLinkMatch(event, workoutId, candidate.activity.id)}>Link</Button></div>
      </div>)}
    </div>
  }

  const activityId = event.linked_activity_id
  if (!activityId) return null
  if (!state.candidates.length) return <p className="mt-2 rounded-md border border-zinc-800 bg-zinc-950 px-2 py-1.5 text-[11px] text-zinc-500">No active-plan workout candidates found.</p>
  return <div className="mt-2 grid gap-1.5 rounded-md border border-zinc-800 bg-zinc-950/70 p-2">
    <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-zinc-500">Workout candidates</p>
    {state.candidates.slice(0, 4).map((candidate) => <div key={candidate.workout.id} className="grid gap-2 rounded-md bg-zinc-900/70 p-2 md:grid-cols-[1fr_auto] md:items-center">
      <div><p className="font-medium text-white">{candidate.workout.title}<span className="ml-2 font-mono text-[10px] text-zinc-500">#{candidate.workout.id}</span></p><p className="mt-1 text-zinc-500">{formatDate(candidate.workout.scheduled_date)} · {formatWorkoutTarget(candidate.workout)} · {candidate.workout.intensity || "--"}</p><p className="mt-1 text-[11px] text-zinc-500">{candidate.reasons.slice(0, 2).join(" · ")}</p></div>
      <div className="flex flex-wrap items-center gap-2 md:justify-end"><Badge className="border-zinc-700 bg-zinc-950 text-zinc-300">{Math.round(candidate.score * 100)}% {candidate.confidence}</Badge><Button size="sm" disabled={busy} onClick={() => onLinkMatch(event, candidate.workout.id, activityId)}>Link</Button></div>
    </div>)}
  </div>
}

function isoDate(value: Date) {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, "0")
  const day = String(value.getDate()).padStart(2, "0")
  return `${year}-${month}-${day}`
}

function analyticsQuery(preset: string, customFrom: string, customTo: string) {
  if (preset === "all") return ""
  if (preset === "custom") {
    const params = new URLSearchParams()
    if (customFrom) params.set("from", customFrom)
    if (customTo) params.set("to", customTo)
    const value = params.toString()
    return value ? `?${value}` : ""
  }
  const days = preset === "7d" ? 7 : preset === "90d" ? 90 : preset === "year" ? 365 : 28
  const to = new Date()
  const from = new Date(to)
  from.setDate(to.getDate() - days + 1)
  return `?from=${isoDate(from)}&to=${isoDate(to)}`
}

function TrendChart({ title, series, formatter, lowerIsBetter = false }: { title: string; series: AnalyticsTimeseries | null; formatter: (value: number | null) => string; lowerIsBetter?: boolean }) {
  const points = series?.points || []
  const values = points.map((point) => point.value).filter((value): value is number => typeof value === "number" && Number.isFinite(value))
  const max = Math.max(1, ...values)
  const min = Math.max(1, Math.min(...values, max))
  return <div className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3">
    <div className="flex items-center justify-between gap-2"><p className="text-xs font-semibold text-white">{title}</p><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{series?.granularity || "week"}</Badge></div>
    <div className="mt-3 grid gap-2">{points.length ? points.slice(-10).map((point) => {
      const numericValue = typeof point.value === "number" && Number.isFinite(point.value) ? point.value : 0
      const width = lowerIsBetter && numericValue > 0 ? min / numericValue * 100 : numericValue / max * 100
      return <div key={`${title}-${point.period_label}`} className="grid grid-cols-[6rem_1fr_4.5rem] items-center gap-2 text-[11px]"><span className="truncate text-zinc-500">{point.period_label}</span><div className="h-2 rounded bg-zinc-900"><div className="h-full rounded bg-orange-400" style={{ width: `${Math.max(4, width)}%` }} /></div><strong className="text-right text-zinc-300">{formatter(point.value)}</strong></div>
    }) : <p className="text-xs text-zinc-500">Нет точек для выбранного периода.</p>}</div>
  </div>
}

function Analytics({ analytics }: { analytics: AnalyticsSummary | null }) {
  const [preset, setPreset] = useState("28d")
  const [customFrom, setCustomFrom] = useState("")
  const [customTo, setCustomTo] = useState("")
  const [summary, setSummary] = useState<AnalyticsSummary | null>(analytics)
  const [volumeTrend, setVolumeTrend] = useState<AnalyticsTimeseries | null>(null)
  const [paceTrend, setPaceTrend] = useState<AnalyticsTimeseries | null>(null)
  const [hrTrend, setHrTrend] = useState<AnalyticsTimeseries | null>(null)
  const [insights, setInsights] = useState<AnalyticsInsight[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [reloadToken, setReloadToken] = useState(0)

  useEffect(() => {
    const query = analyticsQuery(preset, customFrom, customTo)
    let cancelled = false
    async function loadAnalytics() {
      setLoading(true)
      setError("")
      try {
        await devLogin()
        const [nextSummary, distanceSeries, paceSeries, hrSeries, nextInsights] = await Promise.all([
          api.analytics(query),
          api.analyticsTimeseries(`${query}${query ? "&" : "?"}metric=distance&granularity=week`),
          api.analyticsTimeseries(`${query}${query ? "&" : "?"}metric=pace&granularity=week`),
          api.analyticsTimeseries(`${query}${query ? "&" : "?"}metric=hr&granularity=week`),
          api.analyticsInsights(query),
        ])
        if (!cancelled) {
          setSummary(nextSummary)
          setVolumeTrend(distanceSeries)
          setPaceTrend(paceSeries)
          setHrTrend(hrSeries)
          setInsights(nextInsights)
        }
      } catch (caught) {
        console.error(caught)
        if (!cancelled) setError(apiErrorMessage(caught, "Analytics API недоступен"))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void loadAnalytics()
    return () => { cancelled = true }
  }, [preset, customFrom, customTo, reloadToken])

  const months = summary?.months || []
  const maxMonth = Math.max(1, ...months.map((month) => month.distance_km))
  const vdot = summary?.estimated_vdot || null
  const vo2 = summary?.manual_vo2max || null
  return <div className="grid gap-4">
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><p className="font-mono text-[10px] uppercase tracking-[0.18em] text-zinc-500">Analytics Overview</p><h2 className="mt-2 text-lg font-semibold text-white">Training signal center</h2><p className="mt-2 max-w-2xl text-xs leading-5 text-zinc-500">Периодная аналитика: объем, темп, пульс, adherence, best efforts и VO2max/VDOT estimate с источником.</p></div>
        <div className="flex flex-wrap gap-2"><Badge>{summary?.period.label || "loading"}</Badge>{loading ? <Badge className="border-orange-400/40 bg-orange-400/15 text-orange-100">loading</Badge> : null}</div>
      </div>
      <div className="mt-4 grid gap-2 md:grid-cols-[10rem_1fr_1fr]">
        <Select value={preset} onChange={(event) => setPreset(event.target.value)}><option value="7d">7 дней</option><option value="28d">28 дней</option><option value="90d">90 дней</option><option value="year">Год</option><option value="all">Все время</option><option value="custom">Custom</option></Select>
        <Input type="date" value={customFrom} disabled={preset !== "custom"} onChange={(event) => setCustomFrom(event.target.value)} />
        <Input type="date" value={customTo} disabled={preset !== "custom"} onChange={(event) => setCustomTo(event.target.value)} />
      </div>
      {error ? <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-md border border-rose-400/20 bg-rose-400/10 px-2 py-1.5 text-xs text-rose-100"><span>{error}</span><Button size="sm" variant="secondary" onClick={() => setReloadToken((current) => current + 1)}>Retry</Button></div> : null}
    </Card>

    <div className="grid gap-3 md:grid-cols-4">
      <MetricCard label="distance" value={Number(summary?.total_distance_km || 0).toFixed(1)} suffix="km" />
      <MetricCard label="time" value={formatDuration(summary?.total_duration_seconds)} />
      <MetricCard label="workouts" value={summary?.activity_count || 0} />
      <MetricCard label="adherence" value={`${Math.round((summary?.adherence?.completion_rate || 0) * 100)}%`} hint="done workouts / planned workouts" explainer={<CalculationExplainer><p>Completion rate is calculated from active-plan workouts in the selected period. Missed and skipped workouts lower the value.</p></CalculationExplainer>} />
      <MetricCard label="weighted pace" value={`${formatPace(summary?.weighted_average_pace_seconds_per_km)}/км`} hint="total duration / total distance" explainer={<CalculationExplainer><p>Weighted pace uses total moving duration divided by total distance, so short outlier runs do not distort the average like a simple mean would.</p></CalculationExplainer>} />
      <MetricCard label="avg HR" value={summary?.average_heart_rate_bpm || "--"} hint="duration-weighted" explainer={<CalculationExplainer><p>Average HR is weighted by activity duration. Longer runs contribute more than short sessions.</p></CalculationExplainer>} />
      <MetricCard label="load" value={summary?.training_load ?? "--"} hint={summary?.load_method || "unavailable"} explainer={<CalculationExplainer><p>Load sums aerobic training stress when available. If devices do not provide stress values, the card stays unavailable instead of guessing.</p></CalculationExplainer>} />
      <MetricCard label="VDOT / VO2max" value={vdot?.value ?? vo2?.value ?? "--"} hint={vdot ? `${vdot.confidence} · ${vdot.method}` : vo2 ? `${vo2.confidence} · ${vo2.method}` : "needs race/device data"} explainer={<CalculationExplainer><p>VDOT is derived from race-like best efforts. Manual or device VO2max is shown as fallback and keeps its own method and confidence.</p></CalculationExplainer>} />
    </div>

    <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
      <Card><CardHeader><CardTitle>Monthly volume</CardTitle><Badge>{Number(summary?.total_distance_km || 0).toFixed(1)} km total</Badge></CardHeader><div className="space-y-3 p-4">{months.length ? months.map((month) => <div key={month.month} className="grid grid-cols-[110px_1fr_90px] items-center gap-3 text-xs"><span className="text-zinc-400">{month.month}</span><div className="h-2 rounded bg-zinc-900"><div className="h-full rounded bg-orange-400" style={{ width: `${Math.max(6, month.distance_km / maxMonth * 100)}%` }} /></div><strong>{month.distance_km.toFixed(1)} км</strong></div>) : <p className="p-4 text-xs text-zinc-500">Нет месячных данных.</p>}</div></Card>
      <Card><CardHeader><CardTitle>VO2max / VDOT</CardTitle><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">source shown</Badge></CardHeader><div className="grid gap-3 p-4 text-xs"><div className="rounded-md border border-zinc-800 bg-zinc-950 p-3"><p className="text-zinc-500">Estimated VDOT</p><p className="mt-1 text-2xl font-semibold text-white">{vdot?.value ?? "--"}</p><p className="mt-1 text-zinc-500">{vdot ? `${vdot.confidence} · ${vdot.method}` : "Нужен hard effort или race-like activity >= 3 км."}</p></div><div className="rounded-md border border-zinc-800 bg-zinc-950 p-3"><p className="text-zinc-500">Manual/device VO2max</p><p className="mt-1 text-2xl font-semibold text-white">{vo2?.value ?? "--"}</p><p className="mt-1 text-zinc-500">{vo2 ? `${vo2.confidence} · ${vo2.method}` : "Можно добавить в Profile measurements."}</p></div></div></Card>
    </div>

    <div className="grid gap-3 xl:grid-cols-3">
      <TrendChart title="Weekly volume" series={volumeTrend} formatter={(value) => `${Number(value || 0).toFixed(1)} км`} />
      <TrendChart title="Pace trend" series={paceTrend} formatter={(value) => `${formatPace(value)}/км`} lowerIsBetter />
      <TrendChart title="HR trend" series={hrTrend} formatter={(value) => value ? `${Math.round(value)} bpm` : "--"} />
    </div>

    <div className="grid gap-4 xl:grid-cols-[1fr_1fr]">
      <Card><CardHeader><CardTitle>Best efforts</CardTitle><Badge>{summary?.best_efforts.length || 0} efforts</Badge></CardHeader><div className="divide-y divide-zinc-800">{summary?.best_efforts.length ? summary.best_efforts.map((effort) => <div key={`${effort.target_distance_km}-${effort.activity_id}`} className="grid gap-2 px-4 py-3 text-xs md:grid-cols-[5rem_1fr_auto]"><div className="font-semibold text-white">{effort.target_distance_km} км</div><div><p className="text-zinc-300">{formatDuration(effort.duration_seconds)} · {formatPace(effort.pace_seconds_per_km)}/км</p><p className="mt-1 text-zinc-500">{effort.title} · {effort.source} · {effort.confidence}</p></div><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">VDOT {effort.estimated_vdot?.value ?? "--"}</Badge></div>) : <p className="p-4 text-xs text-zinc-500">Нужны активности с достаточной дистанцией.</p>}</div></Card>
      <Card><CardHeader><CardTitle>Insights</CardTitle><Badge>{insights.length} notes</Badge></CardHeader><div className="grid gap-2 p-4">{insights.map((insight) => <div key={insight.title} className="rounded-md border border-zinc-800 bg-zinc-950 p-3 text-xs"><div className="flex flex-wrap items-center justify-between gap-2"><p className="font-semibold text-white">{insight.title}</p><div className="flex gap-1.5"><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{insight.confidence}</Badge><Badge className={insight.severity === "warning" ? "border-orange-400/40 bg-orange-400/15 text-orange-100" : "border-zinc-700 bg-zinc-900 text-zinc-300"}>{insight.severity}</Badge></div></div><p className="mt-1 leading-5 text-zinc-400">{insight.message}</p>{insight.evidence.length ? <p className="mt-1 text-[11px] text-zinc-600">evidence: {insight.evidence.slice(0, 2).map((item) => `${String(item.metric || item.source || "signal")}=${String(item.value ?? item.method ?? item.source ?? "ok")}`).join(" · ")}</p> : null}{insight.reasons.length ? <p className="mt-1 text-[11px] text-zinc-600">{insight.reasons.slice(0, 2).join(" · ")}</p> : null}</div>)}</div></Card>
    </div>

    <Card className="p-4"><div className="grid gap-3 text-xs md:grid-cols-3"><Stat label="training days" value={summary?.consistency.training_days || 0} /><Stat label="days / week" value={summary?.consistency.training_days_per_week || 0} /><Stat label="missed planned" value={summary?.consistency.missed_planned_sessions || 0} /></div></Card>
  </div>
}

function TrainingLoadRecovery() {
  const [preset, setPreset] = useState("28d")
  const [customFrom, setCustomFrom] = useState("")
  const [customTo, setCustomTo] = useState("")
  const [daily, setDaily] = useState<TrainingLoadDaily | null>(null)
  const [weekly, setWeekly] = useState<TrainingLoadWeekly | null>(null)
  const [fitness, setFitness] = useState<TrainingLoadFitnessFatigue | null>(null)
  const [warnings, setWarnings] = useState<TrainingLoadWarning[]>([])
  const [materialization, setMaterialization] = useState<TrainingLoadMaterializationStatus | null>(null)
  const [materializationError, setMaterializationError] = useState("")
  const [loading, setLoading] = useState(false)
  const [materializing, setMaterializing] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => {
    const query = analyticsQuery(preset, customFrom, customTo)
    let cancelled = false
    async function loadTrainingLoad() {
      setLoading(true)
      setError("")
      setMaterializationError("")
      try {
        await devLogin()
        const materializationStatus = api.trainingLoadMaterialization(query).then((status) => ({ status, error: "" })).catch((caught) => {
          console.warn(caught)
          return { status: null, error: apiErrorMessage(caught, "Materialization status unavailable") }
        })
        const [nextDaily, nextWeekly, nextFitness, nextWarnings, nextMaterializationResult] = await Promise.all([
          api.trainingLoadDaily(query),
          api.trainingLoadWeekly(query),
          api.trainingLoadFitnessFatigue(query),
          api.trainingLoadWarnings(query),
          materializationStatus,
        ])
        if (!cancelled) {
          setDaily(nextDaily)
          setWeekly(nextWeekly)
          setFitness(nextFitness)
          setWarnings(nextWarnings)
          setMaterialization(nextMaterializationResult.status)
          setMaterializationError(nextMaterializationResult.error)
        }
      } catch (caught) {
        console.error(caught)
        if (!cancelled) setError(apiErrorMessage(caught, "Training Load API недоступен"))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void loadTrainingLoad()
    return () => { cancelled = true }
  }, [preset, customFrom, customTo])

  const dailyPoints = daily?.points || []
  const weeklyPoints = weekly?.points || []
  const latestWeek = weeklyPoints.length ? weeklyPoints[weeklyPoints.length - 1] : null
  const hardDays = dailyPoints.filter((point) => point.hard_session)
  const recoveryDays = dailyPoints.filter((point) => point.recovery_day).slice(-7)
  const current = fitness?.current
  const method = fitness?.method || daily?.method || "unavailable"
  const methodLabel = loadMethodLabel(method)
  const staleCount = (materialization?.missing_dates.length || 0) + (materialization?.stale_dates.length || 0)
  const materializationRangeLabel = preset === "all" ? "default 28-day window" : "selected range"

  async function backfillMaterialization() {
    const query = analyticsQuery(preset, customFrom, customTo)
    setMaterializing(true)
    setError("")
    try {
      await devLogin()
      const result = await api.backfillTrainingLoad(query)
      setMaterialization(result.status)
      setMaterializationError("")
    } catch (caught) {
      console.error(caught)
      setError(apiErrorMessage(caught, "Daily load backfill не выполнен"))
    } finally {
      setMaterializing(false)
    }
  }

  return <div className="grid gap-4">
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><p className="font-mono text-[10px] uppercase tracking-[0.18em] text-zinc-500">Training Load & Recovery</p><h2 className="mt-2 text-lg font-semibold text-white">Fitness, fatigue and recovery signals</h2><p className="mt-2 max-w-2xl text-xs leading-5 text-zinc-500">Daily/weekly load, CTL/ATL/TSB heuristics, monotony, strain, hard-session spacing and recovery-day alerts. These metrics are coaching signals, not medical predictions.</p></div>
        <div className="flex flex-wrap gap-2"><Badge>{daily?.period.label || "loading"}</Badge><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{methodLabel}</Badge>{materialization ? <Badge className={materialization.fresh ? "border-orange-400/40 bg-orange-400/15 text-orange-100" : "border-amber-400/40 bg-amber-400/10 text-amber-100"}>{materialization.fresh ? "materialized fresh" : `${staleCount} stale/missing`}</Badge> : materializationError ? <Badge className="border-amber-400/40 bg-amber-400/10 text-amber-100">materialization unavailable</Badge> : null}{loading ? <Badge className="border-orange-400/40 bg-orange-400/15 text-orange-100">loading</Badge> : null}</div>
      </div>
      <div className="mt-4 grid gap-2 md:grid-cols-[10rem_1fr_1fr]">
        <Select value={preset} onChange={(event) => setPreset(event.target.value)}><option value="7d">7 дней</option><option value="28d">28 дней</option><option value="90d">90 дней</option><option value="year">Год</option><option value="all">Все время</option><option value="custom">Custom</option></Select>
        <Input type="date" value={customFrom} disabled={preset !== "custom"} onChange={(event) => setCustomFrom(event.target.value)} />
        <Input type="date" value={customTo} disabled={preset !== "custom"} onChange={(event) => setCustomTo(event.target.value)} />
      </div>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-zinc-800 bg-zinc-950/70 p-2 text-xs text-zinc-500">
        <span>Materialized daily loads ({materializationRangeLabel}): {materialization?.fresh ? "fresh" : materialization ? `${materialization.missing_dates.length} missing, ${materialization.stale_dates.length} stale` : materializationError ? `status unavailable: ${materializationError}` : "checking"}</span>
        <Button type="button" variant="secondary" disabled={materializing || loading || Boolean(materialization?.fresh)} onClick={backfillMaterialization}>{materializing ? "Backfilling..." : `Backfill ${materializationRangeLabel}`}</Button>
      </div>
      {error ? <p className="mt-3 rounded-md border border-rose-400/20 bg-rose-400/10 px-2 py-1.5 text-xs text-rose-100">{error}</p> : null}
    </Card>

    <div className="grid gap-3 md:grid-cols-4">
      <MetricCard label="CTL" value={current?.ctl.value ?? "--"} hint={current?.ctl.method || "42-day EWMA"} explainer={<CalculationExplainer><p>Chronic Training Load is a long-window EWMA of daily load. It approximates fitness trend, not readiness by itself.</p></CalculationExplainer>} />
      <MetricCard label="ATL" value={current?.atl.value ?? "--"} hint={current?.atl.method || "7-day EWMA"} explainer={<CalculationExplainer><p>Acute Training Load reacts faster to recent sessions. A sharp ATL rise can indicate short-term fatigue.</p></CalculationExplainer>} />
      <MetricCard label="TSB" value={current?.tsb.value ?? "--"} hint={current?.tsb.method || "CTL - ATL"} explainer={<CalculationExplainer><p>Training Stress Balance is CTL minus ATL. Negative values often mean higher recent fatigue; positive values often mean fresher legs.</p></CalculationExplainer>} />
      <MetricCard label="method" value={methodLabel} hint="load source" />
      <MetricCard label="monotony" value={latestWeek?.monotony ?? "--"} explainer={<CalculationExplainer><p>Monotony compares average daily load with day-to-day variation. Higher values can flag repetitive loading.</p></CalculationExplainer>} />
      <MetricCard label="strain" value={latestWeek?.strain ?? "--"} explainer={<CalculationExplainer><p>Strain combines weekly load with monotony. It highlights weeks that are both heavy and repetitive.</p></CalculationExplainer>} />
      <MetricCard label="hard days" value={latestWeek?.hard_sessions ?? 0} hint="quality sessions" />
      <MetricCard label="recovery days" value={latestWeek?.recovery_days ?? 0} hint="easy or rest days" />
    </div>

    <div className="grid gap-4 xl:grid-cols-[1fr_1fr]">
      <LoadBarChart title="Daily load" points={dailyPoints.slice(-14)} label={(point) => formatDate(point.date)} value={(point) => point.load} suffix="au" />
      <WeeklyLoadChart points={weeklyPoints.slice(-10)} />
    </div>

    <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
      <FitnessFatigueChart fitness={fitness} />
      <TrainingLoadWarnings warnings={warnings} />
    </div>

    <div className="grid gap-4 xl:grid-cols-[1fr_1fr]">
      <HardSessionSpacing hardDays={hardDays} />
      <RecoveryDaysCard recoveryDays={recoveryDays} />
    </div>
  </div>
}

function ZonesAnalytics() {
  const [preset, setPreset] = useState("28d")
  const [customFrom, setCustomFrom] = useState("")
  const [customTo, setCustomTo] = useState("")
  const [granularity, setGranularity] = useState("week")
  const [distribution, setDistribution] = useState<ZoneDistribution | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => {
    const query = analyticsQuery(preset, customFrom, customTo)
    const params = `${query}${query ? "&" : "?"}granularity=${granularity}`
    let cancelled = false
    async function loadZones() {
      setLoading(true)
      setError("")
      try {
        await devLogin()
        const next = await api.zoneDistribution(params)
        if (!cancelled) setDistribution(next)
      } catch (caught) {
        console.error(caught)
        if (!cancelled) setError("Zones Analytics API недоступен")
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void loadZones()
    return () => { cancelled = true }
  }, [preset, customFrom, customTo, granularity])

  const meta = distribution?.metadata || {}
  const classified = Number(meta.classified_actual_duration_seconds || 0)
  const unclassified = Number(meta.unclassified_actual_duration_seconds || 0)
  const total = classified + unclassified
  const lowCompliance = distribution?.low_intensity_compliance
  const lowTarget = lowCompliance?.target || {}
  const lowTargetLabel = `${Number(lowTarget.lower_percentage ?? 75).toFixed(0)}-${Number(lowTarget.upper_percentage ?? 85).toFixed(0)}%`

  return <div className="grid gap-4">
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><p className="font-mono text-[10px] uppercase tracking-[0.18em] text-zinc-500">Zones Analytics</p><h2 className="mt-2 text-lg font-semibold text-white">Intensity distribution and zone governance</h2><p className="mt-2 max-w-2xl text-xs leading-5 text-zinc-500">HR, pace and RPE zones with threshold-based precedence, VDOT pace fallback, Seiler 3-zone split, weekly/monthly buckets and planned-vs-actual distribution.</p></div>
        <div className="flex flex-wrap gap-2"><Badge>{distribution?.period.label || "loading"}</Badge><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{granularity}</Badge>{loading ? <Badge className="border-orange-400/40 bg-orange-400/15 text-orange-100">loading</Badge> : null}</div>
      </div>
      <div className="mt-4 grid gap-2 md:grid-cols-[10rem_8rem_1fr_1fr]">
        <Select value={preset} onChange={(event) => setPreset(event.target.value)}><option value="7d">7 дней</option><option value="28d">28 дней</option><option value="90d">90 дней</option><option value="year">Год</option><option value="all">Все время</option><option value="custom">Custom</option></Select>
        <Select value={granularity} onChange={(event) => setGranularity(event.target.value)}><option value="week">Week</option><option value="month">Month</option></Select>
        <Input type="date" value={customFrom} disabled={preset !== "custom"} onChange={(event) => setCustomFrom(event.target.value)} />
        <Input type="date" value={customTo} disabled={preset !== "custom"} onChange={(event) => setCustomTo(event.target.value)} />
      </div>
      {error ? <p className="mt-3 rounded-md border border-rose-400/20 bg-rose-400/10 px-2 py-1.5 text-xs text-rose-100">{error}</p> : null}
    </Card>

    <div className="grid gap-3 md:grid-cols-4">
      <Card className="p-3"><Stat label="classified" value={formatDuration(classified)} /></Card>
      <Card className="p-3"><Stat label="coverage" value={total ? `${Math.round(classified / total * 100)}%` : "--"} /></Card>
      <Card className="p-3"><Stat label="activities" value={Number(meta.activity_count || 0)} /></Card>
      <Card className="p-3"><Stat label="planned workouts" value={Number(meta.planned_workout_count || 0)} /></Card>
    </div>

    <Card className="p-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><p className="font-semibold text-white">Weekly low-intensity target</p><p className="mt-1 text-xs text-zinc-500">Seiler low share for the latest requested {distribution?.granularity || "week"} bucket. Target defaults to endurance guidance until phase/athlete-level tuning is available.</p></div>
        <div className="flex flex-wrap gap-2"><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">target {lowTargetLabel}</Badge><Badge className={signalClass(lowCompliance?.status)}>{lowCompliance?.status || "unknown"}</Badge><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">actual {lowCompliance?.low_percentage === null || lowCompliance?.low_percentage === undefined ? "--" : `${lowCompliance.low_percentage.toFixed(1)}%`}</Badge></div>
      </div>
    </Card>

    <div className="grid gap-4 xl:grid-cols-[1fr_1fr]">
      <ZoneDistributionBars title="5-zone actual" items={distribution?.actual_five_zone || []} />
      <ZoneDistributionBars title="Seiler 3-zone" items={distribution?.seiler_three_zone || []} />
    </div>

    <div className="grid gap-4 xl:grid-cols-3">
      <ZoneDistributionBars title="Heart-rate distribution" items={distribution?.actual_hr || []} compact />
      <ZoneDistributionBars title="Pace distribution" items={distribution?.actual_pace || []} compact />
      <ZoneDistributionBars title="RPE distribution" items={distribution?.actual_rpe || []} compact />
    </div>

    <div className="grid gap-4 xl:grid-cols-[1fr_1fr]">
      <PlannedActualZones rows={distribution?.planned_vs_actual || []} />
      <ZoneTimeBuckets distribution={distribution} />
    </div>

    <div className="grid gap-4 xl:grid-cols-[1fr_1fr]">
      <Card><CardHeader><div><CardTitle>Configured zones</CardTitle><p className="text-xs text-zinc-500">Manual overrides suppress calculated zones by type; calculated zones show method and confidence.</p></div><Badge>{(distribution?.zones.hr.length || 0) + (distribution?.zones.pace.length || 0) + (distribution?.zones.rpe.length || 0)} zones</Badge></CardHeader><div className="grid gap-4 p-4"><ZoneTable title="Heart rate" zones={distribution?.zones.hr || []} /><ZoneTable title="Pace" zones={distribution?.zones.pace || []} /><ZoneTable title="RPE" zones={distribution?.zones.rpe || []} /></div></Card>
      <Card><CardHeader><CardTitle>Classification notes</CardTitle><Badge>{unclassified ? "partial" : "covered"}</Badge></CardHeader><div className="grid gap-2 p-4 text-xs text-zinc-400"><p>Priority: {(meta.classification_priority as string[] | undefined)?.join(" -> ") || "hr -> pace -> rpe"}.</p><p>Unclassified duration: {formatDuration(unclassified)}. Usually this means missing HR/pace/RPE data or no matching zone range.</p><p>Planned distribution estimates workouts from active plans using intensity/workout type and planned duration.</p></div></Card>
    </div>
  </div>
}

function ZoneDistributionBars({ title, items, compact = false }: { title: string; items: ZoneDistributionItem[]; compact?: boolean }) {
  return <Card>
    <CardHeader><CardTitle>{title}</CardTitle><Badge>{items.length} zones</Badge></CardHeader>
    <div className="grid gap-2 p-4">
      {items.map((item) => <div key={`${title}-${item.zone_key}`} className={cn("grid items-center gap-2 text-[11px]", compact ? "grid-cols-[5.5rem_1fr_4rem]" : "grid-cols-[7rem_1fr_6rem]")}><span className="truncate text-zinc-400">{item.label}</span><div className="h-2 rounded bg-zinc-900"><div className="h-full rounded bg-orange-400" style={{ width: `${Math.max(item.percentage ? 4 : 0, item.percentage)}%` }} /></div><strong className="text-right text-zinc-300">{item.percentage.toFixed(1)}%</strong><span className="col-span-full text-zinc-600">{formatDuration(item.duration_seconds)} · {item.source_count} samples</span></div>)}
      {!items.length ? <p className="text-xs text-zinc-500">Нет данных для распределения.</p> : null}
    </div>
  </Card>
}

function PlannedActualZones({ rows }: { rows: ZonePlannedActual[] }) {
  return <Card>
    <CardHeader><div><CardTitle>Planned vs actual</CardTitle><p className="text-xs text-zinc-500">Zone distribution from active plan intensity compared with classified actual duration.</p></div><Badge>{rows.length} rows</Badge></CardHeader>
    <div className="overflow-x-auto">
      <table className="w-full min-w-[620px] text-left text-xs">
        <thead className="border-b border-zinc-800 text-[10px] uppercase tracking-[0.14em] text-zinc-500"><tr><th className="px-4 py-2">Zone</th><th>Planned</th><th>Actual</th><th>Delta</th></tr></thead>
        <tbody>{rows.map((row) => <tr key={row.zone_key} className="border-b border-zinc-900 last:border-0"><td className="px-4 py-2 font-medium text-white">{row.label}<div className="font-mono text-[10px] text-zinc-600">{row.zone_key}</div></td><td>{formatDuration(row.planned_duration_seconds)}<div className="text-[11px] text-zinc-500">{row.planned_percentage.toFixed(1)}%</div></td><td>{formatDuration(row.actual_duration_seconds)}<div className="text-[11px] text-zinc-500">{row.actual_percentage.toFixed(1)}%</div></td><td><Badge className={Math.abs(row.diff_percentage) >= 15 ? "border-orange-400/40 bg-orange-400/15 text-orange-100" : "border-zinc-700 bg-zinc-900 text-zinc-300"}>{row.diff_percentage > 0 ? "+" : ""}{row.diff_percentage.toFixed(1)}%</Badge></td></tr>)}</tbody>
      </table>
      {!rows.length ? <p className="p-4 text-xs text-zinc-500">Нет planned-vs-actual rows.</p> : null}
    </div>
  </Card>
}

function ZoneTimeBuckets({ distribution }: { distribution: ZoneDistribution | null }) {
  const buckets = distribution?.time_buckets.slice(-8) || []
  return <Card>
    <CardHeader><div><CardTitle>Time in zones by {distribution?.granularity || "week"}</CardTitle><p className="text-xs text-zinc-500">Stacked 5-zone duration buckets for recent periods.</p></div><Badge>{buckets.length} buckets</Badge></CardHeader>
    <div className="grid gap-3 p-4">
      {buckets.map((bucket) => <div key={bucket.period_label} className="grid gap-1 text-[11px]"><div className="flex items-center justify-between gap-2"><span className="text-zinc-400">{bucket.period_label}</span><span className="text-zinc-500">{formatDuration(bucket.total_duration_seconds)}</span></div><div className="flex h-2 overflow-hidden rounded bg-zinc-900">{bucket.items.map((item, index) => <div key={`${bucket.period_label}-${item.zone_key}`} className={cn("h-full", index % 2 === 0 ? "bg-orange-400" : "bg-orange-300/60")} style={{ width: `${item.percentage}%` }} title={`${item.label}: ${item.percentage}%`} />)}</div></div>)}
      {!buckets.length ? <p className="text-xs text-zinc-500">Нет bucket данных за выбранный период.</p> : null}
    </div>
  </Card>
}

function LoadBarChart({ title, points, label, value, suffix }: { title: string; points: TrainingLoadDailyPoint[]; label: (point: TrainingLoadDailyPoint) => string; value: (point: TrainingLoadDailyPoint) => number; suffix: string }) {
  const max = Math.max(1, ...points.map(value))
  return <Card>
    <CardHeader><CardTitle>{title}</CardTitle><Badge>{points.length} days</Badge></CardHeader>
    <div className="grid gap-2 p-4">
      {points.length ? points.map((point) => {
        const numeric = value(point)
        return <div key={point.date} className="grid grid-cols-[5rem_1fr_4.5rem] items-center gap-2 text-[11px]"><span className="truncate text-zinc-500">{label(point)}</span><div className="h-2 rounded bg-zinc-900"><div className={cn("h-full rounded", point.hard_session ? "bg-orange-400" : point.recovery_day ? "bg-zinc-500" : "bg-orange-300/70")} style={{ width: `${Math.max(4, numeric / max * 100)}%` }} /></div><strong className="text-right text-zinc-300">{numeric.toFixed(1)} {suffix}</strong></div>
      }) : <p className="text-xs text-zinc-500">Нет daily load points.</p>}
    </div>
  </Card>
}

function WeeklyLoadChart({ points }: { points: TrainingLoadWeekly["points"] }) {
  const max = Math.max(1, ...points.map((point) => point.load))
  return <Card>
    <CardHeader><CardTitle>Weekly load</CardTitle><Badge>{points.length} weeks</Badge></CardHeader>
    <div className="grid gap-2 p-4">
      {points.length ? points.map((point) => <div key={point.week_start} className="grid grid-cols-[6rem_1fr_5rem] items-center gap-2 text-[11px]"><span className="truncate text-zinc-500">{formatDate(point.week_start)}</span><div className="h-2 rounded bg-zinc-900"><div className="h-full rounded bg-orange-400" style={{ width: `${Math.max(4, point.load / max * 100)}%` }} /></div><strong className="text-right text-zinc-300">{point.load.toFixed(1)} au</strong></div>) : <p className="text-xs text-zinc-500">Нет weekly load points.</p>}
    </div>
  </Card>
}

function FitnessFatigueChart({ fitness }: { fitness: TrainingLoadFitnessFatigue | null }) {
  const points = fitness?.points.slice(-10) || []
  return <Card>
    <CardHeader><div><CardTitle>CTL / ATL / TSB</CardTitle><p className="text-xs text-zinc-500">{fitness?.explanation || "EWMA load heuristics."}</p></div><Badge>{points.length} points</Badge></CardHeader>
    <div className="overflow-x-auto p-4">
      <table className="w-full min-w-[620px] text-left text-xs">
        <thead className="border-b border-zinc-800 text-[10px] uppercase tracking-[0.14em] text-zinc-500"><tr><th className="px-3 py-2">Date</th><th>Load</th><th>CTL</th><th>ATL</th><th>TSB</th></tr></thead>
        <tbody>{points.map((point) => <tr key={point.date} className="border-b border-zinc-900 last:border-0"><td className="px-3 py-2 font-medium text-white">{formatDate(point.date)}</td><td>{point.load.toFixed(1)}</td><td>{point.ctl.toFixed(1)}</td><td>{point.atl.toFixed(1)}</td><td><Badge className={point.tsb <= -10 ? "border-orange-400/40 bg-orange-400/15 text-orange-100" : point.tsb >= 5 ? "border-zinc-700 bg-zinc-900 text-zinc-300" : "border-zinc-800 bg-zinc-950 text-zinc-400"}>{point.tsb.toFixed(1)}</Badge></td></tr>)}</tbody>
      </table>
      {!points.length ? <p className="p-3 text-xs text-zinc-500">Нет fitness/fatigue points.</p> : null}
    </div>
  </Card>
}

function TrainingLoadWarnings({ warnings }: { warnings: TrainingLoadWarning[] }) {
  return <Card>
    <CardHeader><CardTitle>Load alerts</CardTitle><Badge>{warnings.length} signals</Badge></CardHeader>
    <div className="grid gap-2 p-4">
      {warnings.map((warning) => <div key={`${warning.title}-${warning.metric || "signal"}`} className={cn("rounded-md border px-3 py-2 text-xs", signalClass(warning.severity))}><div className="flex flex-wrap items-center justify-between gap-2"><p className="font-semibold text-white">{warning.title}</p><Badge className="border-zinc-700 bg-zinc-950 text-zinc-300">{warning.severity}</Badge></div><p className="mt-1 leading-5 text-zinc-300">{warning.message}</p>{warning.reasons.length ? <p className="mt-1 text-[11px] text-zinc-500">{warning.reasons.slice(0, 3).join(" · ")}</p> : null}</div>)}
      {!warnings.length ? <p className="text-xs text-zinc-500">Нет load alerts.</p> : null}
    </div>
  </Card>
}

function HardSessionSpacing({ hardDays }: { hardDays: TrainingLoadDailyPoint[] }) {
  return <Card>
    <CardHeader><CardTitle>Hard sessions spacing</CardTitle><Badge>{hardDays.length} hard days</Badge></CardHeader>
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-left text-xs">
        <thead className="border-b border-zinc-800 text-[10px] uppercase tracking-[0.14em] text-zinc-500"><tr><th className="px-4 py-2">Date</th><th>Load</th><th>Gap</th><th>Reasons</th></tr></thead>
        <tbody>{hardDays.map((day, index) => {
          const previous = hardDays[index - 1]
          const gap = previous ? Math.round((dateFromISO(day.date).getTime() - dateFromISO(previous.date).getTime()) / 86400000) : null
          return <tr key={day.date} className="border-b border-zinc-900 last:border-0 align-top"><td className="px-4 py-2 font-medium text-white">{formatDate(day.date)}</td><td>{day.load.toFixed(1)} au</td><td><Badge className={gap !== null && gap < 2 ? "border-orange-400/40 bg-orange-400/15 text-orange-100" : "border-zinc-700 bg-zinc-900 text-zinc-300"}>{gap === null ? "first" : `${gap} d`}</Badge></td><td className="max-w-[16rem] text-zinc-500">{day.hard_reasons.join(" · ")}</td></tr>
        })}</tbody>
      </table>
      {!hardDays.length ? <p className="p-4 text-xs text-zinc-500">Hard sessions не обнаружены.</p> : null}
    </div>
  </Card>
}

function RecoveryDaysCard({ recoveryDays }: { recoveryDays: TrainingLoadDailyPoint[] }) {
  return <Card>
    <CardHeader><CardTitle>Recovery days</CardTitle><Badge>{recoveryDays.length} recent</Badge></CardHeader>
    <div className="divide-y divide-zinc-800">
      {recoveryDays.map((day) => <div key={day.date} className="grid gap-2 px-4 py-3 text-xs md:grid-cols-[5rem_1fr_auto]"><div className="font-semibold text-white">{formatDate(day.date)}</div><div><p className="text-zinc-300">{day.load.toFixed(1)} au · {formatDuration(day.duration_seconds)}</p><p className="mt-1 text-zinc-500">{day.activity_count ? `${day.activity_count} light activity` : "No recorded activity"}</p></div><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">recovery</Badge></div>)}
      {!recoveryDays.length ? <p className="p-4 text-xs text-zinc-500">Recovery days за последнюю неделю не найдены.</p> : null}
    </div>
  </Card>
}

function confidenceClass(confidence?: string) {
  if (confidence === "high") return "border-zinc-600 bg-zinc-900 text-zinc-100"
  if (confidence === "medium") return "border-orange-400/40 bg-orange-400/15 text-orange-100"
  return "border-rose-400/30 bg-rose-500/10 text-rose-200"
}

function performanceResultPayload(form: HTMLFormElement) {
  const data = new FormData(form)
  const distance = numberOrNull(data.get("distance_km"))
  const durationMinutes = numberOrNull(data.get("duration_minutes"))
  const activityId = numberOrNull(data.get("activity_id"))
  const resultDate = stringOrNull(data.get("result_date"))
  if (!distance || !durationMinutes) throw new Error("Укажите дистанцию и время результата")
  return {
    result_type: stringOrNull(data.get("result_type")) || "race",
    name: stringOrNull(data.get("name")) || "Race result",
    result_date: resultDate ? new Date(resultDate).toISOString() : null,
    distance_km: distance,
    duration_seconds: Math.round(durationMinutes * 60),
    activity_id: activityId ? Math.round(activityId) : null,
    source: activityId ? "activity" : "manual",
    terrain: stringOrNull(data.get("terrain")) || "road",
    weather: stringOrNull(data.get("weather")),
    elevation_gain_m: numberOrNull(data.get("elevation_gain_m")),
    temperature_c: numberOrNull(data.get("temperature_c")),
    is_noisy: data.get("is_noisy") === "on",
    notes: stringOrNull(data.get("notes")),
  }
}

function PerformanceAnalytics() {
  const [results, setResults] = useState<PerformanceResult[]>([])
  const [vdot, setVdot] = useState<PerformanceVdot | null>(null)
  const [predictions, setPredictions] = useState<PerformancePrediction[]>([])
  const [pbs, setPbs] = useState<PerformancePb[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")

  async function loadPerformance() {
    setLoading(true)
    setError("")
    try {
      await devLogin()
      const [nextResults, nextVdot, nextPredictions, nextPbs] = await Promise.all([
        api.performanceResults(),
        api.performanceVdot(),
        api.performancePredictions(),
        api.performancePbs(),
      ])
      setResults(nextResults)
      setVdot(nextVdot)
      setPredictions(nextPredictions)
      setPbs(nextPbs)
    } catch (caught) {
      console.error(caught)
      setError(caught instanceof Error ? caught.message : "Performance API недоступен")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void loadPerformance() }, [])

  async function submitResult(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    setSaving(true)
    setError("")
    try {
      await api.createPerformanceResult(performanceResultPayload(form))
      form.reset()
      await loadPerformance()
    } catch (caught) {
      console.error(caught)
      setError(caught instanceof Error ? caught.message : "Не удалось сохранить результат")
    } finally {
      setSaving(false)
    }
  }

  const raceResults = results.filter((result) => result.result_type === "race")
  const timeTrials = results.filter((result) => result.result_type === "time_trial")
  const source = vdot?.source
  const latestPb = pbs[0]

  return <div className="grid gap-4">
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><p className="font-mono text-[10px] uppercase tracking-[0.18em] text-zinc-500">Performance Analytics</p><h2 className="mt-2 text-lg font-semibold text-white">Race readiness and equivalent performances</h2><p className="mt-2 max-w-2xl text-xs leading-5 text-zinc-500">Race/time trial results drive VDOT, Riegel predictions, personal bests, threshold trend and pace zones. Easy runs are not used as VDOT sources.</p></div>
        <div className="flex flex-wrap gap-2"><Badge className={confidenceClass(vdot?.confidence)}>{vdot?.confidence || "low"} confidence</Badge>{loading ? <Badge className="border-orange-400/40 bg-orange-400/15 text-orange-100">loading</Badge> : null}</div>
      </div>
      {error ? <p className="mt-3 rounded-md border border-rose-400/20 bg-rose-400/10 px-2 py-1.5 text-xs text-rose-100">{error}</p> : null}
      {vdot?.warnings.length ? <div className="mt-3 grid gap-2">{vdot.warnings.map((warning) => <p key={warning} className="rounded-md border border-orange-400/20 bg-orange-400/10 px-2 py-1.5 text-xs text-orange-100">{warning}</p>)}</div> : null}
    </Card>

    <div className="grid gap-3 md:grid-cols-4">
      <Card className="p-3"><Stat label="VDOT" value={vdot?.estimate?.value ?? "--"} /></Card>
      <Card className="p-3"><Stat label="source" value={source ? `${source.distance_km.toFixed(1)} km` : "--"} /></Card>
      <Card className="p-3"><Stat label="predictions" value={predictions.length} /></Card>
      <Card className="p-3"><Stat label="PB rows" value={pbs.length} /></Card>
    </div>

    <div className="grid gap-4 xl:grid-cols-[24rem_1fr]">
      <Card>
        <CardHeader><div><CardTitle>Add result</CardTitle><p className="text-xs text-zinc-500">Сохраняйте только races или controlled time trials.</p></div><Badge>manual</Badge></CardHeader>
        <form onSubmit={submitResult} className="grid gap-3 p-4 text-xs md:grid-cols-2 xl:grid-cols-1">
          <Field label="Тип"><Select name="result_type" defaultValue="race"><option value="race">Race</option><option value="time_trial">Time trial</option></Select></Field>
          <Field label="Название"><Input name="name" placeholder="5K race / 20 min TT" /></Field>
          <Field label="Дата"><Input name="result_date" type="datetime-local" /></Field>
          <Field label="Дистанция, км"><Input name="distance_km" type="number" min="0.1" max="500" step="0.01" placeholder="5.00" /></Field>
          <Field label="Время, минуты"><Input name="duration_minutes" type="number" min="0.1" max="2880" step="0.1" placeholder="20.0" /></Field>
          <Field label="Activity ID"><Input name="activity_id" type="number" min="1" placeholder="optional" /></Field>
          <Field label="Покрытие"><Select name="terrain" defaultValue="road"><option value="road">Road</option><option value="track">Track</option><option value="trail">Trail</option><option value="mixed">Mixed</option><option value="treadmill">Treadmill</option><option value="unknown">Unknown</option></Select></Field>
          <Field label="Погода"><Input name="weather" placeholder="heat, wind, rain" /></Field>
          <Field label="Набор, м"><Input name="elevation_gain_m" type="number" min="0" step="1" placeholder="optional" /></Field>
          <Field label="Температура C"><Input name="temperature_c" type="number" min="-50" max="60" step="0.5" placeholder="optional" /></Field>
          <label className="flex h-8 items-center gap-2 rounded-md border border-zinc-800 bg-zinc-950 px-2.5 text-zinc-400"><input name="is_noisy" type="checkbox" /> noisy source</label>
          <Field label="Заметки"><Input name="notes" placeholder="optional" /></Field>
          <Button type="submit" size="sm" disabled={saving}>{saving ? "Saving..." : "Save result"}</Button>
        </form>
      </Card>

      <Card>
        <CardHeader><div><CardTitle>VDOT source</CardTitle><p className="text-xs text-zinc-500">Source selection prefers recent race/time trial results with reliable conditions.</p></div><Badge className={confidenceClass(vdot?.confidence)}>{vdot?.confidence || "low"}</Badge></CardHeader>
        <div className="grid gap-3 p-4 text-xs md:grid-cols-[1fr_1fr]">
          <div className="rounded-md border border-zinc-800 bg-zinc-950 p-3"><p className="text-zinc-500">Estimated VDOT</p><p className="mt-1 text-3xl font-semibold text-white">{vdot?.estimate?.value ?? "--"}</p><p className="mt-1 text-zinc-500">{vdot?.estimate ? `${vdot.estimate.method} · ${vdot.estimate.source_reference}` : "No eligible race/time trial yet."}</p></div>
          <div className="rounded-md border border-zinc-800 bg-zinc-950 p-3"><p className="text-zinc-500">Selected result</p><p className="mt-1 text-lg font-semibold text-white">{source?.name || "--"}</p><p className="mt-1 text-zinc-500">{source ? `${source.distance_km.toFixed(2)} км · ${formatDuration(source.duration_seconds)} · ${source.age_days ?? 0} days old` : "Add a result >= 3 km."}</p>{source?.noisy_reasons.length ? <p className="mt-2 text-orange-200">Noisy: {source.noisy_reasons.join(" · ")}</p> : null}</div>
        </div>
      </Card>
    </div>

    <div className="grid gap-4 xl:grid-cols-2">
      <PerformanceResultsTable title="Race results" results={raceResults} />
      <PerformanceResultsTable title="Time trials" results={timeTrials} />
    </div>

    <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
      <PerformancePredictions predictions={predictions} />
      <PerformancePbs pbs={pbs} latestPb={latestPb} />
    </div>

    <div className="grid gap-4 xl:grid-cols-[1fr_1fr]">
      <PerformanceThresholdTrend points={vdot?.threshold_trend || []} />
      <PerformancePaceZones zones={vdot?.pace_zones || []} />
    </div>
  </div>
}

function PerformanceResultsTable({ title, results }: { title: string; results: PerformanceResult[] }) {
  return <Card>
    <CardHeader><CardTitle>{title}</CardTitle><Badge>{results.length} rows</Badge></CardHeader>
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-left text-xs">
        <thead className="border-b border-zinc-800 text-[10px] uppercase tracking-[0.14em] text-zinc-500"><tr><th className="px-4 py-2">Result</th><th>Date</th><th>Distance</th><th>Time</th><th>Pace</th><th>VDOT</th><th>Signal</th></tr></thead>
        <tbody>{results.map((result) => <tr key={result.id} className="border-b border-zinc-900 last:border-0 align-top hover:bg-zinc-900/60"><td className="px-4 py-2 font-medium text-white">{result.name}<div className="text-[11px] text-zinc-500">#{result.id} · {result.source} · {result.terrain}</div></td><td className="text-zinc-400">{formatDateTime(result.result_date)}</td><td>{result.distance_km.toFixed(2)} км</td><td>{formatDuration(result.duration_seconds)}</td><td>{formatPace(result.pace_seconds_per_km)}/км</td><td>{result.estimated_vdot?.value ?? "--"}</td><td><Badge className={result.is_noisy ? "border-orange-400/40 bg-orange-400/15 text-orange-100" : confidenceClass(result.estimated_vdot?.confidence)}>{result.is_noisy ? "noisy" : result.estimated_vdot?.confidence || "low"}</Badge>{result.noisy_reasons.length ? <div className="mt-1 max-w-[11rem] text-[10px] text-zinc-500">{result.noisy_reasons.join(" · ")}</div> : null}</td></tr>)}</tbody>
      </table>
      {!results.length ? <p className="p-4 text-xs text-zinc-500">Нет сохраненных результатов этого типа.</p> : null}
    </div>
  </Card>
}

function PerformancePredictions({ predictions }: { predictions: PerformancePrediction[] }) {
  return <Card>
    <CardHeader><div><CardTitle>Equivalent race predictions</CardTitle><p className="text-xs text-zinc-500">Riegel predictions show confidence and extrapolation warnings.</p></div><Badge>{predictions.length} targets</Badge></CardHeader>
    <div className="overflow-x-auto">
      <table className="w-full min-w-[680px] text-left text-xs">
        <thead className="border-b border-zinc-800 text-[10px] uppercase tracking-[0.14em] text-zinc-500"><tr><th className="px-4 py-2">Target</th><th>Prediction</th><th>Pace</th><th>Source</th><th>Confidence</th><th>Notes</th></tr></thead>
        <tbody>{predictions.map((prediction) => <tr key={prediction.label} className="border-b border-zinc-900 last:border-0 align-top hover:bg-zinc-900/60"><td className="px-4 py-2 font-semibold text-white">{prediction.label}<div className="text-[11px] text-zinc-500">{prediction.target_distance_km} км</div></td><td>{formatDuration(prediction.predicted_duration_seconds)}</td><td>{formatPace(prediction.predicted_pace_seconds_per_km)}/км</td><td>{prediction.source_result_name || "--"}<div className="text-[11px] text-zinc-500">ratio {prediction.extrapolation_ratio ?? "--"}</div></td><td><Badge className={confidenceClass(prediction.confidence)}>{prediction.confidence}</Badge></td><td className="max-w-[15rem] text-zinc-500">{prediction.warnings.length ? prediction.warnings.join(" · ") : prediction.extrapolation_limited ? "extrapolation limited" : prediction.noisy ? "noisy source" : "within range"}</td></tr>)}</tbody>
      </table>
      {!predictions.length ? <p className="p-4 text-xs text-zinc-500">Нужен race/time trial результат &gt;= 3 км для прогнозов.</p> : null}
    </div>
  </Card>
}

function PerformancePbs({ pbs, latestPb }: { pbs: PerformancePb[]; latestPb?: PerformancePb }) {
  return <Card>
    <CardHeader><div><CardTitle>Personal bests</CardTitle><p className="text-xs text-zinc-500">PB uses near-exact race/time trial distances only.</p></div><Badge>{latestPb ? latestPb.label : "--"}</Badge></CardHeader>
    <div className="divide-y divide-zinc-800">
      {pbs.map((pb) => <div key={pb.label} className="grid gap-2 px-4 py-3 text-xs md:grid-cols-[4.5rem_1fr_auto]"><div className="font-semibold text-white">{pb.label}</div><div><p className="text-zinc-300">{formatDuration(pb.normalized_duration_seconds)} · {formatPace(pb.pace_seconds_per_km)}/км</p><p className="mt-1 text-zinc-500">{pb.name} · {formatDateTime(pb.result_date)} · actual {pb.distance_km.toFixed(2)} км</p></div><Badge className={pb.is_noisy ? "border-orange-400/40 bg-orange-400/15 text-orange-100" : "border-zinc-700 bg-zinc-900 text-zinc-300"}>VDOT {pb.estimated_vdot?.value ?? "--"}</Badge></div>)}
      {!pbs.length ? <p className="p-4 text-xs text-zinc-500">Нет PB по стандартным дистанциям.</p> : null}
    </div>
  </Card>
}

function PerformanceThresholdTrend({ points }: { points: PerformanceVdot["threshold_trend"] }) {
  const values = points.map((point) => point.threshold_pace_seconds_per_km).filter((value) => Number.isFinite(value))
  const min = Math.max(1, Math.min(...values, 99999))
  return <Card>
    <CardHeader><div><CardTitle>Threshold trend</CardTitle><p className="text-xs text-zinc-500">Estimated 60-minute pace from race/time trial results.</p></div><Badge>{points.length} points</Badge></CardHeader>
    <div className="grid gap-2 p-4">
      {points.map((point) => <div key={point.result_id} className="grid grid-cols-[6rem_1fr_4.5rem] items-center gap-2 text-[11px]"><span className="truncate text-zinc-500">{new Date(point.result_date).toLocaleDateString("ru-RU", { month: "short", day: "2-digit" })}</span><div className="h-2 rounded bg-zinc-900"><div className="h-full rounded bg-orange-400" style={{ width: `${Math.max(4, min / point.threshold_pace_seconds_per_km * 100)}%` }} /></div><strong className="text-right text-zinc-300">{formatPace(point.threshold_pace_seconds_per_km)}</strong></div>)}
      {!points.length ? <p className="text-xs text-zinc-500">Добавьте результаты, чтобы увидеть trend.</p> : null}
    </div>
  </Card>
}

function formatPerformanceZoneRange(zone: PerformancePaceZone) {
  const format = (value: number | null) => value === null ? "--" : zone.unit === "seconds_per_km" ? `${formatPace(Math.round(value))}/км` : `${value}`
  return `${format(zone.lower_value)} - ${format(zone.upper_value)}`
}

function PerformancePaceZones({ zones }: { zones: PerformancePaceZone[] }) {
  return <Card>
    <CardHeader><div><CardTitle>Pace zones</CardTitle><p className="text-xs text-zinc-500">Derived from profile threshold pace or VDOT threshold estimate.</p></div><Badge>{zones.length} zones</Badge></CardHeader>
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-left text-xs">
        <thead className="border-b border-zinc-800 text-[10px] uppercase tracking-[0.14em] text-zinc-500"><tr><th className="px-4 py-2">Zone</th><th>Range</th><th>Method</th><th>Confidence</th></tr></thead>
        <tbody>{zones.map((zone) => <tr key={zone.zone_key} className="border-b border-zinc-900 last:border-0"><td className="px-4 py-2 font-medium text-white">{zone.label || zone.zone_key}<div className="text-[11px] text-zinc-500">{zone.zone_key}</div></td><td>{formatPerformanceZoneRange(zone)}</td><td><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{zone.method}</Badge><div className="mt-1 max-w-[16rem] text-[10px] text-zinc-600">{zone.source_reference}</div></td><td><Badge className={confidenceClass(zone.confidence)}>{zone.confidence}</Badge></td></tr>)}</tbody>
      </table>
      {!zones.length ? <p className="p-4 text-xs text-zinc-500">Нет данных для pace zones.</p> : null}
    </div>
  </Card>
}

function goalPayload(form: HTMLFormElement) {
  const data = new FormData(form)
  const targetTimeMinutes = numberOrNull(data.get("target_time_minutes"))
  const goalType = stringOrNull(data.get("goal_type")) || "race"
  const raceGoal = goalType === "race"
  return {
    title: stringOrNull(data.get("title")) || "Race goal",
    goal_type: goalType,
    target_value: numberOrNull(data.get("target_value")),
    unit: stringOrNull(data.get("unit")) || (goalType === "monthly_distance" || goalType === "long_run" ? "km" : goalType === "weekly_consistency" ? "days/week" : null),
    period_start: stringOrNull(data.get("period_start")),
    period_end: stringOrNull(data.get("period_end")),
    race_distance_km: raceGoal ? numberOrNull(data.get("race_distance_km")) : null,
    target_date: raceGoal ? stringOrNull(data.get("target_date")) : null,
    target_time_seconds: raceGoal && targetTimeMinutes ? Math.round(targetTimeMinutes * 60) : null,
    priority: raceGoal ? stringOrNull(data.get("priority")) : null,
    course_notes: raceGoal ? stringOrNull(data.get("course_notes")) : null,
    training_plan_id: numberOrNull(data.get("training_plan_id")),
    reason: stringOrNull(data.get("reason")),
  }
}

function goalTypeLabel(type: string) {
  return type.replace(/_/g, " ")
}

function goalProgressText(goal: RunningGoal) {
  const target = goal.progress.target === null || goal.progress.target === undefined ? "--" : goal.progress.target
  const value = goal.progress.value === null || goal.progress.value === undefined ? "--" : goal.progress.value
  return `${value}/${target} · ${Math.round((goal.progress.percentage || 0) * 100)}%`
}

function GoalsRaces() {
  const [goals, setGoals] = useState<RunningGoal[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [busyGoal, setBusyGoal] = useState<number | null>(null)
  const [error, setError] = useState("")

  async function loadGoals() {
    setLoading(true)
    setError("")
    try {
      await devLogin()
      setGoals(await api.goals())
    } catch (caught) {
      console.error(caught)
      setError(caught instanceof Error ? caught.message : "Goals API недоступен")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void loadGoals() }, [])

  async function submitGoal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    setSaving(true)
    setError("")
    try {
      await api.createGoal(goalPayload(form))
      form.reset()
      await loadGoals()
    } catch (caught) {
      console.error(caught)
      setError(caught instanceof Error ? caught.message : "Не удалось сохранить goal")
    } finally {
      setSaving(false)
    }
  }

  async function setGoalStatus(goal: RunningGoal, status: string) {
    setBusyGoal(goal.id)
    setError("")
    try {
      if (status === "completed" || status === "missed") await api.completeGoal(goal.id, { status })
      else await api.updateGoal(goal.id, { status })
      await loadGoals()
    } catch (caught) {
      console.error(caught)
      setError(caught instanceof Error ? caught.message : "Не удалось обновить goal")
    } finally {
      setBusyGoal(null)
    }
  }

  async function removeGoal(goal: RunningGoal) {
    setBusyGoal(goal.id)
    setError("")
    try {
      await api.deleteGoal(goal.id)
      await loadGoals()
    } catch (caught) {
      console.error(caught)
      setError(caught instanceof Error ? caught.message : "Не удалось удалить goal")
    } finally {
      setBusyGoal(null)
    }
  }

  const activeRace = goals.find((goal) => goal.goal_type === "race" && goal.status === "active")
  const activeGoals = goals.filter((goal) => goal.status === "active")

  return <div className="grid gap-4">
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><p className="font-mono text-[10px] uppercase tracking-[0.18em] text-zinc-500">Goals and Races</p><h2 className="mt-2 text-lg font-semibold text-white">Link race goals, plans and performance readiness</h2><p className="mt-2 max-w-2xl text-xs leading-5 text-zinc-500">Goals combine plan adherence, current VDOT/predictions, milestones and status transitions. Race goals require distance and target date.</p></div>
        <div className="flex flex-wrap gap-2"><Badge>{goals.length} goals</Badge><Badge className={loading ? "border-orange-400/40 bg-orange-400/15 text-orange-100" : signalClass(activeGoals.length ? "ok" : "warning")}>{loading ? "loading" : `${activeGoals.length} active`}</Badge></div>
      </div>
      {error ? <p className="mt-3 rounded-md border border-rose-400/20 bg-rose-400/10 px-2 py-1.5 text-xs text-rose-100">{error}</p> : null}
    </Card>

    <div className="grid gap-4 xl:grid-cols-[24rem_1fr]">
      <Card>
        <CardHeader><div><CardTitle>Create goal</CardTitle><p className="text-xs text-zinc-500">Race, consistency, monthly distance, long run or habit.</p></div><Badge>manual</Badge></CardHeader>
        <form onSubmit={submitGoal} className="grid gap-3 p-4 text-xs">
          <Field label="Title"><Input name="title" defaultValue="A race goal" /></Field>
          <Field label="Goal type"><Select name="goal_type" defaultValue="race"><option value="race">Race</option><option value="weekly_consistency">Weekly consistency</option><option value="monthly_distance">Monthly distance</option><option value="long_run">Long run</option><option value="custom_habit">Custom habit</option><option value="health">Health</option></Select></Field>
          <div className="grid gap-2 sm:grid-cols-2"><Field label="Target value"><Input name="target_value" type="number" min="0" step="0.1" placeholder="optional" /></Field><Field label="Unit"><Input name="unit" placeholder="km, days/week" /></Field></div>
          <div className="grid gap-2 sm:grid-cols-2"><Field label="Period start"><Input name="period_start" type="date" /></Field><Field label="Period end"><Input name="period_end" type="date" /></Field></div>
          <div className="rounded-md border border-zinc-800 bg-zinc-950 p-2">
            <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.16em] text-zinc-500">Race goal</p>
            <div className="grid gap-2 sm:grid-cols-2"><Field label="Distance, км"><Input name="race_distance_km" type="number" min="0.1" max="250" step="0.1" defaultValue="10" /></Field><Field label="Race date"><Input name="target_date" type="date" /></Field></div>
            <div className="mt-2 grid gap-2 sm:grid-cols-2"><Field label="Target time, мин"><Input name="target_time_minutes" type="number" min="1" max="2880" step="1" placeholder="optional" /></Field><Field label="Priority"><Select name="priority" defaultValue="b"><option value="a">A race</option><option value="b">B race</option><option value="c">C race</option></Select></Field></div>
            <Field label="Course notes"><Input name="course_notes" placeholder="terrain, elevation, logistics" /></Field>
          </div>
          <Field label="Linked plan ID"><Input name="training_plan_id" type="number" min="1" placeholder="optional" /></Field>
          <Field label="Reason"><Input name="reason" placeholder="why this matters" /></Field>
          <Button type="submit" size="sm" disabled={saving}>{saving ? "Saving..." : "Save goal"}</Button>
        </form>
      </Card>

      <div className="grid gap-4">
        {activeRace ? <GoalFocus goal={activeRace} /> : <Card className="p-4 text-sm text-zinc-500">No active race goal yet. Create one to see readiness, predicted range and milestones.</Card>}
        <div className="grid gap-3">{goals.map((goal) => <GoalCard key={goal.id} goal={goal} busy={busyGoal === goal.id} onStatus={(status) => setGoalStatus(goal, status)} onDelete={() => removeGoal(goal)} />)}</div>
      </div>
    </div>
  </div>
}

function GoalFocus({ goal }: { goal: RunningGoal }) {
  const range = goal.predicted_time_range
  return <Card className="p-4">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><p className="font-mono text-[10px] uppercase tracking-[0.18em] text-zinc-500">Active race</p><h3 className="mt-1 text-base font-semibold text-white">{goal.title}</h3><p className="mt-1 text-xs text-zinc-500">{formatDistance(goal.race_distance_km)} · {formatDate(goal.target_date)} · priority {goal.priority || "--"}</p></div>
      <Badge className={signalClass(goal.progress.readiness)}>{goal.progress.readiness}</Badge>
    </div>
    <div className="mt-3 grid gap-2 md:grid-cols-4">
      <Stat label="target" value={formatTargetTime(goal.target_time_seconds)} />
      <Stat label="prediction" value={range ? formatDuration(range.predicted_duration_seconds) : "--"} />
      <Stat label="range" value={range ? `${formatDuration(range.lower_seconds)}-${formatDuration(range.upper_seconds)}` : "--"} />
      <Stat label="VDOT" value={goal.current_fitness?.estimate?.value ?? "--"} />
    </div>
    <div className="mt-3 grid gap-2 md:grid-cols-3">{goal.milestones.map((milestone) => <div key={milestone.title} className="rounded-md border border-zinc-800 bg-zinc-950 p-2 text-xs"><div className="flex items-center justify-between gap-2"><p className="font-medium text-white">{milestone.title}</p><Badge className={signalClass(milestone.status)}>{milestone.status}</Badge></div><p className="mt-1 text-zinc-500">due {formatDate(milestone.due_date)} · target {String(milestone.target ?? "--")}</p>{milestone.value !== undefined ? <p className="mt-1 text-zinc-400">current {milestone.value}</p> : null}</div>)}</div>
  </Card>
}

function GoalCard({ goal, busy, onStatus, onDelete }: { goal: RunningGoal; busy: boolean; onStatus: (status: string) => void; onDelete: () => void }) {
  return <Card className="p-3 text-xs">
    <div className="flex flex-wrap items-start justify-between gap-2">
      <div><p className="font-semibold text-white">{goal.title}<span className="ml-2 font-mono text-[10px] text-zinc-500">#{goal.id}</span></p><p className="mt-1 text-zinc-500">{goalTypeLabel(goal.goal_type)} · {goalProgressText(goal)} · {goal.unit || goal.progress.metric}</p></div>
      <div className="flex flex-wrap gap-1"><Badge className={planStatusClass(goal.status)}>{goal.status}</Badge><Badge className={signalClass(goal.progress.readiness)}>{goal.progress.readiness}</Badge></div>
    </div>
    <div className="mt-2 grid gap-2 md:grid-cols-3">
      <p className="rounded-md border border-zinc-900 bg-zinc-950 px-2 py-1.5 text-zinc-400">Race: {formatDistance(goal.race_distance_km)} · {formatDate(goal.target_date)}</p>
      <p className="rounded-md border border-zinc-900 bg-zinc-950 px-2 py-1.5 text-zinc-400">Plan: {goal.plan ? `${goal.plan.title} (${Math.round((goal.plan.adherence.completion_rate || 0) * 100)}%)` : "not linked"}</p>
      <p className="rounded-md border border-zinc-900 bg-zinc-950 px-2 py-1.5 text-zinc-400">Prediction: {goal.predicted_time_range ? `${formatDuration(goal.predicted_time_range.predicted_duration_seconds)} · ${goal.predicted_time_range.confidence}` : "--"}</p>
    </div>
    {goal.course_notes || goal.reason ? <p className="mt-2 leading-5 text-zinc-500">{goal.course_notes || goal.reason}</p> : null}
    <div className="mt-3 flex flex-wrap gap-2"><Button size="sm" variant="secondary" disabled={busy} onClick={() => onStatus(goal.status === "paused" ? "active" : "paused")}>{goal.status === "paused" ? "Resume" : "Pause"}</Button><Button size="sm" variant="secondary" disabled={busy} onClick={() => onStatus("completed")}>Complete</Button><Button size="sm" variant="secondary" disabled={busy} onClick={() => onStatus("missed")}>Missed</Button><Button size="sm" variant="secondary" disabled={busy} onClick={() => onStatus("archived")}>Archive</Button><Button size="sm" variant="secondary" disabled={busy} onClick={onDelete}>Delete</Button></div>
  </Card>
}

function ProfileZones({ profile, completeness, safety, zones, measurements, onChanged }: { profile: AthleteProfile | null; completeness: ProfileCompleteness | null; safety: SafetyCheck | null; zones: Zones | null; measurements: AthleteMeasurement[]; onChanged: () => Promise<void> }) {
  if (!profile) return <Card className="p-4 text-sm text-zinc-400">Loading profile...</Card>

  async function submitProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    const maxHr = numberOrNull(data.get("max_heart_rate_bpm"))
    const preferredWeekdays = csvNumbers(data.get("preferred_weekdays"))
    const longRunWeekday = numberOrNull(data.get("long_run_weekday"))
    const validLongRunWeekday = longRunWeekday && (!preferredWeekdays.length || preferredWeekdays.includes(longRunWeekday)) ? longRunWeekday : null
    await api.updateProfile({
      date_of_birth: stringOrNull(data.get("date_of_birth")),
      sex: stringOrNull(data.get("sex")) || "unspecified",
      height_cm: numberOrNull(data.get("height_cm")),
      weight_kg: numberOrNull(data.get("weight_kg")),
      timezone: stringOrNull(data.get("timezone")),
      locale: stringOrNull(data.get("locale")),
      unit_system: stringOrNull(data.get("unit_system")) || "metric",
      preferred_weekdays: preferredWeekdays,
      long_run_weekday: validLongRunWeekday,
      max_run_duration_minutes: numberOrNull(data.get("max_run_duration_minutes")),
      resting_heart_rate_bpm: numberOrNull(data.get("resting_heart_rate_bpm")),
      max_heart_rate_bpm: maxHr,
      max_hr_source: maxHr ? stringOrNull(data.get("max_hr_source")) : null,
      lactate_threshold_hr_bpm: numberOrNull(data.get("lactate_threshold_hr_bpm")),
      lactate_threshold_pace_seconds_per_km: numberOrNull(data.get("lactate_threshold_pace_seconds_per_km")),
      vo2max: numberOrNull(data.get("vo2max")),
      conservative_mode: data.get("conservative_mode") === "on",
      injury_notes: stringOrNull(data.get("injury_notes")),
      health_conditions: stringOrNull(data.get("health_conditions")),
      recovery_status: stringOrNull(data.get("recovery_status")) || "normal",
    })
    await onChanged()
  }

  async function submitMeasurement(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const data = new FormData(form)
    const thresholdPace = numberOrNull(data.get("threshold_pace_seconds_per_km"))
    await api.createMeasurement({
      measurement_type: String(data.get("measurement_type") || "weight"),
      measured_at: stringOrNull(data.get("measured_at")),
      value_numeric: numberOrNull(data.get("value_numeric")),
      value_json: thresholdPace ? { threshold_pace_seconds_per_km: thresholdPace } : null,
      source: String(data.get("source") || "manual"),
      confidence: 1,
      notes: stringOrNull(data.get("notes")),
    })
    form.reset()
    await onChanged()
  }

  async function recalculateZones() {
    await api.recalculateZones()
    await onChanged()
  }

  const completenessScore = Math.round((completeness?.score || 0) * 100)

  return <div className="grid gap-4">
    <div className="grid gap-4 xl:grid-cols-[1fr_22rem]">
      <Card>
        <CardHeader><div><CardTitle>Athlete profile</CardTitle><p className="text-xs text-zinc-500">Физиология, пороги и ограничения для расчетов.</p></div><Badge>{completeness?.confidence || "low"} confidence</Badge></CardHeader>
        <form key={profile.updated_at} onSubmit={submitProfile} className="grid gap-4 p-4 text-xs">
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            <div className="rounded-md border border-zinc-800 bg-zinc-950 p-3">
              <p className="mb-3 font-mono text-[10px] uppercase tracking-[0.16em] text-zinc-500">Personal</p>
              <div className="grid gap-3">
                <Field label="Дата рождения"><Input name="date_of_birth" type="date" defaultValue={profile.date_of_birth || ""} /></Field>
                <Field label="Пол"><Select name="sex" defaultValue={profile.sex}><option value="unspecified">Не указан</option><option value="male">Мужской</option><option value="female">Женский</option><option value="other">Другой</option></Select></Field>
                <Field label="Timezone"><Input name="timezone" defaultValue={profile.timezone || ""} placeholder="Europe/Moscow" /></Field>
                <Field label="Locale"><Input name="locale" defaultValue={profile.locale || ""} placeholder="ru-RU" /></Field>
              </div>
            </div>
            <div className="rounded-md border border-zinc-800 bg-zinc-950 p-3">
              <p className="mb-3 font-mono text-[10px] uppercase tracking-[0.16em] text-zinc-500">Body</p>
              <div className="grid gap-3">
                <Field label="Вес, кг"><Input name="weight_kg" type="number" min="25" max="250" step="0.1" defaultValue={profile.weight_kg ?? ""} placeholder="например 72.5" /></Field>
                <Field label="Рост, см"><Input name="height_cm" type="number" min="80" max="260" step="0.1" defaultValue={profile.height_cm ?? ""} /></Field>
                <Field label="Unit system"><Select name="unit_system" defaultValue={profile.unit_system || "metric"}><option value="metric">Metric</option><option value="imperial">Imperial</option></Select></Field>
              </div>
            </div>
            <div className="rounded-md border border-zinc-800 bg-zinc-950 p-3">
              <p className="mb-3 font-mono text-[10px] uppercase tracking-[0.16em] text-zinc-500">Physiology</p>
              <div className="grid gap-3">
                <div className="grid gap-2 sm:grid-cols-2"><Field label="Пульс покоя"><Input name="resting_heart_rate_bpm" type="number" min="25" max="120" defaultValue={profile.resting_heart_rate_bpm ?? ""} /></Field><Field label="HRmax"><Input name="max_heart_rate_bpm" type="number" min="80" max="240" defaultValue={profile.max_heart_rate_bpm ?? ""} /></Field></div>
                <Field label="Источник HRmax"><Select name="max_hr_source" defaultValue={profile.max_hr_source || "manual"}><option value="manual">Manual</option><option value="measured">Measured</option><option value="tanaka_estimated">Tanaka estimated</option></Select></Field>
                <div className="grid gap-2 sm:grid-cols-2"><Field label="Пороговый пульс"><Input name="lactate_threshold_hr_bpm" type="number" min="60" max="230" defaultValue={profile.lactate_threshold_hr_bpm ?? ""} /></Field><Field label="Пороговый темп, сек/км"><Input name="lactate_threshold_pace_seconds_per_km" type="number" min="120" max="1200" defaultValue={profile.lactate_threshold_pace_seconds_per_km ?? ""} /></Field></div>
                <Field label="VO2max"><Input name="vo2max" type="number" min="10" max="100" step="0.1" defaultValue={profile.vo2max ?? ""} placeholder="если известен" /></Field>
              </div>
            </div>
            <div className="rounded-md border border-zinc-800 bg-zinc-950 p-3">
              <p className="mb-3 font-mono text-[10px] uppercase tracking-[0.16em] text-zinc-500">Preferences</p>
              <div className="grid gap-3">
                <Field label="Training days"><Input name="preferred_weekdays" defaultValue={(profile.preferred_weekdays || []).join(",")} placeholder="ISO weekdays, e.g. 1,3,6" /></Field>
                <Field label="Long run day"><Select name="long_run_weekday" defaultValue={profile.long_run_weekday || ""}><option value="">Auto</option>{WEEKDAY_LABELS.map((label, index) => <option key={label} value={index + 1}>{label}</option>)}</Select></Field>
                <Field label="Max duration, мин"><Input name="max_run_duration_minutes" type="number" min="15" max="600" step="5" defaultValue={profile.max_run_duration_minutes ?? ""} placeholder="optional" /></Field>
              </div>
            </div>
            <div className="rounded-md border border-zinc-800 bg-zinc-950 p-3 md:col-span-2">
              <p className="mb-3 font-mono text-[10px] uppercase tracking-[0.16em] text-zinc-500">Safety</p>
              <div className="grid gap-3 md:grid-cols-2">
                <Field label="Травмы / ограничения"><Input name="injury_notes" defaultValue={profile.injury_notes || ""} placeholder="травмы, ограничения" /></Field>
                <Field label="Conditions"><Input name="health_conditions" defaultValue={profile.health_conditions || ""} placeholder="астма, давление, прочее" /></Field>
                <Field label="Recovery status"><Select name="recovery_status" defaultValue={profile.recovery_status || "normal"}><option value="fresh">Fresh</option><option value="normal">Normal</option><option value="tired">Tired</option><option value="strained">Strained</option><option value="injured">Injured</option><option value="unknown">Unknown</option></Select></Field>
                <label className="flex h-8 items-center gap-2 rounded-md border border-zinc-800 bg-zinc-950 px-2.5 text-zinc-400"><input name="conservative_mode" type="checkbox" defaultChecked={profile.conservative_mode} /> conservative mode</label>
              </div>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2"><Button type="submit">Save profile</Button><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">days {weekdayListLabel(profile.preferred_weekdays)}</Badge><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">long {weekdayLabel(profile.long_run_weekday)}</Badge><Badge className={signalClass(profile.recovery_status)}>{profile.recovery_status || "normal"}</Badge></div>
        </form>
      </Card>

      <div className="grid gap-4">
        <Card className="p-4">
          <div className="flex items-center justify-between"><p className="text-sm font-semibold text-white">Completeness</p><Badge>{completenessScore}%</Badge></div>
          <div className="mt-3 h-2 rounded bg-zinc-900"><div className="h-full rounded bg-orange-400" style={{ width: `${completenessScore}%` }} /></div>
          <div className="mt-3 grid gap-1 text-xs text-zinc-400">
            <span>HR zones: {completeness?.can_calculate_hr_zones ? "ready" : "missing data"}</span>
            <span>HRR zones: {completeness?.can_calculate_hrr_zones ? "ready" : "needs resting HR"}</span>
            <span>Pace zones: {completeness?.can_calculate_pace_zones ? "ready" : "needs threshold pace"}</span>
          </div>
          {completeness?.missing.length ? <div className="mt-3 flex flex-wrap gap-1">{completeness.missing.map((field) => <Badge key={field} className="border-zinc-700 bg-zinc-900 text-zinc-300">{missingLabel(field)}</Badge>)}</div> : null}
        </Card>
        <Card className="p-4">
          <p className="text-sm font-semibold text-white">Safety</p>
          <p className="mt-2 text-xs leading-5 text-zinc-400">{safety?.message}</p>
          {safety?.warnings.length ? <div className="mt-3 grid gap-2">{safety.warnings.map((warning) => <div key={warning} className="rounded-md border border-orange-400/20 bg-orange-400/10 px-2 py-1.5 text-xs text-orange-100">{warning}</div>)}</div> : <p className="mt-3 text-xs text-zinc-500">Нет активных предупреждений.</p>}
        </Card>
      </div>
    </div>

    <div className="grid gap-4 xl:grid-cols-[1fr_1fr]">
      <Card>
        <CardHeader><div><CardTitle>Training zones</CardTitle><p className="text-xs text-zinc-500">Метод, источник и confidence показываются для каждой зоны.</p></div><Button size="sm" onClick={recalculateZones}>Recalculate</Button></CardHeader>
        <div className="grid gap-4 p-4">
          <ZoneTable title="Heart rate" zones={zones?.hr || []} />
          <ZoneTable title="Pace" zones={zones?.pace || []} />
        </div>
      </Card>

      <Card>
        <CardHeader><div><CardTitle>Measurements</CardTitle><p className="text-xs text-zinc-500">История ручных и device-derived измерений.</p></div><Badge>{measurements.length} rows</Badge></CardHeader>
        <form onSubmit={submitMeasurement} className="grid gap-3 border-b border-zinc-800 p-4 text-xs md:grid-cols-2">
          <Field label="Тип"><Select name="measurement_type"><option value="weight">Вес</option><option value="resting_hr">Пульс покоя</option><option value="max_hr">HRmax</option><option value="lactate_threshold">Lactate threshold</option><option value="vo2max">VO2max</option><option value="note">Note</option></Select></Field>
          <Field label="Значение"><Input name="value_numeric" type="number" step="0.1" placeholder="число" /></Field>
          <Field label="Пороговый темп, сек/км"><Input name="threshold_pace_seconds_per_km" type="number" min="120" max="1200" placeholder="для LT" /></Field>
          <Field label="Дата"><Input name="measured_at" type="datetime-local" /></Field>
          <Field label="Источник"><Select name="source"><option value="manual">Manual</option><option value="device">Device</option><option value="lab">Lab</option><option value="screenshot">Screenshot</option></Select></Field>
          <Field label="Заметка"><Input name="notes" placeholder="опционально" /></Field>
          <div className="md:col-span-2"><Button type="submit" size="sm">Add measurement</Button></div>
        </form>
        <div className="max-h-72 overflow-auto">
          <table className="w-full min-w-[540px] text-left text-xs">
            <thead className="sticky top-0 border-b border-zinc-800 bg-zinc-950 text-[10px] uppercase tracking-[0.14em] text-zinc-500"><tr><th className="px-4 py-2">Type</th><th>Value</th><th>Source</th><th>Date</th></tr></thead>
            <tbody>{measurements.map((measurement) => <tr key={`${measurement.source_model}-${measurement.id}`} className="border-b border-zinc-900 last:border-0"><td className="px-4 py-2 font-medium text-white">{measurement.measurement_type}<div className="text-[11px] text-zinc-500">{measurement.notes || measurement.source_model}</div></td><td>{measurementValueLabel(measurement)}</td><td>{measurement.source}</td><td className="text-zinc-400">{measurement.measured_at ? new Date(measurement.measured_at).toLocaleString("ru-RU") : "--"}</td></tr>)}</tbody>
          </table>
          {!measurements.length && <p className="p-4 text-xs text-zinc-500">Измерений пока нет.</p>}
        </div>
      </Card>
    </div>
  </div>
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="grid gap-1"><span className="font-mono text-[10px] uppercase tracking-[0.14em] text-zinc-500">{label}</span>{children}</label>
}

function ZoneTable({ title, zones }: { title: string; zones: Zone[] }) {
  return <div className="rounded-md border border-zinc-800">
    <div className="flex items-center justify-between border-b border-zinc-800 px-3 py-2"><p className="text-xs font-semibold text-white">{title}</p><Badge>{zones.length} zones</Badge></div>
    {zones.length ? <table className="w-full text-left text-xs">
      <thead className="text-[10px] uppercase tracking-[0.14em] text-zinc-500"><tr><th className="px-3 py-2">Zone</th><th>Range</th><th>Method</th><th>Confidence</th></tr></thead>
      <tbody>{zones.map((zone) => <tr key={`${zone.method}-${zone.zone_key}-${zone.id || "calc"}`} className="border-t border-zinc-900 align-top"><td className="px-3 py-2 font-medium text-white">{zone.label || zone.zone_key}<div className="font-mono text-[10px] text-zinc-600">{zone.zone_key}</div></td><td>{formatZoneRange(zone)}</td><td><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{zone.method}</Badge><div className="mt-1 max-w-[16rem] text-[10px] text-zinc-600">{zone.source_reference}</div></td><td>{zone.confidence}</td></tr>)}</tbody>
    </table> : <p className="p-3 text-xs text-zinc-500">Нет данных для расчета.</p>}
  </div>
}

function planWeekCount(plan: Plan) {
  return plan.workouts.length ? Math.max(...plan.workouts.map((workout) => workout.week_index)) : 0
}

function planPlannedDistance(plan: Plan) {
  return plan.workouts.reduce((sum, workout) => sum + (workout.distance_km || 0), 0)
}

function planPlannedDuration(plan: Plan) {
  return plan.workouts.reduce((sum, workout) => sum + (workout.duration_seconds || 0), 0)
}

function planSupportWorkouts(plan: Plan) {
  return plan.workouts.filter((workout) => isSupportWorkoutType(workout.workout_type)).length
}

function planCurrentWeekLabel(plan: Plan) {
  const weekStart = startOfWeekISO()
  const weekEnd = addDays(weekStart, 6)
  const currentWorkout = plan.workouts.find((workout) => workout.scheduled_date && workout.scheduled_date >= weekStart && workout.scheduled_date <= weekEnd)
  if (currentWorkout) return `week ${currentWorkout.week_index}`
  const nextWorkout = plan.workouts.find((workout) => workout.scheduled_date && workout.scheduled_date > weekEnd)
  return nextWorkout ? `next ${formatDate(nextWorkout.scheduled_date)}` : "--"
}

function planStatusClass(status: string) {
  if (status === "active") return "border-orange-400/40 bg-orange-400/15 text-orange-100"
  if (status === "completed") return "border-zinc-500 bg-zinc-800 text-zinc-100"
  if (status === "archived") return "border-zinc-800 bg-zinc-950 text-zinc-500"
  return "border-zinc-700 bg-zinc-900 text-zinc-300"
}

function formatTargetTime(seconds?: number | null) {
  if (!seconds) return "--"
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}` : `${minutes}m`
}

function formatDateTime(value?: string | null) {
  if (!value) return "--"
  return new Date(value).toLocaleString("ru-RU", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })
}

function planGoalLabel(plan: Plan) {
  return `${plan.goal_type}${plan.race_distance_km ? ` · ${plan.race_distance_km.toFixed(1)} км` : ""}`
}

function planCurrentWeekIndex(plan: Plan) {
  const weekStart = startOfWeekISO()
  const weekEnd = addDays(weekStart, 6)
  const currentWorkout = plan.workouts.find((workout) => workout.scheduled_date && workout.scheduled_date >= weekStart && workout.scheduled_date <= weekEnd)
  if (currentWorkout) return currentWorkout.week_index
  const nextWorkout = plan.workouts.find((workout) => workout.scheduled_date && workout.scheduled_date > weekEnd)
  return nextWorkout?.week_index || null
}

function planWorkoutIntensityCategory(workout: PlanWorkout) {
  const type = workout.workout_type || ""
  const intensity = workout.intensity || ""
  if (isSupportWorkoutType(type)) return type === "mobility" || type === "prehab" ? "mobility" : "strength"
  if (["interval", "tempo", "threshold", "hill", "race_pace"].includes(type) || ["interval", "tempo", "threshold", "race_pace", "hard"].includes(intensity)) return "hard"
  if (type === "steady" || intensity.includes("steady")) return "steady"
  return "easy"
}

function fallbackPlanWeeks(plan: Plan): PlanWeekSummary[] {
  const weekIndexes = Array.from(new Set(plan.workouts.map((workout) => workout.week_index))).sort((a, b) => a - b)
  let previousDistance: number | null = null
  return weekIndexes.map((weekIndex) => {
    const workouts = plan.workouts.filter((workout) => workout.week_index === weekIndex)
    const weekly = plan.weekly_adherence.find((item) => item.week_index === weekIndex)
    const plannedDistance = workouts.reduce((sum, workout) => sum + (workout.distance_km || 0), 0)
    const plannedDuration = workouts.reduce((sum, workout) => sum + (workout.duration_seconds || 0), 0) || null
    const supportWorkouts = workouts.filter((workout) => isSupportWorkoutType(workout.workout_type))
    const longRun = Math.max(...workouts.filter((workout) => !isSupportWorkoutType(workout.workout_type)).map((workout) => workout.distance_km || 0), 0) || null
    const week: PlanWeekSummary = {
      week_index: weekIndex,
      planned_distance_km: Number(plannedDistance.toFixed(1)),
      planned_duration_seconds: plannedDuration,
      completed_distance_km: weekly?.completed_distance_km || 0,
      completed_duration_seconds: workouts.reduce((sum, workout) => sum + (workout.actual_duration_seconds || 0), 0),
      completion_rate: weekly?.completion_rate || 0,
      distance_completion_rate: weekly?.distance_completion_rate || 0,
      planned_time_label: formatDuration(plannedDuration),
      hard_sessions: workouts.filter((workout) => planWorkoutIntensityCategory(workout) === "hard").length,
      support_workouts: supportWorkouts.length,
      support_duration_seconds: supportWorkouts.reduce((sum, workout) => sum + (workout.duration_seconds || 0), 0),
      long_run_km: longRun,
      deload: previousDistance !== null && plannedDistance < previousDistance * 0.9,
      workouts,
      warnings: weekly?.warnings || [],
    }
    previousDistance = plannedDistance
    return week
  })
}

function planIntensitySplit(plan: Plan) {
  const totals: Record<string, number> = { easy: 0, steady: 0, hard: 0, strength: 0, mobility: 0 }
  for (const workout of plan.workouts) {
    const category = planWorkoutIntensityCategory(workout)
    totals[category] = (totals[category] || 0) + (workout.distance_km || (isSupportWorkoutType(workout.workout_type) ? (workout.duration_seconds || 0) / 3600 : 0))
  }
  const total = Math.max(Object.values(totals).reduce((sum, value) => sum + value, 0), 1)
  return Object.entries(totals).filter(([, value]) => value > 0).map(([key, value]) => ({ key, value, percent: Math.round((value / total) * 100) }))
}

function workoutTargetMode(workout: PlanWorkout) {
  if (workout.workout_type === "strength" || workout.workout_type === "ofp") return "strength"
  if (workout.workout_type === "mobility" || workout.workout_type === "prehab") return "mobility"
  if (workout.intensity?.includes("HR") || workout.description?.includes("HR")) return "HR"
  if (workout.intensity?.includes("RPE") || workout.description?.includes("RPE")) return "RPE"
  if (workout.description?.includes("pace") || workout.description?.includes("пейс")) return "pace"
  return workout.duration_seconds ? "duration" : "distance"
}

function workoutBlocks(workout: PlanWorkout) {
  if (workout.blocks?.length) {
    return workout.blocks
      .slice()
      .sort((first, second) => first.block_index - second.block_index)
      .map((block) => {
        const repeat = block.repeat_count > 1 ? `${block.repeat_count}x ` : ""
        const target = block.target_distance_km ? `${block.target_distance_km.toFixed(2)} км` : block.target_duration_seconds ? formatDuration(block.target_duration_seconds) : "target"
        const rpe = block.target_rpe_min !== null && block.target_rpe_max !== null ? ` RPE ${block.target_rpe_min}-${block.target_rpe_max}` : ""
        return `${repeat}${block.block_type}: ${target}${rpe}`
      })
  }
  if (workout.workout_type === "strength" || workout.workout_type === "ofp") return ["Warmup", "Calves/soleus", "Single-leg strength", "Glutes/core", "Cooldown"]
  if (workout.workout_type === "mobility" || workout.workout_type === "prehab") return ["Ankle mobility", "Hip mobility", "Glute activation", "Breathing"]
  if (workout.workout_type === "interval") return ["Warmup 10-15m", "Repeats at target", "Easy recovery", "Cooldown"]
  if (["tempo", "threshold", "race_pace"].includes(workout.workout_type)) return ["Warmup", "Controlled quality block", "Cooldown"]
  if (workout.workout_type === "long") return ["Easy start", "Steady middle", "Fuel/hydrate", "Easy finish"]
  if (workout.workout_type === "recovery") return ["Short easy run", "Mobility", "Stop if fatigue rises"]
  return ["Continuous easy run", "Keep form relaxed", "Optional strides"]
}

function workoutPurpose(workout: PlanWorkout) {
  if (workout.workout_type === "strength" || workout.workout_type === "ofp") return "Build runner durability: calves, hips, posterior chain and trunk stability."
  if (workout.workout_type === "mobility" || workout.workout_type === "prehab") return "Restore range of motion and keep common runner weak links controlled."
  if (workout.workout_type === "long") return "Build aerobic endurance and race-specific durability."
  if (workout.workout_type === "interval") return "Raise threshold/VO2 stimulus while keeping recovery controlled."
  if (["tempo", "threshold", "race_pace"].includes(workout.workout_type)) return "Practice sustainable quality without turning the week into a race."
  if (workout.workout_type === "recovery") return "Restore legs and preserve frequency with low load."
  return "Accumulate aerobic volume and support consistency."
}

function workoutSafetyNote(workout: PlanWorkout) {
  if (workout.workout_type === "strength" || workout.workout_type === "ofp") return "Avoid failure, heavy soreness and painful movements; keep 1-2 reps in reserve."
  if (workout.workout_type === "mobility" || workout.workout_type === "prehab") return "Keep it easy and pain-free; mobility should improve readiness, not add fatigue."
  if (["interval", "tempo", "threshold", "race_pace", "long"].includes(workout.workout_type)) return "Reduce or skip if pain, poor sleep, unusual fatigue or HR drift is present."
  return "Keep it conversational; shorten if recovery signals are worse than expected."
}

function Planning() {
  const [plans, setPlans] = useState<Plan[]>([])
  const [result, setResult] = useState<Plan | null>(null)
  const [builderPreview, setBuilderPreview] = useState<PlanBuilderPreview | null>(null)
  const [builderPreviewError, setBuilderPreviewError] = useState("")
  const [previewingBuilder, setPreviewingBuilder] = useState(false)
  const [planWeeks, setPlanWeeks] = useState<PlanWeekSummary[]>([])
  const [planWeeksPlanId, setPlanWeeksPlanId] = useState<number | null>(null)
  const [planWeeksError, setPlanWeeksError] = useState("")
  const [candidatesByWorkout, setCandidatesByWorkout] = useState<Record<number, PlanActivityMatchCandidate[]>>({})
  const [candidateErrors, setCandidateErrors] = useState<Record<number, string>>({})
  const [feedbackDrafts, setFeedbackDrafts] = useState<Record<number, FeedbackDraft>>({})
  const [completionDrafts, setCompletionDrafts] = useState<Record<number, CompletionDraft>>({})
  const [rescheduleDrafts, setRescheduleDrafts] = useState<Record<number, string>>({})
  const [recommendations, setRecommendations] = useState<PlanRecommendations | null>(null)
  const [recommendationPreview, setRecommendationPreview] = useState<PlanRecommendationPreview | null>(null)
  const [recommendationAudits, setRecommendationAudits] = useState<PlanRecommendationAudit[]>([])
  const [planVersions, setPlanVersions] = useState<PlanVersion[]>([])
  const [recommendationError, setRecommendationError] = useState("")
  const [recommendationActionError, setRecommendationActionError] = useState("")
  const [loadingRecommendations, setLoadingRecommendations] = useState(false)
  const [previewingRecommendations, setPreviewingRecommendations] = useState(false)
  const [applyingRecommendations, setApplyingRecommendations] = useState(false)
  const [loadingCandidates, setLoadingCandidates] = useState<number | null>(null)
  const [busyPlan, setBusyPlan] = useState<number | null>(null)
  const [planActionError, setPlanActionError] = useState("")
  const [renameDrafts, setRenameDrafts] = useState<Record<number, string>>({})
  const planBuilderForm = useRef<HTMLFormElement>(null)
  const recommendationsRequest = useRef(0)
  const planWeeksRequest = useRef(0)

  async function loadPlans(preferredPlanId?: number | null) {
    await devLogin()
    const nextPlans = await api.plans()
    const previousTitles = new Map(plans.map((plan) => [plan.id, plan.title]))
    setPlans(nextPlans)
    setRenameDrafts((current) => {
      const next: Record<number, string> = {}
      for (const plan of nextPlans) {
        const currentDraft = current[plan.id]
        const previousTitle = previousTitles.get(plan.id)
        next[plan.id] = currentDraft === undefined || currentDraft === previousTitle ? plan.title : currentDraft
      }
      return next
    })
    setResult((current) => {
      if (preferredPlanId === null) return nextPlans.find((plan) => plan.status === "active") || nextPlans[0] || null
      if (preferredPlanId !== undefined) return nextPlans.find((plan) => plan.id === preferredPlanId) || nextPlans.find((plan) => plan.status === "active") || nextPlans[0] || null
      return current ? nextPlans.find((plan) => plan.id === current.id) || current : nextPlans.find((plan) => plan.status === "active") || nextPlans[0] || null
    })
  }

  async function generate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    await createPlan(false)
  }

  async function createPlan(activatePlan = false) {
    if (!planBuilderForm.current) return
    setBuilderPreviewError("")
    try {
      const plan = await api.generatePlan(planBuilderPayload(planBuilderForm.current, activatePlan))
      setResult(plan)
      await loadPlans(plan.id)
      if (plan.status === "active") await loadRecommendations(plan.id)
    } catch (error) {
      console.error(error)
      setBuilderPreviewError(activatePlan ? "Не удалось создать и активировать план" : "Не удалось создать draft-план")
    }
  }

  async function previewBuilder() {
    if (!planBuilderForm.current) return
    setPreviewingBuilder(true)
    setBuilderPreviewError("")
    try {
      setBuilderPreview(await api.previewPlan(planBuilderPayload(planBuilderForm.current)))
    } catch (error) {
      console.error(error)
      setBuilderPreviewError("Не удалось подготовить preview плана")
    } finally {
      setPreviewingBuilder(false)
    }
  }

  async function activate(id: number) {
    const plan = await api.activatePlan(id)
    setResult(plan)
    await loadPlans(plan.id)
    await loadRecommendations(plan.id)
    await loadPlanVersions(plan.id)
  }

  async function updatePlanStatus(plan: Plan, status: "completed" | "archived") {
    setBusyPlan(plan.id)
    setPlanActionError("")
    try {
      const updated = await api.updatePlan(plan.id, { status })
      await loadPlans(updated.id)
      await loadRecommendations(updated.id)
      await loadRecommendationAudits(updated.id)
      await loadPlanVersions(updated.id)
    } catch (error) {
      console.error(error)
      setPlanActionError(`Не удалось обновить план #${plan.id}`)
    } finally {
      setBusyPlan(null)
    }
  }

  async function renamePlan(plan: Plan) {
    const title = (renameDrafts[plan.id] || plan.title).trim()
    if (!title || title === plan.title) return
    setBusyPlan(plan.id)
    setPlanActionError("")
    try {
      const updated = await api.updatePlan(plan.id, { title })
      await loadPlans(updated.id)
      await loadPlanVersions(updated.id)
    } catch (error) {
      console.error(error)
      setPlanActionError(`Не удалось переименовать план #${plan.id}`)
    } finally {
      setBusyPlan(null)
    }
  }

  async function duplicatePlan(plan: Plan) {
    setBusyPlan(plan.id)
    setPlanActionError("")
    try {
      const duplicated = await api.duplicatePlan(plan.id)
      await loadPlans(duplicated.id)
    } catch (error) {
      console.error(error)
      setPlanActionError(`Не удалось дублировать план #${plan.id}`)
    } finally {
      setBusyPlan(null)
    }
  }

  async function deleteSelectedPlan(plan: Plan) {
    if (!window.confirm(`Delete plan #${plan.id}? This cannot be undone.`)) return
    setBusyPlan(plan.id)
    setPlanActionError("")
    try {
      await api.deletePlan(plan.id)
      await loadPlans(null)
    } catch (error) {
      console.error(error)
      setPlanActionError(plan.status === "active" ? "Активный план нельзя удалить: сначала архивируйте его" : `Не удалось удалить план #${plan.id}`)
    } finally {
      setBusyPlan(null)
    }
  }

  async function loadPlanWeeks(planId: number) {
    const requestId = planWeeksRequest.current + 1
    planWeeksRequest.current = requestId
    setPlanWeeks([])
    setPlanWeeksPlanId(planId)
    setPlanWeeksError("")
    try {
      const nextWeeks = await api.planWeeks(planId)
      if (planWeeksRequest.current === requestId) {
        setPlanWeeks(nextWeeks)
        setPlanWeeksPlanId(planId)
      }
    } catch (error) {
      console.error(error)
      if (planWeeksRequest.current === requestId) {
        setPlanWeeks([])
        setPlanWeeksPlanId(planId)
        setPlanWeeksError("Не удалось загрузить недельную структуру плана")
      }
    }
  }

  async function refreshPlanDetail(planId: number) {
    const plan = await api.plan(planId)
    setResult(plan)
    await loadPlanWeeks(plan.id)
    await loadRecommendations(plan.id)
    await loadPlans(plan.id)
    await loadPlanVersions(plan.id)
  }

  async function patchWorkout(workout: PlanWorkout, payload: Record<string, unknown>, errorMessage: string) {
    setCandidateErrors((current) => ({ ...current, [workout.id]: "" }))
    try {
      await api.updatePlanWorkout(workout.id, payload)
      if (result) await refreshPlanDetail(result.id)
      return true
    } catch (error) {
      console.error(error)
      setCandidateErrors((current) => ({ ...current, [workout.id]: errorMessage }))
      return false
    }
  }

  async function updateWorkout(workout: PlanWorkout, status: string) {
    await patchWorkout(workout, { status }, "Не удалось обновить статус")
  }

  async function rescheduleWorkout(workout: PlanWorkout, scheduledDate: string) {
    if (!scheduledDate) return
    const updated = await patchWorkout(workout, { scheduled_date: scheduledDate }, "Не удалось перенести тренировку")
    if (updated) setRescheduleDrafts((current) => ({ ...current, [workout.id]: scheduledDate }))
  }

  async function unlinkWorkoutActivity(workout: PlanWorkout) {
    await patchWorkout(workout, { completed_activity_id: null }, "Не удалось отвязать активность")
  }

  async function loadCandidates(workout: PlanWorkout) {
    setLoadingCandidates(workout.id)
    setCandidateErrors((current) => ({ ...current, [workout.id]: "" }))
    setCandidatesByWorkout((current) => ({ ...current, [workout.id]: [] }))
    try {
      const candidates = await api.workoutMatchCandidates(workout.id)
      setCandidatesByWorkout((current) => ({ ...current, [workout.id]: candidates }))
    } catch (error) {
      console.error(error)
      setCandidateErrors((current) => ({ ...current, [workout.id]: "Не удалось загрузить кандидатов" }))
    } finally {
      setLoadingCandidates(null)
    }
  }

  async function linkCandidate(workout: PlanWorkout, activityId: number) {
    setCandidateErrors((current) => ({ ...current, [workout.id]: "" }))
    try {
      await api.attachWorkoutActivity(workout.id, activityId)
      setCandidatesByWorkout((current) => ({ ...current, [workout.id]: [] }))
      if (result) await refreshPlanDetail(result.id)
    } catch (error) {
      console.error(error)
      setCandidateErrors((current) => ({ ...current, [workout.id]: "Не удалось привязать активность" }))
    }
  }

  function updateFeedbackDraft(workout: PlanWorkout, patch: Partial<FeedbackDraft>) {
    setFeedbackDrafts((current) => ({
      ...current,
      [workout.id]: { ...feedbackDraftFromWorkout(workout), ...(current[workout.id] || {}), ...patch },
    }))
  }

  function updateCompletionDraft(workout: PlanWorkout, patch: Partial<CompletionDraft>) {
    setCompletionDrafts((current) => ({
      ...current,
      [workout.id]: { ...completionDraftFromWorkout(workout), ...(current[workout.id] || {}), ...patch },
    }))
  }

  async function completeWorkoutManually(workout: PlanWorkout) {
    const draft = completionDrafts[workout.id] || completionDraftFromWorkout(workout)
    const validationError = completionValidationError(draft)
    setCandidateErrors((current) => ({ ...current, [workout.id]: validationError }))
    if (validationError) return
    try {
      await api.completeWorkout(workout.id, completionPayload(draft))
      setCompletionDrafts((current) => {
        const next = { ...current }
        delete next[workout.id]
        return next
      })
      if (result) await refreshPlanDetail(result.id)
    } catch (error) {
      console.error(error)
      setCandidateErrors((current) => ({ ...current, [workout.id]: "Не удалось завершить тренировку вручную" }))
    }
  }

  async function saveFeedback(workout: PlanWorkout) {
    const draft = feedbackDrafts[workout.id] || feedbackDraftFromWorkout(workout)
    setCandidateErrors((current) => ({ ...current, [workout.id]: "" }))
    const validationError = feedbackValidationError(draft)
    if (validationError) {
      setCandidateErrors((current) => ({ ...current, [workout.id]: validationError }))
      return
    }
    try {
      await api.saveWorkoutFeedback(workout.id, feedbackPayload(draft))
      setFeedbackDrafts((current) => {
        const next = { ...current }
        delete next[workout.id]
        return next
      })
      if (result) await refreshPlanDetail(result.id)
    } catch (error) {
      console.error(error)
      setCandidateErrors((current) => ({ ...current, [workout.id]: "Не удалось сохранить feedback" }))
    }
  }

  async function loadRecommendations(planId: number) {
    const requestId = recommendationsRequest.current + 1
    recommendationsRequest.current = requestId
    setLoadingRecommendations(true)
    setRecommendationError("")
    setRecommendationActionError("")
    setRecommendationPreview(null)
    setRecommendations(null)
    try {
      const nextRecommendations = await api.planRecommendations(planId)
      if (recommendationsRequest.current === requestId) setRecommendations(nextRecommendations)
    } catch (error) {
      console.error(error)
      if (recommendationsRequest.current === requestId) setRecommendationError("Не удалось загрузить coach recommendations")
    } finally {
      if (recommendationsRequest.current === requestId) setLoadingRecommendations(false)
    }
  }

  async function loadRecommendationAudits(planId: number) {
    try {
      setRecommendationAudits(await api.planRecommendationAudit(planId))
    } catch (error) {
      console.error(error)
      setRecommendationAudits([])
    }
  }

  async function loadPlanVersions(planId: number) {
    try {
      setPlanVersions(await api.planVersions(planId))
    } catch (error) {
      console.error(error)
      setPlanVersions([])
    }
  }

  async function previewRecommendations(planId: number) {
    setPreviewingRecommendations(true)
    setRecommendationActionError("")
    try {
      setRecommendationPreview(await api.previewPlanRecommendations(planId))
      await loadRecommendationAudits(planId)
    } catch (error) {
      console.error(error)
      setRecommendationActionError("Не удалось подготовить preview корректировок")
    } finally {
      setPreviewingRecommendations(false)
    }
  }

  async function applyRecommendations(planId: number) {
    if (!recommendationPreview?.changes.length) return
    setApplyingRecommendations(true)
    setRecommendationActionError("")
    try {
      const applied = await api.applyPlanRecommendations(planId, recommendationPreview.changes)
      setResult(applied.plan)
      setRecommendationPreview(null)
      await loadPlans(applied.plan.id)
      await loadPlanWeeks(applied.plan.id)
      await loadRecommendations(applied.plan.id)
      await loadRecommendationAudits(applied.plan.id)
      await loadPlanVersions(applied.plan.id)
    } catch (error) {
      console.error(error)
      setRecommendationActionError("Не удалось применить корректировки")
    } finally {
      setApplyingRecommendations(false)
    }
  }

  useEffect(() => { void loadPlans() }, [])
  useEffect(() => {
    if (result?.id) {
      void loadPlanWeeks(result.id)
      void loadRecommendations(result.id)
      void loadRecommendationAudits(result.id)
      void loadPlanVersions(result.id)
    }
    else {
      setPlanWeeks([])
      setPlanWeeksPlanId(null)
      setPlanWeeksError("")
      setRecommendations(null)
      setRecommendationPreview(null)
      setRecommendationAudits([])
      setPlanVersions([])
      setRecommendationError("")
      setRecommendationActionError("")
    }
  }, [result?.id])

  const weekCount = result?.workouts.length ? Math.max(...result.workouts.map((workout) => workout.week_index)) : 0
  const detailWeeks = result ? (planWeeksPlanId === result.id && planWeeks.length ? planWeeks : fallbackPlanWeeks(result)) : []
  const currentWeekIndex = result ? planCurrentWeekIndex(result) : null
  const intensitySplit = result ? planIntensitySplit(result) : []
  const visibleRecommendations = recommendations?.plan_id === result?.id ? recommendations : null
  const hasSafetyInfo = result?.explanation?.includes("Safety gates:") || false
  const conservative = hasSafetyInfo && result?.explanation?.includes("Safety gates: no active safety gates") === false
  const planMode = !result ? null : !hasSafetyInfo ? "legacy" : conservative ? "safety gated" : "standard"
  return <div className="grid gap-4 xl:grid-cols-[24rem_1fr]">
    <Card>
      <CardHeader><div><CardTitle>Program planner</CardTitle><p className="text-xs text-zinc-500">Profile-aware running plus strength/OFP support sessions.</p></div>{result && <Badge>#{result.id}</Badge>}</CardHeader>
      <form ref={planBuilderForm} onSubmit={generate} className="grid gap-3 p-4 text-xs">
        <Field label="Название"><Input name="title" defaultValue="Марафонская программа" /></Field>
        <Field label="Цель"><Select name="goal_type" defaultValue="marathon"><option value="5k">5K</option><option value="10k">10K</option><option value="half_marathon">Half marathon</option><option value="marathon">Marathon</option><option value="custom">Custom</option><option value="base_building">Base building</option></Select></Field>
        <Field label="Дистанция, км"><Input name="race_distance_km" type="number" min="1" max="100" step="0.1" defaultValue="42.2" /></Field>
        <Field label="Дата старта"><Input name="target_date" type="date" /></Field>
        <Field label="Длина, недель"><Input name="plan_length_weeks" type="number" min="4" max="24" step="1" placeholder="если без даты" /></Field>
        <Field label="Целевое время, мин"><Input name="target_time_minutes" type="number" min="1" max="2880" step="1" placeholder="optional" /></Field>
        <Field label="Приоритет"><Select name="priority" defaultValue="b"><option value="a">A race</option><option value="b">B race</option><option value="c">C race</option></Select></Field>
        <Field label="Aggressiveness"><Select name="aggressiveness" defaultValue="auto"><option value="auto">Auto safety</option><option value="beginner">Beginner cap</option><option value="intermediate">Intermediate cap</option><option value="advanced">Advanced if detected</option></Select></Field>
        <Field label="Дней в неделю"><Input name="available_days_per_week" type="number" min="2" max="7" defaultValue="4" /></Field>
        <Field label="Preferred days"><Input name="preferred_weekdays" placeholder="ISO weekdays, e.g. 1,3,6" /></Field>
        <Field label="Текущий объем, км/нед"><Input name="current_weekly_distance_km" type="number" min="0" max="200" step="0.1" placeholder="если пусто, возьмем из истории" /></Field>
        <Field label="Longest recent run, км"><Input name="longest_recent_run_km" type="number" min="0" max="100" step="0.1" placeholder="optional" /></Field>
        <div className="grid gap-2 sm:grid-cols-2"><Field label="Recent race, км"><Input name="recent_race_distance_km" type="number" min="1" max="100" step="0.1" placeholder="optional" /></Field><Field label="Recent race time, мин"><Input name="recent_race_time_minutes" type="number" min="1" max="2880" step="1" placeholder="optional" /></Field></div>
        <div className="grid gap-2 sm:grid-cols-2"><Field label="Intensity"><Select name="intensity_mode" defaultValue="mixed"><option value="mixed">Mixed</option><option value="pace">Pace</option><option value="hr">HR</option><option value="rpe">RPE</option></Select></Field><Field label="Time budget, мин/нед"><Input name="time_budget_minutes_per_week" type="number" min="30" max="5000" step="5" placeholder="optional" /></Field></div>
        <div className="grid gap-2 sm:grid-cols-2"><Field label="Max long run, км"><Input name="max_long_run_km" type="number" min="1" max="100" step="0.1" placeholder="optional" /></Field><Field label="Max long run, мин"><Input name="max_long_run_duration_minutes" type="number" min="15" max="600" step="5" placeholder="optional" /></Field></div>
        <Field label="Terrain"><Input name="terrain" placeholder="road, trail, treadmill" /></Field>
        <div className="rounded-md border border-zinc-800 bg-zinc-950 p-2">
          <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.16em] text-zinc-500">ОФП / support</p>
          <div className="grid gap-2 sm:grid-cols-2"><label className="flex items-center gap-2 rounded-md border border-zinc-800 bg-zinc-950 px-2 py-1.5 text-zinc-400"><input name="include_strength" type="checkbox" defaultChecked /> strength/OFP</label><label className="flex items-center gap-2 rounded-md border border-zinc-800 bg-zinc-950 px-2 py-1.5 text-zinc-400"><input name="include_mobility" type="checkbox" defaultChecked /> mobility/prehab</label></div>
          <div className="mt-2 grid gap-2 sm:grid-cols-3"><Field label="Strength / week"><Input name="strength_sessions_per_week" type="number" min="0" max="3" step="1" defaultValue="1" /></Field><Field label="Mobility / week"><Input name="mobility_sessions_per_week" type="number" min="0" max="4" step="1" defaultValue="1" /></Field><Field label="Equipment"><Select name="strength_equipment" defaultValue="bodyweight"><option value="bodyweight">Bodyweight</option><option value="bands">Bands</option><option value="dumbbells">Dumbbells</option><option value="gym">Gym</option></Select></Field></div>
        </div>
        <div className="grid gap-2 sm:grid-cols-2"><label className="flex items-center gap-2 rounded-md border border-zinc-800 bg-zinc-950 px-2 py-1.5 text-zinc-400"><input name="injury" type="checkbox" /> injury constraint</label><label className="flex items-center gap-2 rounded-md border border-zinc-800 bg-zinc-950 px-2 py-1.5 text-zinc-400"><input name="no_hard_workouts" type="checkbox" /> no hard workouts</label></div>
        <div className="grid gap-2 sm:grid-cols-3"><Button type="button" variant="secondary" disabled={previewingBuilder} onClick={previewBuilder}>{previewingBuilder ? "Previewing..." : "Preview"}</Button><Button type="submit">Create draft</Button><Button type="button" onClick={() => createPlan(true)}>Create active</Button></div>
      </form>
      {builderPreviewError ? <div className="mx-4 mb-4 rounded-md border border-orange-400/20 bg-orange-400/10 px-2 py-1.5 text-xs text-orange-100">{builderPreviewError}</div> : null}
      {builderPreview ? <PlanBuilderPreviewCard preview={builderPreview} /> : null}
      <div className="border-t border-zinc-800 p-4">
        <div className="mb-2 flex items-center justify-between"><p className="text-xs font-semibold text-white">Saved plans</p><Badge>{plans.length} total</Badge></div>
        {planActionError ? <p className="mb-2 rounded-md border border-orange-400/20 bg-orange-400/10 px-2 py-1.5 text-xs text-orange-100">{planActionError}</p> : null}
        <div className="grid gap-2">{plans.map((plan) => <PlanListCard key={plan.id} plan={plan} selected={result?.id === plan.id} busy={busyPlan === plan.id} renameDraft={renameDrafts[plan.id] ?? plan.title} onSelect={() => setResult(plan)} onRenameDraft={(value) => setRenameDrafts((current) => ({ ...current, [plan.id]: value }))} onRename={() => renamePlan(plan)} onActivate={() => activate(plan.id)} onArchive={() => updatePlanStatus(plan, "archived")} onComplete={() => updatePlanStatus(plan, "completed")} onDuplicate={() => duplicatePlan(plan)} onDelete={() => deleteSelectedPlan(plan)} />)}</div>
      </div>
    </Card>
    <Card>
      <CardHeader><div><CardTitle>Plan detail</CardTitle><p className="text-xs text-zinc-500">Structured weeks, execution controls and adaptation history.</p></div>{result && <Badge className={conservative ? "border-orange-400/40 bg-orange-400/15 text-orange-100" : undefined}>{planMode}</Badge>}</CardHeader>
      <div className="grid gap-4 p-4 text-sm text-zinc-400">
        {result ? <>
          <PlanDetailHeader plan={result} currentWeekIndex={currentWeekIndex} />
          <p className="leading-6">{result.explanation}</p>
          <div className="flex flex-wrap items-center gap-2">
            {result.status !== "active" ? <Button size="sm" onClick={() => activate(result.id)}>Activate plan</Button> : <Badge>active plan</Badge>}
            <Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{Math.round((result.adherence?.completion_rate || 0) * 100)}% adherence</Badge>
            <Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{result.adherence?.completed_distance_km || 0}/{result.adherence?.planned_distance_km || 0} км</Badge>
            <Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">linked {result.adherence?.linked_workouts || 0}/{result.adherence?.done_workouts || 0}</Badge>
          </div>
          {result.adherence?.warnings?.length ? <div className="grid gap-2">{result.adherence.warnings.map((warning) => <div key={warning} className="rounded-md border border-orange-400/20 bg-orange-400/10 px-2 py-1.5 text-xs text-orange-100">{warning}</div>)}</div> : null}
          <CoachRecommendations recommendations={visibleRecommendations} preview={recommendationPreview?.plan_id === result.id ? recommendationPreview : null} audits={recommendationAudits} error={recommendationError} actionError={recommendationActionError} loading={loadingRecommendations} previewing={previewingRecommendations} applying={applyingRecommendations} onRefresh={() => loadRecommendations(result.id)} onPreview={() => previewRecommendations(result.id)} onApply={() => applyRecommendations(result.id)} />
          <PlanVersions versions={planVersions} />
          <div className="grid grid-cols-3 gap-2 text-center text-xs">
            <Stat label="weeks" value={weekCount} />
            <Stat label="workouts" value={result.workouts.length} />
            <Stat label="days/week" value={result.available_days_per_week} />
          </div>
          <PlanVolumeChart weeks={detailWeeks} />
          <PlanIntensitySplit split={intensitySplit} />
          {planWeeksError ? <p className="rounded-md border border-orange-400/20 bg-orange-400/10 px-2 py-1.5 text-xs text-orange-100">{planWeeksError}</p> : null}
          <div className="grid gap-3">{detailWeeks.map((week) => <PlanWeek key={week.week_index} summary={week} candidatesByWorkout={candidatesByWorkout} candidateErrors={candidateErrors} feedbackDrafts={feedbackDrafts} completionDrafts={completionDrafts} rescheduleDrafts={rescheduleDrafts} loadingCandidates={loadingCandidates} onFindCandidates={loadCandidates} onLinkCandidate={linkCandidate} onUpdate={updateWorkout} onReschedule={rescheduleWorkout} onUnlinkActivity={unlinkWorkoutActivity} onRescheduleDraft={(workout, value) => setRescheduleDrafts((current) => ({ ...current, [workout.id]: value }))} onFeedbackDraft={updateFeedbackDraft} onCompletionDraft={updateCompletionDraft} onCompleteWorkout={completeWorkoutManually} onSaveFeedback={saveFeedback} />)}</div>
        </> : <p>Generate a plan to see how profile completeness, safety gates and zones change the weekly structure.</p>}
      </div>
    </Card>
  </div>
}

function PlanBuilderPreviewCard({ preview }: { preview: PlanBuilderPreview }) {
  const maxVolume = Math.max(...preview.weekly_volume_curve.map((week) => week.planned_distance_km), 1)
  const split = Object.entries(preview.intensity_split).map(([key, value]) => ({ key, value: Math.round(value * 100) }))
  const firstWorkouts = preview.workouts.slice(0, 8)
  const supportSessions = preview.weekly_volume_curve.reduce((sum, week) => sum + (week.support_sessions || 0), 0)
  return <div className="mx-4 mb-4 rounded-md border border-zinc-800 bg-zinc-950/70 p-3 text-xs">
    <div className="flex flex-wrap items-start justify-between gap-2">
      <div><p className="font-semibold text-white">Builder preview</p><p className="mt-1 text-zinc-500">Baseline, risk flags and first workouts before saving a draft.</p></div>
      <Badge className={preview.risk_flags.some((flag) => flag.severity === "critical" || flag.severity === "warning") ? "border-orange-400/40 bg-orange-400/15 text-orange-100" : "border-zinc-700 bg-zinc-900 text-zinc-300"}>{preview.risk_flags.length} flags</Badge>
    </div>
    <p className="mt-3 leading-5 text-zinc-400">{preview.explanation}</p>
    <div className="mt-3 grid grid-cols-4 gap-2 text-center">
      <Stat label="weeks" value={preview.weeks} />
      <Stat label="current" value={preview.current_weekly_distance_km.toFixed(1)} suffix="km" />
      <Stat label="peak" value={preview.peak_weekly_distance_km.toFixed(1)} suffix="km" />
      <Stat label="support" value={supportSessions} />
    </div>
    <div className="mt-3 rounded-md border border-zinc-800 bg-zinc-950 p-2">
      <div className="flex flex-wrap items-center justify-between gap-2"><p className="font-medium text-white">Baseline</p><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{preview.baseline.training_age_level} · {preview.baseline.confidence}</Badge></div>
      <div className="mt-2 grid grid-cols-2 gap-2 text-zinc-500">
        <p>source: <span className="text-zinc-300">{preview.baseline.current_weekly_volume_source}</span></p>
        <p>history: <span className="text-zinc-300">{preview.baseline.history_span_days} days</span></p>
        <p>consistent: <span className="text-zinc-300">{preview.baseline.consistent_weeks || 0} weeks</span></p>
        <p>quality: <span className="text-zinc-300">{preview.baseline.quality_sessions_8w || 0}/8w</span></p>
        <p>activities: <span className="text-zinc-300">{preview.baseline.activity_count}</span></p>
        <p>recent long: <span className="text-zinc-300">{preview.baseline.recent_long_run_km?.toFixed(1) || "--"} km</span></p>
      </div>
      <div className="mt-2 grid grid-cols-6 gap-1">{preview.baseline.observed_weekly_volume_km.map((volume, index) => <div key={`${index}-${volume}`} className="rounded bg-zinc-900 px-1.5 py-1 text-center"><p className="font-mono text-[10px] text-zinc-600">-{6 - index}w</p><p className="text-zinc-300">{volume.toFixed(1)}</p></div>)}</div>
    </div>
    <div className="mt-3 grid gap-2">
      {preview.weekly_volume_curve.map((week) => <div key={week.week_index} className="grid grid-cols-[3.5rem_1fr_8.5rem] items-center gap-2 text-[11px]"><span className="text-zinc-500">W{week.week_index}</span><div className="h-2 overflow-hidden rounded bg-zinc-900"><div className={cn("h-full rounded", week.is_taper ? "bg-orange-200/80" : "bg-orange-400/70")} style={{ width: `${Math.max(4, Math.round((week.planned_distance_km / maxVolume) * 100))}%` }} /></div><span className="text-right text-zinc-300">{week.planned_distance_km.toFixed(1)} km · {week.phase}</span></div>)}
    </div>
    <div className="mt-3 flex flex-wrap gap-2"><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{preview.intensity_mode}</Badge><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">priority {preview.priority}</Badge>{preview.preferred_weekdays.length ? <Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">days {preview.preferred_weekdays.join(",")}</Badge> : null}{split.map((item) => <Badge key={item.key} className="border-zinc-700 bg-zinc-900 text-zinc-300">{item.key} {item.value}%</Badge>)}</div>
    {preview.risk_flags.length ? <div className="mt-3 grid gap-1.5">{preview.risk_flags.map((flag) => <div key={flag.code} className={cn("rounded-md border px-2 py-1.5", signalClass(flag.severity))}><div className="flex flex-wrap items-center justify-between gap-2"><p className="font-medium">{flag.message}</p><Badge className="border-zinc-700 bg-zinc-950 text-zinc-300">{flag.code}</Badge></div>{flag.reasons.length ? <p className="mt-1 text-[11px] text-zinc-500">{flag.reasons.slice(0, 2).join(" · ")}</p> : null}</div>)}</div> : <p className="mt-3 rounded-md border border-zinc-800 bg-zinc-950 px-2 py-1.5 text-zinc-500">No preview risk flags.</p>}
    <div className="mt-3 grid gap-1.5">{firstWorkouts.map((workout) => <div key={`${workout.week_index}-${workout.day_index}-${workout.title}`} className="rounded-md border border-zinc-900 bg-zinc-950 px-2 py-1.5"><div className="flex flex-wrap items-center justify-between gap-2"><p className="font-medium text-white">W{workout.week_index}D{workout.day_index} · {workout.title}</p><div className="flex flex-wrap gap-1"><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{workout.phase}</Badge><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{workout.workout_type}</Badge></div></div><p className="mt-1 text-zinc-500">{formatDate(workout.scheduled_date)} · {formatWorkoutTarget(workout)} · {workout.intensity || "--"}</p></div>)}</div>
  </div>
}

function PlanListCard({ plan, selected, busy, renameDraft, onSelect, onRenameDraft, onRename, onActivate, onArchive, onComplete, onDuplicate, onDelete }: { plan: Plan; selected: boolean; busy: boolean; renameDraft: string; onSelect: () => void; onRenameDraft: (value: string) => void; onRename: () => void; onActivate: () => void; onArchive: () => void; onComplete: () => void; onDuplicate: () => void; onDelete: () => void }) {
  const weeks = planWeekCount(plan)
  const plannedKm = planPlannedDistance(plan)
  const adherence = Math.round((plan.adherence?.completion_rate || 0) * 100)
  const renameChanged = renameDraft.trim() && renameDraft.trim() !== plan.title
  return <div className={cn("rounded-md border p-2 text-xs", selected ? "border-orange-400/40 bg-orange-400/10" : "border-zinc-800 bg-zinc-950")}>
    <div role="button" tabIndex={0} onClick={onSelect} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") onSelect() }} className="cursor-pointer rounded-sm outline-none focus:ring-1 focus:ring-orange-400/60">
      <div className="flex flex-wrap items-start justify-between gap-2"><div><p className="font-medium text-white">{plan.title}<span className="ml-2 font-mono text-[10px] text-zinc-500">#{plan.id}</span></p><p className="mt-1 text-zinc-500">{plan.goal_type} · target {formatDate(plan.target_date)} · current {planCurrentWeekLabel(plan)}</p></div><Badge className={planStatusClass(plan.status)}>{plan.status}</Badge></div>
      <div className="mt-2 grid grid-cols-4 gap-1 text-center text-[11px]"><Stat label="weeks" value={weeks} /><Stat label="workouts" value={plan.workouts.length} /><Stat label="km" value={plannedKm.toFixed(1)} /><Stat label="support" value={planSupportWorkouts(plan)} /></div>
      <div className="mt-1 grid grid-cols-2 gap-1 text-center text-[11px]"><Stat label="duration" value={formatDuration(planPlannedDuration(plan))} /><Stat label="done" value={`${adherence}%`} /></div>
    </div>
    <div className="mt-2 grid gap-1.5 sm:grid-cols-[1fr_auto]"><Input value={renameDraft} onChange={(event) => onRenameDraft(event.target.value)} placeholder="Plan title" /><Button size="sm" variant="ghost" disabled={busy || !renameChanged} onClick={onRename}>{busy ? "Saving..." : "Rename"}</Button></div>
    <div className="mt-2 flex flex-wrap gap-1.5">
      {plan.status !== "active" ? <Button size="sm" disabled={busy} onClick={onActivate}>Activate</Button> : null}
      {plan.status !== "completed" ? <Button size="sm" variant="ghost" disabled={busy} onClick={onComplete}>Complete</Button> : null}
      {plan.status !== "archived" ? <Button size="sm" variant="ghost" disabled={busy} onClick={onArchive}>Archive</Button> : null}
      <Button size="sm" variant="ghost" disabled={busy} onClick={onDuplicate}>Duplicate</Button>
      <Button size="sm" variant="ghost" disabled={busy || plan.status === "active"} onClick={onDelete}>Delete</Button>
    </div>
  </div>
}

function PlanDetailHeader({ plan, currentWeekIndex }: { plan: Plan; currentWeekIndex: number | null }) {
  const history = [
    { label: "created", value: formatDateTime(plan.created_at) },
    { label: "edited", value: formatDateTime(plan.updated_at) },
  ]
  return <div className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 text-xs">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><p className="font-mono text-[10px] uppercase tracking-[0.16em] text-zinc-500">Plan header</p><h3 className="mt-1 text-base font-semibold text-white">{plan.title}</h3><p className="mt-1 text-zinc-500">{planGoalLabel(plan)}</p></div>
      <div className="flex flex-wrap gap-2"><Badge className={planStatusClass(plan.status)}>{plan.status}</Badge>{currentWeekIndex ? <Badge className="border-orange-400/40 bg-orange-400/15 text-orange-100">current week {currentWeekIndex}</Badge> : <Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">current week --</Badge>}</div>
    </div>
    <div className="mt-3 grid grid-cols-2 gap-2 text-center md:grid-cols-6">
      <Stat label="target date" value={formatDate(plan.target_date)} />
      <Stat label="target time" value={formatTargetTime(plan.target_time_seconds)} />
      <Stat label="planned km" value={(plan.adherence?.planned_distance_km || planPlannedDistance(plan)).toFixed(1)} />
      <Stat label="completed km" value={(plan.adherence?.completed_distance_km || 0).toFixed(1)} />
      <Stat label="support" value={planSupportWorkouts(plan)} />
      <Stat label="duration" value={formatDuration(plan.adherence?.planned_duration_seconds || planPlannedDuration(plan))} />
    </div>
    <div className="mt-3 grid gap-1.5 text-[11px] text-zinc-500 md:grid-cols-2">{history.map((item) => <div key={item.label} className="rounded border border-zinc-900 bg-zinc-950 px-2 py-1"><span className="font-mono uppercase tracking-[0.12em] text-zinc-600">{item.label}</span><span className="ml-2 text-zinc-300">{item.value}</span></div>)}</div>
  </div>
}

function PlanVolumeChart({ weeks }: { weeks: PlanWeekSummary[] }) {
  const maxVolume = Math.max(...weeks.map((week) => Math.max(week.planned_distance_km, week.completed_distance_km)), 1)
  if (!weeks.length) return null
  return <div className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 text-xs">
    <div className="flex flex-wrap items-center justify-between gap-2"><div><p className="font-semibold text-white">Volume chart</p><p className="mt-1 text-zinc-500">Weekly running distance with support-session markers.</p></div><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{weeks.length} weeks</Badge></div>
    <div className="mt-3 grid gap-2">{weeks.map((week) => <div key={week.week_index} className="grid grid-cols-[3.5rem_1fr_7rem] items-center gap-2 text-[11px]"><span className="text-zinc-500">W{week.week_index}</span><div className="grid gap-1"><div className="h-2 overflow-hidden rounded bg-zinc-900"><div className="h-full rounded bg-orange-400/70" style={{ width: `${Math.max(3, Math.round((week.planned_distance_km / maxVolume) * 100))}%` }} /></div><div className="h-2 overflow-hidden rounded bg-zinc-900"><div className="h-full rounded bg-zinc-400/70" style={{ width: `${Math.round((week.completed_distance_km / maxVolume) * 100)}%` }} /></div></div><span className="text-right text-zinc-400">{week.completed_distance_km.toFixed(1)}/{week.planned_distance_km.toFixed(1)} км · S{week.support_workouts}</span></div>)}</div>
  </div>
}

function PlanIntensitySplit({ split }: { split: { key: string; value: number; percent: number }[] }) {
  return <div className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 text-xs">
    <div className="flex flex-wrap items-center justify-between gap-2"><p className="font-semibold text-white">Intensity split</p><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">planned time</Badge></div>
    <div className="mt-3 grid gap-2 md:grid-cols-5">{split.map((item) => <div key={item.key} className="rounded-md border border-zinc-900 bg-zinc-950 p-2"><div className="flex items-center justify-between"><span className="font-medium text-white">{item.key}</span><span className="text-zinc-400">{item.percent}%</span></div><div className="mt-2 h-2 overflow-hidden rounded bg-zinc-900"><div className="h-full rounded bg-orange-400/70" style={{ width: `${Math.max(2, item.percent)}%` }} /></div><p className="mt-1 text-[11px] text-zinc-500">{item.value.toFixed(1)}</p></div>)}</div>
  </div>
}

function PlanVersions({ versions }: { versions: PlanVersion[] }) {
  return <div className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 text-xs">
    <div className="flex flex-wrap items-start justify-between gap-2"><div><p className="font-semibold text-white">Plan versions</p><p className="mt-1 text-zinc-500">Immutable snapshots for generation, manual edits and adaptation.</p></div><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{versions.length} saved</Badge></div>
    {versions.length ? <div className="mt-3 grid gap-2">{versions.slice(0, 5).map((version) => {
      const workoutCount = Array.isArray(version.snapshot_json?.workouts) ? version.snapshot_json.workouts.length : 0
      return <div key={version.id} className="grid gap-2 rounded-md border border-zinc-800 bg-zinc-950 p-2 md:grid-cols-[5rem_1fr_auto] md:items-center">
        <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-zinc-500">v{version.version_number}</div>
        <div><p className="font-medium text-white">{version.summary || version.reason}</p><p className="mt-1 text-zinc-500">{version.reason} · {workoutCount} workouts · {new Date(version.created_at).toLocaleString("ru-RU")}</p></div>
        <Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">snapshot</Badge>
      </div>
    })}</div> : <p className="mt-3 text-zinc-500">Versions will appear after generating or editing a plan.</p>}
  </div>
}

function riskLevel(risk: Record<string, unknown> | null | undefined) {
  return typeof risk?.level === "string" ? risk.level : "--"
}

function CoachRecommendations({ recommendations, preview, audits, error, actionError, loading, previewing, applying, onRefresh, onPreview, onApply }: { recommendations: PlanRecommendations | null; preview: PlanRecommendationPreview | null; audits: PlanRecommendationAudit[]; error: string; actionError: string; loading: boolean; previewing: boolean; applying: boolean; onRefresh: () => void; onPreview: () => void; onApply: () => void }) {
  const statusClass = recommendations?.status === "watch" ? "border-orange-400/40 bg-orange-400/15 text-orange-100" : recommendations?.status === "adjust" ? "border-rose-400/40 bg-rose-400/15 text-rose-100" : "border-zinc-700 bg-zinc-900 text-zinc-300"
  const statusLabel = recommendations?.status || (loading ? "loading" : error ? "error" : "idle")
  const canApply = Boolean(preview?.changes.length) && !applying && !previewing
  return <div className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 text-xs">
    <div className="flex flex-wrap items-start justify-between gap-2">
      <div><p className="font-semibold text-white">Coach recommendations</p><p className="mt-1 text-zinc-500">Adaptive guidance with preview/apply safeguards and audit history.</p></div>
      <div className="flex flex-wrap items-center gap-2"><Badge className={statusClass}>{statusLabel}</Badge><Button size="sm" variant="ghost" disabled={loading || previewing || applying} onClick={onRefresh}>{loading ? "Refreshing..." : "Refresh"}</Button><Button size="sm" variant="ghost" disabled={!recommendations || loading || previewing || applying} onClick={onPreview}>{previewing ? "Previewing..." : "Preview"}</Button><Button size="sm" disabled={!canApply} onClick={onApply}>{applying ? "Applying..." : "Apply"}</Button></div>
    </div>
    {error ? <div className="mt-3 rounded-md border border-orange-400/20 bg-orange-400/10 px-2 py-1.5 text-orange-100">{error}</div> : null}
    {actionError ? <div className="mt-3 rounded-md border border-rose-400/20 bg-rose-400/10 px-2 py-1.5 text-rose-100">{actionError}</div> : null}
    {recommendations ? <>
      <p className="mt-3 leading-5 text-zinc-300">{recommendations.adaptation_summary || recommendations.summary}</p>
      <div className="mt-3 grid gap-2 md:grid-cols-4 xl:grid-cols-6">
        <Stat label="completion" value={`${Math.round(recommendations.metrics.completion_rate * 100)}%`} />
        <Stat label="distance" value={`${Math.round(recommendations.metrics.distance_completion_rate * 100)}%`} />
        <Stat label="recent km" value={recommendations.metrics.recent_completed_distance_km} />
        <Stat label="next 7d km" value={recommendations.metrics.upcoming_planned_distance_km} />
        <Stat label="risk" value={`${riskLevel(recommendations.risk_before)}→${riskLevel(preview?.risk_after || recommendations.risk_after)}`} />
        <Stat label="hard 7d" value={recommendations.metrics.upcoming_hard_workouts || 0} />
      </div>
      <div className="mt-3 grid gap-2">{recommendations.recommendations.map((item) => <div key={`${item.type}-${item.title}-${item.workout_id || item.week_index || "plan"}`} className="rounded-md border border-zinc-800 bg-zinc-950 p-2"><div className="flex flex-wrap items-center justify-between gap-2"><p className="font-medium text-white">{item.title}</p><Badge className={item.severity === "warning" ? "border-orange-400/40 bg-orange-400/15 text-orange-100" : item.severity === "critical" ? "border-rose-400/40 bg-rose-400/15 text-rose-100" : "border-zinc-700 bg-zinc-900 text-zinc-300"}>{item.type}</Badge></div><p className="mt-1 leading-5 text-zinc-400">{item.message}</p>{item.reasons.length ? <p className="mt-1 text-[11px] text-zinc-600">{item.reasons.slice(0, 2).join(" · ")}</p> : null}</div>)}</div>
      {preview ? <div className="mt-3 rounded-md border border-orange-400/20 bg-orange-400/10 p-2">
        <div className="flex flex-wrap items-center justify-between gap-2"><p className="font-semibold text-orange-100">Preview diff</p><Badge className="border-orange-400/40 bg-orange-400/15 text-orange-100">{preview.changes.length} changes</Badge></div>
        {preview.changes.length ? <div className="mt-2 grid gap-1.5">{preview.changes.map((change, index) => <div key={`${change.workout_id}-${change.field}-${index}`} className="grid gap-1 rounded-md border border-zinc-800 bg-zinc-950/80 p-2 md:grid-cols-[7rem_1fr]"><div className="font-mono text-[10px] uppercase tracking-[0.12em] text-zinc-500">#{change.workout_id || "plan"} · {change.field}</div><div><p className="text-zinc-300"><span className="text-zinc-500">{formatChangeValue(change.before)}</span> <span className="text-orange-200">-&gt;</span> <span className="text-white">{formatChangeValue(change.after)}</span></p>{change.reason ? <p className="mt-1 text-[11px] text-zinc-500">{change.reason}</p> : null}</div></div>)}</div> : <p className="mt-2 text-zinc-500">No automatic changes are safe to apply.</p>}
        {preview.skipped.length ? <div className="mt-2 rounded-md border border-zinc-800 bg-zinc-950/80 p-2"><p className="font-medium text-zinc-300">Skipped</p><div className="mt-1 grid gap-1 text-[11px] text-zinc-500">{preview.skipped.slice(0, 4).map((item, index) => <p key={index}>{String(item.action || "none")}: {String(item.reason || "manual review")}</p>)}</div></div> : null}
      </div> : null}
      {audits.length ? <div className="mt-3 rounded-md border border-zinc-800 bg-zinc-950 p-2"><div className="flex items-center justify-between gap-2"><p className="font-medium text-white">Adjustment history</p><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{audits.length}</Badge></div><div className="mt-2 grid gap-1 text-[11px] text-zinc-500">{audits.slice(0, 3).map((audit) => <p key={audit.id}>#{audit.id} · {audit.status} · {new Date(audit.created_at).toLocaleString("ru-RU")}</p>)}</div></div> : null}
    </> : <p className="mt-3 text-zinc-500">{loading ? "Recommendations are loading..." : error ? "Recommendations are unavailable." : "No recommendations loaded."}</p>}
  </div>
}

function PlanWeek({ summary, candidatesByWorkout, candidateErrors, feedbackDrafts, completionDrafts, rescheduleDrafts, loadingCandidates, onFindCandidates, onLinkCandidate, onUpdate, onReschedule, onUnlinkActivity, onRescheduleDraft, onFeedbackDraft, onCompletionDraft, onCompleteWorkout, onSaveFeedback }: { summary: PlanWeekSummary; candidatesByWorkout: Record<number, PlanActivityMatchCandidate[]>; candidateErrors: Record<number, string>; feedbackDrafts: Record<number, FeedbackDraft>; completionDrafts: Record<number, CompletionDraft>; rescheduleDrafts: Record<number, string>; loadingCandidates: number | null; onFindCandidates: (workout: PlanWorkout) => Promise<void>; onLinkCandidate: (workout: PlanWorkout, activityId: number) => Promise<void>; onUpdate: (workout: PlanWorkout, status: string) => Promise<void>; onReschedule: (workout: PlanWorkout, scheduledDate: string) => Promise<void>; onUnlinkActivity: (workout: PlanWorkout) => Promise<void>; onRescheduleDraft: (workout: PlanWorkout, value: string) => void; onFeedbackDraft: (workout: PlanWorkout, patch: Partial<FeedbackDraft>) => void; onCompletionDraft: (workout: PlanWorkout, patch: Partial<CompletionDraft>) => void; onCompleteWorkout: (workout: PlanWorkout) => Promise<void>; onSaveFeedback: (workout: PlanWorkout) => Promise<void> }) {
  return <div className="rounded-md border border-zinc-800 bg-zinc-950/60">
    <div className="border-b border-zinc-800 px-3 py-2">
      <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-xs font-semibold text-white">Week {summary.week_index}</p><div className="flex flex-wrap gap-1.5"><Badge>{summary.planned_distance_km.toFixed(1)} км</Badge>{summary.support_workouts ? <Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">support {summary.support_workouts}</Badge> : null}{summary.deload ? <Badge className="border-orange-400/40 bg-orange-400/15 text-orange-100">deload</Badge> : null}</div></div>
      <div className="mt-2 grid grid-cols-2 gap-2 text-[11px] md:grid-cols-6">
        <div className="rounded bg-zinc-950 px-2 py-1"><span className="text-zinc-600">time</span><div className="text-zinc-300">{summary.planned_time_label}</div></div>
        <div className="rounded bg-zinc-950 px-2 py-1"><span className="text-zinc-600">hard</span><div className="text-zinc-300">{summary.hard_sessions}</div></div>
        <div className="rounded bg-zinc-950 px-2 py-1"><span className="text-zinc-600">long</span><div className="text-zinc-300">{summary.long_run_km?.toFixed(1) || "--"} км</div></div>
        <div className="rounded bg-zinc-950 px-2 py-1"><span className="text-zinc-600">support</span><div className="text-zinc-300">{formatDuration(summary.support_duration_seconds)}</div></div>
        <div className="rounded bg-zinc-950 px-2 py-1"><span className="text-zinc-600">done</span><div className="text-zinc-300">{Math.round(summary.completion_rate * 100)}%</div></div>
        <div className="rounded bg-zinc-950 px-2 py-1"><span className="text-zinc-600">actual</span><div className="text-zinc-300">{summary.completed_distance_km.toFixed(1)} км</div></div>
      </div>
      {summary.warnings.length ? <div className="mt-2 grid gap-1">{summary.warnings.map((warning) => <p key={warning} className="rounded border border-orange-400/20 bg-orange-400/10 px-2 py-1 text-[11px] text-orange-100">{warning}</p>)}</div> : null}
    </div>
    <div className="grid gap-2 p-3">{summary.workouts.map((workout) => {
      const candidates = candidatesByWorkout[workout.id] || []
      const draft = feedbackDrafts[workout.id] || feedbackDraftFromWorkout(workout)
      const completionDraft = completionDrafts[workout.id] || completionDraftFromWorkout(workout)
      const rescheduleDraft = rescheduleDrafts[workout.id] || workout.scheduled_date || ""
      const canGiveFeedback = ["done", "missed", "skipped"].includes(workout.status)
      const canCompleteManually = !workout.completed_activity_id && ["planned", "rescheduled", "missed", "skipped"].includes(workout.status)
      const canReschedule = !workout.completed_activity_id && ["planned", "rescheduled", "missed", "skipped"].includes(workout.status)
      const supportWorkout = isSupportWorkoutType(workout.workout_type)
      return <div key={workout.id} className="rounded-md border border-zinc-900 bg-zinc-950 p-3 text-xs">
        <div className="flex flex-wrap items-start justify-between gap-2"><div><p className="font-medium text-white">{workout.title}</p><p className="mt-1 text-zinc-500">{workout.scheduled_date ? new Date(workout.scheduled_date).toLocaleDateString("ru-RU") : "no date"} · {formatWorkoutTarget(workout)} · {workout.intensity}</p></div><div className="flex flex-wrap gap-1.5"><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{workout.workout_type}</Badge><Badge className={workout.status === "done" ? "border-orange-400/40 bg-orange-400/15 text-orange-100" : "border-zinc-700 bg-zinc-900 text-zinc-300"}>{workout.status}</Badge></div></div>
        <div className="mt-2 grid gap-2 md:grid-cols-4">
          <div className="rounded-md border border-zinc-900 bg-zinc-950/80 px-2 py-1.5"><span className="font-mono text-[10px] uppercase tracking-[0.12em] text-zinc-600">Target</span><p className="mt-1 text-zinc-300">{workoutTargetMode(workout)} · {formatWorkoutTarget(workout)}</p></div>
          <div className="rounded-md border border-zinc-900 bg-zinc-950/80 px-2 py-1.5"><span className="font-mono text-[10px] uppercase tracking-[0.12em] text-zinc-600">Purpose</span><p className="mt-1 text-zinc-400">{workoutPurpose(workout)}</p></div>
          <div className="rounded-md border border-zinc-900 bg-zinc-950/80 px-2 py-1.5 md:col-span-2"><span className="font-mono text-[10px] uppercase tracking-[0.12em] text-zinc-600">Safety note</span><p className="mt-1 text-zinc-400">{workoutSafetyNote(workout)}</p></div>
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5">{workoutBlocks(workout).map((block) => <Badge key={block} className="border-zinc-700 bg-zinc-900 text-zinc-300">{block}</Badge>)}</div>
        <p className="mt-2 leading-5 text-zinc-400">{workout.description}</p>
        {workout.completed_activity_id ? <div className="mt-2 rounded-md border border-orange-400/20 bg-orange-400/10 px-2 py-1.5 text-[11px] text-orange-100">Linked activity #{workout.completed_activity_id}: {formatWorkoutActual(workout)}</div> : null}
        {workout.execution_score?.score !== null && workout.execution_score ? <div className="mt-2 rounded-md border border-zinc-800 bg-zinc-950/80 px-2 py-1.5 text-[11px]"><div className="flex flex-wrap items-center justify-between gap-2"><span className="text-zinc-500">Execution score</span><Badge className={workout.execution_score.score && workout.execution_score.score >= 0.8 ? "border-orange-400/40 bg-orange-400/15 text-orange-100" : workout.execution_score.subjective_risk === "high" ? "border-rose-400/40 bg-rose-400/15 text-rose-100" : "border-zinc-700 bg-zinc-900 text-zinc-300"}>{Math.round((workout.execution_score.score || 0) * 100)}% · {workout.execution_score.status}</Badge></div><div className="mt-1 flex flex-wrap gap-2 text-zinc-500"><span>volume {workout.execution_score.volume_score === null ? "--" : `${Math.round(workout.execution_score.volume_score * 100)}%`}</span><span>intensity {workout.execution_score.intensity_score === null ? "--" : `${Math.round(workout.execution_score.intensity_score * 100)}%`}</span><span>adherence {workout.execution_score.adherence_status}</span></div>{workout.execution_score.flags.length ? <p className="mt-1 text-zinc-600">{workout.execution_score.flags.slice(0, 2).join(" · ")}</p> : null}</div> : null}
        {canCompleteManually ? <div className="mt-2 rounded-md border border-zinc-800 bg-zinc-950/70 p-2">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2"><p className="font-medium text-white">Manual completion</p><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">Workout Detail</Badge></div>
          <div className="grid gap-2 md:grid-cols-4">
            {supportWorkout ? <div className="rounded-md border border-zinc-800 bg-zinc-950 px-2 py-1.5 text-zinc-500">duration-only</div> : <Input type="number" min="0" max="250" step="0.1" placeholder="actual km" value={completionDraft.actual_distance_km} onChange={(event) => onCompletionDraft(workout, { actual_distance_km: event.target.value })} />}
            <Input type="number" min="1" max="2880" step="1" placeholder="minutes" value={completionDraft.actual_duration_minutes} onChange={(event) => onCompletionDraft(workout, { actual_duration_minutes: event.target.value })} />
            <Input type="number" min="0" max="10" step="1" placeholder="RPE" value={completionDraft.rpe} onChange={(event) => onCompletionDraft(workout, { rpe: event.target.value })} />
            <Input type="number" min="30" max="240" step="1" placeholder="avg HR" value={completionDraft.average_heart_rate_bpm} onChange={(event) => onCompletionDraft(workout, { average_heart_rate_bpm: event.target.value })} />
          </div>
          <div className="mt-2 grid gap-2 md:grid-cols-4">
            <Input type="number" min="0" max="10" placeholder="soreness" value={completionDraft.soreness_0_10} onChange={(event) => onCompletionDraft(workout, { soreness_0_10: event.target.value, fatigue: event.target.value })} />
            <Input type="number" min="0" max="10" placeholder="pain" value={completionDraft.pain_level} onChange={(event) => onCompletionDraft(workout, { pain_level: event.target.value, pain: Number(event.target.value) > 0 })} />
            <Input type="number" min="0" max="10" placeholder="sleep" value={completionDraft.sleep_quality_0_10} onChange={(event) => onCompletionDraft(workout, { sleep_quality_0_10: event.target.value, sleep_quality: event.target.value })} />
            <Input type="datetime-local" value={completionDraft.completed_at} onChange={(event) => onCompletionDraft(workout, { completed_at: event.target.value })} />
          </div>
          <div className="mt-2 grid gap-2 md:grid-cols-[1fr_1fr_1fr_auto]"><Input placeholder="pain notes" value={completionDraft.pain_notes} onChange={(event) => onCompletionDraft(workout, { pain_notes: event.target.value })} /><Input placeholder="weather" value={completionDraft.weather_notes} onChange={(event) => onCompletionDraft(workout, { weather_notes: event.target.value })} /><Input placeholder="user notes" value={completionDraft.user_notes} onChange={(event) => onCompletionDraft(workout, { user_notes: event.target.value, notes: event.target.value })} /><Button size="sm" onClick={() => onCompleteWorkout(workout)}>Complete</Button></div>
        </div> : null}
        {canGiveFeedback ? <div className="mt-2 rounded-md border border-zinc-800 bg-zinc-950/70 p-2">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2"><p className="font-medium text-white">Workout feedback</p>{workout.feedback ? <Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">saved</Badge> : <Badge>new</Badge>}</div>
          <div className="grid gap-2 md:grid-cols-5">
            <Input type="number" min="0" max="10" placeholder="RPE" value={draft.rpe} onChange={(event) => onFeedbackDraft(workout, { rpe: event.target.value })} />
            <Input type="number" min="0" max="10" placeholder="soreness" value={draft.soreness_0_10} onChange={(event) => onFeedbackDraft(workout, { soreness_0_10: event.target.value, fatigue: event.target.value })} />
            <Input type="number" min="0" max="10" placeholder="pain" value={draft.pain_level} onChange={(event) => onFeedbackDraft(workout, { pain_level: event.target.value, pain: Number(event.target.value) > 0 })} />
            <Input type="number" min="0" max="10" placeholder="sleep" value={draft.sleep_quality_0_10} onChange={(event) => onFeedbackDraft(workout, { sleep_quality_0_10: event.target.value, sleep_quality: event.target.value })} />
            <label className="flex items-center gap-2 rounded-md border border-zinc-800 bg-zinc-950 px-2 py-1.5 text-zinc-400"><input checked={draft.pain} type="checkbox" onChange={(event) => onFeedbackDraft(workout, { pain: event.target.checked })} /> pain</label>
          </div>
          <div className="mt-2 grid gap-2 md:grid-cols-[1fr_1fr_1fr_auto]"><Input placeholder="pain notes" value={draft.pain_notes} onChange={(event) => onFeedbackDraft(workout, { pain_notes: event.target.value })} /><Input placeholder="weather" value={draft.weather_notes} onChange={(event) => onFeedbackDraft(workout, { weather_notes: event.target.value })} /><Input placeholder="user notes" value={draft.user_notes} onChange={(event) => onFeedbackDraft(workout, { user_notes: event.target.value, notes: event.target.value })} /><Button size="sm" onClick={() => onSaveFeedback(workout)}>Save feedback</Button></div>
        </div> : null}
        {canReschedule ? <div className="mt-2 grid gap-2 md:grid-cols-[1fr_auto]"><Input type="date" value={rescheduleDraft} onChange={(event) => onRescheduleDraft(workout, event.target.value)} /><Button size="sm" variant="ghost" disabled={!rescheduleDraft || rescheduleDraft === workout.scheduled_date} onClick={() => onReschedule(workout, rescheduleDraft)}>Reschedule</Button></div> : null}
        <div className="mt-2 flex flex-wrap gap-2">{workout.completed_activity_id ? <><Badge className="border-orange-400/40 bg-orange-400/15 text-orange-100">linked done</Badge><Button size="sm" variant="ghost" onClick={() => onUnlinkActivity(workout)}>Unlink activity</Button></> : <><Button size="sm" variant="ghost" onClick={() => onUpdate(workout, "missed")}>Missed</Button><Button size="sm" variant="ghost" onClick={() => onUpdate(workout, "skipped")}>Skipped</Button></>}<Button size="sm" variant="ghost" disabled={loadingCandidates === workout.id} onClick={() => onFindCandidates(workout)}>{loadingCandidates === workout.id ? "Matching..." : "Find activity"}</Button></div>
        {candidateErrors[workout.id] ? <p className="mt-2 text-[11px] text-orange-200">{candidateErrors[workout.id]}</p> : null}
        {candidates.length ? <div className="mt-2 grid gap-1.5 rounded-md border border-zinc-800 bg-zinc-950/70 p-2">
          {candidates.map((candidate) => <div key={candidate.activity.id} className="grid gap-2 rounded-md bg-zinc-900/70 p-2 md:grid-cols-[1fr_auto] md:items-center">
            <div><p className="font-medium text-white">{candidate.activity.title}<span className="ml-2 font-mono text-[10px] text-zinc-500">#{candidate.activity.id}</span></p><p className="mt-1 text-zinc-500">{candidate.activity.started_at ? new Date(candidate.activity.started_at).toLocaleDateString("ru-RU") : "без даты"} · {formatDistance(candidate.activity.distance_km)} · {formatDuration(candidate.activity.duration_seconds)}</p><p className="mt-1 text-[11px] text-zinc-500">{candidate.reasons.slice(0, 2).join(" · ")}</p></div>
            <div className="flex flex-wrap items-center gap-2 md:justify-end"><Badge className="border-zinc-700 bg-zinc-950 text-zinc-300">{Math.round(candidate.score * 100)}% {candidate.confidence}</Badge><Button size="sm" aria-label={`Link activity ${candidate.activity.title} #${candidate.activity.id} to planned workout ${workout.title} #${workout.id}`} onClick={() => onLinkCandidate(workout, candidate.activity.id)}>Link</Button></div>
          </div>)}
        </div> : null}
      </div>
    })}</div>
  </div>
}

function SettingsPage({ providers, onChanged }: { providers: LlmProvider[]; onChanged: () => Promise<void> }) {
  const [busyProvider, setBusyProvider] = useState<number | null>(null)
  const [message, setMessage] = useState("")
  const [testResults, setTestResults] = useState<Record<number, LlmProviderTest>>({})
  const [integrations, setIntegrations] = useState<Integration[]>([])
  const [auditLog, setAuditLog] = useState<AuditLogEntry[]>([])
  const [dataMessage, setDataMessage] = useState("")
  const [deleteConfirm, setDeleteConfirm] = useState("")
  const [dataBusy, setDataBusy] = useState(false)

  async function loadDataManagement() {
    try {
      await devLogin()
      const [nextIntegrations, nextAuditLog] = await Promise.all([api.integrations(), api.auditLog(100, 0)])
      setIntegrations(nextIntegrations)
      setAuditLog(nextAuditLog)
    } catch (error) {
      console.error(error)
      setDataMessage("Не удалось загрузить integrations/audit log")
    }
  }

  useEffect(() => { void loadDataManagement() }, [])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const data = new FormData(form)
    setMessage("")
    try {
      await api.createProvider({
        provider: stringOrNull(data.get("provider")) || "openai",
        display_name: stringOrNull(data.get("display_name")) || "LLM provider",
        base_url: stringOrNull(data.get("base_url")),
        model: stringOrNull(data.get("model")) || "gpt-4o-mini",
        api_key: stringOrNull(data.get("api_key")),
        is_default: data.get("is_default") === "on",
      })
      form.reset()
      setMessage("Provider saved. API key was stored server-side and will not be returned.")
      await onChanged()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to save provider")
    }
  }

  async function updateExisting(event: FormEvent<HTMLFormElement>, provider: LlmProvider) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    const nextKey = stringOrNull(data.get("api_key"))
    const payload: Record<string, unknown> = {
      display_name: stringOrNull(data.get("display_name")) || provider.display_name,
      base_url: stringOrNull(data.get("base_url")),
      model: stringOrNull(data.get("model")) || provider.model,
    }
    if (data.get("clear_api_key") === "on") payload.api_key = null
    else if (nextKey) payload.api_key = nextKey
    setBusyProvider(provider.id)
    setMessage("")
    try {
      await api.updateProvider(provider.id, payload)
      setMessage(`Updated ${provider.display_name}.`)
      await onChanged()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to update provider")
    } finally {
      setBusyProvider(null)
    }
  }

  async function setDefault(provider: LlmProvider) {
    setBusyProvider(provider.id)
    setMessage("")
    try {
      await api.setDefaultProvider(provider.id)
      setMessage(`${provider.display_name} is now default.`)
      await onChanged()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to set default provider")
    } finally {
      setBusyProvider(null)
    }
  }

  async function testProvider(provider: LlmProvider) {
    setBusyProvider(provider.id)
    setMessage("")
    try {
      const result = await api.testProvider(provider.id)
      setTestResults((current) => ({ ...current, [provider.id]: result }))
      setMessage(`${provider.display_name}: ${result.status}`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to test provider")
    } finally {
      setBusyProvider(null)
    }
  }

  async function deleteExisting(provider: LlmProvider) {
    setBusyProvider(provider.id)
    setMessage("")
    try {
      await api.deleteProvider(provider.id)
      setMessage(`Deleted ${provider.display_name}.`)
      await onChanged()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to delete provider")
    } finally {
      setBusyProvider(null)
    }
  }

  async function downloadExport() {
    setDataBusy(true)
    setDataMessage("")
    try {
      await devLogin()
      const exported = await api.exportData()
      const blob = new Blob([JSON.stringify(exported, null, 2)], { type: "application/json" })
      const url = URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = url
      link.download = `runforfan-export-${new Date().toISOString().slice(0, 10)}.json`
      link.click()
      URL.revokeObjectURL(url)
      setDataMessage("Export generated. Secrets are omitted; provider keys are represented as has_api_key only.")
      await loadDataManagement()
    } catch (error) {
      setDataMessage(error instanceof Error ? error.message : "Failed to export data")
    } finally {
      setDataBusy(false)
    }
  }

  async function deleteAccountData() {
    if (deleteConfirm !== "DELETE") return
    setDataBusy(true)
    setDataMessage("")
    try {
      await devLogin()
      const result = await api.deleteAccountData("DELETE")
      setDataMessage(`Deleted account-scoped data. Audit #${result.audit_id ?? "--"}.`)
      setDeleteConfirm("")
      await onChanged()
      await loadDataManagement()
    } catch (error) {
      setDataMessage(error instanceof Error ? error.message : "Failed to delete account data")
    } finally {
      setDataBusy(false)
    }
  }

  return <div className="grid gap-4">
    <div className="grid gap-4 xl:grid-cols-[24rem_1fr]">
    <Card><CardHeader><div><CardTitle>Add LLM provider</CardTitle><p className="text-xs text-zinc-500">OpenAI-compatible and Anthropic providers for recognition and explanations. Keys are never returned to the frontend.</p></div><Badge>6.17</Badge></CardHeader><form onSubmit={submit} className="grid gap-3 p-4 text-xs">
      <Field label="Provider"><Select name="provider"><option value="openai">OpenAI compatible</option><option value="anthropic">Anthropic</option></Select></Field>
      <Field label="Display name"><Input name="display_name" placeholder="Display name" required /></Field>
      <Field label="Base URL"><Input name="base_url" placeholder="Full endpoint URL optional" /></Field>
      <Field label="Model"><Input name="model" placeholder="gpt-4o-mini, claude-3-5-sonnet..." required /></Field>
      <Field label="API key"><Input name="api_key" placeholder="API key" type="password" /></Field>
      <label className="flex items-center gap-2 text-xs text-zinc-400"><input name="is_default" type="checkbox" /> default provider</label>
      <Button type="submit">Save provider</Button>
      {message ? <p className="rounded-md border border-zinc-800 bg-zinc-950 px-2 py-1.5 text-xs text-zinc-300">{message}</p> : null}
    </form></Card>
    <Card><CardHeader><div><CardTitle>Providers</CardTitle><p className="text-xs text-zinc-500">Edit, test with a safe prompt, set default or disable providers.</p></div><Badge>{providers.length} total</Badge></CardHeader><div className="divide-y divide-zinc-800">{providers.map((provider) => {
      const result = testResults[provider.id]
      const busy = busyProvider === provider.id
      return <div key={provider.id} className="grid gap-3 px-4 py-3 text-xs">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div><p className="font-medium text-white">{provider.display_name}<span className="ml-2 font-mono text-[10px] text-zinc-500">#{provider.id}</span></p><p className="mt-1 text-zinc-500">{provider.provider} · {provider.model}</p></div>
          <div className="flex flex-wrap gap-1">{provider.is_default && <Badge>default</Badge>}<Badge className={provider.has_api_key ? "border-zinc-700 bg-zinc-900 text-zinc-300" : "border-orange-400/30 bg-orange-400/10 text-orange-200"}>key {provider.has_api_key ? "stored" : "missing"}</Badge><Badge className={provider.supports_vision ? "border-zinc-700 bg-zinc-900 text-zinc-300" : "border-zinc-800 bg-zinc-950 text-zinc-500"}>vision {provider.supports_vision ? "likely" : "unknown"}</Badge></div>
        </div>
        <form onSubmit={(event) => updateExisting(event, provider)} className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
          <Field label="Name"><Input name="display_name" defaultValue={provider.display_name} /></Field>
          <Field label="Base URL"><Input name="base_url" defaultValue={provider.base_url || ""} placeholder="default endpoint" /></Field>
          <Field label="Model"><Input name="model" defaultValue={provider.model} /></Field>
          <Field label="New API key"><Input name="api_key" type="password" placeholder={provider.has_api_key ? "leave blank to keep" : "optional"} /></Field>
          <label className="flex h-8 items-center gap-2 rounded-md border border-zinc-800 bg-zinc-950 px-2.5 text-zinc-400"><input name="clear_api_key" type="checkbox" /> clear key</label>
          <div className="flex flex-wrap gap-2 md:col-span-2 xl:col-span-3"><Button size="sm" type="submit" disabled={busy}>{busy ? "Saving..." : "Save changes"}</Button><Button size="sm" type="button" variant="secondary" disabled={busy || provider.is_default} onClick={() => setDefault(provider)}>Set default</Button><Button size="sm" type="button" variant="secondary" disabled={busy} onClick={() => testProvider(provider)}>{busy ? "Testing..." : "Test"}</Button><Button size="sm" type="button" variant="secondary" disabled={busy} onClick={() => deleteExisting(provider)}>Delete</Button></div>
        </form>
        {result ? <div className={`rounded-md border px-2 py-1.5 text-xs ${result.ok ? "border-zinc-700 bg-zinc-900 text-zinc-200" : "border-orange-400/20 bg-orange-400/10 text-orange-100"}`}>{result.status} · {result.response_ms ?? "--"} ms · vision {result.supports_vision ? "likely" : "unknown"}<div className="mt-1 text-zinc-500">{result.message}</div></div> : null}
      </div>
    })}{!providers.length ? <p className="p-4 text-xs text-zinc-500">No active providers yet.</p> : null}</div></Card>
    </div>
    <div className="grid gap-4 xl:grid-cols-[1fr_1fr]">
      <Card>
        <CardHeader><div><CardTitle>Integrations</CardTitle><p className="text-xs text-zinc-500">Configured and planned data sources.</p></div><Button size="sm" variant="secondary" onClick={loadDataManagement}>Refresh</Button></CardHeader>
        <div className="divide-y divide-zinc-800">{integrations.map((integration) => <div key={integration.id} className="grid gap-2 px-4 py-3 text-xs md:grid-cols-[1fr_auto] md:items-start">
          <div><p className="font-medium text-white">{integration.name}</p><p className="mt-1 text-zinc-500">{integration.description}</p><p className="mt-1 font-mono text-[10px] uppercase tracking-[0.14em] text-zinc-600">{integration.category} · {integration.id}</p></div>
          <Badge className={integration.configured ? "border-zinc-700 bg-zinc-900 text-zinc-300" : integration.status === "planned" ? "border-zinc-800 bg-zinc-950 text-zinc-500" : "border-orange-400/30 bg-orange-400/10 text-orange-200"}>{integration.status}</Badge>
        </div>)}{!integrations.length ? <p className="p-4 text-xs text-zinc-500">No integration data loaded.</p> : null}</div>
      </Card>
      <Card>
        <CardHeader><div><CardTitle>Data management</CardTitle><p className="text-xs text-zinc-500">Export current user data or wipe account-scoped records.</p></div><Badge>6.18</Badge></CardHeader>
        <div className="grid gap-3 p-4 text-xs">
          <Button type="button" disabled={dataBusy} onClick={downloadExport}>{dataBusy ? "Working..." : "Download JSON export"}</Button>
          <div className="rounded-md border border-zinc-800 bg-zinc-950 p-3 text-zinc-400">Export omits API keys and local screenshot file paths. It includes user-scoped activities, plans, goals, profile, providers without secrets, imports and audit log.</div>
          <div className="grid gap-2 rounded-md border border-orange-400/20 bg-orange-400/10 p-3">
            <p className="font-medium text-orange-100">Danger zone: delete account data</p>
            <p className="text-orange-100/80">This keeps the user/session but deletes activities, plans, goals, profile, zones, imports, provider settings and prior audit rows.</p>
            <Input value={deleteConfirm} onChange={(event) => setDeleteConfirm(event.target.value)} placeholder="Type DELETE to confirm" />
            <Button type="button" variant="secondary" disabled={dataBusy || deleteConfirm !== "DELETE"} onClick={deleteAccountData}>Delete user data</Button>
          </div>
          {dataMessage ? <p className="rounded-md border border-zinc-800 bg-zinc-950 px-2 py-1.5 text-xs text-zinc-300">{dataMessage}</p> : null}
        </div>
      </Card>
    </div>
    <Card>
      <CardHeader><div><CardTitle>Audit log</CardTitle><p className="text-xs text-zinc-500">Recent user-scoped import, provider, export and delete events.</p></div><Badge>{auditLog.length} events</Badge></CardHeader>
      <div className="overflow-x-auto"><table className="w-full min-w-[720px] text-left text-xs"><thead className="border-b border-zinc-800 text-[10px] uppercase tracking-[0.14em] text-zinc-500"><tr><th className="px-4 py-2">Time</th><th>Action</th><th>Entity</th><th>Metadata</th></tr></thead><tbody>{auditLog.map((event) => <tr key={event.id} className="border-b border-zinc-900 last:border-0 align-top"><td className="px-4 py-2 text-zinc-500">{new Date(event.created_at).toLocaleString("ru-RU")}</td><td><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{event.action}</Badge></td><td className="text-zinc-400">{event.entity_type}{event.entity_id ? ` #${event.entity_id}` : ""}</td><td className="max-w-[28rem] text-zinc-500">{event.metadata_json ? JSON.stringify(event.metadata_json) : "--"}</td></tr>)}</tbody></table>{!auditLog.length ? <p className="p-4 text-xs text-zinc-500">Audit log is empty.</p> : null}</div>
    </Card>
  </div>
}

export default App
