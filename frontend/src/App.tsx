import { Activity, Bot, CalendarDays, ChartSpline, Goal, HeartPulse, Menu, Moon, Settings, Shield, Upload, X, Zap } from "lucide-react"
import { type FormEvent, type ReactNode, useEffect, useRef, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { api, type Activity as ActivityType, type AthleteMeasurement, type AthleteProfile, type CalendarEvent, type CalendarResponse, type DashboardSummary, devLogin, type ImportBatch, type ImportUploadResult, type LlmProvider, type Plan, type PlanActivityMatchCandidate, type PlanBuilderPreview, type PlanRecommendationAudit, type PlanRecommendationPreview, type PlanRecommendations, type PlanWorkout, type PlanWorkoutMatchCandidate, type ProfileCompleteness, type SafetyCheck, type Zone, type Zones } from "@/lib/api"
import { cn } from "@/lib/utils"

type Page = "overview" | "activities" | "imports" | "calendar" | "analytics" | "profile" | "planning" | "settings"
type FeedbackDraft = { rpe: string; fatigue: string; pain: boolean; pain_level: string; sleep_quality: string; notes: string }
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

const nav = [
  ["overview", "Dashboard", Zap],
  ["activities", "Activities", Activity],
  ["imports", "Imports", Upload],
  ["calendar", "Calendar", CalendarDays],
  ["analytics", "Analytics", ChartSpline],
  ["profile", "Profile & zones", HeartPulse],
  ["planning", "Plans", Goal],
  ["settings", "LLM providers", Settings],
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

function numberOrNull(value: FormDataEntryValue | null) {
  if (value === null || value === "") return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function stringOrNull(value: FormDataEntryValue | null) {
  return value === null || value === "" ? null : String(value)
}

function planBuilderPayload(form: HTMLFormElement) {
  const data = new FormData(form)
  return {
    title: stringOrNull(data.get("title")) || "Марафонская программа",
    goal_type: stringOrNull(data.get("goal_type")) || "marathon",
    race_distance_km: numberOrNull(data.get("race_distance_km")) || 42.2,
    target_date: stringOrNull(data.get("target_date")),
    available_days_per_week: numberOrNull(data.get("available_days_per_week")) || 4,
    current_weekly_distance_km: numberOrNull(data.get("current_weekly_distance_km")),
  }
}

function feedbackDraftFromWorkout(workout: PlanWorkout): FeedbackDraft {
  return {
    rpe: workout.feedback?.rpe?.toString() || "",
    fatigue: workout.feedback?.fatigue?.toString() || "",
    pain: workout.feedback?.pain || false,
    pain_level: workout.feedback?.pain_level?.toString() || "",
    sleep_quality: workout.feedback?.sleep_quality?.toString() || "",
    notes: workout.feedback?.notes || "",
  }
}

function feedbackNumber(value: string) {
  if (value.trim() === "") return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : NaN
}

function feedbackValidationError(draft: FeedbackDraft) {
  const fields: [keyof FeedbackDraft, string][] = [["rpe", "RPE"], ["fatigue", "fatigue"], ["pain_level", "pain"], ["sleep_quality", "sleep"]]
  for (const [field, label] of fields) {
    const value = feedbackNumber(String(draft[field]))
    if (value !== null && (!Number.isFinite(value) || !Number.isInteger(value) || value < 0 || value > 10)) return `${label} должен быть целым числом 0-10`
  }
  return ""
}

function feedbackPayload(draft: FeedbackDraft) {
  return {
    rpe: feedbackNumber(draft.rpe),
    fatigue: feedbackNumber(draft.fatigue),
    pain: draft.pain,
    pain_level: feedbackNumber(draft.pain_level),
    sleep_quality: feedbackNumber(draft.sleep_quality),
    notes: draft.notes || null,
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
  }
  return labels[field] || field
}

function workoutBlockSummary(activity: ActivityType) {
  const workBlocks = activity.workout_blocks?.filter((block) => block.block_type === "work") || []
  if (!workBlocks.length) return null
  const distance = workBlocks[0]?.distance_km
  const sameDistance = distance && workBlocks.every((block) => block.distance_km === distance)
  return sameDistance ? `${workBlocks.length} x ${distance.toFixed(2)} км` : `${workBlocks.length} рабочих блока`
}

function App() {
  const [page, setPage] = useState<Page>("overview")
  const [mobileOpen, setMobileOpen] = useState(false)
  const [activities, setActivities] = useState<ActivityType[]>([])
  const [analytics, setAnalytics] = useState<Record<string, any>>({})
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

function Overview({ activities, analytics, dashboard, providers, onImport, onPlans }: { activities: ActivityType[]; analytics: Record<string, any>; dashboard: DashboardSummary | null; providers: LlmProvider[]; onImport: () => void; onPlans: () => void }) {
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
        <Stat label="activities" value={metrics.activity_count ?? activities.length} />
        <Stat label="distance" value={Number(metrics.total_distance_km || 0).toFixed(1)} suffix="km" />
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
  if (status === "risk" || status === "adjust" || status === "critical") return "border-rose-400/30 bg-rose-500/10 text-rose-200"
  if (status === "watch" || status === "warning") return "border-orange-400/30 bg-orange-400/10 text-orange-200"
  if (status === "ok" || status === "active" || status === "done") return "border-zinc-700 bg-zinc-900 text-zinc-200"
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
        <p className="mt-1 text-zinc-500">{formatDate(focus.scheduled_date)} · week {focus.week_index} · {focus.workout_type} · {formatDistance(focus.distance_km)}</p>
        <p className="mt-2 max-w-3xl leading-5 text-zinc-400">{focus.description || "No target description"}</p>
        {focus.execution_score?.flags?.length ? <p className="mt-2 text-orange-200">{focus.execution_score.flags.slice(0, 2).join(" · ")}</p> : null}
      </div>
      <div className="grid grid-cols-3 gap-2 md:w-64">
        <Stat label="score" value={focus.execution_score?.score === null || focus.execution_score?.score === undefined ? "--" : `${Math.round(focus.execution_score.score * 100)}%`} />
        <Stat label="risk" value={focus.execution_score?.subjective_risk || "--"} />
        <Stat label="actual" value={formatDistance(focus.actual_distance_km)} />
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
        <tbody>{currentWeek.workouts.map((workout) => <tr key={workout.id} className="border-b border-zinc-900 last:border-0 align-top hover:bg-zinc-900/60"><td className="px-4 py-3 font-medium text-white">{workout.title}<div className="text-[11px] text-zinc-500">#{workout.id} · week {workout.week_index}</div></td><td>{formatDate(workout.scheduled_date)}</td><td>{workout.workout_type}<div className="text-[11px] text-zinc-500">{workout.intensity || "--"}</div></td><td>{formatDistance(workout.distance_km)}<div className="text-[11px] text-zinc-500">{formatDuration(workout.duration_seconds)}</div></td><td>{formatDistance(workout.actual_distance_km)}<div className="text-[11px] text-zinc-500">{formatDuration(workout.actual_duration_seconds)}</div></td><td>{workout.execution_score?.score === null || workout.execution_score?.score === undefined ? "--" : `${Math.round(workout.execution_score.score * 100)}%`}<div className="text-[11px] text-zinc-500">{workout.execution_score?.subjective_risk || "--"}</div></td><td><Badge className={signalClass(workout.status)}>{workout.status}</Badge></td></tr>)}</tbody>
      </table>
      {!currentWeek.workouts.length && <p className="p-4 text-xs text-zinc-500">No workouts in the current calendar week.</p>}
    </div>
  </Card>
}

function Stat({ label, value, suffix }: { label: string; value: string | number; suffix?: string }) {
  return <div className="px-4 py-3 text-center"><strong className="block text-lg text-white">{value}{suffix ? ` ${suffix}` : ""}</strong><span className="font-mono text-[10px] uppercase tracking-[0.16em] text-zinc-500">{label}</span></div>
}

function Activities({ activities, compact = false, onImport }: { activities: ActivityType[]; compact?: boolean; onImport?: () => void }) {
  return <Card>
    <CardHeader><div><CardTitle>Activities</CardTitle><p className="text-xs text-zinc-500">{activities.length} total</p></div><Button size="sm" onClick={onImport}>+ Import</Button></CardHeader>
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-left text-xs">
        <thead className="border-b border-zinc-800 text-[10px] uppercase tracking-[0.14em] text-zinc-500"><tr><th className="px-4 py-2">Name</th><th>Distance</th><th>Pace</th><th>HR</th><th>Structure</th><th>ID</th></tr></thead>
        <tbody>{activities.slice(0, compact ? 6 : undefined).map((activity) => {
          const summary = workoutBlockSummary(activity)
          return <tr key={activity.id} className="border-b border-zinc-900 last:border-0 align-top hover:bg-zinc-900/60"><td className="px-4 py-3 font-medium text-white">{activity.title}<div className="text-[11px] text-zinc-500">{activity.started_at ? new Date(activity.started_at).toLocaleString("ru-RU") : "без даты"}</div>{summary && <div className="mt-1 flex items-center gap-2"><Badge>interval</Badge><span className="text-[11px] text-orange-300">{summary}</span></div>}</td><td>{formatDistance(activity.distance_km)}<div className="text-[11px] text-zinc-500">{formatDuration(activity.duration_seconds)}</div></td><td>{formatPace(activity.average_pace_seconds_per_km)}/км</td><td>{activity.average_heart_rate_bpm || "--"}</td><td>{summary || `${activity.segments.length} km splits`}{activity.workout_blocks?.length ? <div className="mt-1 text-[11px] text-zinc-500">{activity.workout_blocks.length} blocks</div> : null}</td><td className="font-mono text-zinc-500">#{activity.id}</td></tr>
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

  useEffect(() => { void loadImports() }, [])

  return <div className="grid gap-4 xl:grid-cols-[24rem_1fr]">
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
          {uploadResult.matched_workout_id ? <div className="rounded-md border border-orange-400/20 bg-orange-400/10 px-3 py-2 text-orange-100">{uploadResult.auto_matched ? "Auto-linked by import matching" : "Currently matched"} to planned workout #{uploadResult.matched_workout_id}.</div> : null}
          {uploadResult.created_activity_id && !uploadResult.matched_workout_id ? <MatchReview candidates={matchCandidates} busy={busy} candidateError={candidateError} linkError={linkError} onLink={linkCandidate} /> : null}
        </div> : <p className="p-4 text-xs text-zinc-500">Upload a screenshot batch to see recognition and matching feedback.</p>}
      </Card>

      <Card>
        <CardHeader><div><CardTitle>Import history</CardTitle><p className="text-xs text-zinc-500">Recent recognition batches for current user.</p></div><Button size="sm" variant="secondary" onClick={loadImports}>Refresh</Button></CardHeader>
        {importHistoryError ? <p className="px-4 pb-2 text-xs text-orange-200">{importHistoryError}</p> : null}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-left text-xs">
            <thead className="border-b border-zinc-800 text-[10px] uppercase tracking-[0.14em] text-zinc-500"><tr><th className="px-4 py-2">Batch</th><th>Status</th><th>Activity</th><th>Match</th><th>Engine</th><th>Message</th><th>Date</th></tr></thead>
            <tbody>{imports.map((batch) => <tr key={batch.id} className="border-b border-zinc-900 last:border-0 align-top"><td className="px-4 py-2 font-mono text-zinc-500">#{batch.id}</td><td><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{batch.status}</Badge></td><td>{batch.created_activity_id ? `#${batch.created_activity_id}` : "--"}</td><td>{batch.matched_workout_id ? `#${batch.matched_workout_id}` : "--"}</td><td>{batch.recognition_engine || "--"}</td><td className="max-w-[18rem] text-zinc-500">{batch.recognition_message || "--"}</td><td className="text-zinc-500">{batch.created_at ? new Date(batch.created_at).toLocaleString("ru-RU") : "--"}</td></tr>)}</tbody>
          </table>
          {!imports.length && <p className="p-4 text-xs text-zinc-500">История импортов пока пуста.</p>}
        </div>
      </Card>
    </div>
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
  const dailyLoads = days.map((day) => (eventsByDate.get(day) || []).reduce((sum, event) => sum + (event.distance_km || 0), 0))
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
    <div className="flex flex-wrap items-start justify-between gap-2"><div className="min-w-0"><p className="truncate font-medium text-white">{event.title}</p><p className="mt-1 text-[11px] text-zinc-500">{isWorkout ? event.workout_type || "workout" : "activity"} · {formatDistance(event.distance_km)} · {formatDuration(event.duration_seconds)}</p></div><Badge className={signalClass(event.status || undefined)}>{event.status || event.kind}</Badge></div>
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
      <div><p className="font-medium text-white">{candidate.workout.title}<span className="ml-2 font-mono text-[10px] text-zinc-500">#{candidate.workout.id}</span></p><p className="mt-1 text-zinc-500">{formatDate(candidate.workout.scheduled_date)} · {formatDistance(candidate.workout.distance_km)} · {candidate.workout.intensity || "--"}</p><p className="mt-1 text-[11px] text-zinc-500">{candidate.reasons.slice(0, 2).join(" · ")}</p></div>
      <div className="flex flex-wrap items-center gap-2 md:justify-end"><Badge className="border-zinc-700 bg-zinc-950 text-zinc-300">{Math.round(candidate.score * 100)}% {candidate.confidence}</Badge><Button size="sm" disabled={busy} onClick={() => onLinkMatch(event, candidate.workout.id, activityId)}>Link</Button></div>
    </div>)}
  </div>
}

function Analytics({ analytics }: { analytics: Record<string, any> }) {
  const months = analytics.months || []
  const max = Math.max(1, ...months.map((month: any) => month.distance_km))
  return <Card><CardHeader><CardTitle>Monthly volume</CardTitle><Badge>{analytics.total_distance_km || 0} km total</Badge></CardHeader><div className="space-y-3 p-4">{months.map((month: any) => <div key={month.month} className="grid grid-cols-[110px_1fr_90px] items-center gap-3 text-xs"><span className="text-zinc-400">{month.month}</span><div className="h-2 rounded bg-zinc-900"><div className="h-full rounded bg-orange-400" style={{ width: `${Math.max(6, month.distance_km / max * 100)}%` }} /></div><strong>{month.distance_km.toFixed(1)} км</strong></div>)}</div></Card>
}

function ProfileZones({ profile, completeness, safety, zones, measurements, onChanged }: { profile: AthleteProfile | null; completeness: ProfileCompleteness | null; safety: SafetyCheck | null; zones: Zones | null; measurements: AthleteMeasurement[]; onChanged: () => Promise<void> }) {
  if (!profile) return <Card className="p-4 text-sm text-zinc-400">Loading profile...</Card>

  async function submitProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    const maxHr = numberOrNull(data.get("max_heart_rate_bpm"))
    await api.updateProfile({
      date_of_birth: stringOrNull(data.get("date_of_birth")),
      sex: stringOrNull(data.get("sex")) || "unspecified",
      height_cm: numberOrNull(data.get("height_cm")),
      weight_kg: numberOrNull(data.get("weight_kg")),
      timezone: stringOrNull(data.get("timezone")),
      locale: stringOrNull(data.get("locale")),
      resting_heart_rate_bpm: numberOrNull(data.get("resting_heart_rate_bpm")),
      max_heart_rate_bpm: maxHr,
      max_hr_source: maxHr ? stringOrNull(data.get("max_hr_source")) : null,
      lactate_threshold_hr_bpm: numberOrNull(data.get("lactate_threshold_hr_bpm")),
      lactate_threshold_pace_seconds_per_km: numberOrNull(data.get("lactate_threshold_pace_seconds_per_km")),
      conservative_mode: data.get("conservative_mode") === "on",
      injury_notes: stringOrNull(data.get("injury_notes")),
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
        <form key={profile.updated_at} onSubmit={submitProfile} className="grid gap-3 p-4 text-xs md:grid-cols-2 xl:grid-cols-3">
          <Field label="Дата рождения"><Input name="date_of_birth" type="date" defaultValue={profile.date_of_birth || ""} /></Field>
          <Field label="Пол"><Select name="sex" defaultValue={profile.sex}><option value="unspecified">Не указан</option><option value="male">Мужской</option><option value="female">Женский</option><option value="other">Другой</option></Select></Field>
          <Field label="Вес, кг"><Input name="weight_kg" type="number" min="25" max="250" step="0.1" defaultValue={profile.weight_kg ?? ""} placeholder="например 72.5" /></Field>
          <Field label="Рост, см"><Input name="height_cm" type="number" min="80" max="260" step="0.1" defaultValue={profile.height_cm ?? ""} /></Field>
          <Field label="Пульс покоя"><Input name="resting_heart_rate_bpm" type="number" min="25" max="120" defaultValue={profile.resting_heart_rate_bpm ?? ""} /></Field>
          <Field label="HRmax"><Input name="max_heart_rate_bpm" type="number" min="80" max="240" defaultValue={profile.max_heart_rate_bpm ?? ""} /></Field>
          <Field label="Источник HRmax"><Select name="max_hr_source" defaultValue={profile.max_hr_source || "manual"}><option value="manual">Manual</option><option value="measured">Measured</option><option value="tanaka_estimated">Tanaka estimated</option></Select></Field>
          <Field label="Пороговый пульс"><Input name="lactate_threshold_hr_bpm" type="number" min="60" max="230" defaultValue={profile.lactate_threshold_hr_bpm ?? ""} /></Field>
          <Field label="Пороговый темп, сек/км"><Input name="lactate_threshold_pace_seconds_per_km" type="number" min="120" max="1200" defaultValue={profile.lactate_threshold_pace_seconds_per_km ?? ""} /></Field>
          <Field label="Timezone"><Input name="timezone" defaultValue={profile.timezone || ""} placeholder="Europe/Moscow" /></Field>
          <Field label="Locale"><Input name="locale" defaultValue={profile.locale || ""} placeholder="ru-RU" /></Field>
          <Field label="Ограничения"><Input name="injury_notes" defaultValue={profile.injury_notes || ""} placeholder="травмы, ограничения" /></Field>
          <label className="flex h-8 items-center gap-2 rounded-md border border-zinc-800 bg-zinc-950 px-2.5 text-zinc-400"><input name="conservative_mode" type="checkbox" defaultChecked={profile.conservative_mode} /> conservative mode</label>
          <div className="md:col-span-2 xl:col-span-3"><Button type="submit">Save profile</Button></div>
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
          <Field label="Тип"><Select name="measurement_type"><option value="weight">Вес</option><option value="resting_hr">Пульс покоя</option><option value="max_hr">HRmax</option><option value="lactate_threshold">Lactate threshold</option><option value="note">Note</option></Select></Field>
          <Field label="Значение"><Input name="value_numeric" type="number" step="0.1" placeholder="число" /></Field>
          <Field label="Пороговый темп, сек/км"><Input name="threshold_pace_seconds_per_km" type="number" min="120" max="1200" placeholder="для LT" /></Field>
          <Field label="Дата"><Input name="measured_at" type="datetime-local" /></Field>
          <Field label="Источник"><Select name="source"><option value="manual">Manual</option><option value="device">Device</option><option value="screenshot">Screenshot</option></Select></Field>
          <Field label="Заметка"><Input name="notes" placeholder="опционально" /></Field>
          <div className="md:col-span-2"><Button type="submit" size="sm">Add measurement</Button></div>
        </form>
        <div className="max-h-72 overflow-auto">
          <table className="w-full min-w-[540px] text-left text-xs">
            <thead className="sticky top-0 border-b border-zinc-800 bg-zinc-950 text-[10px] uppercase tracking-[0.14em] text-zinc-500"><tr><th className="px-4 py-2">Type</th><th>Value</th><th>Source</th><th>Date</th></tr></thead>
            <tbody>{measurements.map((measurement) => <tr key={`${measurement.source_model}-${measurement.id}`} className="border-b border-zinc-900 last:border-0"><td className="px-4 py-2 font-medium text-white">{measurement.measurement_type}<div className="text-[11px] text-zinc-500">{measurement.notes || measurement.source_model}</div></td><td>{measurement.value_numeric ?? "--"}</td><td>{measurement.source}</td><td className="text-zinc-400">{measurement.measured_at ? new Date(measurement.measured_at).toLocaleString("ru-RU") : "--"}</td></tr>)}</tbody>
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

function Planning() {
  const [plans, setPlans] = useState<Plan[]>([])
  const [result, setResult] = useState<Plan | null>(null)
  const [builderPreview, setBuilderPreview] = useState<PlanBuilderPreview | null>(null)
  const [builderPreviewError, setBuilderPreviewError] = useState("")
  const [previewingBuilder, setPreviewingBuilder] = useState(false)
  const [candidatesByWorkout, setCandidatesByWorkout] = useState<Record<number, PlanActivityMatchCandidate[]>>({})
  const [candidateErrors, setCandidateErrors] = useState<Record<number, string>>({})
  const [feedbackDrafts, setFeedbackDrafts] = useState<Record<number, FeedbackDraft>>({})
  const [recommendations, setRecommendations] = useState<PlanRecommendations | null>(null)
  const [recommendationPreview, setRecommendationPreview] = useState<PlanRecommendationPreview | null>(null)
  const [recommendationAudits, setRecommendationAudits] = useState<PlanRecommendationAudit[]>([])
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
    const plan = await api.generatePlan(planBuilderPayload(event.currentTarget))
    setResult(plan)
    await loadPlans(plan.id)
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
  }

  async function updatePlanStatus(plan: Plan, status: "completed" | "archived") {
    setBusyPlan(plan.id)
    setPlanActionError("")
    try {
      const updated = await api.updatePlan(plan.id, { status })
      await loadPlans(updated.id)
      await loadRecommendations(updated.id)
      await loadRecommendationAudits(updated.id)
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

  async function updateWorkout(workout: PlanWorkout, status: string) {
    setCandidateErrors((current) => ({ ...current, [workout.id]: "" }))
    try {
      await api.updatePlanWorkout(workout.id, { status })
      if (result) {
        const plan = await api.plan(result.id)
        setResult(plan)
        await loadRecommendations(plan.id)
      }
      await loadPlans(result?.id)
    } catch (error) {
      console.error(error)
      setCandidateErrors((current) => ({ ...current, [workout.id]: "Не удалось обновить статус" }))
    }
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
      await api.linkPlanWorkoutActivity(workout.id, activityId)
      setCandidatesByWorkout((current) => ({ ...current, [workout.id]: [] }))
      if (result) {
        const plan = await api.plan(result.id)
        setResult(plan)
        await loadRecommendations(plan.id)
      }
      await loadPlans(result?.id)
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
      if (result) {
        const plan = await api.plan(result.id)
        setResult(plan)
        await loadRecommendations(plan.id)
      }
      await loadPlans(result?.id)
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
      await loadRecommendations(applied.plan.id)
      await loadRecommendationAudits(applied.plan.id)
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
      void loadRecommendations(result.id)
      void loadRecommendationAudits(result.id)
    }
    else {
      setRecommendations(null)
      setRecommendationPreview(null)
      setRecommendationAudits([])
      setRecommendationError("")
      setRecommendationActionError("")
    }
  }, [result?.id])

  const weeks = Array.from(new Set(result?.workouts.map((workout) => workout.week_index) || [])).slice(0, 4)
  const weekCount = result?.workouts.length ? Math.max(...result.workouts.map((workout) => workout.week_index)) : 0
  const visibleRecommendations = recommendations?.plan_id === result?.id ? recommendations : null
  const hasSafetyInfo = result?.explanation?.includes("Safety gates:") || false
  const conservative = hasSafetyInfo && result?.explanation?.includes("Safety gates: no active safety gates") === false
  const planMode = !result ? null : !hasSafetyInfo ? "legacy" : conservative ? "safety gated" : "standard"
  const weeklyAdherence = result?.weekly_adherence?.slice(0, 4) || []
  return <div className="grid gap-4 xl:grid-cols-[24rem_1fr]">
    <Card>
      <CardHeader><div><CardTitle>Program planner</CardTitle><p className="text-xs text-zinc-500">Profile-aware rules, zones and safety gates.</p></div>{result && <Badge>#{result.id}</Badge>}</CardHeader>
      <form ref={planBuilderForm} onSubmit={generate} className="grid gap-3 p-4 text-xs">
        <Field label="Название"><Input name="title" defaultValue="Марафонская программа" /></Field>
        <Field label="Цель"><Select name="goal_type" defaultValue="marathon"><option value="5k">5K</option><option value="10k">10K</option><option value="half_marathon">Half marathon</option><option value="marathon">Marathon</option><option value="custom">Custom</option></Select></Field>
        <Field label="Дистанция, км"><Input name="race_distance_km" type="number" min="1" max="100" step="0.1" defaultValue="42.2" /></Field>
        <Field label="Дата старта"><Input name="target_date" type="date" /></Field>
        <Field label="Дней в неделю"><Input name="available_days_per_week" type="number" min="2" max="7" defaultValue="4" /></Field>
        <Field label="Текущий объем, км/нед"><Input name="current_weekly_distance_km" type="number" min="0" max="200" step="0.1" placeholder="если пусто, возьмем из истории" /></Field>
        <div className="grid gap-2 sm:grid-cols-2"><Button type="button" variant="secondary" disabled={previewingBuilder} onClick={previewBuilder}>{previewingBuilder ? "Previewing..." : "Preview plan"}</Button><Button type="submit">Generate plan</Button></div>
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
      <CardHeader><div><CardTitle>Plan output</CardTitle><p className="text-xs text-zinc-500">Safety, zones and first-week prescription.</p></div>{result && <Badge className={conservative ? "border-orange-400/40 bg-orange-400/15 text-orange-100" : undefined}>{planMode}</Badge>}</CardHeader>
      <div className="grid gap-4 p-4 text-sm text-zinc-400">
        {result ? <>
          <p className="leading-6">{result.explanation}</p>
          <div className="flex flex-wrap items-center gap-2">
            {result.status !== "active" ? <Button size="sm" onClick={() => activate(result.id)}>Activate plan</Button> : <Badge>active plan</Badge>}
            <Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{Math.round((result.adherence?.completion_rate || 0) * 100)}% adherence</Badge>
            <Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{result.adherence?.completed_distance_km || 0}/{result.adherence?.planned_distance_km || 0} км</Badge>
            <Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">linked {result.adherence?.linked_workouts || 0}/{result.adherence?.done_workouts || 0}</Badge>
          </div>
          {result.adherence?.warnings?.length ? <div className="grid gap-2">{result.adherence.warnings.map((warning) => <div key={warning} className="rounded-md border border-orange-400/20 bg-orange-400/10 px-2 py-1.5 text-xs text-orange-100">{warning}</div>)}</div> : null}
          <CoachRecommendations recommendations={visibleRecommendations} preview={recommendationPreview?.plan_id === result.id ? recommendationPreview : null} audits={recommendationAudits} error={recommendationError} actionError={recommendationActionError} loading={loadingRecommendations} previewing={previewingRecommendations} applying={applyingRecommendations} onRefresh={() => loadRecommendations(result.id)} onPreview={() => previewRecommendations(result.id)} onApply={() => applyRecommendations(result.id)} />
          <div className="grid grid-cols-3 gap-2 text-center text-xs">
            <Stat label="weeks" value={weekCount} />
            <Stat label="workouts" value={result.workouts.length} />
            <Stat label="days/week" value={result.available_days_per_week} />
          </div>
          {weeklyAdherence.length ? <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">{weeklyAdherence.map((week) => <div key={week.week_index} className="rounded-md border border-zinc-800 bg-zinc-950 px-3 py-2 text-xs"><div className="flex items-center justify-between"><span className="font-medium text-white">Week {week.week_index}</span><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{Math.round(week.completion_rate * 100)}%</Badge></div><div className="mt-2 text-zinc-500">{week.done_workouts}/{week.planned_workouts} done</div><div className="text-zinc-500">{week.completed_distance_km}/{week.planned_distance_km} км</div></div>)}</div> : null}
          <div className="grid gap-3">{weeks.map((week) => <PlanWeek key={week} week={week} workouts={result.workouts.filter((workout) => workout.week_index === week)} candidatesByWorkout={candidatesByWorkout} candidateErrors={candidateErrors} feedbackDrafts={feedbackDrafts} loadingCandidates={loadingCandidates} onFindCandidates={loadCandidates} onLinkCandidate={linkCandidate} onUpdate={updateWorkout} onFeedbackDraft={updateFeedbackDraft} onSaveFeedback={saveFeedback} />)}</div>
        </> : <p>Generate a plan to see how profile completeness, safety gates and zones change the weekly structure.</p>}
      </div>
    </Card>
  </div>
}

function PlanBuilderPreviewCard({ preview }: { preview: PlanBuilderPreview }) {
  const maxVolume = Math.max(...preview.weekly_volume_curve.map((week) => week.planned_distance_km), 1)
  const split = ["easy", "steady", "hard"].map((key) => ({ key, value: Math.round((preview.intensity_split[key] || 0) * 100) }))
  const firstWorkouts = preview.workouts.slice(0, 8)
  return <div className="mx-4 mb-4 rounded-md border border-zinc-800 bg-zinc-950/70 p-3 text-xs">
    <div className="flex flex-wrap items-start justify-between gap-2">
      <div><p className="font-semibold text-white">Builder preview</p><p className="mt-1 text-zinc-500">Baseline, risk flags and first workouts before saving a draft.</p></div>
      <Badge className={preview.risk_flags.some((flag) => flag.severity === "critical" || flag.severity === "warning") ? "border-orange-400/40 bg-orange-400/15 text-orange-100" : "border-zinc-700 bg-zinc-900 text-zinc-300"}>{preview.risk_flags.length} flags</Badge>
    </div>
    <p className="mt-3 leading-5 text-zinc-400">{preview.explanation}</p>
    <div className="mt-3 grid grid-cols-3 gap-2 text-center">
      <Stat label="weeks" value={preview.weeks} />
      <Stat label="current" value={preview.current_weekly_distance_km.toFixed(1)} suffix="km" />
      <Stat label="peak" value={preview.peak_weekly_distance_km.toFixed(1)} suffix="km" />
    </div>
    <div className="mt-3 rounded-md border border-zinc-800 bg-zinc-950 p-2">
      <div className="flex flex-wrap items-center justify-between gap-2"><p className="font-medium text-white">Baseline</p><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{preview.baseline.training_age_level} · {preview.baseline.confidence}</Badge></div>
      <div className="mt-2 grid grid-cols-2 gap-2 text-zinc-500">
        <p>source: <span className="text-zinc-300">{preview.baseline.current_weekly_volume_source}</span></p>
        <p>history: <span className="text-zinc-300">{preview.baseline.history_span_days} days</span></p>
        <p>activities: <span className="text-zinc-300">{preview.baseline.activity_count}</span></p>
        <p>recent long: <span className="text-zinc-300">{preview.baseline.recent_long_run_km?.toFixed(1) || "--"} km</span></p>
      </div>
      <div className="mt-2 grid grid-cols-6 gap-1">{preview.baseline.observed_weekly_volume_km.map((volume, index) => <div key={`${index}-${volume}`} className="rounded bg-zinc-900 px-1.5 py-1 text-center"><p className="font-mono text-[10px] text-zinc-600">-{6 - index}w</p><p className="text-zinc-300">{volume.toFixed(1)}</p></div>)}</div>
    </div>
    <div className="mt-3 grid gap-2">
      {preview.weekly_volume_curve.slice(0, 6).map((week) => <div key={week.week_index} className="grid grid-cols-[3.5rem_1fr_5rem] items-center gap-2 text-[11px]"><span className="text-zinc-500">W{week.week_index}</span><div className="h-2 overflow-hidden rounded bg-zinc-900"><div className="h-full rounded bg-orange-400/70" style={{ width: `${Math.max(4, Math.round((week.planned_distance_km / maxVolume) * 100))}%` }} /></div><span className="text-right text-zinc-300">{week.planned_distance_km.toFixed(1)} km</span></div>)}
    </div>
    <div className="mt-3 flex flex-wrap gap-2">{split.map((item) => <Badge key={item.key} className="border-zinc-700 bg-zinc-900 text-zinc-300">{item.key} {item.value}%</Badge>)}</div>
    {preview.risk_flags.length ? <div className="mt-3 grid gap-1.5">{preview.risk_flags.map((flag) => <div key={flag.code} className={cn("rounded-md border px-2 py-1.5", signalClass(flag.severity))}><div className="flex flex-wrap items-center justify-between gap-2"><p className="font-medium">{flag.message}</p><Badge className="border-zinc-700 bg-zinc-950 text-zinc-300">{flag.code}</Badge></div>{flag.reasons.length ? <p className="mt-1 text-[11px] text-zinc-500">{flag.reasons.slice(0, 2).join(" · ")}</p> : null}</div>)}</div> : <p className="mt-3 rounded-md border border-zinc-800 bg-zinc-950 px-2 py-1.5 text-zinc-500">No preview risk flags.</p>}
    <div className="mt-3 grid gap-1.5">{firstWorkouts.map((workout) => <div key={`${workout.week_index}-${workout.day_index}-${workout.title}`} className="rounded-md border border-zinc-900 bg-zinc-950 px-2 py-1.5"><div className="flex flex-wrap items-center justify-between gap-2"><p className="font-medium text-white">W{workout.week_index}D{workout.day_index} · {workout.title}</p><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{workout.workout_type}</Badge></div><p className="mt-1 text-zinc-500">{formatDate(workout.scheduled_date)} · {workout.distance_km?.toFixed(1) || "--"} km · {workout.intensity || "--"}</p></div>)}</div>
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
      <div className="mt-2 grid grid-cols-4 gap-1 text-center text-[11px]"><Stat label="weeks" value={weeks} /><Stat label="workouts" value={plan.workouts.length} /><Stat label="km" value={plannedKm.toFixed(1)} /><Stat label="done" value={`${adherence}%`} /></div>
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
      <p className="mt-3 leading-5 text-zinc-300">{recommendations.summary}</p>
      <div className="mt-3 grid gap-2 md:grid-cols-4">
        <Stat label="completion" value={`${Math.round(recommendations.metrics.completion_rate * 100)}%`} />
        <Stat label="distance" value={`${Math.round(recommendations.metrics.distance_completion_rate * 100)}%`} />
        <Stat label="recent km" value={recommendations.metrics.recent_completed_distance_km} />
        <Stat label="next 7d km" value={recommendations.metrics.upcoming_planned_distance_km} />
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

function PlanWeek({ week, workouts, candidatesByWorkout, candidateErrors, feedbackDrafts, loadingCandidates, onFindCandidates, onLinkCandidate, onUpdate, onFeedbackDraft, onSaveFeedback }: { week: number; workouts: PlanWorkout[]; candidatesByWorkout: Record<number, PlanActivityMatchCandidate[]>; candidateErrors: Record<number, string>; feedbackDrafts: Record<number, FeedbackDraft>; loadingCandidates: number | null; onFindCandidates: (workout: PlanWorkout) => Promise<void>; onLinkCandidate: (workout: PlanWorkout, activityId: number) => Promise<void>; onUpdate: (workout: PlanWorkout, status: string) => Promise<void>; onFeedbackDraft: (workout: PlanWorkout, patch: Partial<FeedbackDraft>) => void; onSaveFeedback: (workout: PlanWorkout) => Promise<void> }) {
  const plannedDistance = workouts.reduce((sum, workout) => sum + (workout.distance_km || 0), 0)
  return <div className="rounded-md border border-zinc-800 bg-zinc-950/60">
    <div className="flex items-center justify-between border-b border-zinc-800 px-3 py-2"><p className="text-xs font-semibold text-white">Week {week}</p><Badge>{plannedDistance.toFixed(1)} км</Badge></div>
    <div className="grid gap-2 p-3">{workouts.map((workout) => {
      const candidates = candidatesByWorkout[workout.id] || []
      const draft = feedbackDrafts[workout.id] || feedbackDraftFromWorkout(workout)
      const canGiveFeedback = ["done", "missed", "skipped"].includes(workout.status)
      return <div key={workout.id} className="rounded-md border border-zinc-900 bg-zinc-950 p-3 text-xs">
        <div className="flex flex-wrap items-start justify-between gap-2"><div><p className="font-medium text-white">{workout.title}</p><p className="mt-1 text-zinc-500">{workout.scheduled_date ? new Date(workout.scheduled_date).toLocaleDateString("ru-RU") : "no date"} · {workout.distance_km?.toFixed(1) || "--"} км · {workout.intensity}</p></div><Badge className={workout.status === "done" ? "border-orange-400/40 bg-orange-400/15 text-orange-100" : "border-zinc-700 bg-zinc-900 text-zinc-300"}>{workout.status}</Badge></div>
        <p className="mt-2 leading-5 text-zinc-400">{workout.description}</p>
        {workout.completed_activity_id ? <div className="mt-2 rounded-md border border-orange-400/20 bg-orange-400/10 px-2 py-1.5 text-[11px] text-orange-100">Linked activity #{workout.completed_activity_id}: {formatDistance(workout.actual_distance_km)} · {formatDuration(workout.actual_duration_seconds)}</div> : null}
        {workout.execution_score?.score !== null && workout.execution_score ? <div className="mt-2 rounded-md border border-zinc-800 bg-zinc-950/80 px-2 py-1.5 text-[11px]"><div className="flex flex-wrap items-center justify-between gap-2"><span className="text-zinc-500">Execution score</span><Badge className={workout.execution_score.score && workout.execution_score.score >= 0.8 ? "border-orange-400/40 bg-orange-400/15 text-orange-100" : workout.execution_score.subjective_risk === "high" ? "border-rose-400/40 bg-rose-400/15 text-rose-100" : "border-zinc-700 bg-zinc-900 text-zinc-300"}>{Math.round((workout.execution_score.score || 0) * 100)}% · {workout.execution_score.status}</Badge></div>{workout.execution_score.flags.length ? <p className="mt-1 text-zinc-600">{workout.execution_score.flags.slice(0, 2).join(" · ")}</p> : null}</div> : null}
        {canGiveFeedback ? <div className="mt-2 rounded-md border border-zinc-800 bg-zinc-950/70 p-2">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2"><p className="font-medium text-white">Workout feedback</p>{workout.feedback ? <Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">saved</Badge> : <Badge>new</Badge>}</div>
          <div className="grid gap-2 md:grid-cols-5">
            <Input type="number" min="0" max="10" placeholder="RPE" value={draft.rpe} onChange={(event) => onFeedbackDraft(workout, { rpe: event.target.value })} />
            <Input type="number" min="0" max="10" placeholder="fatigue" value={draft.fatigue} onChange={(event) => onFeedbackDraft(workout, { fatigue: event.target.value })} />
            <Input type="number" min="0" max="10" placeholder="pain" value={draft.pain_level} onChange={(event) => onFeedbackDraft(workout, { pain_level: event.target.value, pain: Number(event.target.value) > 0 })} />
            <Input type="number" min="0" max="10" placeholder="sleep" value={draft.sleep_quality} onChange={(event) => onFeedbackDraft(workout, { sleep_quality: event.target.value })} />
            <label className="flex items-center gap-2 rounded-md border border-zinc-800 bg-zinc-950 px-2 py-1.5 text-zinc-400"><input checked={draft.pain} type="checkbox" onChange={(event) => onFeedbackDraft(workout, { pain: event.target.checked })} /> pain</label>
          </div>
          <div className="mt-2 grid gap-2 md:grid-cols-[1fr_auto]"><Input placeholder="notes" value={draft.notes} onChange={(event) => onFeedbackDraft(workout, { notes: event.target.value })} /><Button size="sm" onClick={() => onSaveFeedback(workout)}>Save feedback</Button></div>
        </div> : null}
        <div className="mt-2 flex flex-wrap gap-2">{workout.completed_activity_id ? <Button size="sm" variant="secondary" onClick={() => onUpdate(workout, "done")}>Done</Button> : <><Button size="sm" variant="ghost" onClick={() => onUpdate(workout, "missed")}>Missed</Button><Button size="sm" variant="ghost" onClick={() => onUpdate(workout, "skipped")}>Skipped</Button></>}<Button size="sm" variant="ghost" disabled={loadingCandidates === workout.id} onClick={() => onFindCandidates(workout)}>{loadingCandidates === workout.id ? "Matching..." : "Find activity"}</Button></div>
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
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = Object.fromEntries(new FormData(event.currentTarget).entries())
    await api.createProvider({ ...data, is_default: data.is_default === "on" })
    event.currentTarget.reset()
    await onChanged()
  }
  return <div className="grid gap-4 xl:grid-cols-[24rem_1fr]">
    <Card><CardHeader><CardTitle>Add LLM provider</CardTitle><Badge>OpenAI / Anthropic</Badge></CardHeader><form onSubmit={submit} className="grid gap-3 p-4">
      <Select name="provider"><option value="openai">OpenAI compatible</option><option value="anthropic">Anthropic</option></Select>
      <Input name="display_name" placeholder="Display name" required />
      <Input name="base_url" placeholder="Base URL optional" />
      <Input name="model" placeholder="Model" required />
      <Input name="api_key" placeholder="API key" type="password" />
      <label className="flex items-center gap-2 text-xs text-zinc-400"><input name="is_default" type="checkbox" /> default provider</label>
      <Button type="submit">Save provider</Button>
    </form></Card>
    <Card><CardHeader><CardTitle>Providers</CardTitle><Badge>{providers.length} total</Badge></CardHeader><div className="divide-y divide-zinc-800">{providers.map((provider) => <div key={provider.id} className="flex items-center justify-between gap-3 px-4 py-3 text-xs"><div><p className="font-medium text-white">{provider.display_name}</p><p className="text-zinc-500">{provider.provider} · {provider.model}</p></div><div className="flex items-center gap-2">{provider.is_default && <Badge>default</Badge>}<span className="text-zinc-500">key: {provider.has_api_key ? "encrypted" : "none"}</span></div></div>)}</div></Card>
  </div>
}

export default App
