import { Activity, BatteryCharging, BookOpen, Bot, CalendarDays, ChartSpline, Goal, HeartPulse, Menu, Moon, Settings, Shield, Sun, Trophy, Upload, X, Zap } from "lucide-react"
import { type FormEvent, type ReactNode, useEffect, useRef, useState } from "react"
import { useLocation, useNavigate } from "react-router-dom"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardHeader, CardTitle } from "@/components/ui/card"
import { CalculationExplainer } from "@/components/ui/calculation-explainer"
import { DataTable, type DataTableColumn } from "@/components/ui/data-table"
import { Input } from "@/components/ui/input"
import { MetricCard } from "@/components/ui/metric-card"
import { Select } from "@/components/ui/select"
import { api, type Activity as ActivityType, type ActivityValidation, type AnalyticsInsight, type AnalyticsSummary, type AnalyticsTimeseries, type AthleteMeasurement, type AthleteProfile, type AthleteState, type AthleteStateSignal, type AuditLogEntry, authConfig, type AuthUser, type CalendarEvent, type CalendarResponse, clearAuthToken, type CoachAction, type CoachActionPreview, type CsvImportResult, type DailyReadiness, type DailyReadinessActionPreview, type DashboardSummary, devLogin, hasAuthToken, type ImportBatch, type ImportUploadResult, type Integration, type LlmProvider, type LlmProviderTest, onAuthExpired, type PerformancePaceZone, type PerformancePb, type PerformancePrediction, type PerformanceResult, type PerformanceVdot, type Plan, type PlanActivityMatchCandidate, type PlanBuilderPreview, type PlanRecommendationAudit, type PlanRecommendationPreview, type PlanRecommendations, type PlanRollbackPreview, type PlanVersion, type PlanWeekSummary, type PlanWorkout, type PlanWorkoutMatchCandidate, type ProfileCompleteness, type RunningGoal, type SafetyCheck, telegramBotLink, telegramLogin, type TelegramLoginPayload, telegramStartCodeLogin, type TrainingLoadDaily, type TrainingLoadDailyPoint, type TrainingLoadFitnessFatigue, type TrainingLoadMaterializationStatus, type TrainingLoadWarning, type TrainingLoadWeekly, type WorkoutMissReason, type Zone, type ZoneDistribution, type ZoneDistributionItem, type ZonePlannedActual, type Zones } from "@/lib/api"
import { getInitialLanguage, languageLocale, saveLanguage, type Language, useDomTranslations } from "@/lib/i18n"
import { createLatestRequestGate } from "@/lib/latest-request"
import { cn } from "@/lib/utils"

type Page = "overview" | "activities" | "imports" | "calendar" | "analytics" | "load" | "zones" | "performance" | "goals" | "profile" | "planning" | "settings"
type Theme = "dark" | "light"
type FeedbackDraft = { rpe: string; soreness_0_10: string; fatigue: string; pain: boolean; pain_level: string; sleep_quality_0_10: string; sleep_quality: string; pain_notes: string; user_notes: string; weather_notes: string; notes: string }
type CompletionDraft = FeedbackDraft & { actual_distance_km: string; actual_duration_minutes: string; average_heart_rate_bpm: string; completed_at: string }
type WorkoutTargetDraft = { title: string; workout_type: string; distance_km: string; duration_minutes: string; intensity: string; description: string }
type CalendarMatchState =
  | { mode: "workout_to_activity"; candidates: PlanActivityMatchCandidate[] }
  | { mode: "activity_to_workout"; candidates: PlanWorkoutMatchCandidate[] }

type CoachActionTarget = { workoutId: number; title: string; action: CoachAction; targetDate?: string; eventId?: string }

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

const ACTIVE_IMPORT_STATUSES = new Set(["queued", "retry_scheduled", "recognizing", "uploaded", "processing", "confirming"])
const RETRYABLE_IMPORT_STATUSES = new Set(["retry_scheduled", "validation_failed", "recognition_failed", "rejected_no_llm_template"])

function importStatusLabel(status: string) {
  switch (status) {
    case "queued":
      return uiText("ждет обработки", "waiting")
    case "retry_scheduled":
      return uiText("повторим", "will retry")
    case "recognizing":
      return uiText("читаем скриншоты", "reading screenshots")
    case "uploaded":
      return uiText("загружено", "uploaded")
    case "processing":
      return uiText("готовим тренировку", "preparing workout")
    case "confirming":
      return uiText("сохраняем", "saving")
    case "pending_confirmation":
      return uiText("нужна проверка", "review needed")
    case "recognized":
      return uiText("данные готовы", "data ready")
    case "validation_failed":
      return uiText("нужна повторная попытка", "retry needed")
    case "recognition_failed":
      return uiText("не удалось прочитать", "could not read")
    case "duplicate":
      return uiText("дубликат", "duplicate")
    case "rejected_no_llm_template":
      return uiText("не удалось прочитать", "could not read")
    case "rejected_by_user":
      return uiText("отклонено", "rejected")
    case "imported":
      return uiText("добавлено", "added")
    case "partial_failed":
      return uiText("добавлено частично", "partially added")
    case "failed":
      return uiText("нужна повторная попытка", "retry needed")
    default:
      return uiText("проверяем", "checking")
  }
}

function importStatusClass(batch: Pick<ImportBatch, "status" | "requires_confirmation">) {
  if (batch.requires_confirmation) return "border-orange-400/40 bg-orange-400/15 text-orange-100"
  if (batch.status === "retry_scheduled") return "border-orange-400/40 bg-orange-400/15 text-orange-100"
  if (ACTIVE_IMPORT_STATUSES.has(batch.status)) return "border-sky-400/40 bg-sky-400/15 text-sky-100"
  if (["validation_failed", "recognition_failed", "rejected_no_llm_template", "failed"].includes(batch.status)) return "border-red-400/40 bg-red-400/15 text-red-100"
  if (["recognized", "duplicate", "imported"].includes(batch.status)) return "border-emerald-400/40 bg-emerald-400/15 text-emerald-100"
  if (batch.status === "partial_failed") return "border-orange-400/40 bg-orange-400/15 text-orange-100"
  return "border-zinc-700 bg-zinc-900 text-zinc-300"
}

function importNextAction(batch: Pick<ImportBatch, "status" | "requires_confirmation" | "created_activity_id" | "matched_workout_id">) {
  if (batch.requires_confirmation) return uiText("Проверьте данные", "Review recognized data")
  if (ACTIVE_IMPORT_STATUSES.has(batch.status)) return batch.status === "retry_scheduled" ? uiText("Попробуем еще раз автоматически", "Trying again automatically") : uiText("Готовим тренировку", "Preparing your workout")
  if (RETRYABLE_IMPORT_STATUSES.has(batch.status) || batch.status === "failed") return uiText("Можно попробовать еще раз", "You can try again")
  if (batch.status === "duplicate") return uiText("Похоже, это дубликат", "Looks like a duplicate")
  if (batch.created_activity_id && batch.matched_workout_id) return uiText("Тренировка добавлена в план", "Workout added to the plan")
  if (batch.created_activity_id) return uiText("Тренировка добавлена", "Workout added")
  if (batch.status === "recognized") return uiText("Данные готовы", "Data is ready")
  return importStatusLabel(batch.status)
}

function importNextActionDescription(batch: Pick<ImportBatch, "status" | "requires_confirmation" | "created_activity_id" | "matched_workout_id" | "recognition_retry_at">) {
  if (batch.requires_confirmation) return uiText("Проверьте основные данные и подтвердите тренировку.", "Review the main details, then confirm the workout.")
  if (ACTIVE_IMPORT_STATUSES.has(batch.status)) return batch.status === "retry_scheduled"
    ? uiText(`Еще одна попытка запланирована${batch.recognition_retry_at ? `: ${formatLocalDateTime(batch.recognition_retry_at)}` : "."}`, `Another attempt is scheduled${batch.recognition_retry_at ? `: ${formatLocalDateTime(batch.recognition_retry_at)}` : "."}`)
    : uiText("Скриншоты можно закрыть: статус обновится сам.", "You can leave this page: the status will update automatically.")
  if (RETRYABLE_IMPORT_STATUSES.has(batch.status) || batch.status === "failed") return uiText("Нажмите «Повторить сейчас». Если не получится, технические детали останутся ниже.", "Press Retry now. If it still fails, technical details stay below.")
  if (batch.created_activity_id && batch.matched_workout_id) return uiText("Она уже учтена в истории и текущем плане.", "It is already counted in your history and current plan.")
  if (batch.created_activity_id) return uiText("Если тренировка была запланирована, выберите ее ниже.", "If this workout was planned, select it below.")
  return uiText("Статус появится здесь после загрузки скриншотов.", "Status will appear here after screenshot upload.")
}

function importQueuedMessage() {
  return uiText("Скриншоты загружены. Runforfan проверит данные и обновит статус здесь.", "Screenshots uploaded. Runforfan will check the details and update the status here.")
}

function csvImportDoneMessage(result?: CsvImportResult | null) {
  if (!result) return uiText("Тренировки из CSV добавлены.", "Workouts from CSV were added.")
  return uiText(`Добавлено тренировок: ${result.created_activities}. Отмечено в плане: ${result.matched_workouts}.`, `Workouts added: ${result.created_activities}. Marked in the plan: ${result.matched_workouts}.`)
}

function uploadCountLabel(count: number) {
  if (isEnglishLanguage()) return `${count} ${count === 1 ? "upload" : "uploads"}`
  const remainder100 = count % 100
  const remainder10 = count % 10
  const noun = remainder100 >= 11 && remainder100 <= 14 ? "загрузок" : remainder10 === 1 ? "загрузка" : remainder10 >= 2 && remainder10 <= 4 ? "загрузки" : "загрузок"
  return `${count} ${noun}`
}

type CalendarEventCardProps = Omit<CalendarDayProps, "day" | "events" | "load" | "maxLoad"> & {
  event: CalendarEvent
}

const SUPPORT_WORKOUT_TYPES = new Set(["strength", "ofp", "mobility", "prehab", "core", "cross_training"])
const WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
const ONBOARDING_DISMISSED_KEY = "runforfan_onboarding_dismissed"
const THEME_KEY = "runforfan_theme"
const ONBOARDING_READY_SCORE = 0.8
const DEFAULT_HR_ZONE_ROWS = [
  { zone_key: "z1", label: "Z1 Recovery" },
  { zone_key: "z2", label: "Z2 Easy" },
  { zone_key: "z3", label: "Z3 Steady" },
  { zone_key: "z4", label: "Z4 Threshold" },
  { zone_key: "z5", label: "Z5 Hard" },
]

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
    // Onboarding can still run when browser storage is blocked.
  }
}

function getInitialTheme(): Theme {
  const stored = safeStorageGet(THEME_KEY)
  if (stored === "light" || stored === "dark") return stored
  if (window.matchMedia?.("(prefers-color-scheme: light)").matches) return "light"
  return "dark"
}

function guideHref() {
  return `${import.meta.env.BASE_URL || "/app/"}alpha-tester-guide.html`
}

const primaryNav = [
  ["overview", "Сегодня", "Today", Zap],
  ["planning", "План", "Plan", Goal],
  ["imports", "Добавить тренировку", "Add workout", Upload],
  ["analytics", "Прогресс", "Progress", ChartSpline],
  ["profile", "Профиль", "Profile", HeartPulse],
] as const

const secondaryNav = [
  ["calendar", "Календарь", "Calendar", CalendarDays],
  ["activities", "Тренировки", "Workouts", Activity],
  ["goals", "Цели", "Goals", Goal],
  ["load", "Нагрузка", "Load", BatteryCharging],
  ["zones", "Зоны", "Zones", Shield],
  ["performance", "Форма", "Performance", Trophy],
  ["settings", "Настройки", "Settings", Settings],
] as const

const PAGE_PATHS: Record<Page, string> = {
  overview: "/",
  activities: "/activities",
  imports: "/imports",
  calendar: "/calendar",
  analytics: "/analytics",
  load: "/load",
  zones: "/zones",
  performance: "/performance",
  goals: "/goals",
  profile: "/profile",
  planning: "/planning",
  settings: "/settings",
}

function pageFromPathname(pathname: string): { page: Page; known: boolean } {
  const segment = pathname.replace(/^\/+|\/+$/g, "").split("/")[0]
  if (!segment || segment === "dashboard" || segment === "overview") return { page: "overview", known: true }
  if (Object.prototype.hasOwnProperty.call(PAGE_PATHS, segment)) return { page: segment as Page, known: true }
  return { page: "overview", known: false }
}

function formatPace(seconds?: number | null) {
  if (!seconds) return "--"
  return `${Math.floor(seconds / 60)}'${String(seconds % 60).padStart(2, "0")}`
}

function isEnglishLanguage() {
  return languageLocale() === "en-US"
}

function uiText(ru: string, en: string) {
  return isEnglishLanguage() ? en : ru
}

function pageTitle(page: Page) {
  const item = [...primaryNav, ...secondaryNav].find(([key]) => key === page)
  return item ? uiText(item[1], item[2]) : "Runforfan"
}

function appStatusLabel(status: string) {
  switch (status) {
    case "LOADING":
      return uiText("загружаем", "loading")
    case "LOGIN REQUIRED":
      return uiText("нужен вход", "login needed")
    case "API ERROR":
      return uiText("нет связи", "connection issue")
    case "DEMO USER":
      return uiText("демо", "demo")
    case "TELEGRAM USER":
      return uiText("вход выполнен", "signed in")
    default:
      return uiText("статус", "status")
  }
}

function kmUnit() {
  return isEnglishLanguage() ? "km" : "км"
}

function kgUnit() {
  return isEnglishLanguage() ? "kg" : "кг"
}

function perKmUnit() {
  return `/${kmUnit()}`
}

function noDateLabel() {
  return isEnglishLanguage() ? "no date" : "без даты"
}

function sentenceCase(value: string) {
  if (!value) return value
  return value.charAt(0).toLocaleUpperCase(languageLocale()) + value.slice(1)
}

function periodPresetLabel(preset: string) {
  if (preset === "7d") return uiText("7 дней", "7 days")
  if (preset === "28d") return uiText("28 дней", "28 days")
  if (preset === "90d") return uiText("90 дней", "90 days")
  if (preset === "year") return uiText("год", "year")
  if (preset === "all") return uiText("все время", "all time")
  return uiText("свой период", "custom range")
}

function splitCountLabel(count: number) {
  return isEnglishLanguage() ? `${count} km splits` : `${count} км сплитов`
}

function blockCountLabel(count: number) {
  return isEnglishLanguage() ? `${count} blocks` : `${count} блоков`
}

function derivedMetricCountLabel(count: number) {
  return isEnglishLanguage() ? `${count} derived metrics` : `${count} расчетных метрик`
}

function formatDistance(km?: number | null) {
  return km ? `${km.toFixed(2)} ${kmUnit()}` : "--"
}

function dateValue(value: string) {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) ? new Date(`${value}T00:00:00`) : new Date(value)
}

function formatLocalDate(value?: string | null) {
  return value ? dateValue(value).toLocaleDateString(languageLocale()) : "--"
}

function formatLocalDateTime(value?: string | null) {
  return value ? dateValue(value).toLocaleString(languageLocale()) : "--"
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

function formatDurationMinutes(seconds?: number | null) {
  if (!seconds) return "--"
  const minutes = Math.max(1, Math.round(seconds / 60))
  return isEnglishLanguage() ? `${minutes} min` : `${minutes} мин`
}

function formatOptionalNumber(value?: number | null) {
  if (value === null || value === undefined) return "--"
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}

function isSupportWorkoutType(type?: string | null) {
  return SUPPORT_WORKOUT_TYPES.has(type || "")
}

function formatWorkoutTarget(target: { distance_km?: number | null; duration_seconds?: number | null; workout_type?: string | null }) {
  const duration = formatDuration(target.duration_seconds)
  const durationMinutes = formatDurationMinutes(target.duration_seconds)
  const distance = formatDistance(target.distance_km)
  if (isSupportWorkoutType(target.workout_type)) return durationMinutes !== "--" ? `${durationMinutes} ${workoutTypeLabel(target.workout_type)}` : workoutTypeLabel(target.workout_type)
  if (distance !== "--" && duration !== "--") return `${distance} · ${duration}`
  if (distance !== "--") return distance
  return durationMinutes !== "--" ? durationMinutes : duration
}

function formatWorkoutActual(workout: { actual_distance_km?: number | null; actual_duration_seconds?: number | null; workout_type?: string | null }) {
  const duration = formatDuration(workout.actual_duration_seconds)
  const durationMinutes = formatDurationMinutes(workout.actual_duration_seconds)
  const distance = formatDistance(workout.actual_distance_km)
  if (isSupportWorkoutType(workout.workout_type)) return durationMinutes !== "--" ? `${durationMinutes} ${workoutTypeLabel(workout.workout_type)}` : "--"
  if (distance !== "--" && duration !== "--") return `${distance} · ${duration}`
  if (distance !== "--") return distance
  return durationMinutes !== "--" ? durationMinutes : duration
}

function coachWorkoutTitle(workout?: PlanWorkout | null) {
  if (!workout) return uiText("Свободный день", "Open day")
  const target = formatWorkoutTarget(workout)
  return `${sentenceCase(workoutTypeLabel(workout.workout_type))}${target !== "--" ? ` · ${target}` : ""}`
}

function coachPreviewWorkoutTitle(workout: { workout_type?: string | null; distance_km?: number | null; duration_seconds?: number | null }) {
  const target = formatWorkoutTarget(workout)
  return `${sentenceCase(workoutTypeLabel(workout.workout_type))}${target !== "--" ? ` · ${target}` : ""}`
}

function runKindLabel(activity: Pick<ActivityType, "activity_type">) {
  if (activity.activity_type.includes("strength")) return uiText("ОФП", "Strength")
  if (activity.activity_type.includes("walk")) return uiText("Ходьба", "Walk")
  if (activity.activity_type.includes("run")) return uiText("Пробежка", "Run")
  if (activity.activity_type.includes("workout")) return uiText("Тренировка", "Workout")
  return uiText("Тренировка", "Workout")
}

function readinessCoachMessage(readiness?: DashboardSummary["readiness"] | null) {
  if (!readiness) return uiText("Сверяем план и последние тренировки.", "Checking your plan and recent workouts.")
  if (["risk", "critical", "at_risk"].includes(readiness.status)) return uiText("Сегодня лучше снизить нагрузку или заменить тренировку легким движением, если есть боль или сильная усталость.", "Today is a day to reduce load or switch to easy movement if pain or heavy fatigue is present.")
  if (["watch", "warning", "adjust"].includes(readiness.status)) return uiText("Перед стартом проверьте сон, усталость и самочувствие. Тренировку можно сократить без чувства вины.", "Before starting, check sleep, fatigue and how you feel. Shortening the workout is acceptable.")
  return uiText("Серьезных ограничений не видно. Держите тренировку контролируемой.", "No major constraints are visible. Keep the workout controlled.")
}

function profileZoneReadinessLabels(completeness?: ProfileCompleteness | null) {
  if (!completeness) return []
  return [
    completeness.can_calculate_hr_zones ? uiText("Пульсовые зоны готовы", "Heart-rate zones are ready") : uiText("Для пульсовых зон нужен максимальный пульс или возраст", "Heart-rate zones need maximum heart rate or age"),
    completeness.can_calculate_hrr_zones ? uiText("Зоны по резерву пульса готовы", "Heart-rate reserve zones are ready") : uiText("Для точных пульсовых зон нужен пульс покоя", "More precise heart-rate zones need resting heart rate"),
    completeness.can_calculate_pace_zones ? uiText("Темповые зоны готовы", "Pace zones are ready") : uiText("Для темповых зон нужен пороговый темп", "Pace zones need threshold pace"),
  ]
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

function isUnauthorized(caught: unknown) {
  return caught instanceof Error && caught.message.startsWith("401:")
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

function targetDraftFromWorkout(workout: PlanWorkout): WorkoutTargetDraft {
  return {
    title: workout.title || "",
    workout_type: workout.workout_type || "easy",
    distance_km: workout.distance_km?.toString() || "",
    duration_minutes: workout.duration_seconds ? String(Math.round(workout.duration_seconds / 60)) : "",
    intensity: workout.intensity || "",
    description: workout.description || "",
  }
}

function targetPayload(draft: WorkoutTargetDraft) {
  const distance = numberOrNull(draft.distance_km)
  const durationMinutes = numberOrNull(draft.duration_minutes)
  const workoutType = draft.workout_type.trim() || "easy"
  return {
    title: draft.title.trim() || null,
    workout_type: workoutType,
    distance_km: isSupportWorkoutType(workoutType) ? null : distance,
    duration_seconds: durationMinutes ? Math.round(durationMinutes * 60) : null,
    intensity: draft.intensity.trim() || null,
    description: draft.description.trim() || null,
  }
}

function targetDraftChanged(workout: PlanWorkout, draft: WorkoutTargetDraft) {
  const payload = targetPayload(draft)
  return payload.title !== workout.title
    || payload.workout_type !== workout.workout_type
    || payload.distance_km !== (workout.distance_km ?? null)
    || payload.duration_seconds !== (workout.duration_seconds ?? null)
    || payload.intensity !== (workout.intensity ?? null)
    || payload.description !== (workout.description ?? null)
}

function feedbackNumber(value: string) {
  if (value.trim() === "") return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : NaN
}

function feedbackValidationError(draft: FeedbackDraft) {
  const fields: [keyof FeedbackDraft, string][] = [["rpe", "RPE"], ["soreness_0_10", uiText("забитость", "soreness")], ["pain_level", uiText("боль", "pain")], ["sleep_quality_0_10", uiText("сон", "sleep")]]
  for (const [field, label] of fields) {
    const value = feedbackNumber(String(draft[field]))
    if (value !== null && (!Number.isFinite(value) || !Number.isInteger(value) || value < 0 || value > 10)) return uiText(`${label} должен быть целым числом 0-10`, `${label} must be an integer from 0 to 10`)
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
  if (distance !== null && (!Number.isFinite(distance) || distance < 0 || distance > 250)) return uiText("Фактическая дистанция должна быть 0-250 км", "Actual distance must be 0-250 km")
  if (duration === null || !Number.isFinite(duration) || duration <= 0 || duration > 2880) return uiText("Фактическое время должно быть 1-2880 минут", "Actual time must be 1-2880 minutes")
  const hr = feedbackNumber(draft.average_heart_rate_bpm)
  if (hr !== null && (!Number.isFinite(hr) || !Number.isInteger(hr) || hr < 30 || hr > 240)) return uiText("Средний HR должен быть целым числом 30-240", "Average HR must be an integer from 30 to 240")
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

function activityWritePayload(form: HTMLFormElement) {
  const data = new FormData(form)
  const durationMinutes = numberOrNull(data.get("duration_minutes"))
  const durationSeconds = numberOrNull(data.get("duration_seconds"))
  const startedAt = stringOrNull(data.get("started_at"))
  const parsedStartedAt = startedAt ? new Date(startedAt) : null
  return {
    activity_type: stringOrNull(data.get("activity_type")) || "manual_workout",
    title: stringOrNull(data.get("title")) || uiText("Тренировка", "Workout"),
    started_at: parsedStartedAt && !Number.isNaN(parsedStartedAt.getTime()) ? parsedStartedAt.toISOString() : null,
    distance_km: numberOrNull(data.get("distance_km")),
    duration_seconds: durationSeconds === null ? durationMinutes === null ? null : Math.round(durationMinutes * 60) : Math.round(durationSeconds),
    average_heart_rate_bpm: numberOrNull(data.get("average_heart_rate_bpm")),
    source_note: stringOrNull(data.get("source_note")),
  }
}

function activityDurationSeconds(activity: ActivityType) {
  return activity.duration_seconds ? String(activity.duration_seconds) : ""
}

function datetimeLocalValue(value?: string | null) {
  if (!value) return ""
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value.slice(0, 16)
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000)
  return local.toISOString().slice(0, 19)
}

function formatZoneValue(zone: Zone, value: number | null) {
  if (value === null) return "--"
  if (zone.unit === "seconds_per_km") return `${formatPace(Math.round(value))}${perKmUnit()}`
  if (zone.unit === "bpm") return `${Math.round(value)} ${uiText("уд/мин", "bpm")}`
  return `${value}`
}

function formatZoneRange(zone: Zone) {
  return `${formatZoneValue(zone, zone.lower_value)} - ${formatZoneValue(zone, zone.upper_value)}`
}

function manualHrZoneRows(zones?: Zone[] | null) {
  return DEFAULT_HR_ZONE_ROWS.map((fallback) => {
    const existing = zones?.find((zone) => zone.zone_key === fallback.zone_key)
    return {
      zone_key: fallback.zone_key,
      label: existing?.label || fallback.label,
      lower_value: existing?.lower_value ?? null,
      upper_value: existing?.upper_value ?? null,
    }
  })
}

function missingLabel(field: string) {
  const labelsRu: Record<string, string> = {
    date_of_birth: "дата рождения",
    resting_heart_rate_bpm: "пульс покоя",
    max_heart_rate_bpm_or_birthdate: "максимальный пульс или возраст",
    lactate_threshold_pace_seconds_per_km: "пороговый темп",
    lactate_threshold_hr_bpm: "пороговый пульс",
    weight_kg: "вес",
    height_cm: "рост",
    preferred_weekdays: "тренировочные дни",
    max_run_duration_minutes: "макс. длительность",
  }
  const labelsEn: Record<string, string> = {
    date_of_birth: "date of birth",
    resting_heart_rate_bpm: "resting heart rate",
    max_heart_rate_bpm_or_birthdate: "maximum heart rate or age",
    lactate_threshold_pace_seconds_per_km: "threshold pace",
    lactate_threshold_hr_bpm: "threshold heart rate",
    weight_kg: "weight",
    height_cm: "height",
    preferred_weekdays: "training days",
    max_run_duration_minutes: "max duration",
  }
  const labels = languageLocale() === "en-US" ? labelsEn : labelsRu
  return labels[field] || field
}

function safetyMessageLabel(message?: string | null) {
  if (!message) return "--"
  if (message.includes("не является медицинским устройством")) {
    return uiText(
      "Runforfan не является медицинским устройством; при боли, головокружении или ухудшении самочувствия нужно прекратить тренировку и обратиться к специалисту.",
      "Runforfan is not a medical device. If you feel pain, dizziness or worsening well-being, stop the workout and consult a professional."
    )
  }
  if (/safe|ok|normal|норм/i.test(message)) return uiText("Серьезных ограничений не видно. Все равно ориентируйтесь на самочувствие.", "No major constraints are visible. Still use how you feel as the final guide.")
  return uiText("Есть факторы, из-за которых план стоит держать осторожнее.", "There are factors that should keep the plan more conservative.")
}

function safetyWarningLabel(warning: string) {
  if (warning.includes("Keep the next workouts controlled")) return uiText("Следующие тренировки держите спокойнее и проверьте самочувствие перед увеличением нагрузки.", "Keep the next workouts calmer and check how you feel before adding load.")
  if (warning.includes("Указаны травмы")) return uiText("Указаны травмы или ограничения: планировщик будет осторожнее.", "Injuries or constraints are listed: the planner will stay more conservative.")
  if (warning.includes("Указаны медицинские состояния")) return uiText("Указаны медицинские состояния: спорные нагрузки требуют консультации специалиста.", "Health conditions are listed: uncertain workloads require professional advice.")
  if (warning.includes("Recovery status:")) return uiText("Восстановление сейчас не идеальное: снизьте интенсивность и длительность до нормального самочувствия.", "Recovery is not ideal right now: reduce intensity and duration until you feel normal.")
  if (warning.includes("Нет HRmax")) return uiText("Для пульсовых подсказок нужен максимальный пульс или возраст.", "Heart-rate guidance needs maximum heart rate or age.")
  if (warning.includes("Нет порогового темпа")) return uiText("Нет порогового темпа: темповые зоны будут недоступны.", "No threshold pace: pace zones will be unavailable.")
  return uiText("Проверьте самочувствие и при необходимости сделайте тренировку легче.", "Check how you feel and make the workout easier if needed.")
}

function weekdayLabel(value?: number | null) {
  if (!value) return "--"
  const labels = languageLocale() === "en-US" ? WEEKDAY_LABELS : ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
  return labels[value - 1] || String(value)
}

function weekdayListLabel(values?: number[] | null) {
  return values?.length ? values.map(weekdayLabel).join(", ") : "--"
}

function measurementValueLabel(measurement: AthleteMeasurement) {
  const value = measurement.value_numeric
  if (value === null || value === undefined) return "--"
  if (measurement.measurement_type === "weight") return `${value.toFixed(1)} ${kgUnit()}`
  if (measurement.measurement_type === "vo2max") return `${value.toFixed(1)} ml/kg/min`
  if (["resting_hr", "max_hr", "lactate_threshold"].includes(measurement.measurement_type)) return `${Math.round(value)} ${uiText("уд/мин", "bpm")}`
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}

function workoutBlockSummary(activity: ActivityType) {
  const workBlocks = activity.workout_blocks?.filter((block) => block.block_type === "work") || []
  if (!workBlocks.length) return null
  const distance = workBlocks[0]?.distance_km
  const sameDistance = distance && workBlocks.every((block) => block.distance_km === distance)
  return sameDistance ? `${workBlocks.length} x ${distance.toFixed(2)} ${kmUnit()}` : isEnglishLanguage() ? `${workBlocks.length} work blocks` : `${workBlocks.length} рабочих блока`
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
  if (metric.unit === "seconds_per_km") return `${formatPace(metric.metric_value)}${perKmUnit()}`
  if (metric.unit === "seconds") return formatDuration(metric.metric_value)
  if (metric.unit === "minutes") return `${metric.metric_value.toFixed(1)} min`
  if (metric.unit === "kcal") return `${metric.metric_value.toFixed(0)} kcal`
  if (metric.unit === "kmh") return `${metric.metric_value.toFixed(2)} km/h`
  if (metric.unit === "km") return `${metric.metric_value.toFixed(2)} ${kmUnit()}`
  if (metric.unit === "count") return String(Math.round(metric.metric_value))
  return `${Number.isInteger(metric.metric_value) ? Math.round(metric.metric_value) : metric.metric_value.toFixed(1)} ${metric.unit}`
}

function formatValidationValue(value?: number | null, unit?: string | null) {
  if (value === null || value === undefined) return "--"
  if (unit === "seconds_per_km") return `${formatPace(Math.round(value))}${perKmUnit()}`
  if (unit === "seconds") return formatDuration(Math.round(value))
  if (unit === "km") return `${value.toFixed(2)} ${kmUnit()}`
  if (unit === "bpm") return `${Math.round(value)} ${uiText("уд/мин", "bpm")}`
  if (unit === "spm") return `${Math.round(value)} spm`
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
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

function calculationSourceReference(calculation?: { source_reference?: string | null } | null) {
  return calculation?.source_reference || "source reference unavailable"
}

function calculationMetadata(calculation?: { method?: string | null; confidence?: string | null; source_reference?: string | null } | null) {
  const parts = [calculation?.confidence, calculation?.method, calculation?.source_reference].filter(Boolean)
  return parts.length ? parts.join(" · ") : "source reference unavailable"
}

function authUserName(user: AuthUser | null) {
  if (!user) return "Telegram user"
  if (user.is_demo) return user.display_name || "Demo Runner"
  const telegramName = [user.first_name, user.last_name].filter(Boolean).join(" ").trim()
  return telegramName || (user.username ? `@${user.username}` : user.display_name || "Telegram user")
}

function authUserMeta(user: AuthUser | null) {
  if (!user) return "authenticated"
  if (user.username) return `@${user.username}`
  if (user.telegram_id) return `tg:${user.telegram_id}`
  return user.is_demo ? "demo" : "authenticated"
}

function authUserInitial(user: AuthUser | null) {
  return authUserName(user).trim().charAt(0).toUpperCase() || "T"
}

function trainingLoadMethodMetadata(method?: string | null, methods?: string[] | null) {
  const labels = methods?.length ? methods.map(loadMethodLabel).join(", ") : loadMethodLabel(method || "unavailable")
  return labels || "load source unavailable"
}

function App() {
  const location = useLocation()
  const navigate = useNavigate()
  const route = pageFromPathname(location.pathname)
  const page = route.page
  const [mobileOpen, setMobileOpen] = useState(false)
  const [theme, setTheme] = useState<Theme>(() => getInitialTheme())
  const [language, setLanguage] = useState<Language>(() => getInitialLanguage())
  const [activities, setActivities] = useState<ActivityType[]>([])
  const [analytics, setAnalytics] = useState<AnalyticsSummary | null>(null)
  const [dashboard, setDashboard] = useState<DashboardSummary | null>(null)
  const [dailyReadiness, setDailyReadiness] = useState<DailyReadiness | null>(null)
  const [athleteState, setAthleteState] = useState<AthleteState | null>(null)
  const [athleteStateError, setAthleteStateError] = useState("")
  const [providers, setProviders] = useState<LlmProvider[]>([])
  const [profile, setProfile] = useState<AthleteProfile | null>(null)
  const [completeness, setCompleteness] = useState<ProfileCompleteness | null>(null)
  const [safety, setSafety] = useState<SafetyCheck | null>(null)
  const [zones, setZones] = useState<Zones | null>(null)
  const [measurements, setMeasurements] = useState<AthleteMeasurement[]>([])
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(null)
  const [onboardingDismissed, setOnboardingDismissed] = useState(() => safeStorageGet(ONBOARDING_DISMISSED_KEY) === "true")
  const [authReady, setAuthReady] = useState(() => authConfig.devLoginEnabled || hasAuthToken())
  const [authExchangePending, setAuthExchangePending] = useState(() => new URLSearchParams(window.location.search).has("telegram_login_code"))
  const [authError, setAuthError] = useState("")
  const [status, setStatus] = useState("LOADING")
  const athleteStateRequests = useRef(createLatestRequestGate())

  function dismissOnboarding() {
    safeStorageSet(ONBOARDING_DISMISSED_KEY, "true")
    setOnboardingDismissed(true)
  }

  function setPage(nextPage: Page, options?: { replace?: boolean }) {
    navigate(PAGE_PATHS[nextPage], { replace: options?.replace })
  }

  function changeLanguage(nextLanguage: Language) {
    setLanguage(nextLanguage)
    saveLanguage(nextLanguage)
  }

  function toggleTheme() {
    setTheme((current) => current === "dark" ? "light" : "dark")
  }

  async function loginWithTelegram(payload: TelegramLoginPayload) {
    setAuthError("")
    const data = await telegramLogin(payload)
    setCurrentUser(data.user)
    setAuthReady(true)
    setStatus("TELEGRAM USER")
  }

  function authenticatedStatus() {
    return authConfig.devLoginEnabled ? "DEMO USER" : "TELEGRAM USER"
  }

  async function refreshAthleteState() {
    const requestId = athleteStateRequests.current.begin()
    try {
      const nextAthleteState = await api.todayAthleteState()
      if (!athleteStateRequests.current.isLatest(requestId)) return
      setAthleteState(nextAthleteState)
      setAthleteStateError("")
    } catch (error) {
      if (!athleteStateRequests.current.isLatest(requestId)) return
      console.error(error)
      setAthleteStateError(apiErrorMessage(error, uiText("Сводка состояния временно недоступна.", "Athlete State is temporarily unavailable.")))
    }
  }

  async function refreshGlobal({ throwOnError = false }: { throwOnError?: boolean } = {}) {
    try {
      await devLogin()
      const [nextUser, nextActivities, nextAnalytics, nextDashboard, nextReadiness, nextProviders] = await Promise.all([
        api.currentUser(),
        api.activities(),
        api.analytics(),
        api.dashboardSummary(),
        api.todayReadiness(),
        api.providers(),
      ])
      setCurrentUser(nextUser)
      setActivities(nextActivities)
      setAnalytics(nextAnalytics)
      setDashboard(nextDashboard)
      setDailyReadiness(nextReadiness)
      setProviders(nextProviders)
      setStatus(authenticatedStatus())
      await refreshAthleteState()
    } catch (error) {
      if (!authConfig.devLoginEnabled && isUnauthorized(error)) {
        clearAuthToken()
        setCurrentUser(null)
        setAuthReady(false)
        setStatus("LOGIN REQUIRED")
        if (throwOnError) throw error
        return
      }
      setStatus("API ERROR")
      console.error(error)
      if (throwOnError) throw error
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
      if (nextCompleteness.score >= ONBOARDING_READY_SCORE) dismissOnboarding()
      setStatus(authenticatedStatus())
    } catch (error) {
      if (!authConfig.devLoginEnabled && isUnauthorized(error)) {
        clearAuthToken()
        setCurrentUser(null)
        setAuthReady(false)
        setStatus("LOGIN REQUIRED")
        return
      }
      setStatus("API ERROR")
      console.error(error)
    }
  }

  const effectiveCompleteness = completeness || dashboard?.profile_completeness || null
  const onboardingRequired = Boolean(effectiveCompleteness && effectiveCompleteness.score < ONBOARDING_READY_SCORE && !onboardingDismissed)

  useEffect(() => {
    if (!route.known) navigate(PAGE_PATHS.overview, { replace: true })
  }, [route.known, navigate])
  useEffect(() => {
    if (authReady) void refreshGlobal()
  }, [authReady])
  useEffect(() => {
    document.documentElement.classList.toggle("light", theme === "light")
    document.documentElement.classList.toggle("dark", theme === "dark")
    document.documentElement.style.colorScheme = theme
    safeStorageSet(THEME_KEY, theme)
  }, [theme])
  useEffect(() => {
    const url = new URL(window.location.href)
    const code = url.searchParams.get("telegram_login_code")
    if (!code) return
    url.searchParams.delete("telegram_login_code")
    const nextUrl = `${url.pathname}${url.search}${url.hash}`
    window.history.replaceState(null, "", nextUrl || window.location.pathname)
    let cancelled = false
    setStatus("TELEGRAM LOGIN")
    setAuthError("")
    void telegramStartCodeLogin(code).then((data) => {
      if (cancelled) return
      setCurrentUser(data.user)
      setAuthReady(true)
      setStatus("TELEGRAM USER")
    }).catch((error) => {
      if (cancelled) return
      console.error(error)
      setAuthReady(false)
      setStatus("LOGIN REQUIRED")
      setAuthError(apiErrorMessage(error, "Telegram bot login failed"))
    }).finally(() => {
      if (!cancelled) setAuthExchangePending(false)
    })
    return () => { cancelled = true }
  }, [])
  useEffect(() => onAuthExpired(() => {
    setCurrentUser(null)
    setAuthReady(false)
    setStatus("LOGIN REQUIRED")
  }), [])
  useEffect(() => {
    if (authReady && page === "profile") void refreshProfileData()
  }, [authReady, page])
  useEffect(() => {
    if (onboardingRequired && page !== "profile") navigate(PAGE_PATHS.profile, { replace: true })
  }, [onboardingRequired, page, navigate])
  useDomTranslations(language)

  if (!authReady) return <TelegramLoginGate theme={theme} onThemeToggle={toggleTheme} language={language} onLanguageChange={changeLanguage} onLogin={loginWithTelegram} initialError={authError} loading={authExchangePending} />

  return (
    <div className="min-h-screen bg-[#090909] text-zinc-100">
      <div className="grid min-h-screen lg:grid-cols-[14rem_1fr]">
        <Sidebar page={page} setPage={setPage} className="hidden lg:block" />
        {mobileOpen && <>
          <button aria-label={uiText("Закрыть меню", "Close menu overlay")} className="fixed inset-0 z-40 bg-black/70" onClick={() => setMobileOpen(false)} />
          <aside className="fixed inset-y-0 left-0 z-50 w-72 max-w-[86vw] overflow-y-auto border-r border-zinc-800 bg-[#111] lg:hidden">
            <div className="flex h-12 items-center justify-end border-b border-zinc-800 px-2"><Button variant="ghost" size="icon" onClick={() => setMobileOpen(false)}><X /></Button></div>
            <Sidebar page={page} setPage={(next) => { setPage(next); setMobileOpen(false) }} />
          </aside>
        </>}

        <div className="min-w-0 max-w-full">
          <Topbar page={page} status={status} currentUser={currentUser} theme={theme} onThemeToggle={toggleTheme} language={language} onLanguageChange={changeLanguage} onMenu={() => setMobileOpen(true)} />
          <main className="min-w-0 max-w-full overflow-hidden p-4 md:p-6">
            {page === "overview" && <Overview activities={activities} dashboard={dashboard} dailyReadiness={dailyReadiness} athleteState={athleteState} athleteStateError={athleteStateError} onRetryAthleteState={refreshAthleteState} onReadinessChanged={(value) => { setDailyReadiness(value); void refreshAthleteState() }} onActionApplied={() => refreshGlobal({ throwOnError: true })} onImport={() => setPage("imports")} onPlans={() => setPage("planning")} />}
            {page === "activities" && <Activities activities={activities} onImport={() => setPage("imports")} onChanged={refreshGlobal} />}
            {page === "imports" && <ImportsPage onChanged={refreshGlobal} />}
            {page === "calendar" && <CalendarPage onImport={() => setPage("imports")} onPlans={() => setPage("planning")} />}
            {page === "analytics" && <Analytics analytics={analytics} />}
            {page === "load" && <TrainingLoadRecovery />}
            {page === "zones" && <ZonesAnalytics />}
            {page === "performance" && <PerformanceAnalytics />}
            {page === "goals" && <GoalsRaces />}
            {page === "profile" && <ProfileZones profile={profile} completeness={completeness} safety={safety} zones={zones} measurements={measurements} onboardingMode={onboardingRequired} onDismissOnboarding={dismissOnboarding} onChanged={refreshProfileData} />}
            {page === "planning" && <Planning />}
            {page === "settings" && <SettingsPage providers={providers} onChanged={refreshGlobal} />}
          </main>
        </div>
      </div>
    </div>
  )
}

function TelegramLoginGate({ theme, onThemeToggle, language, onLanguageChange, onLogin, initialError, loading }: { theme: Theme; onThemeToggle: () => void; language: Language; onLanguageChange: (language: Language) => void; onLogin: (payload: TelegramLoginPayload) => Promise<void>; initialError?: string; loading?: boolean }) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [error, setError] = useState(initialError || "")
  const [botUrl, setBotUrl] = useState("")
  const botUsername = authConfig.telegramBotUsername

  useEffect(() => setError(initialError || ""), [initialError])

  useEffect(() => {
    let cancelled = false
    void telegramBotLink().then((link) => {
      if (!cancelled && link.bot_url) setBotUrl(link.bot_url)
    }).catch((caught) => {
      console.error(caught)
    })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (!botUsername || !containerRef.current) return
    const callbackName = `runforfanTelegramLogin_${Date.now()}`
    const callbacks = window as typeof window & Record<string, (user: TelegramLoginPayload) => void>
    callbacks[callbackName] = (user) => {
      setError("")
      void onLogin(user).catch((caught) => {
        console.error(caught)
        setError(apiErrorMessage(caught, "Telegram login failed"))
      })
    }
    const script = document.createElement("script")
    script.src = "https://telegram.org/js/telegram-widget.js?22"
    script.async = true
    script.setAttribute("data-telegram-login", botUsername)
    script.setAttribute("data-size", "large")
    script.setAttribute("data-request-access", "write")
    script.setAttribute("data-userpic", "false")
    script.setAttribute("data-onauth", `${callbackName}(user)`)
    containerRef.current.innerHTML = ""
    containerRef.current.appendChild(script)
    return () => {
      delete callbacks[callbackName]
      script.remove()
    }
  }, [botUsername, onLogin])

  return <div className="min-h-screen bg-[#090909] p-4 text-zinc-100 md:p-8">
    <div className="mx-auto grid min-h-[calc(100vh-4rem)] max-w-5xl place-items-center">
      <Card className="w-full max-w-xl border-orange-400/30 bg-zinc-950 p-6">
        <div className="flex items-center justify-between gap-3">
          <p className="font-mono text-[10px] uppercase tracking-[0.24em] text-orange-200">RUNFORFAN · {uiText("ВХОД", "LOGIN")}</p>
          <div className="flex items-center gap-2">
            <LanguageToggle language={language} onLanguageChange={onLanguageChange} />
            <Button type="button" variant="ghost" size="icon" aria-label={theme === "light" ? "Switch to dark theme" : "Switch to light theme"} aria-pressed={theme === "light"} onClick={onThemeToggle}>{theme === "light" ? <Moon /> : <Sun />}</Button>
          </div>
        </div>
        <h1 className="mt-3 text-2xl font-semibold text-white">{uiText("Вход через Telegram", "Sign in with Telegram")}</h1>
        <p className="mt-3 text-sm leading-6 text-zinc-400">{uiText("Откройте бота в Telegram, нажмите Start и вернитесь по ссылке из сообщения.", "Open the Telegram bot, press Start, then return through the link from the bot message.")}</p>
        <div className="mt-5 space-y-3 rounded-lg border border-zinc-800 bg-black/30 p-4">
          {loading ? <p className="text-sm text-orange-100">{uiText("Завершаем вход через Telegram...", "Finishing Telegram login...")}</p> : null}
          {botUrl ? <a className="inline-flex h-11 items-center justify-center rounded-md bg-orange-400 px-4 text-sm font-semibold text-black transition-colors hover:bg-orange-300 md:h-10" href={botUrl} target="_blank" rel="noreferrer">{uiText("Открыть Telegram-бота", "Open Telegram bot")}</a> : <p className="text-sm text-orange-100">{uiText("Бот временно недоступен. Попробуйте позже.", "Telegram bot is temporarily unavailable. Try again later.")}</p>}
          {botUsername ? <div ref={containerRef} className="min-h-10" /> : null}
          {error ? <p className="mt-3 rounded-md border border-rose-400/20 bg-rose-400/10 px-2 py-1.5 text-xs text-rose-100">{error}</p> : null}
        </div>
      </Card>
    </div>
  </div>
}

function Sidebar({ page, setPage, className }: { page: Page; setPage: (page: Page) => void; className?: string }) {
  const navButton = ([key, ruLabel, enLabel, Icon]: (typeof primaryNav | typeof secondaryNav)[number]) => {
    const active = page === key
    return <button key={key} onClick={() => setPage(key)} aria-current={active ? "page" : undefined} className={cn("relative flex min-h-11 w-full items-center gap-2 rounded-md px-3 text-left text-sm font-medium transition-colors lg:min-h-9 lg:px-2 lg:text-xs", active ? "bg-zinc-800 text-white before:absolute before:left-0 before:top-2 before:h-7 before:w-0.5 before:bg-orange-400 lg:before:top-1 lg:before:h-7" : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-100")}><Icon className="h-4 w-4" />{uiText(ruLabel, enLabel)}</button>
  }

  return <div className={cn("sticky top-0 h-screen overflow-y-auto border-r border-zinc-800 bg-[#111] pb-4 text-zinc-300", className)}>
    <div className="border-b border-zinc-800 px-3 py-3">
      <p className="font-mono text-[10px] uppercase tracking-[0.24em] text-zinc-500">RUNFORFAN</p>
      <h1 className="mt-1 text-sm font-semibold text-white">{uiText("Мои тренировки", "My training")}</h1>
    </div>
    <nav className="space-y-1 p-2" aria-label={uiText("Основная навигация", "Primary navigation")}>
      {primaryNav.map(navButton)}
      <details className="group pt-2" open={secondaryNav.some(([key]) => key === page)}>
        <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between rounded-md px-3 text-xs font-semibold text-zinc-500 transition-colors hover:bg-zinc-900 hover:text-zinc-200 lg:min-h-9 lg:px-2 [&::-webkit-details-marker]:hidden"><span>{uiText("Еще", "More")}</span><span className="text-orange-300 group-open:hidden">+</span><span className="hidden text-zinc-500 group-open:inline">-</span></summary>
        <div className="mt-1 space-y-1 pl-1">{secondaryNav.map(navButton)}</div>
      </details>
    </nav>
    <div className="mt-4 border-t border-zinc-800 p-2">
      <div className="flex h-11 items-center gap-2 rounded-md px-3 text-xs text-zinc-500 lg:h-8 lg:px-2"><Shield className="h-4 w-4" /> {uiText("Вход через Telegram", "Telegram login")}</div>
      <div className="flex h-11 items-center gap-2 rounded-md px-3 text-xs text-zinc-500 lg:h-8 lg:px-2"><Bot className="h-4 w-4" /> {uiText("Ключи тренера", "Coach keys")}</div>
      <a href={guideHref()} className="flex h-11 items-center gap-2 rounded-md px-3 text-xs text-zinc-500 transition-colors hover:bg-zinc-900 hover:text-zinc-100 lg:h-8 lg:px-2"><BookOpen className="h-4 w-4" /> {uiText("Гид тестера", "Tester guide")}</a>
    </div>
  </div>
}

function LanguageToggle({ language, onLanguageChange }: { language: Language; onLanguageChange: (language: Language) => void }) {
  return <div className="inline-flex rounded-md border border-zinc-800 bg-zinc-950 p-0.5" aria-label="Language">
    {(["ru", "en"] as const).map((item) => <button
      key={item}
      type="button"
      aria-label={item === "ru" ? "Use Russian" : "Use English"}
      aria-pressed={language === item}
      onClick={() => onLanguageChange(item)}
      className={cn("h-8 rounded px-2.5 font-mono text-[10px] font-semibold uppercase tracking-[0.12em] transition-colors md:h-6 md:px-2", language === item ? "bg-orange-500 text-black" : "text-zinc-500 hover:bg-zinc-900 hover:text-zinc-200")}
    >{item}</button>)}
  </div>
}

function AuthUserPill({ user, className }: { user: AuthUser | null; className?: string }) {
  const name = authUserName(user)
  const meta = authUserMeta(user)
  return <div className={cn("min-w-0 items-center gap-2 rounded-full border border-zinc-800 bg-zinc-950 px-2 py-1", className)} title={`${name} · ${meta}`}>
    <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-orange-400 text-[10px] font-bold text-black" translate="no">{authUserInitial(user)}</span>
    <span className="min-w-0 truncate text-xs font-medium text-zinc-100" translate="no">{name}</span>
    <span className="min-w-0 truncate font-mono text-[10px] text-zinc-500" translate="no">{meta}</span>
  </div>
}

function Topbar({ page, status, currentUser, theme, onThemeToggle, language, onLanguageChange, onMenu }: { page: Page; status: string; currentUser: AuthUser | null; theme: Theme; onThemeToggle: () => void; language: Language; onLanguageChange: (language: Language) => void; onMenu: () => void }) {
  return <header className="sticky top-0 z-30 border-b border-zinc-800 bg-[#090909]/95 backdrop-blur">
    <div className="flex h-12 items-center justify-between px-3">
      <div className="flex min-w-0 items-center gap-2">
        <Button variant="ghost" size="icon" className="lg:hidden" aria-label={uiText("Открыть меню", "Open menu")} onClick={onMenu}><Menu /></Button>
        <div className="min-w-0">
          <p className="hidden font-mono text-[10px] uppercase tracking-[0.24em] text-zinc-500 sm:block">RUNFORFAN</p>
          <h2 className="truncate text-sm font-semibold text-white sm:text-base">{pageTitle(page)}</h2>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <LanguageToggle language={language} onLanguageChange={onLanguageChange} />
        <AuthUserPill user={currentUser} className="hidden max-w-[18rem] sm:flex [&>span:nth-child(2)]:max-w-[9rem] [&>span:nth-child(3)]:max-w-[7rem]" />
        <Badge className="hidden sm:inline-flex">{appStatusLabel(status)}</Badge>
        <Button variant="ghost" size="icon" aria-label={theme === "light" ? "Switch to dark theme" : "Switch to light theme"} aria-pressed={theme === "light"} onClick={onThemeToggle}>{theme === "light" ? <Moon /> : <Sun />}</Button>
      </div>
    </div>
  </header>
}

function Overview({ activities, dashboard, dailyReadiness, athleteState, athleteStateError, onRetryAthleteState, onReadinessChanged, onActionApplied, onImport, onPlans }: { activities: ActivityType[]; dashboard: DashboardSummary | null; dailyReadiness: DailyReadiness | null; athleteState: AthleteState | null; athleteStateError: string; onRetryAthleteState: () => Promise<void>; onReadinessChanged: (value: DailyReadiness) => void; onActionApplied: () => Promise<void>; onImport: () => void; onPlans: () => void }) {
  const currentWeek = dashboard?.current_week
  const plan = dashboard?.active_plan
  const recentActivities = dashboard?.recent_activities?.length ? dashboard.recent_activities : activities
  const readiness = dashboard?.readiness
  const visibleAlertCount = (dashboard?.alerts || []).filter((alert) => !/provider|llm|import|profile|engine|template/i.test(`${alert.title} ${alert.message} ${alert.action || ""}`)).length
  const showSignals = Boolean(visibleAlertCount || (readiness?.status && readiness.status !== "ok"))
  return <div className="grid gap-4">
    <WorkoutFocus todayWorkout={dashboard?.today_workout || null} nextWorkout={dashboard?.next_workout || null} currentWeek={currentWeek || null} activePlanTitle={plan?.title || null} onPlans={onPlans} onImport={onImport} />
    <DailyCoachCheckIn readiness={dailyReadiness} onChanged={onReadinessChanged} onActionApplied={onActionApplied} />
    <AthleteStateCard athleteState={athleteState} error={athleteStateError} onRetry={onRetryAthleteState} />
    <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
      {currentWeek ? <CurrentWeekCoachCard currentWeek={currentWeek} onPlans={onPlans} /> : <Card className="p-4 text-sm text-zinc-400">{uiText("Создайте план, чтобы видеть неделю целиком.", "Create a plan to see the week at a glance.")}</Card>}
      <RecentRunsCard activities={recentActivities.slice(0, 3)} />
    </div>
    {showSignals ? <CollapsibleSection title={uiText("Перед тренировкой", "Before your workout")} summary={<Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{uiText("если нужно", "if needed")}</Badge>}><DashboardSignals dashboard={dashboard} /></CollapsibleSection> : null}
  </div>
}

type DailyCheckInDraft = {
  sleep: string
  fatigue: string
  soreness: string
  stress: string
  pain: boolean
  painLevel: string
  illness: boolean
  notes: string
}

function dailyDraft(readiness: DailyReadiness | null): DailyCheckInDraft {
  const checkin = readiness?.checkin
  return {
    sleep: checkin?.sleep_quality_0_10?.toString() || "",
    fatigue: checkin?.fatigue_0_10?.toString() || "",
    soreness: checkin?.soreness_0_10?.toString() || "",
    stress: checkin?.stress_0_10?.toString() || "",
    pain: checkin?.pain || false,
    painLevel: checkin?.pain_level_0_10?.toString() || "",
    illness: checkin?.illness_symptoms || false,
    notes: checkin?.notes || "",
  }
}

function dailyStatusClass(status?: string) {
  if (status === "stop") return "border-rose-400/40 bg-rose-500/10 text-rose-100"
  if (status === "rest" || status === "modify") return "border-orange-400/40 bg-orange-400/10 text-orange-100"
  if (status === "proceed") return "border-emerald-400/30 bg-emerald-400/10 text-emerald-100"
  return "border-zinc-700 bg-zinc-900 text-zinc-300"
}

function dailyStatusLabel(status?: string) {
  if (status === "stop") return uiText("стоп", "stop")
  if (status === "rest") return uiText("отдых", "rest")
  if (status === "modify") return uiText("облегчить", "modify")
  if (status === "proceed") return uiText("по плану", "on plan")
  return uiText("нужен check-in", "check-in needed")
}

function readinessChangeValue(value: unknown) {
  if (value === null || value === undefined) return "--"
  if (Array.isArray(value)) return `${value.length} ${uiText("блоков", "blocks")}`
  if (typeof value === "object") return JSON.stringify(value)
  return String(value)
}

function readinessChangeLabel(field: string) {
  const labels: Record<string, string> = {
    workout_type: uiText("Тип", "Type"),
    title: uiText("Название", "Title"),
    distance_km: uiText("Дистанция, км", "Distance, km"),
    duration_seconds: uiText("Длительность, сек", "Duration, sec"),
    intensity: uiText("Интенсивность", "Intensity"),
    description: uiText("Инструкция", "Instructions"),
    blocks: uiText("Структура", "Structure"),
  }
  return labels[field] || field
}

function ReadinessActionDialog({ preview, applying, error, onApply, onClose }: { preview: DailyReadinessActionPreview; applying: boolean; error: string; onApply: () => void; onClose: () => void }) {
  const dialogRef = useRef<HTMLDivElement | null>(null)
  const applyButtonRef = useRef<HTMLButtonElement | null>(null)
  const closeRef = useRef(onClose)
  const applyingRef = useRef(applying)
  closeRef.current = onClose
  applyingRef.current = applying

  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    applyButtonRef.current?.focus()
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !applyingRef.current) closeRef.current()
      if (event.key !== "Tab" || !dialogRef.current) return
      const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>('button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'))
      if (!focusable.length) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    window.addEventListener("keydown", onKeyDown)
    return () => {
      window.removeEventListener("keydown", onKeyDown)
      previousFocus?.focus()
    }
  }, [])

  return <div className="fixed inset-0 z-50 grid place-items-center overflow-y-auto bg-black/80 p-3" role="presentation" onMouseDown={(event) => { if (event.currentTarget === event.target && !applying) onClose() }}>
    <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="readiness-action-title" aria-describedby="readiness-action-summary" className="my-auto w-full max-w-2xl rounded-2xl border border-orange-400/30 bg-[#111] shadow-2xl shadow-black/50">
      <div className="border-b border-zinc-800 p-4"><p className="text-xs font-semibold text-orange-200">Daily coach</p><h3 id="readiness-action-title" className="mt-1 text-xl font-semibold text-white">{uiText("Подтвердите изменение тренировки", "Confirm workout change")}</h3><p id="readiness-action-summary" className="mt-2 text-sm leading-6 text-zinc-400">{preview.summary}</p></div>
      <div className="grid max-h-[65vh] gap-4 overflow-y-auto p-4">
        <div className="grid gap-2">{preview.changes.map((change) => <div key={change.field} className="grid gap-2 rounded-xl border border-zinc-800 bg-zinc-950/70 p-3 text-xs sm:grid-cols-[8rem_1fr_auto_1fr] sm:items-center"><span className="font-medium text-zinc-400">{readinessChangeLabel(change.field)}</span><span className="min-w-0 break-words text-zinc-500">{readinessChangeValue(change.before)}</span><span className="text-orange-300">→</span><span className="min-w-0 break-words text-white">{readinessChangeValue(change.after)}</span></div>)}</div>
        <div className="grid gap-2 rounded-xl border border-zinc-800 p-3 text-xs sm:grid-cols-2"><div><p className="text-zinc-500">{uiText("Неделя: дистанция", "Week: distance")}</p><p className="mt-1 text-white">{formatDistance(preview.weekly_effect.planned_distance_km_before)} → {formatDistance(preview.weekly_effect.planned_distance_km_after)}</p></div><div><p className="text-zinc-500">{uiText("Неделя: время", "Week: duration")}</p><p className="mt-1 text-white">{formatDuration(preview.weekly_effect.planned_duration_seconds_before)} → {formatDuration(preview.weekly_effect.planned_duration_seconds_after)}</p></div></div>
        <p className="text-[11px] leading-5 text-zinc-600">{preview.disclaimer}</p>
        {error ? <p className="rounded-xl border border-rose-400/30 bg-rose-500/10 p-3 text-xs text-rose-200">{error}</p> : null}
      </div>
      <div className="flex flex-col-reverse gap-2 border-t border-zinc-800 p-4 sm:flex-row sm:justify-end"><Button variant="secondary" disabled={applying} onClick={onClose}>{uiText("Оставить как есть", "Keep original")}</Button><Button ref={applyButtonRef} disabled={applying} onClick={onApply}>{applying ? uiText("Применяем...", "Applying...") : uiText("Применить изменение", "Apply change")}</Button></div>
    </div>
  </div>
}

function MissWorkoutDialog({ title, busy, error, onSubmit, onClose }: { title: string; busy: boolean; error: string; onSubmit: (reason: WorkoutMissReason, notes?: string) => void; onClose: () => void }) {
  const [reason, setReason] = useState<WorkoutMissReason>("schedule_conflict")
  const [notes, setNotes] = useState("")
  const dialogRef = useRef<HTMLDivElement | null>(null)
  const reasonRef = useRef<HTMLSelectElement | null>(null)
  const closeRef = useRef(onClose)
  const busyRef = useRef(busy)
  closeRef.current = onClose
  busyRef.current = busy

  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    reasonRef.current?.focus()
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !busyRef.current) closeRef.current()
      if (event.key !== "Tab" || !dialogRef.current) return
      const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'))
      if (!focusable.length) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener("keydown", onKeyDown)
    return () => {
      document.removeEventListener("keydown", onKeyDown)
      previousFocus?.focus()
    }
  }, [])

  return <div className="fixed inset-0 z-50 flex overflow-y-auto bg-black/75 p-3 backdrop-blur-sm" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose() }}>
    <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="miss-workout-title" aria-describedby="miss-workout-description" className="my-auto w-full max-w-lg rounded-2xl border border-zinc-700 bg-[#111] p-4 shadow-2xl shadow-black/50">
      <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-orange-300">Coach timeline</p>
      <h2 id="miss-workout-title" className="mt-2 text-lg font-semibold text-white">{uiText("Отметить пропуск", "Mark workout missed")}</h2>
      <p id="miss-workout-description" className="mt-2 text-xs leading-5 text-zinc-400">{title}. {uiText("Причина поможет безопасно адаптировать следующие решения. Пропущенный объём не будет автоматически компенсирован.", "The reason helps keep later decisions safe. Missed volume will not be automatically compensated.")}</p>
      <div className="mt-4 grid gap-3">
        <Field label={uiText("Причина", "Reason")}><Select ref={reasonRef} value={reason} onChange={(event) => setReason(event.target.value as WorkoutMissReason)}><option value="illness">{uiText("Болезнь", "Illness")}</option><option value="pain">{uiText("Боль", "Pain")}</option><option value="fatigue">{uiText("Усталость", "Fatigue")}</option><option value="schedule_conflict">{uiText("Не подошло расписание", "Schedule conflict")}</option><option value="weather">{uiText("Погода", "Weather")}</option><option value="other">{uiText("Другое", "Other")}</option></Select></Field>
        <Field label={uiText("Комментарий (необязательно)", "Note (optional)")}><Input value={notes} maxLength={1000} onChange={(event) => setNotes(event.target.value)} /></Field>
      </div>
      {error ? <p role="alert" aria-live="assertive" className="mt-3 rounded-md border border-orange-400/20 bg-orange-400/10 px-3 py-2 text-xs text-orange-100">{error}</p> : null}
      <div className="mt-4 flex flex-wrap justify-end gap-2"><Button variant="secondary" disabled={busy} onClick={onClose}>{uiText("Отмена", "Cancel")}</Button><Button disabled={busy} onClick={() => onSubmit(reason, notes.trim() || undefined)}>{busy ? uiText("Сохраняем...", "Saving...") : uiText("Сохранить пропуск", "Save missed workout")}</Button></div>
    </div>
  </div>
}

function coachActionChangeLabel(field: string) {
  const labels: Record<string, string> = {
    status: uiText("Статус", "Status"),
    scheduled_date: uiText("Дата", "Date"),
  }
  return labels[field] || readinessChangeLabel(field)
}

function coachActionServerSummary(summary: string, action: CoachAction) {
  const summaries: Record<string, [string, string]> = {
    "Тренировка будет отменена без переноса пропущенного объёма.": ["Тренировка будет отменена без переноса пропущенного объема.", "The workout will be skipped without moving missed volume to another session."],
    "Тренировка будет перенесена после проверки интервалов между тяжёлыми сессиями.": ["Тренировка будет перенесена после проверки интервалов между тяжелыми сессиями.", "The workout will be rescheduled after checking spacing between hard sessions."],
  }
  const mapped = summaries[summary]
  if (mapped) return uiText(...mapped)
  return action === "skip"
    ? uiText("Тренировка будет отменена. Проверьте изменения и ограничения ниже.", "The workout will be skipped. Review the changes and constraints below.")
    : uiText("Тренировка будет перенесена. Проверьте изменения и ограничения ниже.", "The workout will be rescheduled. Review the changes and constraints below.")
}

function coachActionConstraintFact(fact: string) {
  const facts: Record<string, [string, string]> = {
    "No missed volume will be moved to another workout.": ["Пропущенный объем не будет перенесен на другую тренировку.", "No missed volume will be moved to another workout."],
    "Hard-session spacing was checked against the current active plan.": ["Интервалы между тяжелыми тренировками проверены по текущему активному плану.", "Hard-session spacing was checked against the current active plan."],
    "This workout is not classified as a hard session by the planning policy.": ["Эта тренировка не относится к тяжелым по правилам планирования.", "This workout is not classified as a hard session by the planning policy."],
  }
  const mapped = facts[fact]
  return mapped ? uiText(...mapped) : fact
}

function coachActionDurationEffect(before: number, after: number) {
  if (before <= 0 && after <= 0) return uiText("Длительность не задана в плане", "Duration target is unavailable for this plan")
  const value = (seconds: number) => seconds > 0 ? formatDuration(seconds) : uiText("0 мин", "0 min")
  return `${value(before)} → ${value(after)}`
}

function CoachActionDialog({ target, onApplied, onClose }: { target: CoachActionTarget; onApplied: () => Promise<void>; onClose: () => void }) {
  const [reason, setReason] = useState<WorkoutMissReason>("schedule_conflict")
  const [notes, setNotes] = useState("")
  const [preview, setPreview] = useState<CoachActionPreview | null>(null)
  const [previewing, setPreviewing] = useState(false)
  const [applying, setApplying] = useState(false)
  const [error, setError] = useState("")
  const dialogRef = useRef<HTMLDivElement | null>(null)
  const reasonRef = useRef<HTMLSelectElement | null>(null)
  const applyButtonRef = useRef<HTMLButtonElement | null>(null)
  const closeRef = useRef(onClose)
  const busyRef = useRef(false)
  closeRef.current = onClose
  busyRef.current = previewing || applying

  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    reasonRef.current?.focus()
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !busyRef.current) closeRef.current()
      if (event.key !== "Tab" || !dialogRef.current) return
      const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'))
      if (!focusable.length) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener("keydown", onKeyDown)
    return () => {
      document.removeEventListener("keydown", onKeyDown)
      previousFocus?.focus()
    }
  }, [])

  useEffect(() => {
    if (preview) applyButtonRef.current?.focus()
  }, [preview])

  async function createPreview() {
    setPreviewing(true)
    setError("")
    try {
      setPreview(await api.previewCoachAction(target.workoutId, {
        action: target.action,
        reason,
        notes: notes.trim() || null,
        target_date: target.action === "reschedule" ? target.targetDate || null : null,
      }))
    } catch (caught) {
      setError(apiErrorMessage(caught, uiText("Не удалось проверить изменение", "Could not prepare the change preview")))
    } finally {
      setPreviewing(false)
    }
  }

  async function applyPreview() {
    if (!preview) return
    setApplying(true)
    setError("")
    try {
      await api.applyCoachAction(preview.preview_id)
      await onApplied()
      onClose()
    } catch (caught) {
      setError(apiErrorMessage(caught, uiText("Preview устарел или изменение нельзя применить", "The preview expired or the change can no longer be applied")))
    } finally {
      setApplying(false)
    }
  }

  const actionLabel = target.action === "skip" ? uiText("отменить тренировку", "skip workout") : uiText("перенести тренировку", "reschedule workout")
  return <div className="fixed inset-0 z-50 flex overflow-y-auto bg-black/75 p-3 backdrop-blur-sm" onMouseDown={(event) => { if (event.target === event.currentTarget && !busyRef.current) onClose() }}>
    <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="coach-action-title" aria-describedby="coach-action-description" className="my-auto flex max-h-[calc(100dvh-1.5rem)] w-full max-w-2xl min-h-0 flex-col overflow-hidden rounded-2xl border border-orange-400/30 bg-[#111] shadow-2xl shadow-black/50">
      <div className="shrink-0 border-b border-zinc-800 p-4"><p className="font-mono text-[10px] uppercase tracking-[0.18em] text-orange-300">Coach action</p><h2 id="coach-action-title" className="mt-2 text-lg font-semibold text-white">{preview ? uiText("Проверьте изменение плана", "Review plan change") : `${uiText("Подготовить", "Prepare")} ${actionLabel}`}</h2><p id="coach-action-description" className="mt-2 text-xs leading-5 text-zinc-400">{preview ? coachActionServerSummary(preview.summary, preview.action) : `${target.title}. ${uiText("Сначала укажите причину. Тренер проверит влияние на план до подтверждения.", "Choose a reason first. Coach will check the plan impact before confirmation.")}`}</p></div>
      <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden p-4">
        <div className="grid gap-4">
          {!preview ? <div className="grid gap-3"><Field label={uiText("Причина", "Reason")}><Select ref={reasonRef} value={reason} disabled={previewing} onChange={(event) => setReason(event.target.value as WorkoutMissReason)}><option value="illness">{uiText("Болезнь", "Illness")}</option><option value="pain">{uiText("Боль", "Pain")}</option><option value="fatigue">{uiText("Усталость", "Fatigue")}</option><option value="schedule_conflict">{uiText("Не подошло расписание", "Schedule conflict")}</option><option value="weather">{uiText("Погода", "Weather")}</option><option value="other">{uiText("Другое", "Other")}</option></Select></Field><Field label={uiText("Комментарий (необязательно)", "Note (optional)")}><Input value={notes} disabled={previewing} maxLength={1000} onChange={(event) => setNotes(event.target.value)} /></Field></div> : <><div className="grid gap-2">{preview.changes.map((change) => <div key={change.field} className="grid min-w-0 gap-2 rounded-xl border border-zinc-800 bg-zinc-950/70 p-3 text-xs sm:grid-cols-[8rem_minmax(0,1fr)_auto_minmax(0,1fr)] sm:items-center"><span className="font-medium text-zinc-400">{coachActionChangeLabel(change.field)}</span><span className="min-w-0 break-words text-zinc-500">{readinessChangeValue(change.before)}</span><span className="text-orange-300">→</span><span className="min-w-0 break-words text-white">{readinessChangeValue(change.after)}</span></div>)}</div><div className="grid gap-2 rounded-xl border border-zinc-800 p-3 text-xs sm:grid-cols-2"><div><p className="text-zinc-500">{uiText("Текущая неделя: дистанция", "Current week: distance")}</p><p className="mt-1 break-words text-white">{formatDistance(preview.weekly_effect.planned_distance_km_before)} → {formatDistance(preview.weekly_effect.planned_distance_km_after)}</p></div><div><p className="text-zinc-500">{uiText("Текущая неделя: время", "Current week: duration")}</p><p className="mt-1 break-words text-white">{coachActionDurationEffect(preview.weekly_effect.planned_duration_seconds_before, preview.weekly_effect.planned_duration_seconds_after)}</p></div></div>{preview.calendar_week_effects.length ? <div className="grid gap-2"><p className="text-xs font-medium text-white">{uiText("Нагрузка по календарным неделям", "Calendar week load")}</p>{preview.calendar_week_effects.map((effect) => <div key={effect.week_start} className="grid min-w-0 gap-1.5 rounded-xl border border-zinc-800 bg-zinc-950/70 p-3 text-xs sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:gap-2"><span className="break-words text-zinc-400">{formatDate(effect.week_start)} - {formatDate(effect.week_end)}</span><span className="break-words text-zinc-300">{formatDistance(effect.planned_distance_km_before)} → {formatDistance(effect.planned_distance_km_after)}</span><span className="break-words text-zinc-300">{coachActionDurationEffect(effect.planned_duration_seconds_before, effect.planned_duration_seconds_after)}</span></div>)}</div> : null}{preview.constraint_facts.length ? <div className="rounded-xl border border-orange-400/20 bg-orange-400/10 p-3 text-xs text-orange-100"><p className="font-medium">{uiText("Проверка ограничений", "Constraint check")}</p><div className="mt-2 grid gap-1">{preview.constraint_facts.map((fact) => <p key={fact}>{coachActionConstraintFact(fact)}</p>)}</div></div> : null}<p className="text-[11px] leading-5 text-zinc-600">{uiText("Правила", "Rules")} {preview.rule_version} · {uiText("действует до", "valid until")} {formatLocalDateTime(preview.expires_at)}</p></>}
          {error ? <p role="alert" aria-live="assertive" className="rounded-xl border border-rose-400/30 bg-rose-500/10 p-3 text-xs text-rose-200">{error}</p> : null}
        </div>
      </div>
      <div className="shrink-0 flex flex-col-reverse gap-2 border-t border-zinc-800 p-4 sm:flex-row sm:justify-end"><Button variant="secondary" disabled={previewing || applying} onClick={onClose}>{uiText("Оставить как есть", "Keep original")}</Button>{preview ? <Button ref={applyButtonRef} disabled={applying} onClick={applyPreview}>{applying ? uiText("Применяем...", "Applying...") : uiText("Подтвердить изменение", "Confirm change")}</Button> : <Button disabled={previewing} onClick={createPreview}>{previewing ? uiText("Проверяем...", "Checking...") : uiText("Показать последствия", "Show impact")}</Button>}</div>
    </div>
  </div>
}

function PlanRollbackDialog({ preview, applying, error, onApply, onClose }: { preview: PlanRollbackPreview; applying: boolean; error: string; onApply: () => void; onClose: () => void }) {
  const dialogRef = useRef<HTMLDivElement | null>(null)
  const applyRef = useRef<HTMLButtonElement | null>(null)
  const closeRef = useRef(onClose)
  const applyingRef = useRef(applying)
  closeRef.current = onClose
  applyingRef.current = applying

  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    applyRef.current?.focus()
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !applyingRef.current) closeRef.current()
      if (event.key !== "Tab" || !dialogRef.current) return
      const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>('button:not([disabled]), [tabindex]:not([tabindex="-1"])'))
      if (!focusable.length) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener("keydown", onKeyDown)
    return () => {
      document.removeEventListener("keydown", onKeyDown)
      previousFocus?.focus()
    }
  }, [])

  return <div className="fixed inset-0 z-50 flex overflow-y-auto bg-black/80 p-3 backdrop-blur-sm" onMouseDown={(event) => { if (event.target === event.currentTarget && !applying) onClose() }}>
    <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="rollback-title" aria-describedby="rollback-summary" className="my-auto w-full max-w-2xl rounded-2xl border border-orange-400/30 bg-[#111] shadow-2xl shadow-black/50">
      <div className="border-b border-zinc-800 p-4"><p className="font-mono text-[10px] uppercase tracking-[0.18em] text-orange-300">Compensating rollback</p><h2 id="rollback-title" className="mt-2 text-lg font-semibold text-white">{uiText(`Отменить изменения версии v${preview.version_number}`, `Reverse version v${preview.version_number}`)}</h2><p id="rollback-summary" className="mt-2 text-xs leading-5 text-zinc-400">{uiText("История не удаляется: будет создана новая компенсирующая версия. Перед применением сервер повторно проверит актуальность плана и safety-ограничения.", "History is preserved: a new compensating version will be created. The server rechecks plan freshness and safety before applying.")}</p></div>
      <div className="grid max-h-[65vh] gap-2 overflow-y-auto p-4">{preview.changes.map((change, index) => <div key={`${change.workout_id}-${change.field}-${index}`} className="grid gap-2 rounded-xl border border-zinc-800 bg-zinc-950/70 p-3 text-xs sm:grid-cols-[7rem_8rem_1fr_auto_1fr] sm:items-center"><span className="font-mono text-[10px] text-zinc-500">#{change.workout_id}</span><span className="font-medium text-zinc-400">{coachActionChangeLabel(change.field)}</span><span className="min-w-0 break-words text-zinc-500">{readinessChangeValue(change.before)}</span><span className="text-orange-300">→</span><span className="min-w-0 break-words text-white">{readinessChangeValue(change.after)}</span></div>)}{error ? <p role="alert" className="rounded-xl border border-rose-400/30 bg-rose-500/10 p-3 text-xs text-rose-200">{error}</p> : null}</div>
      <div className="flex flex-col-reverse gap-2 border-t border-zinc-800 p-4 sm:flex-row sm:justify-end"><Button variant="secondary" disabled={applying} onClick={onClose}>{uiText("Оставить план", "Keep plan")}</Button><Button ref={applyRef} disabled={applying} onClick={onApply}>{applying ? uiText("Проверяем и отменяем...", "Checking and reversing...") : uiText("Создать компенсирующую версию", "Create compensating version")}</Button></div>
    </div>
  </div>
}

function DailyCoachCheckIn({ readiness, onChanged, onActionApplied }: { readiness: DailyReadiness | null; onChanged: (value: DailyReadiness) => void; onActionApplied: () => Promise<void> }) {
  const [draft, setDraft] = useState<DailyCheckInDraft>(() => dailyDraft(readiness))
  const [editing, setEditing] = useState(() => !readiness?.checkin)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")
  const [actionPreview, setActionPreview] = useState<DailyReadinessActionPreview | null>(null)
  const [previewingAction, setPreviewingAction] = useState(false)
  const [applyingAction, setApplyingAction] = useState(false)
  const [actionError, setActionError] = useState("")

  useEffect(() => {
    setDraft(dailyDraft(readiness))
    if (readiness?.checkin) setEditing(false)
  }, [readiness])

  async function submit(event: FormEvent) {
    event.preventDefault()
    setSaving(true)
    setError("")
    try {
      const value = (raw: string) => raw === "" ? null : Number(raw)
      const next = await api.saveTodayReadiness({
        sleep_quality_0_10: value(draft.sleep),
        fatigue_0_10: value(draft.fatigue),
        soreness_0_10: value(draft.soreness),
        stress_0_10: value(draft.stress),
        pain: draft.pain,
        pain_level_0_10: draft.pain ? value(draft.painLevel) : null,
        pain_notes: null,
        illness_symptoms: draft.illness,
        illness_notes: null,
        notes: draft.notes.trim() || null,
      })
      onChanged(next)
      setEditing(false)
    } catch (caught) {
      setError(apiErrorMessage(caught, uiText("Не удалось сохранить check-in", "Could not save check-in")))
    } finally {
      setSaving(false)
    }
  }

  async function previewAction() {
    setPreviewingAction(true)
    setActionError("")
    try {
      setActionPreview(await api.previewTodayReadinessAction())
    } catch (caught) {
      setActionError(apiErrorMessage(caught, uiText("Рекомендация изменилась. Обновите check-in и попробуйте снова.", "The guidance changed. Refresh your check-in and try again.")))
    } finally {
      setPreviewingAction(false)
    }
  }

  async function applyAction() {
    if (!actionPreview) return
    setApplyingAction(true)
    setActionError("")
    try {
      await api.applyTodayReadinessAction(actionPreview.preview_id)
      setActionPreview(null)
    } catch (caught) {
      setActionError(apiErrorMessage(caught, uiText("Preview устарел или изменился. Закройте окно и создайте новый preview.", "The preview expired or changed. Close it and create a new preview.")))
      setApplyingAction(false)
      return
    }
    try {
      await onActionApplied()
    } catch {
      try {
        onChanged(await api.todayReadiness())
        setActionError(uiText("Изменение применено, но часть данных экрана не обновилась. Перезагрузите страницу позже.", "The change was applied, but some screen data could not refresh. Reload the page later."))
      } catch {
        setActionError(uiText("Изменение применено. Не удалось обновить экран; данные появятся после перезагрузки.", "The change was applied. The screen could not refresh; the new data will appear after reload."))
      }
    } finally {
      setApplyingAction(false)
    }
  }

  const recommendation = readiness?.recommendation
  const scoreOptions = Array.from({ length: 11 }, (_, value) => value)
  return <Card className="overflow-hidden">
    <CardHeader className="border-b border-zinc-800"><div><p className="text-xs font-semibold text-orange-200">Daily coach</p><CardTitle className="mt-1">{uiText("Как вы себя чувствуете сегодня?", "How do you feel today?")}</CardTitle><p className="mt-1 text-xs text-zinc-500">{uiText("Четыре сигнала помогают безопасно уточнить сегодняшнюю нагрузку.", "Four signals help safely adjust today's guidance.")}</p></div><Badge className={dailyStatusClass(recommendation?.status)}>{dailyStatusLabel(recommendation?.status)}</Badge></CardHeader>
    {editing ? <form className="grid gap-4 p-4" onSubmit={submit}>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[
          ["sleep", uiText("Сон", "Sleep"), uiText("10 = отлично", "10 = excellent")],
          ["fatigue", uiText("Усталость", "Fatigue"), uiText("10 = очень высокая", "10 = very high")],
          ["soreness", uiText("Мышцы", "Soreness"), uiText("10 = сильно болят", "10 = very sore")],
          ["stress", uiText("Стресс", "Stress"), uiText("10 = очень высокий", "10 = very high")],
        ].map(([field, label, hint]) => <label key={field} className="grid gap-1 text-xs text-zinc-300"><span className="font-medium text-white">{label}</span><Select required value={draft[field as keyof Pick<DailyCheckInDraft, "sleep" | "fatigue" | "soreness" | "stress">]} onChange={(event) => setDraft((current) => ({ ...current, [field]: event.target.value }))}><option value="">--</option>{scoreOptions.map((value) => <option key={value} value={value}>{value}</option>)}</Select><span className="text-zinc-600">{hint}</span></label>)}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-xl border border-zinc-800 bg-zinc-950/70 p-3"><label className="flex items-center gap-2 text-sm font-medium text-white"><input type="checkbox" checked={draft.pain} onChange={(event) => setDraft((current) => ({ ...current, pain: event.target.checked, painLevel: event.target.checked ? current.painLevel : "" }))} />{uiText("Есть боль", "I have pain")}</label>{draft.pain ? <label className="mt-3 grid gap-1 text-xs text-zinc-400"><span>{uiText("Уровень боли 0-10", "Pain level 0-10")}</span><Select value={draft.painLevel} onChange={(event) => setDraft((current) => ({ ...current, painLevel: event.target.value }))}><option value="">{uiText("Не указан", "Not specified")}</option>{scoreOptions.map((value) => <option key={value} value={value}>{value}</option>)}</Select></label> : null}</div>
        <label className="flex items-center gap-2 rounded-xl border border-zinc-800 bg-zinc-950/70 p-3 text-sm font-medium text-white"><input type="checkbox" checked={draft.illness} onChange={(event) => setDraft((current) => ({ ...current, illness: event.target.checked }))} />{uiText("Есть симптомы болезни", "I have illness symptoms")}</label>
      </div>
      <label className="grid gap-1 text-xs text-zinc-400"><span>{uiText("Комментарий, если нужен", "Optional note")}</span><Input value={draft.notes} maxLength={2000} placeholder={uiText("Например: тяжёлые ноги после вчерашней тренировки", "For example: heavy legs after yesterday's workout")} onChange={(event) => setDraft((current) => ({ ...current, notes: event.target.value }))} /></label>
      {error ? <p className="text-xs text-rose-300">{error}</p> : null}
      <div className="flex flex-wrap gap-2"><Button type="submit" disabled={saving}>{saving ? uiText("Сохраняем...", "Saving...") : uiText("Получить рекомендацию", "Get guidance")}</Button>{readiness?.checkin ? <Button type="button" variant="secondary" onClick={() => { setDraft(dailyDraft(readiness)); setEditing(false) }}>{uiText("Отмена", "Cancel")}</Button> : null}</div>
    </form> : recommendation ? <div className="grid gap-4 p-4 md:grid-cols-[minmax(0,1fr)_auto] md:items-start">
      <div className="min-w-0"><h3 className="text-lg font-semibold text-white">{recommendation.title}</h3><p className="mt-2 max-w-3xl text-sm leading-6 text-zinc-300">{recommendation.message}</p>{recommendation.prescribed_workout ? <p className="mt-3 rounded-xl border border-orange-400/20 bg-orange-400/10 p-3 text-sm text-orange-100">{recommendation.prescribed_workout.duration_seconds ? `${formatDuration(recommendation.prescribed_workout.duration_seconds)} · ` : ""}RPE {recommendation.prescribed_workout.rpe_range.join("-")} · {workoutIntensityLabel(recommendation.prescribed_workout.intensity)}</p> : null}<div className="mt-3 grid gap-1">{recommendation.reasons.map((reason) => <p key={reason} className="text-xs leading-5 text-zinc-500">• {reason}</p>)}</div><p className="mt-3 text-[11px] leading-5 text-zinc-600">{recommendation.disclaimer}</p></div>
      <div className="grid gap-2">{["shorten_easy", "easy_replacement"].includes(recommendation.action) && recommendation.workout_id === readiness?.today_workout?.id ? <Button disabled={previewingAction} onClick={previewAction}>{previewingAction ? uiText("Готовим preview...", "Preparing preview...") : uiText("Изменить тренировку", "Change workout")}</Button> : null}<Button variant="secondary" onClick={() => setEditing(true)}>{uiText("Изменить check-in", "Edit check-in")}</Button>{actionError && !actionPreview ? <p className="max-w-xs text-xs leading-5 text-rose-300">{actionError}</p> : null}</div>
    </div> : <div className="p-4 text-sm text-zinc-500">{uiText("Загружаем рекомендацию...", "Loading guidance...")}</div>}
    {actionPreview ? <ReadinessActionDialog preview={actionPreview} applying={applyingAction} error={actionError} onApply={applyAction} onClose={() => { setActionPreview(null); setActionError("") }} /> : null}
  </Card>
}

function signalClass(status?: string) {
  if (status === "risk" || status === "adjust" || status === "critical" || status === "at_risk" || status === "missed" || status === "strained" || status === "injured") return "border-rose-400/30 bg-rose-500/10 text-rose-200"
  if (status === "watch" || status === "warning" || status === "tired" || status === "below" || status === "above") return "border-orange-400/30 bg-orange-400/10 text-orange-200"
  if (status === "ok" || status === "active" || status === "done" || status === "on_track" || status === "completed" || status === "fresh" || status === "normal" || status === "within") return "border-zinc-700 bg-zinc-900 text-zinc-200"
  return "border-zinc-700 bg-zinc-900 text-zinc-400"
}

function signalStatusLabel(status?: string | null) {
  if (!status) return uiText("загрузка", "loading")
  if (status === "watch") return uiText("внимание", "watch")
  if (status === "warning") return uiText("предупреждение", "warning")
  if (status === "risk" || status === "critical" || status === "at_risk") return uiText("риск", "risk")
  if (status === "adjust") return uiText("нужна правка", "adjust")
  if (status === "ok" || status === "normal" || status === "within") return uiText("норма", "ok")
  if (status === "active") return uiText("активно", "active")
  if (status === "done" || status === "completed") return uiText("готово", "done")
  if (status === "missed") return uiText("пропущено", "missed")
  if (status === "planned") return uiText("запланировано", "planned")
  if (status === "fresh") return uiText("свежий", "fresh")
  if (status === "tired") return uiText("усталость", "tired")
  if (status === "strained") return uiText("перегруз", "strained")
  if (status === "injured") return uiText("травма", "injured")
  return status
}

function athleteSignalLabel(key: string, fallback: string) {
  const labels: Record<string, string> = {
    readiness: uiText("Самочувствие сегодня", "Daily readiness"),
    profile_safety: uiText("Ограничения профиля", "Profile safety"),
    recent_safety_reports: uiText("Боль и болезнь", "Pain and illness"),
    recent_feedback: uiText("Обратная связь", "Post-workout feedback"),
    execution_quality: uiText("Выполнение плана", "Execution quality"),
    weekly_adherence: uiText("Текущая неделя", "Weekly adherence"),
    training_load: uiText("Тренировочная нагрузка", "Training load"),
  }
  return labels[key] || fallback
}

function freshnessLabel(value: string) {
  const labels: Record<string, string> = {
    fresh: uiText("сегодня", "fresh"),
    current: uiText("актуально", "current"),
    aging: uiText("давность растет", "aging"),
    stale: uiText("устарело", "stale"),
    missing: uiText("нет данных", "missing"),
  }
  return labels[value] || value
}

function athleteConfidenceLabel(value: string) {
  const labels: Record<string, string> = {
    high: uiText("высокая уверенность", "high confidence"),
    medium: uiText("средняя уверенность", "medium confidence"),
    low: uiText("низкая уверенность", "low confidence"),
    none: uiText("нет оценки", "not assessed"),
  }
  return labels[value] || value
}

function athleteSignalPriority(signal: AthleteStateSignal) {
  return { risk: 0, watch: 1, unknown: 2, ok: 3 }[signal.status] ?? 4
}

function AthleteStateCard({ athleteState, error, onRetry }: { athleteState: AthleteState | null; error: string; onRetry: () => Promise<void> }) {
  if (error && !athleteState) return <Card className="grid gap-3 p-4 text-sm sm:grid-cols-[1fr_auto] sm:items-center"><div><p className="font-medium text-white">{uiText("Сводка состояния недоступна", "Athlete State unavailable")}</p><p className="mt-1 text-xs leading-5 text-zinc-500">{error}</p></div><Button size="sm" variant="secondary" onClick={() => void onRetry()}>{uiText("Повторить", "Retry")}</Button></Card>
  if (!athleteState) return <Card className="p-4 text-sm text-zinc-500">{uiText("Собираем объяснимую сводку состояния...", "Building your explainable athlete state...")}</Card>
  const signals = [...athleteState.signals].sort((left, right) => athleteSignalPriority(left) - athleteSignalPriority(right))
  const visible = signals.slice(0, 4)
  const evidenceCount = athleteState.signals.reduce((total, item) => total + item.source_refs.length, 0)
  return <Card className="overflow-hidden">
    <CardHeader className="border-b border-zinc-800">
      <div className="min-w-0"><p className="text-xs font-semibold text-orange-200">Athlete state</p><CardTitle className="mt-1">{athleteState.headline}</CardTitle><p className="mt-1 max-w-3xl text-xs leading-5 text-zinc-500">{athleteState.summary}</p></div>
      <Badge className={signalClass(athleteState.status)}>{signalStatusLabel(athleteState.status)}</Badge>
    </CardHeader>
    <div className="grid gap-3 p-4">
      {error ? <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-orange-400/20 bg-orange-400/10 p-3 text-xs text-orange-100"><span>{error} {uiText("Показан предыдущий снимок.", "Showing the previous snapshot.")}</span><Button size="sm" variant="secondary" onClick={() => void onRetry()}>{uiText("Повторить", "Retry")}</Button></div> : null}
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        {visible.map((item) => <div key={item.key} className={cn("min-w-0 rounded-xl border p-3", signalClass(item.status))}>
          <div className="flex flex-wrap items-start justify-between gap-2"><p className="text-xs font-semibold">{athleteSignalLabel(item.key, item.label)}</p><span className="font-mono text-[9px] uppercase tracking-[0.12em] opacity-70">{signalStatusLabel(item.status)}</span></div>
          <p className="mt-2 text-xs leading-5 text-zinc-300">{item.summary}</p>
          <p className="mt-2 text-[10px] leading-4 text-zinc-500">{freshnessLabel(item.freshness)} · {athleteConfidenceLabel(item.confidence)}</p>
        </div>)}
      </div>
      <CollapsibleSection title={uiText("Источники и ограничения", "Evidence and limitations")} summary={<Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{evidenceCount} {uiText("источников", "sources")}</Badge>}>
        <div className="grid gap-2 text-xs sm:grid-cols-2">
          {signals.map((item) => <div key={item.key} className="rounded-xl border border-zinc-800 bg-zinc-950/70 p-3"><div className="flex flex-wrap items-center justify-between gap-2"><p className="font-medium text-white">{athleteSignalLabel(item.key, item.label)}</p><span className="text-zinc-600">{item.source_refs.length} source refs</span></div><p className="mt-1 leading-5 text-zinc-500">{item.limitations[0] || uiText("Дополнительных ограничений нет.", "No additional limitation recorded.")}</p></div>)}
        </div>
        <p className="mt-3 text-[11px] leading-5 text-zinc-600">{athleteState.disclaimer} · {uiText("Снимок", "Snapshot")} #{athleteState.snapshot_id} · {athleteState.rule_version}</p>
      </CollapsibleSection>
    </div>
  </Card>
}

function formatDate(value?: string | null) {
  if (!value) return "--"
  return new Date(`${value}T00:00:00`).toLocaleDateString(languageLocale(), { day: "2-digit", month: "short" })
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

function WorkoutFocus({ todayWorkout, nextWorkout, currentWeek, activePlanTitle, onPlans, onImport }: { todayWorkout: PlanWorkout | null; nextWorkout: PlanWorkout | null; currentWeek: DashboardSummary["current_week"] | null; activePlanTitle: string | null; onPlans: () => void; onImport: () => void }) {
  const focus = todayWorkout || nextWorkout
  const isToday = Boolean(todayWorkout)
  return <Card className="overflow-hidden border-orange-400/30 bg-[radial-gradient(circle_at_top_left,rgba(251,146,60,0.18),transparent_34%),#0b0b0b]">
    <CardHeader className="border-orange-400/20 bg-orange-400/10"><div><CardTitle className="text-base">{isToday ? uiText("Карточка на сегодня", "Today's coach card") : uiText("Ближайший шаг", "Next step")}</CardTitle><p className="text-xs text-orange-100/80">{activePlanTitle ? uiText("Смотрите только то, что нужно сделать дальше.", "See only what to do next.") : uiText("План еще не выбран.", "No active plan yet.")}</p></div></CardHeader>
    {focus ? <div className="grid gap-4 p-4 text-sm md:grid-cols-[minmax(0,1fr)_16rem] md:items-end">
      <div className="min-w-0">
        <p className="text-2xl font-semibold tracking-tight text-white md:text-3xl">{coachWorkoutTitle(focus)}</p>
        <p className="mt-2 text-sm text-orange-100">{focus.scheduled_date ? formatLocalDate(focus.scheduled_date) : noDateLabel()} · {workoutIntensityLabel(focus.intensity)}</p>
        <div className="mt-4 grid gap-2 md:grid-cols-2">
          <div className="rounded-xl border border-orange-400/20 bg-black/20 p-3"><p className="text-[11px] font-semibold text-orange-100/70">{uiText("Зачем сегодня", "Why today")}</p><p className="mt-1 leading-6 text-zinc-200">{workoutPurpose(focus)}</p></div>
          <div className="rounded-xl border border-zinc-800 bg-zinc-950/70 p-3"><p className="text-[11px] font-semibold text-zinc-500">{uiText("Как не переборщить", "How to keep it easy enough")}</p><p className="mt-1 leading-6 text-zinc-300">{workoutSafetyNote(focus)}</p></div>
        </div>
      </div>
      <div className="grid gap-2">
        <Button className="w-full" onClick={onPlans}>{uiText("Открыть план", "Open plan")}</Button>
        <Button className="w-full" variant="secondary" onClick={onImport}>{uiText("Добавить выполненную тренировку", "Add completed workout")}</Button>
      </div>
    </div> : <div className="grid gap-3 p-4 text-sm text-zinc-400 md:grid-cols-[1fr_auto] md:items-center"><div><p className="font-semibold text-white">{uiText("Сегодня нет активной тренировки", "No active workout today")}</p><p className="mt-1 text-xs leading-5 text-zinc-500">{currentWeek?.message || uiText("Создайте программу или добавьте тренировку, чтобы Runforfan начал подсказывать следующий шаг.", "Create a plan or add a workout so Runforfan can suggest the next step.")}</p></div><div className="grid gap-2 sm:grid-cols-2 md:grid-cols-1"><Button onClick={onPlans}>{uiText("Создать план", "Create plan")}</Button><Button variant="secondary" onClick={onImport}>{uiText("Добавить тренировку", "Add workout")}</Button></div></div>}
  </Card>
}

function DashboardSignals({ dashboard }: { dashboard: DashboardSummary | null }) {
  const alerts = (dashboard?.alerts || []).filter((alert) => !/provider|llm|import|profile|engine|template/i.test(`${alert.title} ${alert.message} ${alert.action || ""}`)).slice(0, 2)
  const factors = dashboard?.readiness.factors || []
  const showSignals = alerts.length || (dashboard?.readiness.status && dashboard.readiness.status !== "ok")
  if (!showSignals) return null
  return <Card>
    <CardHeader><div><CardTitle>{uiText("Перед тренировкой", "Before your workout")}</CardTitle><p className="text-xs text-zinc-500">{uiText("Подсказки, которые помогут выбрать нагрузку или вовремя отдохнуть.", "Guidance to help you choose the right load or take a rest day.")}</p></div><Badge className={signalClass(dashboard?.readiness.status)}>{signalStatusLabel(dashboard?.readiness.status)}</Badge></CardHeader>
    <div className="grid gap-3 p-4 text-xs">
      <p className="leading-5 text-zinc-300">{readinessCoachMessage(dashboard?.readiness)}</p>
      <div className="grid gap-2">
        {alerts.map((alert) => <div key={`${alert.title}-${alert.message}`} className={cn("rounded-md border px-3 py-2", signalClass(alert.severity))}><p className="font-medium">{alert.severity === "critical" ? uiText("Лучше снизить нагрузку", "Reduce load") : uiText("Проверьте самочувствие", "Check how you feel")}</p><p className="mt-1 leading-5 text-zinc-300/90">{uiText("Если ощущение не обычное, сократите тренировку или перенесите ее.", "If things feel unusual, shorten or move the workout.")}</p></div>)}
      </div>
      {factors.length ? <CollapsibleSection title={uiText("Почему показали предупреждение", "Why this appeared")} summary={<Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{uiText("детали", "details")}</Badge>}><div className="grid gap-1">{factors.slice(0, 3).map((factor) => <p key={factor} className="rounded-md border border-zinc-800 bg-zinc-950 px-3 py-2 text-zinc-400">{safetyWarningLabel(factor)}</p>)}</div></CollapsibleSection> : null}
    </div>
  </Card>
}

function CurrentWeekCoachCard({ currentWeek, onPlans }: { currentWeek: DashboardSummary["current_week"]; onPlans: () => void }) {
  const adherence = currentWeek.adherence
  const total = adherence?.total_workouts ?? currentWeek.workouts.length
  const done = adherence?.done_workouts ?? currentWeek.workouts.filter((workout) => workout.status === "done").length
  const plannedDistance = adherence?.planned_distance_km ?? currentWeek.workouts.reduce((sum, workout) => sum + (workout.distance_km || 0), 0)
  const completedDistance = adherence?.completed_distance_km ?? currentWeek.workouts.reduce((sum, workout) => sum + (workout.actual_distance_km || 0), 0)
  const percent = Math.round((adherence?.completion_rate ?? (total ? done / total : 0)) * 100)
  const next = currentWeek.workouts.find((workout) => ["planned", "rescheduled"].includes(workout.status)) || currentWeek.workouts[0]
  return <Card className="p-4">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><p className="text-xs font-semibold text-orange-200">{uiText("Неделя", "Week")}</p><h3 className="mt-1 text-lg font-semibold text-white">{uiText("Как идет текущая неделя", "How this week is going")}</h3><p className="mt-1 text-xs text-zinc-500">{formatDate(currentWeek.week_start)} - {formatDate(currentWeek.week_end)}</p></div>
      <Button size="sm" variant="secondary" onClick={onPlans}>{uiText("В план", "Open plan")}</Button>
    </div>
    <div className="mt-4 h-2 overflow-hidden rounded-full bg-zinc-900"><div className="h-full rounded-full bg-orange-400" style={{ width: `${Math.min(100, Math.max(0, percent))}%` }} /></div>
    <div className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
      <Stat label={uiText("сделано", "done")} value={`${done}/${total}`} />
      <Stat label={uiText("план", "planned")} value={formatDistance(plannedDistance)} />
      <Stat label={uiText("факт", "actual")} value={formatDistance(completedDistance)} />
    </div>
    {next ? <div className="mt-3 rounded-xl border border-zinc-800 bg-zinc-950/70 p-3 text-xs"><p className="font-medium text-white">{uiText("Следующий шаг", "Next step")}: {coachWorkoutTitle(next)}</p><p className="mt-1 text-zinc-500">{next.scheduled_date ? formatLocalDate(next.scheduled_date) : noDateLabel()} · {workoutPurpose(next)}</p></div> : <p className="mt-3 text-xs text-zinc-500">{uiText("На этой неделе нет запланированных тренировок.", "There are no planned workouts this week.")}</p>}
  </Card>
}

function RecentRunsCard({ activities, onImport }: { activities: ActivityType[]; onImport?: () => void }) {
  return <Card className="p-4">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><p className="text-xs font-semibold text-orange-200">{uiText("История", "History")}</p><h3 className="mt-1 text-lg font-semibold text-white">{uiText("Последние тренировки", "Recent workouts")}</h3><p className="mt-1 text-xs text-zinc-500">{uiText("Дата, длительность и основные показатели.", "Date, duration and key metrics.")}</p></div>
      {onImport ? <Button size="sm" variant="secondary" onClick={onImport}>{uiText("Добавить тренировку", "Add workout")}</Button> : null}
    </div>
    <div className="mt-4 grid gap-2">
      {activities.slice(0, 3).map((activity) => <div key={activity.id} className="grid gap-2 rounded-xl border border-zinc-800 bg-zinc-950/70 p-3 text-xs md:grid-cols-[1fr_auto] md:items-center">
        <div><p className="font-medium text-white">{runKindLabel(activity)} · {activity.started_at ? formatLocalDate(activity.started_at) : noDateLabel()}</p><p className="mt-1 text-zinc-500">{formatDistance(activity.distance_km)} · {formatDuration(activity.duration_seconds)} · {formatPace(activity.average_pace_seconds_per_km)}{perKmUnit()}</p></div>
        {activity.average_heart_rate_bpm ? <Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{activity.average_heart_rate_bpm} {uiText("уд/мин", "bpm")}</Badge> : <Badge className="border-zinc-800 bg-zinc-950 text-zinc-500">{uiText("без пульса", "no heart rate")}</Badge>}
      </div>)}
      {!activities.length ? <p className="rounded-xl border border-zinc-800 bg-zinc-950/70 p-3 text-xs text-zinc-500">{uiText("Тренировок пока нет. Добавьте первую со скриншотов или вручную.", "No workouts yet. Add the first one from screenshots or manually.")}</p> : null}
    </div>
  </Card>
}

function CurrentWeekCard({ currentWeek, onPlans }: { currentWeek: DashboardSummary["current_week"]; onPlans: () => void }) {
  const adherence = currentWeek.adherence
  return <Card>
    <CardHeader><div><CardTitle>{uiText("Неделя в плане", "Plan this week")}</CardTitle><p className="text-xs text-zinc-500" translate="no">{currentWeek.plan_title || uiText("Нет активного плана", "No active plan")} · {formatDate(currentWeek.week_start)} - {formatDate(currentWeek.week_end)}</p></div><div className="flex items-center gap-2"><Badge className={signalClass(currentWeek.status)}>{signalStatusLabel(currentWeek.status)}</Badge><Button size="sm" variant="secondary" onClick={onPlans}>{uiText("План", "Plan")}</Button></div></CardHeader>
    <div className="grid gap-3 border-t border-zinc-800 p-4 text-xs md:grid-cols-4">
      <Stat label={uiText("тренировок", "workouts")} value={adherence?.total_workouts ?? 0} />
      <Stat label={uiText("сделано", "done")} value={adherence?.done_workouts ?? 0} />
      <Stat label={uiText("план", "planned")} value={formatDistance(adherence?.planned_distance_km)} />
      <Stat label={uiText("факт", "actual")} value={formatDistance(adherence?.completed_distance_km)} />
    </div>
    <div className="grid gap-2 p-4">
      {currentWeek.workouts.map((workout) => <div key={`mobile-${workout.id}`} className="rounded-md border border-zinc-800 bg-zinc-950 p-3 text-xs">
        <div className="flex items-start justify-between gap-2"><div className="min-w-0"><p className="truncate font-medium text-white" translate="no">{workout.title}</p><p className="mt-1 text-zinc-500">{formatDate(workout.scheduled_date)} · {workoutTypeLabel(workout.workout_type)} · {workoutIntensityLabel(workout.intensity)}</p></div><Badge className={signalClass(workout.status)}>{workoutStatusLabel(workout.status)}</Badge></div>
        <div className="mt-3 grid grid-cols-2 gap-2 text-center"><Stat label={uiText("цель", "target")} value={formatWorkoutTarget(workout)} /><Stat label={uiText("факт", "actual")} value={formatWorkoutActual(workout)} /></div>
        <p className="mt-2 rounded-md border border-zinc-900 bg-zinc-950/70 px-2 py-1.5 text-[11px] leading-5 text-zinc-400">{workoutPurpose(workout)}</p>
      </div>)}
      {!currentWeek.workouts.length && <p className="text-xs text-zinc-500">No workouts in the current calendar week.</p>}
    </div>
  </Card>
}

function Stat({ label, value, suffix }: { label: string; value: string | number; suffix?: string }) {
  return <div className="px-4 py-3 text-center"><strong className="block text-base leading-tight text-white md:text-lg" translate="no">{value}{suffix ? ` ${suffix}` : ""}</strong><span className="text-[11px] font-medium text-zinc-500" data-i18n-ui>{label}</span></div>
}

function CollapsibleSection({ title, summary, defaultOpen = false, children, className }: { title: string; summary?: ReactNode; defaultOpen?: boolean; children: ReactNode; className?: string }) {
  const [isOpen, setIsOpen] = useState(defaultOpen)
  useEffect(() => { if (defaultOpen) setIsOpen(true) }, [defaultOpen])

  return <details open={isOpen} onToggle={(event) => setIsOpen(event.currentTarget.open)} className={cn("group rounded-md border border-zinc-800 bg-zinc-950/70", className)}>
    <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 px-3 py-2 text-xs font-semibold text-white [&::-webkit-details-marker]:hidden">
      <span>{title}</span>
      <span className="flex items-center gap-2 text-[10px] font-normal uppercase tracking-[0.14em] text-zinc-500">{summary}<span className="text-orange-300 group-open:hidden">{uiText("открыть", "open")}</span><span className="hidden text-zinc-500 group-open:inline">{uiText("скрыть", "hide")}</span></span>
    </summary>
    <div hidden={!isOpen} className="border-t border-zinc-800 p-3">{children}</div>
  </details>
}

function ResponsiveDetailPanel({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return <div className="fixed inset-0 z-50 bg-black/80 p-2 md:static md:bg-transparent md:p-0">
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-lg border border-orange-400/30 bg-zinc-950 md:block md:h-auto md:overflow-visible md:rounded-none md:border-0 md:bg-transparent">
      <div className="flex items-center justify-between border-b border-zinc-800 px-3 py-2 md:hidden"><p className="text-sm font-semibold text-white">{title}</p><Button size="sm" variant="ghost" onClick={onClose}>{uiText("Закрыть", "Close")}</Button></div>
      <div className="min-h-0 overflow-y-auto p-2 md:overflow-visible md:p-0">{children}</div>
    </div>
  </div>
}

function Activities({ activities, compact = false, onImport, onChanged }: { activities: ActivityType[]; compact?: boolean; onImport?: () => void; onChanged?: () => Promise<void> }) {
  const [detail, setDetail] = useState<ActivityType | null>(null)
  const [validation, setValidation] = useState<ActivityValidation | null>(null)
  const [detailError, setDetailError] = useState("")
  const [detailLoading, setDetailLoading] = useState(false)
  const [manualBusy, setManualBusy] = useState(false)
  const [manualMessage, setManualMessage] = useState("")
  const detailRequestId = useRef(0)

  async function openActivityDetail(activityId: number) {
    const requestId = detailRequestId.current + 1
    detailRequestId.current = requestId
    setDetail(activities.find((activity) => activity.id === activityId) || null)
    setValidation(null)
    setDetailError("")
    setDetailLoading(true)
    try {
      await devLogin()
      const [nextActivity, nextValidation] = await Promise.all([api.activity(activityId), api.activityValidation(activityId)])
      if (detailRequestId.current !== requestId) return
      setDetail(nextActivity)
      setValidation(nextValidation)
    } catch (error) {
      if (detailRequestId.current !== requestId) return
      console.error(error)
      setDetailError(error instanceof Error ? error.message : "Не удалось загрузить detail")
    } finally {
      if (detailRequestId.current === requestId) setDetailLoading(false)
    }
  }

  function closeActivityDetail() {
    detailRequestId.current += 1
    setDetail(null)
    setValidation(null)
    setDetailError("")
    setDetailLoading(false)
  }

  async function createManualActivity(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const payload = activityWritePayload(event.currentTarget)
    if (!payload.duration_seconds) {
      setManualMessage("Duration is required for manual activity.")
      return
    }
    setManualBusy(true)
    setManualMessage("")
    try {
      await devLogin()
      const created = await api.createActivity(payload)
      setManualMessage(`Created activity #${created.id}. Pace and speed were derived from distance/time when available.`)
      event.currentTarget.reset()
      setDetail(created)
      setValidation(await api.activityValidation(created.id))
      await onChanged?.()
    } catch (error) {
      setManualMessage(apiErrorMessage(error, "Failed to create manual activity"))
    } finally {
      setManualBusy(false)
    }
  }

  async function updateActivity(activityId: number, payload: Record<string, unknown>) {
    setDetailLoading(true)
    setDetailError("")
    try {
      await devLogin()
      const updated = await api.updateActivity(activityId, payload)
      const nextValidation = await api.activityValidation(activityId)
      setDetail(updated)
      setValidation(nextValidation)
      await onChanged?.()
      return updated
    } catch (error) {
      const message = apiErrorMessage(error, "Не удалось обновить activity")
      setDetailError(message)
      throw error
    } finally {
      setDetailLoading(false)
    }
  }

  if (!compact) {
    const activityColumns: DataTableColumn<ActivityType>[] = [
      { key: "name", header: uiText("Тренировка", "Workout"), sortValue: (activity) => activity.started_at ? Date.parse(activity.started_at) : 0, cell: (activity) => {
        const summary = workoutBlockSummary(activity)
        return <div className="font-medium text-white">{activity.title}<div className="text-[11px] text-zinc-500">{activity.started_at ? formatLocalDateTime(activity.started_at) : noDateLabel()}</div>{summary && <div className="mt-1 flex items-center gap-2"><Badge>interval</Badge><span className="text-[11px] text-orange-300">{summary}</span></div>}</div>
      } },
      { key: "distance", header: uiText("Дистанция", "Distance"), sortValue: (activity) => activity.distance_km || 0, cell: (activity) => <>{formatDistance(activity.distance_km)}<div className="text-[11px] text-zinc-500">{formatDuration(activity.duration_seconds)}</div></> },
      { key: "pace", header: uiText("Темп", "Pace"), sortValue: (activity) => activity.average_pace_seconds_per_km || 99999, cell: (activity) => {
        const derived = primaryActivityMetrics(activity)
        return <>{formatPace(activity.average_pace_seconds_per_km)}{perKmUnit()}{derived.length ? <div className="mt-1 flex flex-wrap gap-1">{derived.slice(0, 2).map((metric) => <Badge key={metric.metric_key} className="border-zinc-700 bg-zinc-900 text-zinc-300">{activityMetricLabel(metric.metric_key)} {formatActivityMetric(metric)}</Badge>)}</div> : null}</>
      } },
      { key: "hr", header: uiText("Пульс", "Heart rate"), sortValue: (activity) => activity.average_heart_rate_bpm || 0, cell: (activity) => activity.average_heart_rate_bpm || "--" },
      { key: "structure", header: uiText("Состав", "Structure"), sortValue: (activity) => activity.workout_blocks?.length || activity.segments.length || 0, cell: (activity) => {
        const summary = workoutBlockSummary(activity)
        return <>{summary || splitCountLabel(activity.segments.length)}{activity.workout_blocks?.length ? <div className="mt-1 text-[11px] text-zinc-500">{blockCountLabel(activity.workout_blocks.length)}</div> : null}{activity.derived_metrics?.length ? <div className="mt-1 text-[11px] text-orange-300">{derivedMetricCountLabel(activity.derived_metrics.length)}</div> : null}</>
      } },
      { key: "id", header: "ID", sortValue: (activity) => activity.id, cell: (activity) => <span className="font-mono text-zinc-500">#{activity.id}</span> },
      { key: "detail", header: uiText("Подробнее", "Details"), cell: (activity) => <Button size="sm" variant="secondary" onClick={() => void openActivityDetail(activity.id)}>{uiText("Открыть", "Open")}</Button> },
    ]
    return <Card>
      <CardHeader><div><CardTitle>{uiText("История тренировок", "Workout history")}</CardTitle><p className="text-xs text-zinc-500">{activities.length} {uiText("всего", "total")}</p></div><Button size="sm" onClick={onImport}>{uiText("Добавить тренировку", "Add workout")}</Button></CardHeader>
      <CollapsibleSection title={uiText("Добавить вручную", "Add manually")} summary={<Badge>{uiText("без скриншотов", "without screenshots")}</Badge>} className="mx-4 mt-4 md:mx-0 md:mt-0 md:rounded-none md:border-x-0 md:border-b-0">
      <form onSubmit={createManualActivity} className="grid gap-3 text-xs md:grid-cols-6">
        <Field label={uiText("Название", "Title")}><Input name="title" placeholder={uiText("Например, утренняя тренировка", "For example, morning workout")} /></Field>
        <Field label={uiText("Дата и время", "Date and time")}><Input name="started_at" type="datetime-local" /></Field>
        <Field label={uiText("Тип", "Type")}><Select name="activity_type"><option value="manual_workout">{uiText("тренировка", "workout")}</option><option value="outdoor_run">{uiText("бег на улице", "outdoor run")}</option><option value="treadmill_run">{uiText("беговая дорожка", "treadmill run")}</option><option value="manual_strength">{uiText("силовая тренировка", "strength workout")}</option></Select></Field>
        <Field label={uiText("Дистанция, км", "Distance, km")}><Input name="distance_km" type="number" step="0.01" placeholder="5.0" /></Field>
        <Field label={uiText("Длительность, мин", "Duration, min")}><Input name="duration_minutes" type="number" step="1" min="1" required placeholder="30" /></Field>
        <Field label={uiText("Средний пульс", "Average heart rate")}><Input name="average_heart_rate_bpm" type="number" step="1" placeholder="145" /></Field>
        <div className="md:col-span-5"><Field label={uiText("Комментарий", "Note")}><Input name="source_note" placeholder={uiText("Например, часы не записали тренировку", "For example, the watch did not record it")} /></Field></div>
        <div className="flex items-end"><Button type="submit" size="sm" disabled={manualBusy}>{uiText("Добавить", "Add")}</Button></div>
        {manualMessage ? <p className="md:col-span-6 rounded-md border border-zinc-800 bg-zinc-950 px-3 py-2 text-zinc-300" translate="no">{manualMessage}</p> : null}
      </form>
      </CollapsibleSection>
      <DataTable
        rows={activities}
        columns={activityColumns}
        getRowKey={(activity) => activity.id}
        getSearchText={(activity) => `${activity.title} ${activity.id} ${activity.started_at || ""}`}
        filterPlaceholder={uiText("Поиск по названию или дате", "Search by title or date")}
        emptyState={<div className="flex flex-wrap items-center gap-3"><span>{uiText("Тренировки не найдены.", "No workouts found.")}</span><Button size="sm" variant="secondary" onClick={onImport}>{uiText("Добавить тренировку", "Add workout")}</Button></div>}
        mobileCard={(activity) => {
          const summary = workoutBlockSummary(activity)
          const derived = primaryActivityMetrics(activity)
          return <div className="rounded-md border border-zinc-800 bg-zinc-950 p-3 text-xs">
            <div className="flex items-start justify-between gap-2"><div className="min-w-0"><p className="truncate font-medium text-white" translate="no">{activity.title}</p><p className="mt-1 text-[11px] text-zinc-500">{activity.started_at ? formatLocalDateTime(activity.started_at) : noDateLabel()}</p></div><Badge className="font-mono text-zinc-400">#{activity.id}</Badge></div>
            <div className="mt-3 grid grid-cols-3 gap-2 text-center"><Stat label="distance" value={formatDistance(activity.distance_km)} /><Stat label="pace" value={`${formatPace(activity.average_pace_seconds_per_km)}${perKmUnit()}`} /><Stat label="hr" value={activity.average_heart_rate_bpm || "--"} /></div>
            <div className="mt-2 flex flex-wrap items-center gap-1.5">{summary ? <Badge>interval</Badge> : null}<Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{summary || splitCountLabel(activity.segments.length)}</Badge>{derived.slice(0, 1).map((metric) => <Badge key={metric.metric_key} className="border-zinc-700 bg-zinc-900 text-zinc-300">{activityMetricLabel(metric.metric_key)} {formatActivityMetric(metric)}</Badge>)}</div>
            <Button className="mt-3 w-full" size="sm" variant="secondary" onClick={() => void openActivityDetail(activity.id)}>{uiText("Подробнее", "Details")}</Button>
          </div>
        }}
      />
      {detail ? <ResponsiveDetailPanel title={uiText("Детали тренировки", "Workout details")} onClose={closeActivityDetail}><ActivityDetailPanel activity={detail} validation={validation} loading={detailLoading} error={detailError} onClose={closeActivityDetail} onRefresh={() => void openActivityDetail(detail.id)} onUpdate={updateActivity} /></ResponsiveDetailPanel> : null}
      {activities.some((activity) => activity.workout_blocks?.length) && <CollapsibleSection title="Interval structures" summary={<Badge>{activities.filter((activity) => activity.workout_blocks?.length).length}</Badge>} className="mx-4 mb-4"><div className="grid gap-3 lg:grid-cols-2">
        {activities.filter((activity) => activity.workout_blocks?.length).map((activity) => <div key={`blocks-${activity.id}`} className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-3">
          <div className="mb-2 flex items-start justify-between gap-3"><div className="min-w-0"><p className="break-words text-sm font-medium text-white" translate="no">{activity.title}</p><p className="text-[11px] text-zinc-500">Интервальная структура</p></div><Badge className="shrink-0" translate="no">{workoutBlockSummary(activity) || "blocks"}</Badge></div>
          <div className="grid gap-1" translate="no">{activity.workout_blocks.map((block) => <div key={block.id} className="grid grid-cols-2 gap-x-2 gap-y-1 rounded-md bg-zinc-900/60 px-2 py-1.5 text-[11px] sm:grid-cols-[minmax(5rem,1fr)_auto_auto_auto] sm:items-center"><span className={cn("min-w-0 break-words font-medium", block.block_type === "work" ? "text-orange-300" : "text-zinc-400")}>{block.title}</span><span className="text-right text-zinc-500 sm:text-left">{formatDuration(block.duration_seconds)}</span><span>{formatDistance(block.distance_km)}</span><span className="text-right sm:text-left">{formatPace(block.pace_seconds_per_km)}{perKmUnit()}</span></div>)}</div>
        </div>)}
      </div></CollapsibleSection>}
    </Card>
  }
  return <Card>
    <CardHeader><div><CardTitle>{uiText("Тренировки", "Workouts")}</CardTitle><p className="text-xs text-zinc-500">{activities.length} {uiText("всего", "total")}</p></div><Button size="sm" onClick={onImport}>{uiText("Добавить тренировку", "Add workout")}</Button></CardHeader>
    <div className="grid gap-2 p-4 md:hidden">
      {activities.slice(0, compact ? 6 : undefined).map((activity) => {
        const summary = workoutBlockSummary(activity)
        const derived = primaryActivityMetrics(activity)
        return <div key={`compact-mobile-${activity.id}`} className="rounded-md border border-zinc-800 bg-zinc-950 p-3 text-xs">
          <div className="flex items-start justify-between gap-2"><div className="min-w-0"><p className="truncate font-medium text-white" translate="no">{activity.title}</p><p className="mt-1 text-[11px] text-zinc-500">{activity.started_at ? formatLocalDateTime(activity.started_at) : noDateLabel()}</p></div><Badge className="font-mono text-zinc-400" translate="no">#{activity.id}</Badge></div>
          <div className="mt-3 grid grid-cols-3 gap-2 text-center"><Stat label="distance" value={formatDistance(activity.distance_km)} /><Stat label="pace" value={`${formatPace(activity.average_pace_seconds_per_km)}${perKmUnit()}`} /><Stat label="hr" value={activity.average_heart_rate_bpm || "--"} /></div>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">{summary ? <Badge>interval</Badge> : null}<Badge className="border-zinc-700 bg-zinc-900 text-zinc-300" translate="no">{summary || splitCountLabel(activity.segments.length)}</Badge>{derived.slice(0, 1).map((metric) => <Badge key={metric.metric_key} className="border-zinc-700 bg-zinc-900 text-zinc-300" translate="no">{activityMetricLabel(metric.metric_key)} {formatActivityMetric(metric)}</Badge>)}</div>
        </div>
      })}
      {!activities.length ? <p className="text-xs text-zinc-500">{uiText("Тренировок пока нет.", "No workouts yet.")}</p> : null}
    </div>
    <div className="hidden overflow-x-auto md:block">
      <table className="w-full min-w-[720px] text-left text-xs">
        <thead className="border-b border-zinc-800 text-[10px] uppercase tracking-[0.14em] text-zinc-500"><tr><th className="px-4 py-2">Name</th><th>Distance</th><th>Pace</th><th>HR</th><th>Structure</th><th>ID</th></tr></thead>
        <tbody>{activities.slice(0, compact ? 6 : undefined).map((activity) => {
          const summary = workoutBlockSummary(activity)
          const derived = primaryActivityMetrics(activity)
          return <tr key={activity.id} className="border-b border-zinc-900 last:border-0 align-top hover:bg-zinc-900/60"><td className="px-4 py-3 font-medium text-white">{activity.title}<div className="text-[11px] text-zinc-500">{activity.started_at ? formatLocalDateTime(activity.started_at) : noDateLabel()}</div>{summary && <div className="mt-1 flex items-center gap-2"><Badge>interval</Badge><span className="text-[11px] text-orange-300">{summary}</span></div>}</td><td>{formatDistance(activity.distance_km)}<div className="text-[11px] text-zinc-500">{formatDuration(activity.duration_seconds)}</div></td><td>{formatPace(activity.average_pace_seconds_per_km)}{perKmUnit()}{derived.length ? <div className="mt-1 flex flex-wrap gap-1">{derived.slice(0, 2).map((metric) => <Badge key={metric.metric_key} className="border-zinc-700 bg-zinc-900 text-zinc-300">{activityMetricLabel(metric.metric_key)} {formatActivityMetric(metric)}</Badge>)}</div> : null}</td><td>{activity.average_heart_rate_bpm || "--"}</td><td>{summary || splitCountLabel(activity.segments.length)}{activity.workout_blocks?.length ? <div className="mt-1 text-[11px] text-zinc-500">{blockCountLabel(activity.workout_blocks.length)}</div> : null}{activity.derived_metrics?.length ? <div className="mt-1 text-[11px] text-orange-300">{derivedMetricCountLabel(activity.derived_metrics.length)}</div> : null}</td><td className="font-mono text-zinc-500">#{activity.id}</td></tr>
        })}</tbody>
      </table>
    </div>
    {!compact && activities.some((activity) => activity.workout_blocks?.length) && <div className="grid gap-3 border-t border-zinc-800 p-4 lg:grid-cols-2">
      {activities.filter((activity) => activity.workout_blocks?.length).map((activity) => <div key={`blocks-${activity.id}`} className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-3">
        <div className="mb-2 flex items-start justify-between gap-3"><div className="min-w-0"><p className="break-words text-sm font-medium text-white" translate="no">{activity.title}</p><p className="text-[11px] text-zinc-500">Интервальная структура</p></div><Badge className="shrink-0" translate="no">{workoutBlockSummary(activity) || "blocks"}</Badge></div>
        <div className="grid gap-1" translate="no">{activity.workout_blocks.map((block) => <div key={block.id} className="grid grid-cols-2 gap-x-2 gap-y-1 rounded-md bg-zinc-900/60 px-2 py-1.5 text-[11px] sm:grid-cols-[minmax(5rem,1fr)_auto_auto_auto] sm:items-center"><span className={cn("min-w-0 break-words font-medium", block.block_type === "work" ? "text-orange-300" : "text-zinc-400")}>{block.title}</span><span className="text-right text-zinc-500 sm:text-left">{formatDuration(block.duration_seconds)}</span><span>{formatDistance(block.distance_km)}</span><span className="text-right sm:text-left">{formatPace(block.pace_seconds_per_km)}{perKmUnit()}</span></div>)}</div>
      </div>)}
    </div>}
  </Card>
}

function ActivityDetailPanel({ activity, validation, loading, error, onClose, onRefresh, onUpdate }: { activity: ActivityType; validation: ActivityValidation | null; loading: boolean; error: string; onClose: () => void; onRefresh: () => void; onUpdate: (activityId: number, payload: Record<string, unknown>) => Promise<ActivityType> }) {
  const derived = [...(activity.derived_metrics || [])].sort((left, right) => left.metric_key.localeCompare(right.metric_key))
  const segments = [...(activity.segments || [])].sort((left, right) => left.segment_index - right.segment_index)
  const workoutBlocks = [...(activity.workout_blocks || [])].sort((left, right) => left.block_index - right.block_index)
  const sources = activity.sources || []
  const validationChecks = validation?.checks || []
  const warnings = validation?.issues || []
  const [editMessage, setEditMessage] = useState("")

  async function submitEdit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setEditMessage("")
    const payload = activityWritePayload(event.currentTarget)
    if (!payload.duration_seconds) {
      setEditMessage("Duration is required.")
      return
    }
    try {
      const updated = await onUpdate(activity.id, payload)
      setEditMessage(`Saved #${updated.id}. Derived metrics and load were recalculated.`)
    } catch (caught) {
      setEditMessage(apiErrorMessage(caught, "Failed to save activity"))
    }
  }

  return <Card className="border-orange-400/25 bg-zinc-950/70">
    <CardHeader>
      <div className="min-w-0">
        <CardTitle>{uiText("Детали тренировки", "Workout details")}</CardTitle>
        <p className="mt-1 truncate text-xs text-zinc-500" translate="no">{activity.title} · #{activity.id} · {activity.started_at ? formatLocalDateTime(activity.started_at) : noDateLabel()}</p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Badge className={signalClass(validation?.status)}>{loading ? "loading" : validation?.status || "validation"}</Badge>
        <Button size="sm" variant="secondary" onClick={onRefresh} disabled={loading}>{uiText("Обновить", "Refresh")}</Button>
        <Button size="sm" variant="ghost" onClick={onClose}>{uiText("Закрыть", "Close")}</Button>
      </div>
    </CardHeader>
    <div className="grid gap-4 border-t border-zinc-800 p-4 text-xs">
      {error ? <div className="rounded-md border border-orange-400/20 bg-orange-400/10 px-3 py-2 text-orange-100" translate="no">{error}</div> : null}
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="distance" value={formatDistance(activity.distance_km)} hint={activity.activity_type} />
        <MetricCard label="duration" value={formatDuration(activity.duration_seconds)} hint={activity.started_at ? formatLocalDate(activity.started_at) : noDateLabel()} />
        <MetricCard label="weighted pace" value={validation?.weighted_pace_seconds_per_km ? `${formatPace(validation.weighted_pace_seconds_per_km)}${perKmUnit()}` : `${formatPace(activity.average_pace_seconds_per_km)}${perKmUnit()}`} hint={validation?.weighted_pace_seconds_per_km ? "from segments" : "imported activity pace"} explainer={<CalculationExplainer><p>Segment-weighted pace uses sum(duration_seconds) / sum(distance_km). If segments are missing, imported activity pace is shown.</p></CalculationExplainer>} />
        <MetricCard label="training load" value={activity.aerobic_training_stress ?? primaryActivityMetrics(activity).find((metric) => metric.metric_key === "training_load_proxy")?.metric_value?.toFixed(0) ?? "--"} hint={activity.aerobic_training_stress ? "imported ATS" : "derived proxy when available"} />
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <Stat label="avg hr" value={activity.average_heart_rate_bpm ? `${activity.average_heart_rate_bpm} bpm` : "--"} />
        <Stat label="cadence" value={activity.average_cadence_spm ? `${activity.average_cadence_spm} spm` : "--"} />
        <Stat label="elevation" value={activity.elevation_gain_m || activity.elevation_loss_m ? `+${activity.elevation_gain_m || 0} / -${activity.elevation_loss_m || 0} m` : "--"} />
        <Stat label="sources" value={`${sources.length || validation?.source_counts.screenshots || 0} screenshots`} />
      </div>

      <CollapsibleSection title="Quick edit" summary={<Badge>manual correction</Badge>}>
      <form key={`${activity.id}-${activity.title}-${activity.activity_type}-${activity.started_at || ""}-${activity.distance_km || ""}-${activity.duration_seconds}-${activity.average_heart_rate_bpm || ""}-${activity.source_note || ""}`} onSubmit={submitEdit} className="grid gap-3 text-xs md:grid-cols-6">
        <div className="md:col-span-6 flex flex-wrap items-center justify-between gap-2"><div><p className="font-semibold text-white">Quick edit</p><p className="mt-1 text-zinc-500">Manual corrections recalculate pace, speed, derived metrics and daily load.</p></div><Badge>manual correction</Badge></div>
        <Field label="Title"><Input name="title" defaultValue={activity.title} /></Field>
        <Field label="Started"><Input name="started_at" type="datetime-local" step="1" defaultValue={datetimeLocalValue(activity.started_at)} /></Field>
        <Field label="Type"><Select name="activity_type" defaultValue={activity.activity_type}><option value="manual_workout">manual workout</option><option value="outdoor_run">outdoor run</option><option value="treadmill_run">treadmill run</option><option value="manual_strength">strength</option></Select></Field>
        <Field label="Distance km"><Input name="distance_km" type="number" step="0.01" defaultValue={activity.distance_km?.toString() || ""} /></Field>
        <Field label="Duration sec"><Input name="duration_seconds" type="number" step="1" min="60" required defaultValue={activityDurationSeconds(activity)} /></Field>
        <Field label="Avg HR"><Input name="average_heart_rate_bpm" type="number" step="1" defaultValue={activity.average_heart_rate_bpm?.toString() || ""} /></Field>
        <div className="md:col-span-5"><Field label="Source note"><Input name="source_note" defaultValue={activity.source_note || ""} /></Field></div>
        <div className="flex items-end"><Button type="submit" size="sm" variant="secondary" disabled={loading}>Save edit</Button></div>
        {editMessage ? <p className="md:col-span-6 rounded-md border border-zinc-800 bg-zinc-900 px-3 py-2 text-zinc-300" translate="no">{editMessage}</p> : null}
      </form>
      </CollapsibleSection>

      <div className="grid gap-2 rounded-lg border border-zinc-800 bg-zinc-950 p-3">
        <div className="flex flex-wrap items-center justify-between gap-2"><div><p className="font-semibold text-white">Validation report</p><p className="mt-1 text-zinc-500">Data quality checks for pace, segments, blocks and physiological ranges.</p></div><Badge className={signalClass(validation?.status)}>{warnings.length} warnings</Badge></div>
        {validationChecks.length ? <div className="grid gap-2">
          {validationChecks.map((check) => <div key={`${check.code}-${check.metric || "metric"}`} className={cn("rounded-md border px-3 py-2", check.severity === "warning" ? "border-orange-400/25 bg-orange-400/10 text-orange-100" : "border-zinc-800 bg-zinc-900 text-zinc-300")} translate="no">
            <div className="flex flex-wrap items-center justify-between gap-2"><p className="font-medium">{check.message}</p><Badge className={signalClass(check.severity)}>{check.severity}</Badge></div>
            <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.14em] text-zinc-500">{check.code} · expected {formatValidationValue(check.expected, check.unit)} · actual {formatValidationValue(check.actual, check.unit)}</p>
          </div>)}
        </div> : loading && !validation ? <p className="rounded-md border border-zinc-800 bg-zinc-900 px-3 py-2 text-zinc-500">Loading validation checks...</p> : !validation ? <p className="rounded-md border border-orange-400/20 bg-orange-400/10 px-3 py-2 text-orange-100">Validation report is unavailable for this activity.</p> : <p className="rounded-md border border-zinc-800 bg-zinc-900 px-3 py-2 text-zinc-500">No validation issues detected for loaded data.</p>}
      </div>

      <CollapsibleSection title="Recognition sources" summary={<Badge>{sources.length} sources</Badge>}>
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2"><div><p className="font-semibold text-white">Recognition sources</p><p className="mt-1 text-zinc-500">Safe screenshot metadata linked to this activity; local file paths are not exposed.</p></div><Badge>{sources.length} sources</Badge></div>
        {sources.length ? <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
          {sources.map((source) => <div key={source.source_id} className="rounded-md border border-zinc-800 bg-zinc-900 px-3 py-2" translate="no">
            <p className="font-medium text-white">{source.file_name || `source #${source.source_id}`}</p>
            <p className="mt-1 text-[11px] text-zinc-500">#{source.source_id} · {source.source_app || "unknown app"} · {source.screen_type || "screenshot"}</p>
            <p className="mt-1 text-[11px] text-zinc-500">captured {source.captured_at ? formatLocalDateTime(source.captured_at) : "unknown"} · uploaded {source.uploaded_at ? formatLocalDateTime(source.uploaded_at) : "unknown"}</p>
            {source.notes ? <p className="mt-2 text-[11px] text-zinc-400">{source.notes}</p> : null}
          </div>)}
        </div> : <p className="text-zinc-500">No linked screenshot sources for this activity.</p>}
      </CollapsibleSection>

      <CollapsibleSection title="Splits and workout blocks" summary={<Badge>{segments.length + workoutBlocks.length} rows</Badge>}>
      <div className="grid gap-4 xl:grid-cols-2">
        <div className="overflow-x-auto rounded-lg border border-zinc-800">
          <table className="w-full min-w-[560px] text-left text-xs">
            <thead className="border-b border-zinc-800 text-[10px] uppercase tracking-[0.14em] text-zinc-500"><tr><th className="px-3 py-2">Split</th><th>Distance</th><th>Time</th><th>Pace</th><th>HR</th><th>Cadence</th></tr></thead>
            <tbody>{segments.map((segment) => <tr key={segment.id} className="border-b border-zinc-900 last:border-0"><td className="px-3 py-2 font-mono text-zinc-500">#{segment.segment_index}</td><td>{formatDistance(segment.distance_km)}</td><td>{formatDuration(segment.duration_seconds)}</td><td>{formatPace(segment.pace_seconds_per_km)}{perKmUnit()}</td><td>{segment.average_heart_rate_bpm || "--"}</td><td>{segment.average_cadence_spm || "--"}</td></tr>)}</tbody>
          </table>
          {!segments.length ? <p className="p-3 text-zinc-500">No split rows.</p> : null}
        </div>
        <div className="overflow-x-auto rounded-lg border border-zinc-800">
          <table className="w-full min-w-[560px] text-left text-xs">
            <thead className="border-b border-zinc-800 text-[10px] uppercase tracking-[0.14em] text-zinc-500"><tr><th className="px-3 py-2">Block</th><th>Type</th><th>Distance</th><th>Time</th><th>Pace</th><th>HR</th></tr></thead>
            <tbody>{workoutBlocks.map((block) => <tr key={block.id} className="border-b border-zinc-900 last:border-0"><td className="px-3 py-2 font-medium text-white">{block.title}</td><td><Badge className={block.block_type === "work" ? "border-orange-400/40 bg-orange-400/15 text-orange-100" : "border-zinc-700 bg-zinc-900 text-zinc-300"}>{block.block_type}</Badge></td><td>{formatDistance(block.distance_km)}</td><td>{formatDuration(block.duration_seconds)}</td><td>{block.pace_seconds_per_km ? `${formatPace(block.pace_seconds_per_km)}${perKmUnit()}` : "--"}</td><td>{block.average_heart_rate_bpm || "--"}</td></tr>)}</tbody>
          </table>
          {!workoutBlocks.length ? <p className="p-3 text-zinc-500">No structured workout blocks.</p> : null}
        </div>
      </div>
      </CollapsibleSection>

      <CollapsibleSection title="Calculations and source metadata" summary={<Badge>{derived.length} metrics</Badge>}>
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2"><p className="font-semibold text-white">Calculations and source metadata</p><Badge>{derived.length} metrics</Badge></div>
        {derived.length ? <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
          {derived.map((metric) => <div key={metric.metric_key} className="rounded-md border border-zinc-800 bg-zinc-900 px-3 py-2" translate="no"><p className="font-medium text-white">{activityMetricLabel(metric.metric_key)}: {formatActivityMetric(metric)}</p><p className="mt-1 text-[11px] text-zinc-500">{metric.method} · {metric.source_reference || "no source"}</p><p className="mt-1 font-mono text-[10px] text-zinc-600">computed {formatLocalDateTime(metric.computed_at)} · hash {metric.input_hash.slice(0, 8)}</p></div>)}
        </div> : <p className="text-zinc-500">No derived metrics yet.</p>}
      </CollapsibleSection>
    </div>
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
  const [message, setMessage] = useState<string | null>(null)
  const activeImportCount = imports.filter((batch) => ACTIVE_IMPORT_STATUSES.has(batch.status)).length

  async function loadImports() {
    setImportHistoryError("")
    try {
      await devLogin()
      const nextImports = await api.imports()
      setImports(nextImports)
      setUploadResult((current) => {
        if (!current) {
          const latestScreenshotImport = nextImports.find((batch) => batch.recognition_engine !== "csv")
          return latestScreenshotImport ? { ...latestScreenshotImport } : null
        }
        const updated = nextImports.find((batch) => batch.id === current.id)
        return updated ? { ...updated } : current
      })
      return nextImports
    } catch (error) {
      console.error(error)
      setImportHistoryError(uiText("Не удалось загрузить историю загрузок", "Could not load upload history"))
      return []
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
      setCandidateError(uiText("Не удалось найти подходящую тренировку в плане. Позже ее можно отметить вручную в разделе «План».", "Could not find a matching workout in the plan. You can mark it manually in Plan later."))
    }
  }

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const input = form.elements.namedItem("screenshots") as HTMLInputElement | null
    const files = Array.from(input?.files || [])
    if (!files.length) {
      setMessage(uiText("Выберите хотя бы один скриншот.", "Choose at least one screenshot."))
      return
    }
    if (files.length > 6) {
      setMessage(uiText("Загрузите не больше 6 скриншотов за один раз.", "Upload no more than 6 screenshots at once."))
      return
    }
    setBusy(true)
    setMessage(uiText("Загружаем скриншоты...", "Uploading screenshots..."))
    setMatchCandidates([])
    setCandidateError("")
    setLinkError("")
    try {
      await devLogin()
      const result = await api.uploadScreenshots(files)
      setUploadResult(result)
      setMessage(importQueuedMessage())
      await loadCandidatesForResult(result)
      await loadImports()
      await onChanged()
      form.reset()
    } catch (error) {
      console.error(error)
      setMessage(apiErrorMessage(error, uiText("Не удалось загрузить скриншоты", "Could not upload screenshots")))
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
      setMessage(uiText("Выберите CSV файл.", "Choose a CSV file."))
      return
    }
    setBusy(true)
    setMessage(uiText("Добавляем тренировки из CSV...", "Adding workouts from CSV..."))
    try {
      await devLogin()
      const result = await api.uploadCsv(file, stringOrNull(new FormData(form).get("source_app")) || "csv")
      setCsvResult(result)
      setMessage(csvImportDoneMessage(result))
      await loadImports()
      await onChanged()
      form.reset()
    } catch (error) {
      console.error(error)
      setMessage(apiErrorMessage(error, uiText("Не удалось добавить тренировки из CSV", "Could not add workouts from CSV")))
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
      setLinkError(uiText("Не удалось отметить тренировку в плане. Обновите список или сделайте это позже в разделе «План».", "Could not mark the workout in the plan. Refresh the list or do it later in Plan."))
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
      setMessage(uiText("Тренировка подтверждена и добавлена в историю.", "Workout confirmed and added to history."))
      await loadCandidatesForResult(result)
      await loadImports()
      await onChanged()
    } catch (error) {
      console.error(error)
      setMessage(apiErrorMessage(error, uiText("Не удалось подтвердить тренировку", "Could not confirm the workout")))
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
      setMessage(uiText("Загрузка отменена. Тренировка не добавлена.", "Upload cancelled. The workout was not added."))
      await loadImports()
      await onChanged()
    } catch (error) {
      console.error(error)
      setMessage(apiErrorMessage(error, uiText("Не удалось отменить загрузку", "Could not cancel the upload")))
    } finally {
      setBusy(false)
    }
  }

  async function retryImport(batchId: number) {
    setBusy(true)
    setLinkError("")
    try {
      await devLogin()
      const result = await api.retryImport(batchId)
      setUploadResult(result)
      setMessage(uiText("Скриншоты отправлены на повторную проверку.", "Screenshots were sent for another check."))
      await loadImports()
    } catch (error) {
      console.error(error)
      setMessage(apiErrorMessage(error, uiText("Не удалось повторно проверить скриншоты", "Could not check the screenshots again")))
    } finally {
      setBusy(false)
    }
  }

  async function updateImportCandidate(batchId: number, payload: Record<string, unknown>) {
    setBusy(true)
    try {
      await devLogin()
      const result = await api.updateImportCandidate(batchId, payload)
      setUploadResult(result)
      setMessage(uiText("Правки сохранены. Теперь можно подтвердить тренировку.", "Changes saved. You can now confirm the workout."))
      await loadImports()
    } catch (error) {
      console.error(error)
      setMessage(apiErrorMessage(error, uiText("Не удалось сохранить правки", "Could not save corrections")))
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => { void loadImports() }, [])
  useEffect(() => {
    if (!uploadResult?.created_activity_id || uploadResult.matched_workout_id) return
    void loadCandidatesForResult(uploadResult)
  }, [uploadResult?.created_activity_id, uploadResult?.matched_workout_id])
  useEffect(() => {
    if (!activeImportCount) return
    const interval = window.setInterval(() => {
      void loadImports().then((nextImports) => {
        if (!nextImports.some((batch) => ACTIVE_IMPORT_STATUSES.has(batch.status))) {
          void onChanged()
        }
      })
    }, 3500)
    return () => window.clearInterval(interval)
  }, [activeImportCount])

  return <div className="grid gap-4">
    <div className="grid gap-4 xl:grid-cols-[24rem_1fr]">
      <Card>
        <CardHeader><div><CardTitle>{uiText("Добавить тренировку", "Add a workout")}</CardTitle><p className="text-xs text-zinc-500">{uiText("Выберите скриншоты одной тренировки. Данные обработаются в фоне.", "Select screenshots from one workout. The details will be processed in the background.")}</p></div>{activeImportCount ? <Badge className="border-sky-400/40 bg-sky-400/15 text-sky-100">{activeImportCount} {uiText("в работе", "processing")}</Badge> : null}</CardHeader>
        <form onSubmit={upload} className="grid gap-3 p-4 text-xs">
          <Field label={uiText("Скриншоты", "Screenshots")}><Input name="screenshots" type="file" accept="image/png,image/jpeg,image/webp" multiple required /></Field>
          <Button type="submit" disabled={busy}>{busy ? uiText("Загружаем...", "Uploading...") : uiText("Загрузить скриншоты", "Upload screenshots")}</Button>
        </form>
        <div className="border-t border-zinc-800 p-4 text-xs text-zinc-400" aria-live="polite">
          <p className="leading-5" translate="no">{message || uiText("Выберите скриншоты одной тренировки. До 6 файлов за раз.", "Choose screenshots from one workout. Up to 6 files at once.")}</p>
          <p className="mt-2 text-zinc-600">{uiText("Страницу можно закрыть: обработка продолжится, а статус обновится автоматически.", "You can leave this page: processing will continue and the status will update automatically.")}</p>
        </div>
      </Card>

      <Card>
        <CardHeader><div><CardTitle>{uiText("Последняя тренировка", "Latest workout")}</CardTitle><p className="text-xs text-zinc-500">{uiText("Здесь появится результат и следующий шаг.", "The result and your next step will appear here.")}</p></div>{uploadResult && <Badge className={importStatusClass(uploadResult)}>{importStatusLabel(uploadResult.status)}</Badge>}</CardHeader>
        {uploadResult ? <div className="grid gap-3 p-4 text-xs">
          <div className={cn("rounded-lg border p-3", importStatusClass(uploadResult))}>
            <p className="text-base font-semibold text-white">{importNextAction(uploadResult)}</p>
            <p className="mt-1 leading-5 text-zinc-300">{importNextActionDescription(uploadResult)}</p>
          </div>
          {RETRYABLE_IMPORT_STATUSES.has(uploadResult.status) || uploadResult.status === "failed" ? <div><Button type="button" size="sm" variant="secondary" disabled={busy} onClick={() => retryImport(uploadResult.id)}>{busy ? uiText("Запускаем...", "Starting...") : uiText("Повторить сейчас", "Retry now")}</Button></div> : null}
          {uploadResult.requires_confirmation && uploadResult.candidate ? <CollapsibleSection title={uiText("Проверьте данные", "Review recognized data")} summary={<Badge>{uiText("нужно подтвердить", "confirm")}</Badge>} defaultOpen><ImportCandidateReview batch={uploadResult} busy={busy} onConfirm={confirmImport} onReject={rejectImport} onUpdate={updateImportCandidate} /></CollapsibleSection> : null}
          {uploadResult.matched_workout_id ? <div className="rounded-md border border-orange-400/20 bg-orange-400/10 px-3 py-2 text-orange-100">{uploadResult.auto_matched ? uiText("Тренировка автоматически отмечена в плане.", "The workout was marked in your plan automatically.") : uiText("Тренировка отмечена в плане.", "The workout was marked in your plan.")}</div> : null}
          {uploadResult.created_activity_id && !uploadResult.matched_workout_id ? <MatchReview candidates={matchCandidates} busy={busy} candidateError={candidateError} linkError={linkError} onLink={linkCandidate} /> : null}
          <CollapsibleSection title={uiText("Технические детали", "Technical details")} summary={<Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{uiText("скрыто", "hidden")}</Badge>}>
            <div className="grid gap-0 divide-y divide-zinc-800 rounded-md border border-zinc-800 bg-zinc-950/60 px-3">
              <ImportMeta label={uiText("Пакет", "Batch")} value={`#${uploadResult.id}`} />
              <ImportMeta label={uiText("Способ", "Engine")} value={uploadResult.recognition_engine || "--"} />
              <ImportMeta label={uiText("Попытки", "Attempts")} value={`${uploadResult.recognition_attempt_count || 0}/${uploadResult.recognition_max_attempts || "?"}`} />
              {uploadResult.created_activity_id ? <ImportMeta label={uiText("Активность", "Activity")} value={`#${uploadResult.created_activity_id}`} /> : null}
              {uploadResult.matched_workout_id ? <ImportMeta label={uiText("Тренировка плана", "Plan workout")} value={`#${uploadResult.matched_workout_id}`} /> : null}
            </div>
            <div className="mt-3 rounded-md border border-zinc-800 bg-zinc-950 p-3 text-zinc-400" translate="no">{uploadResult.recognition_message || "No recognition message"}</div>
            {uploadResult.recognition_last_error && uploadResult.recognition_last_error !== uploadResult.recognition_message ? <div className="mt-2 rounded-md border border-red-400/20 bg-red-400/10 px-3 py-2 text-red-100" translate="no"><strong>{uiText("Причина:", "Reason:")}</strong> {uploadResult.recognition_last_error}</div> : null}
          </CollapsibleSection>
        </div> : <p className="p-4 text-xs text-zinc-500">{uiText("Загрузите скриншоты, и здесь появится текущий статус.", "Upload screenshots to see the current status here.")}</p>}
      </Card>
    </div>

    <CollapsibleSection title={uiText("Добавить из CSV", "Add from CSV")} summary={<Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{uiText("другой способ", "another option")}</Badge>}>
      <form onSubmit={uploadCsv} className="grid gap-3 p-4 text-xs">
        <Field label={uiText("CSV файл", "CSV file")}><Input name="csv_file" type="file" accept=".csv,text/csv" required /></Field>
        <Field label={uiText("Источник", "Source")}><Input name="source_app" defaultValue="csv" placeholder="garmin, strava, manual" /></Field>
        <Button type="submit" disabled={busy}>{busy ? uiText("Добавляем...", "Adding...") : uiText("Добавить тренировки", "Add workouts")}</Button>
      </form>
      {csvResult ? <div className="grid grid-cols-2 gap-2 border-t border-zinc-800 p-4 text-xs md:grid-cols-4">
        <Stat label={uiText("добавлено", "added")} value={csvResult.created_activities} />
        <Stat label={uiText("дубликаты", "duplicates")} value={csvResult.skipped_duplicates} />
        <Stat label={uiText("в плане", "in plan")} value={csvResult.matched_workouts} />
        <Stat label={uiText("ошибки", "failed")} value={csvResult.failed_rows} />
        {csvResult.errors.length ? <p className="col-span-full rounded-md border border-orange-400/20 bg-orange-400/10 px-3 py-2 text-orange-100" translate="no">{csvResult.errors.slice(0, 3).join(" · ")}</p> : null}
      </div> : null}
    </CollapsibleSection>

    <CollapsibleSection title={uiText("История загрузок", "Upload history")} summary={<Badge>{uploadCountLabel(imports.length)}</Badge>}>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2 text-xs"><p className="text-zinc-500">{uiText("Техническая история загрузок и очереди подтверждений.", "Technical upload history and confirmation queue.")}{activeImportCount ? ` ${uiText("В работе", "Active")}: ${activeImportCount}.` : ""}</p><Button type="button" size="sm" variant="secondary" onClick={loadImports}>{uiText("Обновить", "Refresh")}</Button></div>
        {importHistoryError ? <p className="pb-2 text-xs text-orange-200">{importHistoryError}</p> : null}
        <div className="grid gap-2 md:hidden">
          {imports.map((batch) => <div key={`import-mobile-${batch.id}`} className="rounded-md border border-zinc-800 bg-zinc-950 p-3 text-xs" translate="no">
            <div className="flex items-start justify-between gap-2"><div><p className="font-mono text-[10px] uppercase tracking-[0.14em] text-zinc-500">Batch #{batch.id}</p><p className="mt-1 text-zinc-500">{batch.created_at ? formatLocalDateTime(batch.created_at) : "--"}</p></div><Badge className={importStatusClass(batch)}>{importStatusLabel(batch.status)}</Badge></div>
            <div className="mt-2 grid grid-cols-2 gap-2 text-zinc-500"><span>Activity {batch.created_activity_id ? `#${batch.created_activity_id}` : "--"}</span><span>Match {batch.matched_workout_id ? `#${batch.matched_workout_id}` : "--"}</span><span className="col-span-full">Engine {batch.recognition_engine || "--"}</span></div>
            <p className="mt-2 break-words text-zinc-500">{batch.recognition_message || "--"}</p>
            {ACTIVE_IMPORT_STATUSES.has(batch.status) ? <p className="mt-1 text-sky-200">Attempt {batch.recognition_attempt_count || 0}/{batch.recognition_max_attempts || "?"}{batch.recognition_retry_at ? ` · retry ${formatLocalDateTime(batch.recognition_retry_at)}` : ""}</p> : null}
            {batch.requires_confirmation ? <div className="mt-3 flex flex-wrap gap-2"><Button type="button" size="sm" disabled={busy} onClick={() => confirmImport(batch.id)}>{uiText("Подтвердить", "Confirm")}</Button><Button type="button" size="sm" variant="secondary" disabled={busy} onClick={() => rejectImport(batch.id)}>{uiText("Не использовать", "Reject")}</Button></div> : null}
            {RETRYABLE_IMPORT_STATUSES.has(batch.status) ? <div className="mt-3"><Button type="button" size="sm" variant="secondary" disabled={busy} onClick={() => retryImport(batch.id)}>{uiText("Повторить сейчас", "Retry now")}</Button></div> : null}
          </div>)}
          {!imports.length && <p className="text-xs text-zinc-500">{uiText("Загрузок пока нет.", "No uploads yet.")}</p>}
        </div>
        <div className="hidden overflow-x-auto md:block">
          <table className="w-full min-w-[720px] text-left text-xs">
            <thead className="border-b border-zinc-800 text-[10px] uppercase tracking-[0.14em] text-zinc-500"><tr><th className="px-4 py-2">Batch</th><th>Status</th><th>Activity</th><th>Match</th><th>Engine</th><th>Message</th><th>Action</th><th>Date</th></tr></thead>
            <tbody>{imports.map((batch) => <tr key={batch.id} className="border-b border-zinc-900 last:border-0 align-top"><td className="px-4 py-2 font-mono text-zinc-500" translate="no">#{batch.id}</td><td><Badge className={importStatusClass(batch)} translate="no">{importStatusLabel(batch.status)}</Badge>{ACTIVE_IMPORT_STATUSES.has(batch.status) ? <p className="mt-1 text-[10px] text-sky-200" translate="no">{batch.recognition_attempt_count || 0}/{batch.recognition_max_attempts || "?"}</p> : null}</td><td translate="no">{batch.created_activity_id ? `#${batch.created_activity_id}` : "--"}</td><td translate="no">{batch.matched_workout_id ? `#${batch.matched_workout_id}` : "--"}</td><td translate="no">{batch.recognition_engine || "--"}</td><td className="max-w-[18rem] break-words text-zinc-500" translate="no">{batch.recognition_message || "--"}</td><td>{batch.requires_confirmation ? <div className="flex flex-wrap gap-1"><Button type="button" size="sm" disabled={busy} onClick={() => confirmImport(batch.id)}>{uiText("Подтвердить", "Confirm")}</Button><Button type="button" size="sm" variant="secondary" disabled={busy} onClick={() => rejectImport(batch.id)}>{uiText("Не использовать", "Reject")}</Button></div> : RETRYABLE_IMPORT_STATUSES.has(batch.status) ? <Button type="button" size="sm" variant="secondary" disabled={busy} onClick={() => retryImport(batch.id)}>{uiText("Повторить", "Retry")}</Button> : <span className="text-zinc-600">--</span>}</td><td className="text-zinc-500" translate="no">{batch.created_at ? formatLocalDateTime(batch.created_at) : "--"}</td></tr>)}</tbody>
          </table>
          {!imports.length && <p className="p-4 text-xs text-zinc-500">{uiText("Загрузок пока нет.", "No uploads yet.")}</p>}
        </div>
    </CollapsibleSection>
  </div>
}

function ImportMeta({ label, value }: { label: string; value: string }) {
  return <div className="grid min-h-10 grid-cols-[7rem_minmax(0,1fr)] items-center gap-3 py-2"><span className="font-mono text-[10px] uppercase tracking-[0.14em] text-zinc-500">{label}</span><strong className="min-w-0 break-words text-right font-medium text-white" translate="no">{value}</strong></div>
}

function ImportCandidateReview({ batch, busy, onConfirm, onReject, onUpdate }: { batch: ImportUploadResult; busy: boolean; onConfirm: (batchId: number) => Promise<void>; onReject: (batchId: number) => Promise<void>; onUpdate: (batchId: number, payload: Record<string, unknown>) => Promise<void> }) {
  const candidate = batch.candidate
  const [draft, setDraft] = useState({ title: "", started_at: "", distance_km: "", duration_seconds: "", average_pace_seconds_per_km: "", average_heart_rate_bpm: "" })

  useEffect(() => {
    if (!candidate) return
    setDraft({
      title: candidate.activity.title || "",
      started_at: candidate.activity.started_at || "",
      distance_km: candidate.activity.distance_km?.toString() || "",
      duration_seconds: candidate.activity.duration_seconds?.toString() || "",
      average_pace_seconds_per_km: candidate.activity.average_pace_seconds_per_km?.toString() || "",
      average_heart_rate_bpm: candidate.activity.average_heart_rate_bpm?.toString() || "",
    })
  }, [candidate])

  if (!candidate) return null

  function submitCorrection(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const payload: Record<string, unknown> = {}
    const trimmedTitle = draft.title.trim()
    payload.title = trimmedTitle || null
    payload.started_at = draft.started_at.trim() || null
    for (const key of ["distance_km", "duration_seconds"] as const) {
      const value = draft[key].trim()
      if (value) payload[key] = Number(value)
    }
    for (const key of ["average_pace_seconds_per_km", "average_heart_rate_bpm"] as const) {
      const value = draft[key].trim()
      payload[key] = value ? Number(value) : null
    }
    void onUpdate(batch.id, payload)
  }

  return <div className="grid gap-3 rounded-md border border-orange-400/25 bg-orange-400/10 p-3 text-xs">
    <div className="flex flex-wrap items-center justify-between gap-2"><div><p className="font-semibold text-orange-50">{uiText("Проверьте данные тренировки", "Review workout details")}</p><p className="mt-1 text-orange-100/70">{uiText("Тренировка появится в истории после подтверждения.", "The workout will appear in your history after confirmation.")}</p></div><Badge className="border-orange-400/40 bg-orange-400/15 text-orange-100">{uiText("нужно проверить", "review needed")}</Badge></div>
    <div className="grid gap-2 md:grid-cols-4"><Stat label={uiText("название", "title")} value={candidate.activity.title || "--"} /><Stat label={uiText("дистанция", "distance")} value={candidate.activity.distance_km ? `${candidate.activity.distance_km} ${kmUnit()}` : "--"} /><Stat label={uiText("время", "duration")} value={candidate.activity.duration_seconds ? formatDuration(candidate.activity.duration_seconds) : "--"} /><Stat label={uiText("темп", "pace")} value={candidate.activity.average_pace_seconds_per_km ? formatPace(candidate.activity.average_pace_seconds_per_km) : "--"} /></div>
    <form onSubmit={submitCorrection} className="grid gap-2 rounded-md border border-orange-400/20 bg-zinc-950/70 p-3">
      <p className="text-xs font-semibold text-orange-100/80">{uiText("Исправить перед подтверждением", "Correct before confirming")}</p>
      <div className="grid gap-2 md:grid-cols-3">
        <Field label={uiText("Название", "Title")}><Input value={draft.title} onChange={(event) => setDraft((current) => ({ ...current, title: event.target.value }))} /></Field>
        <Field label={uiText("Когда началась", "Start time")}><Input value={draft.started_at} onChange={(event) => setDraft((current) => ({ ...current, started_at: event.target.value }))} placeholder="2026-06-08T07:00:00+00:00" /></Field>
        <Field label={uiText("Дистанция, км", "Distance, km")}><Input type="number" step="0.01" value={draft.distance_km} onChange={(event) => setDraft((current) => ({ ...current, distance_km: event.target.value }))} /></Field>
        <Field label={uiText("Время, сек", "Duration, sec")}><Input type="number" step="1" value={draft.duration_seconds} onChange={(event) => setDraft((current) => ({ ...current, duration_seconds: event.target.value }))} /></Field>
        <Field label={uiText("Темп, сек/км", "Pace, sec/km")}><Input type="number" step="1" value={draft.average_pace_seconds_per_km} onChange={(event) => setDraft((current) => ({ ...current, average_pace_seconds_per_km: event.target.value }))} /></Field>
        <Field label={uiText("Средний пульс", "Average heart rate")}><Input type="number" step="1" value={draft.average_heart_rate_bpm} onChange={(event) => setDraft((current) => ({ ...current, average_heart_rate_bpm: event.target.value }))} /></Field>
      </div>
      <div><Button type="submit" size="sm" variant="secondary" disabled={busy}>{uiText("Сохранить правки", "Save corrections")}</Button></div>
    </form>
    <div className="flex flex-wrap gap-2"><Button size="sm" disabled={busy} onClick={() => onConfirm(batch.id)}>{uiText("Добавить тренировку", "Add workout")}</Button><Button size="sm" variant="secondary" disabled={busy} onClick={() => onReject(batch.id)}>{uiText("Отменить", "Cancel")}</Button></div>
    <CollapsibleSection title={uiText("Технические детали распознавания", "Recognition technical details")} summary={<Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{confidenceLabel(candidate.confidence || "low")}</Badge>}>
      {candidate.uncertainty_notes.length ? <p className="text-[11px] text-orange-100/70" translate="no">uncertainty: {candidate.uncertainty_notes.slice(0, 3).join(" · ")}</p> : null}
      {candidate.estimated_fields.length ? <p className="mt-1 text-[11px] text-orange-100/70" translate="no">estimated: {candidate.estimated_fields.slice(0, 4).join(" · ")}</p> : null}
      <p className="mt-1 text-[11px] text-zinc-500" translate="no">segments {candidate.segments_count} · splits {candidate.split_blocks_count} · blocks {candidate.workout_blocks_count}</p>
    </CollapsibleSection>
  </div>
}

function MatchReview({ candidates, busy, candidateError, linkError, onLink }: { candidates: PlanWorkoutMatchCandidate[]; busy: boolean; candidateError: string; linkError: string; onLink: (candidate: PlanWorkoutMatchCandidate) => Promise<void> }) {
  if (candidateError) return <div className="rounded-md border border-orange-400/20 bg-orange-400/10 px-3 py-2 text-xs text-orange-100">{candidateError}</div>
  if (!candidates.length) return <div className="rounded-md border border-zinc-800 bg-zinc-950 px-3 py-2 text-xs text-zinc-500">{uiText("Не нашли подходящую тренировку в активном плане. Позже ее можно отметить вручную в разделе «План».", "No matching workout was found in the active plan. You can mark it manually in Plan later.")}</div>
  return <div className="grid gap-2">
    <p className="text-xs font-semibold text-white">{uiText("Отметить тренировку в плане", "Mark a planned workout")}</p>
    {linkError ? <p className="rounded-md border border-orange-400/20 bg-orange-400/10 px-3 py-2 text-xs text-orange-100">{linkError}</p> : null}
    {candidates.slice(0, 4).map((candidate) => <div key={candidate.workout.id} className="grid gap-2 rounded-md border border-zinc-800 bg-zinc-950 p-3 text-xs md:grid-cols-[1fr_auto] md:items-center">
      <div><p className="font-medium text-white">{coachWorkoutTitle(candidate.workout)}</p><p className="mt-1 text-zinc-500">{candidate.workout.scheduled_date ? formatLocalDate(candidate.workout.scheduled_date) : noDateLabel()} · {workoutTypeLabel(candidate.workout.workout_type)} · {formatWorkoutTarget(candidate.workout)}</p></div>
      <div className="flex flex-wrap items-center gap-2 md:justify-end"><Button size="sm" disabled={busy} aria-label={uiText("Отметить эту тренировку выполненной в плане", "Mark this planned workout as completed")} onClick={() => onLink(candidate)}>{uiText("Отметить в плане", "Mark in plan")}</Button></div>
      <CollapsibleSection title={uiText("Почему предложили", "Why suggested")} className="md:col-span-2" summary={<Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{uiText("детали", "details")}</Badge>}>
        <p className="text-[11px] text-zinc-500" translate="no">{candidate.reasons.slice(0, 3).join(" · ") || candidate.confidence}</p>
      </CollapsibleSection>
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
  const [missEvent, setMissEvent] = useState<CalendarEvent | null>(null)
  const [missError, setMissError] = useState("")
  const [coachAction, setCoachAction] = useState<CoachActionTarget | null>(null)

  async function loadRange(fromValue = fromDate, toValue = toDate) {
    setError("")
    setCalendarMatches({})
    setCalendarMatchErrors({})
    if (fromValue > toValue) {
      setError("Дата начала должна быть раньше или равна дате окончания")
      return false
    }
    if (calendarRangeDayCount(fromValue, toValue) > MAX_CALENDAR_DAYS) {
      setError(`Диапазон календаря не может превышать ${MAX_CALENDAR_DAYS} дней`)
      return false
    }
    setLoading(true)
    try {
      await devLogin()
      setCalendar(await api.calendar(fromValue, toValue))
      setRescheduleDrafts({})
      return true
    } catch (loadError) {
      console.error(loadError)
      setError(loadError instanceof Error ? loadError.message : "Не удалось загрузить календарь")
      return false
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
    if (status === "missed") {
      setMissError("")
      setMissEvent(event)
      return
    }
    if (status === "skipped") {
      setCoachAction({ workoutId: event.planned_workout_id, eventId: event.id, title: event.title, action: "skip" })
    }
  }

  async function missCalendarWorkout(reason: WorkoutMissReason, notes?: string) {
    const workoutId = missEvent?.planned_workout_id
    if (!missEvent || !workoutId) return
    const target = missEvent
    setBusyEvent(missEvent.id)
    setMissError("")
    try {
      await api.missWorkout(workoutId, reason, notes)
      setCalendar((current) => current ? { ...current, events: current.events.map((event) => event.id === target.id ? { ...event, status: "missed" } : event) } : current)
      setMissEvent(null)
    } catch (updateError) {
      console.error(updateError)
      setMissError(uiText("Не удалось сохранить пропуск", "Failed to save missed workout"))
      setBusyEvent("")
      return
    }
    setBusyEvent("")
    const refreshed = await loadRange(calendar?.from_date || fromDate, calendar?.to_date || toDate)
    if (!refreshed) {
      setError(uiText("Пропуск сохранён, но календарь не обновился", "Missed workout saved, but calendar refresh failed"))
    }
  }

  async function rescheduleCalendarWorkout(event: CalendarEvent, scheduledDate: string) {
    if (!event.planned_workout_id) return
    setCalendarMatchErrors((current) => ({ ...current, [event.id]: "" }))
    if (!scheduledDate) {
      setCalendarMatchErrors((current) => ({ ...current, [event.id]: "Выберите новую дату" }))
      return
    }
    setCoachAction({ workoutId: event.planned_workout_id, eventId: event.id, title: event.title, action: "reschedule", targetDate: scheduledDate })
  }

  async function refreshCalendarCoachAction() {
    const refreshed = await loadRange(calendar?.from_date || fromDate, calendar?.to_date || toDate)
    if (!refreshed) throw new Error(uiText("Изменение применено, но календарь не обновился", "The change was applied, but calendar refresh failed"))
    if (coachAction?.action === "reschedule" && coachAction.targetDate && coachAction.eventId) {
      setRescheduleDrafts((current) => ({ ...current, [coachAction.eventId!]: coachAction.targetDate! }))
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
    {missEvent ? <MissWorkoutDialog title={missEvent.title} busy={busyEvent === missEvent.id} error={missError} onSubmit={missCalendarWorkout} onClose={() => setMissEvent(null)} /> : null}
    {coachAction ? <CoachActionDialog target={coachAction} onApplied={refreshCalendarCoachAction} onClose={() => setCoachAction(null)} /> : null}
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
        <div className="mt-3 flex flex-wrap gap-2"><Button size="sm" variant="secondary" onClick={() => applyQuickRange("week")}>{uiText("Эта неделя", "This week")}</Button><Button size="sm" variant="secondary" onClick={() => applyQuickRange("next")}>{uiText("Следующая неделя", "Next week")}</Button><Button size="sm" variant="secondary" onClick={() => applyQuickRange("month")}>{uiText("Этот месяц", "This month")}</Button><Button size="sm" variant="ghost" onClick={onImport}>{uiText("Добавить тренировку", "Add workout")}</Button><Button size="sm" variant="ghost" onClick={onPlans}>{uiText("Открыть план", "Open plan")}</Button></div>
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
      <div className="grid gap-2 p-4 text-xs md:grid-cols-2">{calendar.warnings.map((warning) => <div key={`${warning.title}-${warning.date}-${warning.planned_workout_ids.join("-")}`} className="rounded-md border border-orange-400/20 bg-orange-400/10 p-3 text-orange-100" translate="no"><p className="font-medium">{warning.title}</p><p className="mt-1 leading-5 text-orange-100/80">{warning.message}</p><p className="mt-1 font-mono text-[10px] uppercase tracking-[0.14em] text-orange-200/70">{formatDate(warning.date)} · workouts {warning.planned_workout_ids.map((id) => `#${id}`).join(", ")}</p></div>)}</div>
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
  return <div className={cn("min-h-0 rounded-lg border bg-zinc-950/60 p-3 text-xs md:min-h-48", day === today ? "border-orange-400/40" : "border-zinc-800")}>
    <div className="flex items-start justify-between gap-2"><div><p className="font-medium text-white">{formatDate(day)}</p><p className="mt-1 font-mono text-[10px] uppercase tracking-[0.14em] text-zinc-500">{dateFromISO(day).toLocaleDateString(languageLocale(), { weekday: "short" })}</p></div>{events.length ? <Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{events.length}</Badge> : null}</div>
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
    <div className="flex flex-wrap items-start justify-between gap-2"><div className="min-w-0" translate="no"><p className="truncate font-medium text-white">{event.title}</p><p className="mt-1 text-[11px] text-zinc-500">{isWorkout ? event.workout_type || "workout" : event.workout_type || "activity"} · target: {formatWorkoutTarget(event)}</p></div><Badge className={signalClass(event.status || undefined)} translate="no">{event.status || event.kind}</Badge></div>
    {score !== null && score !== undefined ? <p className="mt-2 text-[11px] text-zinc-500" translate="no">Score {Math.round(score * 100)}% · {event.execution_score?.subjective_risk}</p> : null}
    {event.linked_activity_id && isWorkout ? <p className="mt-2 rounded border border-orange-400/20 bg-orange-400/10 px-2 py-1 text-[11px] text-orange-100">Linked activity #{event.linked_activity_id}</p> : null}
    {event.planned_workout_id && !isWorkout ? <p className="mt-2 rounded border border-orange-400/20 bg-orange-400/10 px-2 py-1 text-[11px] text-orange-100">Matched to workout #{event.planned_workout_id}</p> : null}
    {(canReschedule || isWorkout || canFindWorkoutActivity || canFindActivityWorkout || matchError || matchState) ? <CollapsibleSection title="Actions" summary={<Badge>{busy || loadingMatches ? "busy" : "more"}</Badge>} className="mt-2">
    {canReschedule ? <div className="grid gap-1.5 rounded-md border border-zinc-800 bg-zinc-950/70 p-2">
      <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-zinc-500">Reschedule</p>
      <div className="grid gap-1.5 sm:grid-cols-[1fr_auto]"><Input type="date" value={rescheduleDraft} onChange={(change) => onRescheduleDraft(event.id, change.target.value)} /><Button size="sm" variant="ghost" disabled={busy || !rescheduleDraft || rescheduleDraft === event.date} onClick={() => onReschedule(event, rescheduleDraft)}>Move</Button></div>
    </div> : null}
    <div className="mt-2 flex flex-wrap gap-1.5">
      {isWorkout ? <>
        <Button size="sm" variant="ghost" disabled={busy || !["planned", "rescheduled"].includes(event.status || "") || Boolean(event.linked_activity_id)} onClick={() => onUpdate(event, "missed")}>Missed</Button>
        <Button size="sm" variant="ghost" disabled={busy || !["planned", "rescheduled"].includes(event.status || "") || Boolean(event.linked_activity_id)} onClick={() => onUpdate(event, "skipped")}>Skipped</Button>
      </> : null}
      {canFindWorkoutActivity || canFindActivityWorkout ? <Button size="sm" variant="ghost" disabled={busy || loadingMatches} onClick={() => onFindMatches(event)}>{loadingMatches ? "Matching..." : canFindWorkoutActivity ? "Find activity" : "Find workout"}</Button> : null}
    </div>
    {matchError ? <p className="mt-2 rounded-md border border-orange-400/20 bg-orange-400/10 px-2 py-1.5 text-[11px] text-orange-100">{matchError}</p> : null}
    {matchState ? <CalendarMatchCandidates event={event} state={matchState} busy={busy} onLinkMatch={onLinkMatch} /> : null}
    </CollapsibleSection> : null}
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
        <div translate="no"><p className="font-medium text-white">{candidate.activity.title}<span className="ml-2 font-mono text-[10px] text-zinc-500">#{candidate.activity.id}</span></p><p className="mt-1 text-zinc-500">{candidate.activity.started_at ? formatLocalDate(candidate.activity.started_at) : noDateLabel()} · {formatDistance(candidate.activity.distance_km)} · {formatDuration(candidate.activity.duration_seconds)}</p><p className="mt-1 text-[11px] text-zinc-500">{candidate.reasons.slice(0, 2).join(" · ")}</p></div>
        <div className="flex flex-wrap items-center gap-2 md:justify-end"><Badge className="border-zinc-700 bg-zinc-950 text-zinc-300" translate="no">{Math.round(candidate.score * 100)}% {candidate.confidence}</Badge><Button size="sm" disabled={busy} onClick={() => onLinkMatch(event, workoutId, candidate.activity.id)}>Link</Button></div>
      </div>)}
    </div>
  }

  const activityId = event.linked_activity_id
  if (!activityId) return null
  if (!state.candidates.length) return <p className="mt-2 rounded-md border border-zinc-800 bg-zinc-950 px-2 py-1.5 text-[11px] text-zinc-500">No active-plan workout candidates found.</p>
  return <div className="mt-2 grid gap-1.5 rounded-md border border-zinc-800 bg-zinc-950/70 p-2">
    <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-zinc-500">Workout candidates</p>
    {state.candidates.slice(0, 4).map((candidate) => <div key={candidate.workout.id} className="grid gap-2 rounded-md bg-zinc-900/70 p-2 md:grid-cols-[1fr_auto] md:items-center">
      <div translate="no"><p className="font-medium text-white">{candidate.workout.title}<span className="ml-2 font-mono text-[10px] text-zinc-500">#{candidate.workout.id}</span></p><p className="mt-1 text-zinc-500">{formatDate(candidate.workout.scheduled_date)} · target: {formatWorkoutTarget(candidate.workout)} · {candidate.workout.intensity || "--"}</p><p className="mt-1 text-[11px] text-zinc-500">{candidate.reasons.slice(0, 2).join(" · ")}</p></div>
      <div className="flex flex-wrap items-center gap-2 md:justify-end"><Badge className="border-zinc-700 bg-zinc-950 text-zinc-300" translate="no">{Math.round(candidate.score * 100)}% {candidate.confidence}</Badge><Button size="sm" disabled={busy} onClick={() => onLinkMatch(event, candidate.workout.id, activityId)}>Link</Button></div>
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
    <div className="flex items-center justify-between gap-2"><p className="text-xs font-semibold text-white">{title}</p><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{trendGranularityLabel(series?.granularity)}</Badge></div>
    <div className="mt-3 grid gap-2">{points.length ? points.slice(-10).map((point) => {
      const numericValue = typeof point.value === "number" && Number.isFinite(point.value) ? point.value : 0
      const width = lowerIsBetter && numericValue > 0 ? min / numericValue * 100 : numericValue / max * 100
      return <div key={`${title}-${point.period_label}`} className="grid grid-cols-[6rem_1fr_4.5rem] items-center gap-2 text-[11px]"><span className="truncate text-zinc-500">{point.period_label}</span><div className="h-2 rounded bg-zinc-900"><div className="h-full rounded bg-orange-400" style={{ width: `${Math.max(4, width)}%` }} /></div><strong className="text-right text-zinc-300">{formatter(point.value)}</strong></div>
    }) : <p className="text-xs text-zinc-500">{uiText("Нет точек для выбранного периода.", "No points for the selected period.")}</p>}</div>
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
        <div><p className="text-xs font-semibold text-orange-200">{uiText("Прогресс", "Progress")}</p><h2 className="mt-2 text-lg font-semibold text-white">{uiText("Как меняется ваша форма", "How your fitness is changing")}</h2><p className="mt-2 max-w-2xl text-xs leading-5 text-zinc-500">{uiText("Сначала общий вывод, затем детали для тех, кто хочет смотреть глубже.", "A coaching summary first, then details if you want to look deeper.")}</p></div>
        <div className="flex flex-wrap gap-2"><Badge>{periodPresetLabel(preset)}</Badge>{loading ? <Badge className="border-orange-400/40 bg-orange-400/15 text-orange-100">{uiText("обновляем", "updating")}</Badge> : null}</div>
      </div>
      <div className="mt-4 grid gap-2 md:grid-cols-[10rem_1fr_1fr]">
        <Select value={preset} onChange={(event) => setPreset(event.target.value)}><option value="7d">{uiText("7 дней", "7 days")}</option><option value="28d">{uiText("28 дней", "28 days")}</option><option value="90d">{uiText("90 дней", "90 days")}</option><option value="year">{uiText("Год", "Year")}</option><option value="all">{uiText("Все время", "All time")}</option><option value="custom">{uiText("Свой период", "Custom")}</option></Select>
        <Input type="date" value={customFrom} disabled={preset !== "custom"} onChange={(event) => setCustomFrom(event.target.value)} />
        <Input type="date" value={customTo} disabled={preset !== "custom"} onChange={(event) => setCustomTo(event.target.value)} />
      </div>
      {error ? <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-md border border-rose-400/20 bg-rose-400/10 px-2 py-1.5 text-xs text-rose-100"><span>{error}</span><Button size="sm" variant="secondary" onClick={() => setReloadToken((current) => current + 1)}>{uiText("Повторить", "Retry")}</Button></div> : null}
    </Card>

    <Card className="overflow-hidden border-orange-400/25 bg-[radial-gradient(circle_at_top_right,rgba(251,146,60,0.14),transparent_32%),#0b0b0b] p-4">
      <div className="grid gap-4 lg:grid-cols-[1fr_0.85fr] lg:items-end">
        <div><p className="text-xs font-semibold text-orange-200">{uiText("Вывод тренера", "Coach summary")}</p><h3 className="mt-2 text-2xl font-semibold tracking-tight text-white">{summary?.activity_count ? uiText("Регулярность важнее отдельных быстрых дней", "Consistency matters more than single fast days") : uiText("Добавьте первые тренировки", "Add your first workouts")}</h3><p className="mt-3 max-w-2xl text-sm leading-6 text-zinc-300">{summary?.activity_count ? uiText(`За период: ${summary.activity_count} тренировок и ${Number(summary.total_distance_km || 0).toFixed(1)} ${kmUnit()}. Средний темп и выполнение плана смотрите как тренд, а не как оценку дня.`, `This period: ${summary.activity_count} workouts and ${Number(summary.total_distance_km || 0).toFixed(1)} ${kmUnit()}. Treat average pace and plan completion as trends, not a daily grade.`) : uiText("Добавьте несколько тренировок, и здесь появится понятный обзор прогресса.", "Add a few workouts to see a clear progress summary here.")}</p></div>
        <div className="grid grid-cols-2 gap-2 text-center text-xs">
          <Stat label={uiText("дистанция", "distance")} value={Number(summary?.total_distance_km || 0).toFixed(1)} suffix={kmUnit()} />
          <Stat label={uiText("тренировки", "workouts")} value={summary?.activity_count || 0} />
          <p className="col-span-2 rounded-xl border border-zinc-800 bg-zinc-950/70 px-3 py-2 text-left leading-5 text-zinc-400">{uiText("Средний темп", "Average pace")}: <span className="text-white">{formatPace(summary?.weighted_average_pace_seconds_per_km)}{perKmUnit()}</span>. {uiText("План выполнен", "Plan completion")}: <span className="text-white">{Math.round((summary?.adherence?.completion_rate || 0) * 100)}%</span>.</p>
        </div>
      </div>
    </Card>

    <CollapsibleSection title={uiText("Графики и подробности", "Charts and details")} summary={<Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{uiText("посмотреть глубже", "look deeper")}</Badge>}>
      <div className="grid gap-4">
        <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
          <Card><CardHeader><CardTitle>{uiText("Объем по месяцам", "Monthly volume")}</CardTitle><Badge>{Number(summary?.total_distance_km || 0).toFixed(1)} {kmUnit()}</Badge></CardHeader><div className="space-y-3 p-4">{months.length ? months.map((month) => <div key={month.month} className="grid grid-cols-[110px_1fr_90px] items-center gap-3 text-xs" translate="no"><span className="text-zinc-400">{month.month}</span><div className="h-2 rounded bg-zinc-900"><div className="h-full rounded bg-orange-400" style={{ width: `${Math.max(6, month.distance_km / maxMonth * 100)}%` }} /></div><strong>{month.distance_km.toFixed(1)} {kmUnit()}</strong></div>) : <p className="p-4 text-xs text-zinc-500">{uiText("Нет месячных данных.", "No monthly data yet.")}</p>}</div></Card>
          <Card><CardHeader><CardTitle>{uiText("Пульс и время", "Heart rate and time")}</CardTitle><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{uiText("за период", "period")}</Badge></CardHeader><div className="grid gap-3 p-4 text-xs"><Stat label={uiText("время", "time")} value={formatDuration(summary?.total_duration_seconds)} /><Stat label={uiText("ср. пульс", "avg HR")} value={summary?.average_heart_rate_bpm || "--"} /><Stat label={uiText("пропущено", "missed")} value={summary?.consistency.missed_planned_sessions || 0} /></div></Card>
        </div>
        <div className="grid gap-3 xl:grid-cols-3">
          <TrendChart title={uiText("Дистанция по неделям", "Weekly distance")} series={volumeTrend} formatter={(value) => `${Number(value || 0).toFixed(1)} ${kmUnit()}`} />
          <TrendChart title={uiText("Темп", "Pace trend")} series={paceTrend} formatter={(value) => `${formatPace(value)}${perKmUnit()}`} lowerIsBetter />
          <TrendChart title={uiText("Пульс", "Heart rate trend")} series={hrTrend} formatter={(value) => value ? `${Math.round(value)} ${uiText("уд/мин", "bpm")}` : "--"} />
        </div>
        <div className="grid gap-4 xl:grid-cols-[1fr_1fr]">
          <Card><CardHeader><CardTitle>{uiText("Лучшие отрезки", "Best efforts")}</CardTitle><Badge>{summary?.best_efforts.length || 0}</Badge></CardHeader><div className="divide-y divide-zinc-800">{summary?.best_efforts.length ? summary.best_efforts.map((effort) => <div key={`${effort.target_distance_km}-${effort.activity_id}`} className="grid gap-2 px-4 py-3 text-xs md:grid-cols-[5rem_1fr_auto]"><div className="font-semibold text-white" translate="no">{effort.target_distance_km} {kmUnit()}</div><div><p className="text-zinc-300" translate="no">{formatDuration(effort.duration_seconds)} · {formatPace(effort.pace_seconds_per_km)}{perKmUnit()}</p><p className="mt-1 text-zinc-500">{uiText("лучший результат за период", "best result in this period")}</p></div><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{effort.started_at ? formatLocalDate(effort.started_at) : noDateLabel()}</Badge></div>) : <p className="p-4 text-xs text-zinc-500">{uiText("Пока нет достаточно длинных пробежек для лучших усилий.", "No sufficiently long runs for best efforts yet.")}</p>}</div></Card>
          <Card><CardHeader><CardTitle>{uiText("Подсказки", "Insights")}</CardTitle><Badge>{insights.length}</Badge></CardHeader><div className="grid gap-2 p-4">{insights.map((insight) => <div key={insight.title} className="rounded-md border border-zinc-800 bg-zinc-950 p-3 text-xs"><div className="flex flex-wrap items-center justify-between gap-2"><p className="font-semibold text-white">{insightCoachTitle(insight)}</p><Badge className={insight.severity === "warning" || insight.severity === "critical" ? signalClass(insight.severity) : "border-zinc-700 bg-zinc-900 text-zinc-300"}>{signalStatusLabel(insight.severity)}</Badge></div><p className="mt-1 leading-5 text-zinc-400">{insightCoachMessage(insight)}</p>{insight.evidence.length || insight.reasons.length ? <CollapsibleSection title={uiText("Детали расчета", "Calculation details")} className="mt-2" summary={<Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{confidenceLabel(insight.confidence)}</Badge>}><p className="text-[11px] text-zinc-600" translate="no">{insight.title}: {insight.message}</p><p className="mt-1 text-[11px] text-zinc-600" translate="no">{insight.evidence.slice(0, 2).map((item) => `${String(item.metric || item.source || "signal")}=${String(item.value ?? item.method ?? item.source ?? "ok")}`).join(" · ")}</p>{insight.reasons.length ? <p className="mt-1 text-[11px] text-zinc-600" translate="no">{insight.reasons.slice(0, 2).join(" · ")}</p> : null}</CollapsibleSection> : null}</div>)}</div></Card>
        </div>
      </div>
    </CollapsibleSection>

    <CollapsibleSection title={uiText("Продвинутые показатели", "Advanced metrics")} summary={<Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">VDOT / VO2max</Badge>}>
      <div className="grid gap-3 text-xs md:grid-cols-3">
        <Stat label="VDOT" value={vdot?.value ?? "--"} />
        <Stat label="VO2max" value={vo2?.value ?? "--"} />
        <Stat label="load" value={summary?.training_load ?? "--"} />
      </div>
      <p className="mt-3 text-[11px] text-zinc-500" translate="no">{vdot ? calculationMetadata(vdot) : vo2 ? calculationMetadata(vo2) : summary?.load_method || "technical estimates appear after enough data"}</p>
    </CollapsibleSection>
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
      <MetricCard label="CTL" value={current?.ctl.value ?? "--"} hint={current?.ctl ? `${current.ctl.method} · ${current.ctl.confidence}` : "42-day EWMA"} explainer={<CalculationExplainer><p>Chronic Training Load is a long-window EWMA of daily load. It approximates fitness trend, not readiness by itself.</p><p className="mt-2 text-zinc-500">Source: {calculationSourceReference(current?.ctl)}</p></CalculationExplainer>} />
      <MetricCard label="ATL" value={current?.atl.value ?? "--"} hint={current?.atl ? `${current.atl.method} · ${current.atl.confidence}` : "7-day EWMA"} explainer={<CalculationExplainer><p>Acute Training Load reacts faster to recent sessions. A sharp ATL rise can indicate short-term fatigue.</p><p className="mt-2 text-zinc-500">Source: {calculationSourceReference(current?.atl)}</p></CalculationExplainer>} />
      <MetricCard label="TSB" value={current?.tsb.value ?? "--"} hint={current?.tsb ? `${current.tsb.method} · ${current.tsb.confidence}` : "CTL - ATL"} explainer={<CalculationExplainer><p>Training Stress Balance is CTL minus ATL. Negative values often mean higher recent fatigue; positive values often mean fresher legs.</p><p className="mt-2 text-zinc-500">Source: {calculationSourceReference(current?.tsb)}</p></CalculationExplainer>} />
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
    <div className="grid gap-2 p-4 md:hidden">
      {rows.map((row) => <div key={`mobile-planned-actual-${row.zone_key}`} className="rounded-md border border-zinc-800 bg-zinc-950 p-3 text-xs">
        <div className="flex flex-wrap items-start justify-between gap-2"><div><p className="font-medium text-white">{row.label}</p><p className="font-mono text-[10px] text-zinc-600">{row.zone_key}</p></div><Badge className={Math.abs(row.diff_percentage) >= 15 ? "border-orange-400/40 bg-orange-400/15 text-orange-100" : "border-zinc-700 bg-zinc-900 text-zinc-300"}>{row.diff_percentage > 0 ? "+" : ""}{row.diff_percentage.toFixed(1)}%</Badge></div>
        <div className="mt-3 grid grid-cols-2 gap-2 text-center"><Stat label="planned" value={formatDuration(row.planned_duration_seconds)} /><Stat label="actual" value={formatDuration(row.actual_duration_seconds)} /></div>
        <p className="mt-2 text-[11px] text-zinc-500">planned {row.planned_percentage.toFixed(1)}% · actual {row.actual_percentage.toFixed(1)}%</p>
      </div>)}
      {!rows.length ? <p className="text-xs text-zinc-500">Нет planned-vs-actual rows.</p> : null}
    </div>
    <div className="hidden overflow-x-auto md:block">
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
        return <div key={point.date} className="grid grid-cols-[5rem_1fr_4.5rem] items-center gap-2 text-[11px]"><span className="truncate text-zinc-500">{label(point)}</span><div className="h-2 rounded bg-zinc-900"><div className={cn("h-full rounded", point.hard_session ? "bg-orange-400" : point.recovery_day ? "bg-zinc-500" : "bg-orange-300/70")} style={{ width: `${Math.max(4, numeric / max * 100)}%` }} /></div><strong className="text-right text-zinc-300">{numeric.toFixed(1)} {suffix}</strong><span className="col-span-full text-[10px] text-zinc-600">source: {trainingLoadMethodMetadata(point.load_method, point.load_methods)}</span></div>
      }) : <p className="text-xs text-zinc-500">Нет daily load points.</p>}
    </div>
  </Card>
}

function WeeklyLoadChart({ points }: { points: TrainingLoadWeekly["points"] }) {
  const max = Math.max(1, ...points.map((point) => point.load))
  return <Card>
    <CardHeader><CardTitle>Weekly load</CardTitle><Badge>{points.length} weeks</Badge></CardHeader>
    <div className="grid gap-2 p-4">
      {points.length ? points.map((point) => <div key={point.week_start} className="grid grid-cols-[6rem_1fr_5rem] items-center gap-2 text-[11px]"><span className="truncate text-zinc-500">{formatDate(point.week_start)}</span><div className="h-2 rounded bg-zinc-900"><div className="h-full rounded bg-orange-400" style={{ width: `${Math.max(4, point.load / max * 100)}%` }} /></div><strong className="text-right text-zinc-300">{point.load.toFixed(1)} au</strong><span className="col-span-full text-[10px] text-zinc-600">source: {loadMethodLabel(point.load_method)}</span></div>) : <p className="text-xs text-zinc-500">Нет weekly load points.</p>}
    </div>
  </Card>
}

function FitnessFatigueChart({ fitness }: { fitness: TrainingLoadFitnessFatigue | null }) {
  const points = fitness?.points.slice(-10) || []
  return <Card>
    <CardHeader><div><CardTitle>CTL / ATL / TSB</CardTitle><p className="text-xs text-zinc-500">{fitness?.explanation || "EWMA load heuristics."}</p></div><Badge>{points.length} points</Badge></CardHeader>
    <div className="grid gap-2 p-4 md:hidden">
      {points.map((point) => <div key={`mobile-fitness-${point.date}`} className="rounded-md border border-zinc-800 bg-zinc-950 p-3 text-xs">
        <div className="flex items-center justify-between gap-2"><p className="font-medium text-white">{formatDate(point.date)}</p><Badge className={point.tsb <= -10 ? "border-orange-400/40 bg-orange-400/15 text-orange-100" : point.tsb >= 5 ? "border-zinc-700 bg-zinc-900 text-zinc-300" : "border-zinc-800 bg-zinc-950 text-zinc-400"}>TSB {point.tsb.toFixed(1)}</Badge></div>
        <div className="mt-3 grid grid-cols-3 gap-2 text-center"><Stat label="load" value={point.load.toFixed(1)} /><Stat label="ctl" value={point.ctl.toFixed(1)} /><Stat label="atl" value={point.atl.toFixed(1)} /></div>
      </div>)}
      {!points.length ? <p className="text-xs text-zinc-500">Нет fitness/fatigue points.</p> : null}
    </div>
    <div className="hidden overflow-x-auto p-4 md:block">
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
      {warnings.map((warning) => <div key={`${warning.title}-${warning.metric || "signal"}`} className={cn("rounded-md border px-3 py-2 text-xs", signalClass(warning.severity))} translate="no"><div className="flex flex-wrap items-center justify-between gap-2"><p className="font-semibold text-white">{warning.title}</p><Badge className="border-zinc-700 bg-zinc-950 text-zinc-300">{warning.severity}</Badge></div><p className="mt-1 leading-5 text-zinc-300">{warning.message}</p>{warning.metric ? <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.12em] text-zinc-500">{warning.metric}: {formatOptionalNumber(warning.value)} / threshold {formatOptionalNumber(warning.threshold)}</p> : null}{warning.reasons.length ? <p className="mt-1 text-[11px] text-zinc-500">{warning.reasons.slice(0, 3).join(" · ")}</p> : null}</div>)}
      {!warnings.length ? <p className="text-xs text-zinc-500">Нет load alerts.</p> : null}
    </div>
  </Card>
}

function HardSessionSpacing({ hardDays }: { hardDays: TrainingLoadDailyPoint[] }) {
  return <Card>
    <CardHeader><CardTitle>Hard sessions spacing</CardTitle><Badge>{hardDays.length} hard days</Badge></CardHeader>
    <div className="grid gap-2 p-4 md:hidden">
      {hardDays.map((day, index) => {
        const previous = hardDays[index - 1]
        const gap = previous ? Math.round((dateFromISO(day.date).getTime() - dateFromISO(previous.date).getTime()) / 86400000) : null
        return <div key={`mobile-hard-${day.date}`} className="rounded-md border border-zinc-800 bg-zinc-950 p-3 text-xs" translate="no">
          <div className="flex flex-wrap items-start justify-between gap-2"><div><p className="font-medium text-white">{formatDate(day.date)}</p><p className="mt-1 text-zinc-500">{day.load.toFixed(1)} au</p></div><Badge className={gap !== null && gap < 2 ? "border-orange-400/40 bg-orange-400/15 text-orange-100" : "border-zinc-700 bg-zinc-900 text-zinc-300"}>{gap === null ? "first" : `${gap} d`}</Badge></div>
          {day.hard_reasons.length ? <p className="mt-2 break-words text-[11px] text-zinc-500">{day.hard_reasons.join(" · ")}</p> : null}
        </div>
      })}
      {!hardDays.length ? <p className="text-xs text-zinc-500">Hard sessions не обнаружены.</p> : null}
    </div>
    <div className="hidden overflow-x-auto md:block">
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
      {recoveryDays.map((day) => <div key={day.date} className="grid gap-2 px-4 py-3 text-xs md:grid-cols-[5rem_1fr_auto]" translate="no"><div className="font-semibold text-white">{formatDate(day.date)}</div><div><p className="text-zinc-300">{day.load.toFixed(1)} au · {formatDuration(day.duration_seconds)}</p><p className="mt-1 text-zinc-500">{day.activity_count ? `${day.activity_count} light activity` : "No recorded activity"}</p></div><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">recovery</Badge></div>)}
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
      {error ? <p className="mt-3 rounded-md border border-rose-400/20 bg-rose-400/10 px-2 py-1.5 text-xs text-rose-100" translate="no">{error}</p> : null}
      {vdot?.warnings.length ? <div className="mt-3 grid gap-2" translate="no">{vdot.warnings.map((warning) => <p key={warning} className="rounded-md border border-orange-400/20 bg-orange-400/10 px-2 py-1.5 text-xs text-orange-100">{warning}</p>)}</div> : null}
    </Card>

    <div className="grid gap-3 md:grid-cols-4">
      <Card className="p-3"><Stat label="VDOT" value={vdot?.estimate?.value ?? "--"} /></Card>
      <Card className="p-3"><Stat label="source" value={source ? `${source.distance_km.toFixed(1)} ${kmUnit()}` : "--"} /></Card>
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
          <div className="rounded-md border border-zinc-800 bg-zinc-950 p-3"><p className="text-zinc-500">Estimated VDOT</p><p className="mt-1 text-3xl font-semibold text-white">{vdot?.estimate?.value ?? "--"}</p><p className="mt-1 text-zinc-500">{vdot?.estimate ? calculationMetadata(vdot.estimate) : "No eligible race/time trial yet."}</p></div>
          <div className="rounded-md border border-zinc-800 bg-zinc-950 p-3"><p className="text-zinc-500">Selected result</p><p className="mt-1 text-lg font-semibold text-white" translate="no">{source?.name || "--"}</p><p className="mt-1 text-zinc-500" translate={source ? "no" : undefined}>{source ? `${source.distance_km.toFixed(2)} ${kmUnit()} · ${formatDuration(source.duration_seconds)} · ${source.age_days ?? 0} days old` : "Add a result >= 3 km."}</p>{source?.noisy_reasons.length ? <p className="mt-2 text-orange-200" translate="no">Noisy: {source.noisy_reasons.join(" · ")}</p> : null}</div>
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
    <div className="grid gap-2 p-4 md:hidden">
      {results.map((result) => <div key={`mobile-result-${result.id}`} className="min-w-0 rounded-md border border-zinc-800 bg-zinc-950 p-3 text-xs">
        <div className="flex flex-wrap items-start justify-between gap-2"><div className="min-w-0" translate="no"><p className="truncate font-medium text-white">{result.name}</p><p className="mt-1 text-zinc-500">#{result.id} · {formatDateTime(result.result_date)} · {result.terrain}</p></div><Badge className={result.is_noisy ? "border-orange-400/40 bg-orange-400/15 text-orange-100" : confidenceClass(result.estimated_vdot?.confidence)}>{result.is_noisy ? "noisy" : result.estimated_vdot?.confidence || "low"}</Badge></div>
        <div className="mt-3 grid grid-cols-3 gap-2 text-center"><Stat label="distance" value={`${result.distance_km.toFixed(2)} ${kmUnit()}`} /><Stat label="time" value={formatDuration(result.duration_seconds)} /><Stat label="pace" value={`${formatPace(result.pace_seconds_per_km)}${perKmUnit()}`} /></div>
        <p className="mt-2 break-words text-[11px] text-zinc-500" translate="no">VDOT {result.estimated_vdot?.value ?? "--"}{result.estimated_vdot ? ` · ${calculationMetadata(result.estimated_vdot)}` : ""}</p>
        {result.noisy_reasons.length ? <p className="mt-1 break-words text-[11px] text-orange-200" translate="no">{result.noisy_reasons.join(" · ")}</p> : null}
      </div>)}
      {!results.length ? <p className="text-xs text-zinc-500">Нет сохраненных результатов этого типа.</p> : null}
    </div>
    <div className="hidden overflow-x-auto md:block">
      <table className="w-full min-w-[720px] text-left text-xs">
        <thead className="border-b border-zinc-800 text-[10px] uppercase tracking-[0.14em] text-zinc-500"><tr><th className="px-4 py-2">Result</th><th>Date</th><th>Distance</th><th>Time</th><th>Pace</th><th>VDOT</th><th>Signal</th></tr></thead>
        <tbody>{results.map((result) => <tr key={result.id} className="border-b border-zinc-900 last:border-0 align-top hover:bg-zinc-900/60"><td className="px-4 py-2 font-medium text-white">{result.name}<div className="text-[11px] text-zinc-500">#{result.id} · {result.source} · {result.terrain}</div></td><td className="text-zinc-400">{formatDateTime(result.result_date)}</td><td>{result.distance_km.toFixed(2)} {kmUnit()}</td><td>{formatDuration(result.duration_seconds)}</td><td>{formatPace(result.pace_seconds_per_km)}{perKmUnit()}</td><td>{result.estimated_vdot?.value ?? "--"}{result.estimated_vdot ? <div className="mt-1 max-w-[13rem] text-[10px] text-zinc-600">{calculationMetadata(result.estimated_vdot)}</div> : null}</td><td><Badge className={result.is_noisy ? "border-orange-400/40 bg-orange-400/15 text-orange-100" : confidenceClass(result.estimated_vdot?.confidence)}>{result.is_noisy ? "noisy" : result.estimated_vdot?.confidence || "low"}</Badge>{result.noisy_reasons.length ? <div className="mt-1 max-w-[11rem] text-[10px] text-zinc-500">{result.noisy_reasons.join(" · ")}</div> : null}</td></tr>)}</tbody>
      </table>
      {!results.length ? <p className="p-4 text-xs text-zinc-500">Нет сохраненных результатов этого типа.</p> : null}
    </div>
  </Card>
}

function PerformancePredictions({ predictions }: { predictions: PerformancePrediction[] }) {
  return <Card>
    <CardHeader><div><CardTitle>Equivalent race predictions</CardTitle><p className="text-xs text-zinc-500">Riegel predictions show confidence and extrapolation warnings.</p></div><Badge>{predictions.length} targets</Badge></CardHeader>
    <div className="grid gap-2 p-4 md:hidden">
      {predictions.map((prediction) => <div key={`mobile-prediction-${prediction.label}`} className="min-w-0 rounded-md border border-zinc-800 bg-zinc-950 p-3 text-xs">
        <div className="flex flex-wrap items-start justify-between gap-2"><div><p className="font-semibold text-white">{prediction.label}</p><p className="mt-1 text-zinc-500">{prediction.target_distance_km} {kmUnit()} · source {prediction.source_distance_km?.toFixed(2) ?? "--"} {kmUnit()}</p></div><Badge className={confidenceClass(prediction.confidence)}>{prediction.confidence}</Badge></div>
        <div className="mt-3 grid grid-cols-2 gap-2 text-center"><Stat label="prediction" value={formatDuration(prediction.predicted_duration_seconds)} /><Stat label="pace" value={`${formatPace(prediction.predicted_pace_seconds_per_km)}${perKmUnit()}`} /></div>
        <p className="mt-2 break-words text-[11px] text-zinc-500" translate="no">{prediction.source_result_name || "--"} · ratio {prediction.extrapolation_ratio ?? "--"}</p>
        <p className="mt-1 break-words text-[11px] text-zinc-600" translate="no">{prediction.warnings.length ? prediction.warnings.join(" · ") : prediction.extrapolation_limited ? "extrapolation limited" : prediction.noisy ? "noisy source" : "within range"} · {prediction.method} · {prediction.source_reference}</p>
      </div>)}
      {!predictions.length ? <p className="text-xs text-zinc-500">Нужен race/time trial результат &gt;= 3 км для прогнозов.</p> : null}
    </div>
    <div className="hidden overflow-x-auto md:block">
      <table className="w-full min-w-[680px] text-left text-xs">
        <thead className="border-b border-zinc-800 text-[10px] uppercase tracking-[0.14em] text-zinc-500"><tr><th className="px-4 py-2">Target</th><th>Prediction</th><th>Pace</th><th>Source</th><th>Confidence</th><th>Notes</th></tr></thead>
        <tbody>{predictions.map((prediction) => <tr key={prediction.label} className="border-b border-zinc-900 last:border-0 align-top hover:bg-zinc-900/60"><td className="px-4 py-2 font-semibold text-white">{prediction.label}<div className="text-[11px] text-zinc-500">{prediction.target_distance_km} {kmUnit()}</div></td><td>{formatDuration(prediction.predicted_duration_seconds)}</td><td>{formatPace(prediction.predicted_pace_seconds_per_km)}{perKmUnit()}</td><td>{prediction.source_result_name || "--"}<div className="text-[11px] text-zinc-500">ratio {prediction.extrapolation_ratio ?? "--"}</div><div className="text-[10px] text-zinc-600">source {prediction.source_distance_km?.toFixed(2) ?? "--"} {kmUnit()} · {formatDuration(prediction.source_duration_seconds)}</div></td><td><Badge className={confidenceClass(prediction.confidence)}>{prediction.confidence}</Badge></td><td className="max-w-[15rem] text-zinc-500">{prediction.warnings.length ? prediction.warnings.join(" · ") : prediction.extrapolation_limited ? "extrapolation limited" : prediction.noisy ? "noisy source" : "within range"}<div className="mt-1 text-[10px] text-zinc-600">{prediction.method} · {prediction.source_reference}</div></td></tr>)}</tbody>
      </table>
      {!predictions.length ? <p className="p-4 text-xs text-zinc-500">Нужен race/time trial результат &gt;= 3 км для прогнозов.</p> : null}
    </div>
  </Card>
}

function PerformancePbs({ pbs, latestPb }: { pbs: PerformancePb[]; latestPb?: PerformancePb }) {
  return <Card>
    <CardHeader><div><CardTitle>Personal bests</CardTitle><p className="text-xs text-zinc-500">PB uses near-exact race/time trial distances only.</p></div><Badge>{latestPb ? latestPb.label : "--"}</Badge></CardHeader>
    <div className="divide-y divide-zinc-800">
      {pbs.map((pb) => <div key={pb.label} className="grid gap-2 px-4 py-3 text-xs md:grid-cols-[4.5rem_1fr_auto]" translate="no"><div className="font-semibold text-white">{pb.label}</div><div><p className="text-zinc-300">{formatDuration(pb.normalized_duration_seconds)} · {formatPace(pb.pace_seconds_per_km)}{perKmUnit()}</p><p className="mt-1 text-zinc-500">{pb.name} · {formatDateTime(pb.result_date)} · actual {pb.distance_km.toFixed(2)} {kmUnit()}</p>{pb.estimated_vdot ? <p className="mt-1 text-[11px] text-zinc-600">VDOT: {calculationMetadata(pb.estimated_vdot)}</p> : null}{pb.noisy_reasons.length ? <p className="mt-1 text-[11px] text-orange-200">Noisy: {pb.noisy_reasons.join(" · ")}</p> : null}</div><Badge className={pb.is_noisy ? "border-orange-400/40 bg-orange-400/15 text-orange-100" : "border-zinc-700 bg-zinc-900 text-zinc-300"}>VDOT {pb.estimated_vdot?.value ?? "--"}</Badge></div>)}
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
      {points.map((point) => <div key={point.result_id} className="grid grid-cols-[6rem_1fr_4.5rem] items-center gap-2 text-[11px]"><span className="truncate text-zinc-500">{dateValue(point.result_date).toLocaleDateString(languageLocale(), { month: "short", day: "2-digit" })}</span><div className="h-2 rounded bg-zinc-900"><div className="h-full rounded bg-orange-400" style={{ width: `${Math.max(4, min / point.threshold_pace_seconds_per_km * 100)}%` }} /></div><strong className="text-right text-zinc-300">{formatPace(point.threshold_pace_seconds_per_km)}</strong><span className="col-span-full text-[10px] text-zinc-600">{point.source} · {point.confidence}</span></div>)}
      {!points.length ? <p className="text-xs text-zinc-500">Добавьте результаты, чтобы увидеть trend.</p> : null}
    </div>
  </Card>
}

function formatPerformanceZoneRange(zone: PerformancePaceZone) {
  const format = (value: number | null) => value === null ? "--" : zone.unit === "seconds_per_km" ? `${formatPace(Math.round(value))}${perKmUnit()}` : `${value}`
  return `${format(zone.lower_value)} - ${format(zone.upper_value)}`
}

function PerformancePaceZones({ zones }: { zones: PerformancePaceZone[] }) {
  return <Card>
    <CardHeader><div><CardTitle>Pace zones</CardTitle><p className="text-xs text-zinc-500">Derived from profile threshold pace or VDOT threshold estimate.</p></div><Badge>{zones.length} zones</Badge></CardHeader>
    <div className="grid gap-2 p-4 md:hidden">
      {zones.map((zone) => <div key={`mobile-pace-zone-${zone.zone_key}`} className="min-w-0 rounded-md border border-zinc-800 bg-zinc-950 p-3 text-xs"><div className="flex flex-wrap items-start justify-between gap-2"><div><p className="font-medium text-white">{zone.label || zone.zone_key}</p><p className="mt-1 font-mono text-[10px] uppercase tracking-[0.14em] text-zinc-600">{zone.zone_key}</p></div><Badge className={confidenceClass(zone.confidence)}>{zone.confidence}</Badge></div><p className="mt-2 text-zinc-300">{formatPerformanceZoneRange(zone)}</p><p className="mt-1 break-words text-[11px] text-zinc-600" translate="no">{zone.method} · {zone.source_reference}</p></div>)}
      {!zones.length ? <p className="text-xs text-zinc-500">Нет данных для pace zones.</p> : null}
    </div>
    <div className="hidden overflow-x-auto md:block">
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
      <CollapsibleSection title="Create goal" summary={<Badge>manual</Badge>}>
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
      </CollapsibleSection>

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
      <div><p className="font-mono text-[10px] uppercase tracking-[0.18em] text-zinc-500">Active race</p><h3 className="mt-1 text-base font-semibold text-white" translate="no">{goal.title}</h3><p className="mt-1 text-xs text-zinc-500" translate="no">{formatDistance(goal.race_distance_km)} · {formatDate(goal.target_date)} · priority {goal.priority || "--"}</p></div>
      <Badge className={signalClass(goal.progress.readiness)} translate="no">{goal.progress.readiness}</Badge>
    </div>
    <div className="mt-3 grid gap-2 md:grid-cols-4">
      <Stat label="target" value={formatTargetTime(goal.target_time_seconds)} />
      <Stat label="prediction" value={range ? formatDuration(range.predicted_duration_seconds) : "--"} />
      <Stat label="range" value={range ? `${formatDuration(range.lower_seconds)}-${formatDuration(range.upper_seconds)}` : "--"} />
      <Stat label="VDOT" value={goal.current_fitness?.estimate?.value ?? "--"} />
    </div>
    <div className="mt-3 grid gap-2 md:grid-cols-3">{goal.milestones.map((milestone) => <div key={milestone.title} className="rounded-md border border-zinc-800 bg-zinc-950 p-2 text-xs" translate="no"><div className="flex items-center justify-between gap-2"><p className="font-medium text-white">{milestone.title}</p><Badge className={signalClass(milestone.status)}>{milestone.status}</Badge></div><p className="mt-1 text-zinc-500">due {formatDate(milestone.due_date)} · target {String(milestone.target ?? "--")}</p>{milestone.value !== undefined ? <p className="mt-1 text-zinc-400">current {milestone.value}</p> : null}</div>)}</div>
  </Card>
}

function GoalCard({ goal, busy, onStatus, onDelete }: { goal: RunningGoal; busy: boolean; onStatus: (status: string) => void; onDelete: () => void }) {
  return <Card className="p-3 text-xs">
    <div className="flex flex-wrap items-start justify-between gap-2">
      <div translate="no"><p className="font-semibold text-white">{goal.title}<span className="ml-2 font-mono text-[10px] text-zinc-500">#{goal.id}</span></p><p className="mt-1 text-zinc-500">{goalTypeLabel(goal.goal_type)} · {goalProgressText(goal)} · {goal.unit || goal.progress.metric}</p></div>
      <div className="flex flex-wrap gap-1"><Badge className={planStatusClass(goal.status)} translate="no">{goal.status}</Badge><Badge className={signalClass(goal.progress.readiness)} translate="no">{goal.progress.readiness}</Badge></div>
    </div>
    <div className="mt-2 grid gap-2 md:grid-cols-3">
      <p className="rounded-md border border-zinc-900 bg-zinc-950 px-2 py-1.5 text-zinc-400">Race: {formatDistance(goal.race_distance_km)} · {formatDate(goal.target_date)}</p>
      <p className="rounded-md border border-zinc-900 bg-zinc-950 px-2 py-1.5 text-zinc-400" translate="no">Plan: {goal.plan ? `${goal.plan.title} (${Math.round((goal.plan.adherence.completion_rate || 0) * 100)}%)` : "not linked"}</p>
      <p className="rounded-md border border-zinc-900 bg-zinc-950 px-2 py-1.5 text-zinc-400">Prediction: {goal.predicted_time_range ? `${formatDuration(goal.predicted_time_range.predicted_duration_seconds)} · ${goal.predicted_time_range.confidence}` : "--"}</p>
    </div>
    {goal.course_notes || goal.reason ? <p className="mt-2 leading-5 text-zinc-500" translate="no">{goal.course_notes || goal.reason}</p> : null}
    <CollapsibleSection title="More actions" className="mt-3"><div className="flex flex-wrap gap-2"><Button size="sm" variant="secondary" disabled={busy} onClick={() => onStatus(goal.status === "paused" ? "active" : "paused")}>{goal.status === "paused" ? "Resume" : "Pause"}</Button><Button size="sm" variant="secondary" disabled={busy} onClick={() => onStatus("completed")}>Complete</Button><Button size="sm" variant="secondary" disabled={busy} onClick={() => onStatus("missed")}>Missed</Button><Button size="sm" variant="secondary" disabled={busy} onClick={() => onStatus("archived")}>Archive</Button><Button size="sm" variant="secondary" disabled={busy} onClick={onDelete}>Delete</Button></div></CollapsibleSection>
  </Card>
}

function ProfileZones({ profile, completeness, safety, zones, measurements, onboardingMode, onDismissOnboarding, onChanged }: { profile: AthleteProfile | null; completeness: ProfileCompleteness | null; safety: SafetyCheck | null; zones: Zones | null; measurements: AthleteMeasurement[]; onboardingMode?: boolean; onDismissOnboarding?: () => void; onChanged: () => Promise<void> }) {
  const [zoneMessage, setZoneMessage] = useState("")
  const [zoneError, setZoneError] = useState("")
  const [savingZones, setSavingZones] = useState(false)

  if (!profile) return <Card className="p-4 text-sm text-zinc-400">{uiText("Загружаем профиль...", "Loading profile...")}</Card>

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
    await api.recalculateZones()
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
    await api.recalculateZones()
    form.reset()
    await onChanged()
  }

  async function recalculateZones() {
    await api.recalculateZones()
    await onChanged()
  }

  async function submitManualHrZones(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    const rows = DEFAULT_HR_ZONE_ROWS.map((row) => ({
      zone_key: row.zone_key,
      label: stringOrNull(data.get(`${row.zone_key}_label`)) || row.label,
      lower_value: numberOrNull(data.get(`${row.zone_key}_lower`)),
      upper_value: numberOrNull(data.get(`${row.zone_key}_upper`)),
      unit: "bpm",
    }))
    setZoneError("")
    setZoneMessage("")
    const invalid = rows.find((row) => row.lower_value === null && row.upper_value === null)
    if (invalid) {
      setZoneError(`${invalid.zone_key.toUpperCase()} must define at least min or max bpm.`)
      return
    }
    const reversed = rows.find((row) => row.lower_value !== null && row.upper_value !== null && row.lower_value > row.upper_value)
    if (reversed) {
      setZoneError(`${reversed.zone_key.toUpperCase()} min bpm must be <= max bpm.`)
      return
    }
    for (let index = 0; index < rows.length; index += 1) {
      const row = rows[index]
      const previous = rows[index - 1]
      if (index > 0 && row.lower_value === null) {
        setZoneError(`${row.zone_key.toUpperCase()} must define min bpm to avoid overlap with lower zones.`)
        return
      }
      if (index < rows.length - 1 && row.upper_value === null) {
        setZoneError(`${row.zone_key.toUpperCase()} must define max bpm to avoid overlap with higher zones.`)
        return
      }
      if (previous?.upper_value !== null && previous?.upper_value !== undefined && row.lower_value !== null && row.lower_value <= previous.upper_value) {
        setZoneError(`${row.zone_key.toUpperCase()} min bpm must be greater than ${previous.zone_key.toUpperCase()} max bpm.`)
        return
      }
    }
    setSavingZones(true)
    try {
      await api.replaceHrZones(rows)
      setZoneMessage("Manual HR zones saved. Calculated HR zones are suppressed until overrides are cleared.")
      await onChanged()
    } catch (caught) {
      console.error(caught)
      setZoneError(apiErrorMessage(caught, "Manual HR zones were not saved"))
    } finally {
      setSavingZones(false)
    }
  }

  async function clearManualHrZones() {
    setSavingZones(true)
    setZoneError("")
    setZoneMessage("")
    try {
      await api.replaceHrZones([])
      await api.recalculateZones()
      setZoneMessage("Manual HR overrides cleared. Calculated HR zones restored when profile inputs are available.")
      await onChanged()
    } catch (caught) {
      console.error(caught)
      setZoneError(apiErrorMessage(caught, "Manual HR zones were not cleared"))
    } finally {
      setSavingZones(false)
    }
  }

  const completenessScore = Math.round((completeness?.score || 0) * 100)
  const hrRows = manualHrZoneRows(zones?.hr || [])
  const hrZoneFormKey = hrRows.map((row) => `${row.zone_key}:${row.label}:${row.lower_value ?? ""}:${row.upper_value ?? ""}`).join("|")
  const hasManualHrZones = Boolean(zones?.hr.some((zone) => zone.method === "manual"))
  const onboardingReady = Boolean(completeness && completeness.score >= ONBOARDING_READY_SCORE)
  const zoneReadiness = profileZoneReadinessLabels(completeness)

  return <div className="grid gap-4">
    {onboardingMode ? <Card className="border-orange-400/30 bg-orange-400/10 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><p className="text-[11px] font-semibold text-orange-100">{uiText("Первичная настройка", "First setup")}</p><h2 className="mt-1 text-lg font-semibold text-white">{uiText("Заполните данные для безопасного плана", "Complete setup before planning")}</h2><p className="mt-2 max-w-2xl text-xs leading-5 text-orange-100/80">{uiText("Дни тренировок, пульс, ограничения и пороговые значения помогают сделать план осторожнее и точнее.", "Training days, heart-rate inputs, constraints and thresholds make the plan safer and more precise.")}</p></div>
        <div className="flex flex-wrap gap-2"><Badge>{completenessScore}%</Badge><Button type="button" size="sm" variant="secondary" onClick={onDismissOnboarding}>{uiText("Пропустить пока", "Skip for now")}</Button></div>
      </div>
      <div className="mt-3 grid gap-2 text-xs md:grid-cols-2">
        <div className="rounded-md border border-orange-400/20 bg-black/20 p-3"><p className="font-semibold text-white">{uiText("Что добавить", "What to add")}</p><p className="mt-1 text-orange-100/80">{completeness?.missing.length ? completeness.missing.map(missingLabel).join(" · ") : uiText("Основные данные заполнены.", "Required setup inputs are present.")}</p></div>
        <div className="rounded-md border border-orange-400/20 bg-black/20 p-3"><p className="font-semibold text-white">{uiText("Готовность зон", "Zone readiness")}</p><p className="mt-1 text-orange-100/80">{zoneReadiness.join(" · ") || uiText("Загружаем готовность зон.", "Loading zone readiness.")}</p>{onboardingReady ? <p className="mt-1 text-orange-100">{uiText("Готово: можно строить план.", "Ready: planning can start.")}</p> : null}</div>
      </div>
    </Card> : null}
    <Card className="overflow-hidden border-orange-400/25 bg-[radial-gradient(circle_at_top_right,rgba(251,146,60,0.14),transparent_32%),#0b0b0b] p-4">
      <div className="grid gap-4 lg:grid-cols-[1fr_18rem] lg:items-end">
        <div>
          <p className="text-xs font-semibold text-orange-200">{uiText("Что нужно плану", "What the plan needs")}</p>
          <h2 className="mt-2 text-2xl font-semibold tracking-tight text-white">{completeness?.missing.length ? uiText("Заполните только данные, которые влияют на тренировки", "Fill only the details that affect training") : uiText("Профиль готов для спокойного планирования", "Profile is ready for calm planning")}</h2>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-zinc-300">{completeness?.missing.length ? uiText(`Сейчас важнее всего: ${completeness.missing.slice(0, 3).map(missingLabel).join(", ")}. Остальное можно оставить на потом.`, `Most useful now: ${completeness.missing.slice(0, 3).map(missingLabel).join(", ")}. Everything else can wait.`) : uiText("Дни, пульс и ограничения достаточно заполнены. Меняйте профиль только когда меняется реальная ситуация.", "Training days, heart rate and limits are filled enough. Change the profile only when your real situation changes.")}</p>
        </div>
        <div className="rounded-xl border border-orange-400/20 bg-black/20 p-3 text-xs">
          <p className="font-semibold text-orange-100">{uiText("Готовность", "Readiness")}: {completenessScore}%</p>
          <div className="mt-2 h-2 rounded-full bg-zinc-900"><div className="h-full rounded-full bg-orange-400" style={{ width: `${completenessScore}%` }} /></div>
          <p className="mt-2 leading-5 text-orange-100/75">{safetyMessageLabel(safety?.message)}</p>
        </div>
      </div>
    </Card>
    <div className="grid gap-4 xl:grid-cols-[1fr_22rem]">
      <Card>
        <CardHeader><div><CardTitle>{uiText("Профиль бегуна", "Runner profile")}</CardTitle><p className="text-xs text-zinc-500">{uiText("Дни тренировок, пульс и ограничения, которые влияют на план.", "Training days, heart-rate inputs and constraints that affect the plan.")}</p></div><Badge>{confidenceLabel(completeness?.confidence || "low")}</Badge></CardHeader>
        <form key={profile.updated_at} onSubmit={submitProfile} className="grid gap-4 p-4 text-xs">
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-zinc-800 bg-zinc-950/70 p-3">
            <div><p className="font-semibold text-white">{uiText("Сохранить базовые данные", "Save essential setup")}</p><p className="mt-1 text-zinc-500">{uiText("Это обновит зоны и безопасные рекомендации.", "This updates zones and safer recommendations.")}</p></div>
            <Button type="submit">{uiText("Сохранить профиль", "Save profile")}</Button>
          </div>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            <CollapsibleSection title={uiText("Когда вы можете бегать", "Training availability")} defaultOpen>
              <div className="grid gap-3">
                <Field label={uiText("Дни тренировок", "Training days")}><Input name="preferred_weekdays" defaultValue={(profile.preferred_weekdays || []).join(",")} placeholder="1,3,6" /></Field>
                <Field label={uiText("День длинной", "Long run day")}><Select name="long_run_weekday" defaultValue={profile.long_run_weekday || ""}><option value="">{uiText("авто", "Auto")}</option>{[1, 2, 3, 4, 5, 6, 7].map((day) => <option key={day} value={day}>{weekdayLabel(day)}</option>)}</Select></Field>
                <Field label={uiText("Макс. длительность, мин", "Max duration, min")}><Input name="max_run_duration_minutes" type="number" min="15" max="600" step="5" defaultValue={profile.max_run_duration_minutes ?? ""} placeholder={uiText("необязательно", "optional")} /></Field>
              </div>
            </CollapsibleSection>
            <CollapsibleSection title={uiText("Пульс и пороги", "Heart rate and thresholds")} defaultOpen>
              <div className="grid gap-3">
                <div className="grid gap-2 sm:grid-cols-2"><Field label={uiText("Пульс покоя", "Resting heart rate")}><Input name="resting_heart_rate_bpm" type="number" min="25" max="120" defaultValue={profile.resting_heart_rate_bpm ?? ""} /></Field><Field label={uiText("Максимальный пульс", "Maximum heart rate")}><Input name="max_heart_rate_bpm" type="number" min="80" max="240" defaultValue={profile.max_heart_rate_bpm ?? ""} /></Field></div>
                <Field label={uiText("Откуда максимальный пульс", "Maximum heart-rate source")}><Select name="max_hr_source" defaultValue={profile.max_hr_source || "manual"}><option value="manual">{uiText("Введен вручную", "Entered manually")}</option><option value="measured">{uiText("Измерен", "Measured")}</option><option value="tanaka_estimated">{uiText("Оценка по возрасту", "Age estimate")}</option></Select></Field>
                <div className="grid gap-2 sm:grid-cols-2"><Field label={uiText("Пороговый пульс", "Threshold heart rate")}><Input name="lactate_threshold_hr_bpm" type="number" min="60" max="230" defaultValue={profile.lactate_threshold_hr_bpm ?? ""} /></Field><Field label={uiText("Пороговый темп, сек/км", "Threshold pace, sec/km")}><Input name="lactate_threshold_pace_seconds_per_km" type="number" min="120" max="1200" defaultValue={profile.lactate_threshold_pace_seconds_per_km ?? ""} /></Field></div>
                <Field label={uiText("VO2max, если известен", "VO2max, if known")}><Input name="vo2max" type="number" min="10" max="100" step="0.1" defaultValue={profile.vo2max ?? ""} placeholder={uiText("необязательно", "optional")} /></Field>
              </div>
            </CollapsibleSection>
            <CollapsibleSection title={uiText("Восстановление и безопасность", "Recovery and safety")} className="md:col-span-2" defaultOpen={onboardingMode}>
              <div className="grid gap-3 md:grid-cols-2">
                <Field label={uiText("Травмы / ограничения", "Injuries / limits")}><Input name="injury_notes" defaultValue={profile.injury_notes || ""} placeholder={uiText("травмы, ограничения", "injuries, limitations")} /></Field>
                <Field label={uiText("Медицинские особенности", "Health notes")}><Input name="health_conditions" defaultValue={profile.health_conditions || ""} placeholder={uiText("астма, давление, прочее", "asthma, blood pressure, other")} /></Field>
                <Field label={uiText("Восстановление сейчас", "Current recovery")}><Select name="recovery_status" defaultValue={profile.recovery_status || "normal"}><option value="fresh">{uiText("свежо", "Fresh")}</option><option value="normal">{uiText("нормально", "Normal")}</option><option value="tired">{uiText("усталость", "Tired")}</option><option value="strained">{uiText("перегруз", "Strained")}</option><option value="injured">{uiText("травма", "Injured")}</option><option value="unknown">{uiText("не знаю", "Unknown")}</option></Select></Field>
                <label className="flex h-8 items-center gap-2 rounded-md border border-zinc-800 bg-zinc-950 px-2.5 text-zinc-400"><input name="conservative_mode" type="checkbox" defaultChecked={profile.conservative_mode} /> {uiText("делать план осторожнее", "keep the plan conservative")}</label>
              </div>
            </CollapsibleSection>
            <CollapsibleSection title={uiText("Личные данные", "Personal details")}>
              <div className="grid gap-3">
                <Field label={uiText("Дата рождения", "Date of birth")}><Input name="date_of_birth" type="date" defaultValue={profile.date_of_birth || ""} /></Field>
                <Field label={uiText("Пол", "Sex")}><Select name="sex" defaultValue={profile.sex}><option value="unspecified">{uiText("не указан", "Not specified")}</option><option value="male">{uiText("мужской", "Male")}</option><option value="female">{uiText("женский", "Female")}</option><option value="other">{uiText("другой", "Other")}</option></Select></Field>
                <Field label={uiText("Часовой пояс", "Timezone")}><Input name="timezone" defaultValue={profile.timezone || ""} placeholder="Europe/Moscow" /></Field>
                <Field label={uiText("Язык данных", "Data locale")}><Input name="locale" defaultValue={profile.locale || ""} placeholder="ru-RU" /></Field>
              </div>
            </CollapsibleSection>
            <CollapsibleSection title={uiText("Тело и единицы", "Body and units")}>
              <div className="grid gap-3">
                <Field label={uiText("Вес, кг", "Weight, kg")}><Input name="weight_kg" type="number" min="25" max="250" step="0.1" defaultValue={profile.weight_kg ?? ""} placeholder={uiText("например 72.5", "for example 72.5")} /></Field>
                <Field label={uiText("Рост, см", "Height, cm")}><Input name="height_cm" type="number" min="80" max="260" step="0.1" defaultValue={profile.height_cm ?? ""} /></Field>
                <Field label={uiText("Единицы", "Units")}><Select name="unit_system" defaultValue={profile.unit_system || "metric"}><option value="metric">{uiText("метрические", "Metric")}</option><option value="imperial">{uiText("имперские", "Imperial")}</option></Select></Field>
              </div>
            </CollapsibleSection>
          </div>
          <div className="flex flex-wrap items-center gap-2"><Button type="submit">{uiText("Сохранить профиль", "Save profile")}</Button><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{uiText("дни", "days")} {weekdayListLabel(profile.preferred_weekdays)}</Badge><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{uiText("длинная", "long")} {weekdayLabel(profile.long_run_weekday)}</Badge><Badge className={signalClass(profile.recovery_status)}>{signalStatusLabel(profile.recovery_status)}</Badge></div>
        </form>
      </Card>

      <div className="grid gap-4">
        <Card className="p-4">
          <div className="flex items-center justify-between"><p className="text-sm font-semibold text-white">{uiText("Готовность профиля", "Profile readiness")}</p><Badge>{completenessScore}%</Badge></div>
          <div className="mt-3 h-2 rounded bg-zinc-900"><div className="h-full rounded bg-orange-400" style={{ width: `${completenessScore}%` }} /></div>
          <div className="mt-3 grid gap-1 text-xs text-zinc-400">
            {zoneReadiness.map((item) => <span key={item}>{item}</span>)}
          </div>
          {completeness?.missing.length ? <div className="mt-3 flex flex-wrap gap-1">{completeness.missing.map((field) => <Badge key={field} className="border-zinc-700 bg-zinc-900 text-zinc-300">{missingLabel(field)}</Badge>)}</div> : null}
        </Card>
        <Card className="p-4">
          <p className="text-sm font-semibold text-white">{uiText("Безопасность", "Safety")}</p>
          <p className="mt-2 text-xs leading-5 text-zinc-400">{safetyMessageLabel(safety?.message)}</p>
          {safety?.warnings.length ? <div className="mt-3 grid gap-2">{safety.warnings.map((warning) => <div key={warning} className="rounded-md border border-orange-400/20 bg-orange-400/10 px-2 py-1.5 text-xs text-orange-100">{safetyWarningLabel(warning)}</div>)}</div> : <p className="mt-3 text-xs text-zinc-500">{uiText("Нет активных предупреждений.", "No active warnings.")}</p>}
        </Card>
      </div>
    </div>

    <CollapsibleSection title={uiText("Зоны, измерения и точные настройки", "Zones, measurements and exact overrides")} summary={<Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{uiText("продвинуто", "advanced")}</Badge>}>
    <div className="grid gap-4 xl:grid-cols-[1fr_1fr]">
      <Card>
        <CardHeader><div><CardTitle>{uiText("Тренировочные зоны", "Training zones")}</CardTitle><p className="text-xs text-zinc-500">{uiText("Обычно их можно не трогать. Точные методы скрыты в деталях.", "Most runners can leave these alone. Exact methods are hidden in details.")}</p></div><Button size="sm" onClick={recalculateZones}>{uiText("Пересчитать", "Recalculate")}</Button></CardHeader>
        <div className="grid gap-4 p-4">
          <ZoneTable title="Heart rate" zones={zones?.hr || []} />
          <ZoneTable title="Pace" zones={zones?.pace || []} />
          <CollapsibleSection title="Manual HR override" summary={<Badge className={hasManualHrZones ? "border-orange-400/40 bg-orange-400/15 text-orange-100" : "border-zinc-700 bg-zinc-900 text-zinc-300"}>{hasManualHrZones ? "manual active" : "calculated active"}</Badge>} defaultOpen={hasManualHrZones}>
            <div className="flex flex-wrap items-center justify-between gap-2"><div><p className="text-xs font-semibold text-white">Manual HR override</p><p className="mt-1 text-[11px] text-zinc-500">Save manual bpm ranges when lab/device zones should override calculated HR zones.</p></div><Badge className={hasManualHrZones ? "border-orange-400/40 bg-orange-400/15 text-orange-100" : "border-zinc-700 bg-zinc-900 text-zinc-300"}>{hasManualHrZones ? "manual active" : "calculated active"}</Badge></div>
            <form key={hrZoneFormKey} onSubmit={submitManualHrZones} className="mt-3 grid gap-2 text-xs">
              {hrRows.map((row) => <div key={row.zone_key} className="grid gap-2 md:grid-cols-[5rem_1fr_6rem_6rem]"><span className="flex items-center font-mono text-[10px] uppercase tracking-[0.14em] text-zinc-500">{row.zone_key}</span><Input name={`${row.zone_key}_label`} defaultValue={row.label} placeholder="Label" /><Input name={`${row.zone_key}_lower`} type="number" min="30" max="240" defaultValue={row.lower_value ?? ""} placeholder="min bpm" /><Input name={`${row.zone_key}_upper`} type="number" min="30" max="240" defaultValue={row.upper_value ?? ""} placeholder="max bpm" /></div>)}
              <div className="flex flex-wrap items-center gap-2"><Button type="submit" size="sm" disabled={savingZones}>{savingZones ? "Saving..." : "Save manual HR zones"}</Button><Button type="button" size="sm" variant="secondary" disabled={savingZones || !hasManualHrZones} onClick={clearManualHrZones}>Clear manual HR zones</Button></div>
              {zoneMessage ? <p className="rounded-md border border-orange-400/20 bg-orange-400/10 px-2 py-1.5 text-[11px] text-orange-100">{zoneMessage}</p> : null}
              {zoneError ? <p className="rounded-md border border-rose-400/20 bg-rose-400/10 px-2 py-1.5 text-[11px] text-rose-100">{zoneError}</p> : null}
            </form>
          </CollapsibleSection>
        </div>
      </Card>

      <Card>
        <CardHeader><div><CardTitle>Measurements</CardTitle><p className="text-xs text-zinc-500">История ручных и device-derived измерений.</p></div><Badge>{measurements.length} rows</Badge></CardHeader>
        <CollapsibleSection title="Add measurement" className="m-4">
        <form onSubmit={submitMeasurement} className="grid gap-3 text-xs md:grid-cols-2">
          <Field label="Тип"><Select name="measurement_type"><option value="weight">Вес</option><option value="resting_hr">Пульс покоя</option><option value="max_hr">HRmax</option><option value="lactate_threshold">Lactate threshold</option><option value="vo2max">VO2max</option><option value="note">Note</option></Select></Field>
          <Field label="Значение"><Input name="value_numeric" type="number" step="0.1" placeholder="число" /></Field>
          <Field label="Пороговый темп, сек/км"><Input name="threshold_pace_seconds_per_km" type="number" min="120" max="1200" placeholder="для LT" /></Field>
          <Field label="Дата"><Input name="measured_at" type="datetime-local" /></Field>
          <Field label="Источник"><Select name="source"><option value="manual">Manual</option><option value="device">Device</option><option value="lab">Lab</option><option value="screenshot">Screenshot</option></Select></Field>
          <Field label="Заметка"><Input name="notes" placeholder="опционально" /></Field>
          <div className="md:col-span-2"><Button type="submit" size="sm">Add measurement</Button></div>
        </form>
        </CollapsibleSection>
        <div className="grid gap-2 p-4 md:hidden">
          {measurements.map((measurement) => <div key={`measurement-mobile-${measurement.source_model}-${measurement.id}`} className="min-w-0 rounded-md border border-zinc-800 bg-zinc-950 p-3 text-xs"><div className="flex flex-wrap items-start justify-between gap-2"><div className="min-w-0"><p className="font-medium text-white">{measurement.measurement_type}</p><p className="mt-1 break-words text-zinc-500">{measurement.notes || measurement.source_model}</p></div><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{measurement.source}</Badge></div><div className="mt-2 grid grid-cols-2 gap-2 text-center"><Stat label="value" value={measurementValueLabel(measurement)} /><Stat label="date" value={measurement.measured_at ? formatLocalDateTime(measurement.measured_at) : "--"} /></div></div>)}
          {!measurements.length && <p className="text-xs text-zinc-500">Измерений пока нет.</p>}
        </div>
        <div className="hidden max-h-72 overflow-auto md:block">
          <table className="w-full min-w-[540px] text-left text-xs">
            <thead className="sticky top-0 border-b border-zinc-800 bg-zinc-950 text-[10px] uppercase tracking-[0.14em] text-zinc-500"><tr><th className="px-4 py-2">Type</th><th>Value</th><th>Source</th><th>Date</th></tr></thead>
            <tbody>{measurements.map((measurement) => <tr key={`${measurement.source_model}-${measurement.id}`} className="border-b border-zinc-900 last:border-0"><td className="px-4 py-2 font-medium text-white">{measurement.measurement_type}<div className="text-[11px] text-zinc-500">{measurement.notes || measurement.source_model}</div></td><td>{measurementValueLabel(measurement)}</td><td>{measurement.source}</td><td className="text-zinc-400">{measurement.measured_at ? formatLocalDateTime(measurement.measured_at) : "--"}</td></tr>)}</tbody>
          </table>
          {!measurements.length && <p className="p-4 text-xs text-zinc-500">Измерений пока нет.</p>}
        </div>
      </Card>
    </div>
    </CollapsibleSection>
  </div>
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="grid gap-1"><span className="text-[11px] font-medium text-zinc-500">{label}</span>{children}</label>
}

function ZoneTable({ title, zones }: { title: string; zones: Zone[] }) {
  return <div className="min-w-0 rounded-md border border-zinc-800">
    <div className="flex min-w-0 flex-wrap items-center justify-between gap-2 border-b border-zinc-800 px-3 py-2"><p className="text-xs font-semibold text-white">{title}</p><Badge>{zones.length} zones</Badge></div>
    {zones.length ? <><div className="grid gap-2 p-3 md:hidden">{zones.map((zone) => <div key={`mobile-zone-${zone.method}-${zone.zone_key}-${zone.id || "calc"}`} className="min-w-0 rounded-md border border-zinc-800 bg-zinc-950 p-3 text-xs"><div className="flex flex-wrap items-start justify-between gap-2"><div><p className="font-medium text-white">{zone.label || zone.zone_key}</p><p className="text-[11px] text-zinc-500">{zone.zone_key}</p></div></div><p className="mt-2 text-zinc-300">{formatZoneRange(zone)}</p><CollapsibleSection title={uiText("Метод", "Method")} className="mt-2" summary={<Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{zone.confidence}</Badge>}><p className="break-words text-[11px] text-zinc-600" translate="no">{zone.method} · {zone.source_reference}</p></CollapsibleSection></div>)}</div><div className="hidden max-w-full overflow-x-auto md:block"><table className="w-full min-w-[520px] text-left text-xs">
      <thead className="text-[10px] uppercase tracking-[0.14em] text-zinc-500"><tr><th className="px-3 py-2">Zone</th><th>Range</th><th>Method</th><th>Confidence</th></tr></thead>
      <tbody>{zones.map((zone) => <tr key={`${zone.method}-${zone.zone_key}-${zone.id || "calc"}`} className="border-t border-zinc-900 align-top"><td className="px-3 py-2 font-medium text-white">{zone.label || zone.zone_key}<div className="font-mono text-[10px] text-zinc-600">{zone.zone_key}</div></td><td>{formatZoneRange(zone)}</td><td><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{zone.method}</Badge><div className="mt-1 max-w-[16rem] text-[10px] text-zinc-600">{zone.source_reference}</div></td><td>{zone.confidence}</td></tr>)}</tbody>
    </table></div></> : <p className="p-3 text-xs text-zinc-500">Нет данных для расчета.</p>}
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
  if (currentWorkout) return `${uiText("неделя", "week")} ${currentWorkout.week_index}`
  const nextWorkout = plan.workouts.find((workout) => workout.scheduled_date && workout.scheduled_date > weekEnd)
  return nextWorkout ? `${uiText("следующая", "next")} ${formatDate(nextWorkout.scheduled_date)}` : "--"
}

function planStatusClass(status: string) {
  if (status === "active") return "border-orange-400/40 bg-orange-400/15 text-orange-100"
  if (status === "completed") return "border-zinc-500 bg-zinc-800 text-zinc-100"
  if (status === "archived") return "border-zinc-800 bg-zinc-950 text-zinc-500"
  return "border-zinc-700 bg-zinc-900 text-zinc-300"
}

function planStatusLabel(status: string) {
  if (status === "active") return uiText("активная", "active")
  if (status === "completed") return uiText("завершена", "completed")
  if (status === "archived") return uiText("архив", "archived")
  if (status === "draft") return uiText("черновик", "draft")
  return status
}

function planGoalTypeLabel(goalType: string) {
  if (goalType === "5k") return uiText("5 км", "5K")
  if (goalType === "10k") return uiText("10 км", "10K")
  if (goalType === "half_marathon") return uiText("полумарафон", "half marathon")
  if (goalType === "marathon") return uiText("марафон", "marathon")
  if (goalType === "base_building") return uiText("база", "base")
  if (goalType === "custom") return uiText("своя цель", "custom goal")
  return goalType
}

function workoutTypeLabel(type?: string | null) {
  if (type === "easy") return uiText("легкий бег", "easy run")
  if (type === "recovery") return uiText("восстановление", "recovery")
  if (type === "strides") return uiText("легкий + ускорения", "easy + strides")
  if (type === "steady") return uiText("ровная работа", "steady")
  if (type === "interval") return uiText("интервалы", "intervals")
  if (type === "tempo") return uiText("темповая", "tempo")
  if (type === "threshold") return uiText("пороговая", "threshold")
  if (type === "hill") return uiText("горки", "hills")
  if (type === "long") return uiText("длинная", "long run")
  if (type === "race_pace") return uiText("темп старта", "race pace")
  if (type === "strength" || type === "ofp") return "ОФП"
  if (type === "mobility" || type === "prehab") return uiText("мобилити", "mobility")
  return type || uiText("тренировка", "workout")
}

function workoutStatusLabel(status: string) {
  if (status === "planned") return uiText("запланирована", "planned")
  if (status === "rescheduled") return uiText("перенесена", "rescheduled")
  if (status === "done") return uiText("сделана", "done")
  if (status === "missed") return uiText("пропущена", "missed")
  if (status === "skipped") return uiText("отменена", "skipped")
  return status
}

function workoutIntensityLabel(intensity?: string | null) {
  if (!intensity) return uiText("по плану", "planned")
  const lower = intensity.toLowerCase()
  if (lower.includes("easy-long")) return uiText("легко, долго", "easy-long")
  if (lower.includes("easy")) return uiText("легко", "easy")
  if (lower.includes("recovery")) return uiText("восстановительно", "recovery")
  if (lower.includes("steady")) return uiText("ровно", "steady")
  if (lower.includes("interval")) return uiText("быстро с отдыхом", "fast with recovery")
  if (lower.includes("tempo") || lower.includes("threshold")) return uiText("контролируемо быстро", "controlled fast")
  if (lower.includes("race")) return uiText("темп старта", "race pace")
  if (lower.includes("strides")) return uiText("легко + ускорения", "easy + strides")
  return uiText("по самочувствию", "by feel")
}

function trainingLevelLabel(level: string) {
  if (level === "beginner") return uiText("начинаем осторожно", "careful start")
  if (level === "intermediate") return uiText("средняя база", "moderate base")
  if (level === "advanced") return uiText("хорошая база", "strong base")
  if (level === "novice") return uiText("мало истории", "limited history")
  return level || uiText("по истории", "based on history")
}

function trendGranularityLabel(granularity?: string | null) {
  if (granularity === "week") return uiText("неделя", "week")
  if (granularity === "month") return uiText("месяц", "month")
  if (granularity === "day") return uiText("день", "day")
  return granularity || uiText("период", "period")
}

function insightCoachTitle(insight: AnalyticsInsight) {
  if (insight.severity === "critical" || insight.severity === "warning") return uiText("Стоит проверить нагрузку", "Check your load")
  return uiText("Наблюдение по прогрессу", "Progress note")
}

function insightCoachMessage(insight: AnalyticsInsight) {
  const text = `${insight.title} ${insight.message} ${insight.reasons.join(" ")}`.toLowerCase()
  if (text.includes("fatigue") || text.includes("устал")) return uiText("В последних данных есть признаки усталости. Следующую тяжелую работу лучше держать короче и спокойнее.", "Recent data suggests fatigue. Keep the next hard workout shorter and calmer.")
  if (text.includes("hard") || text.includes("intensity") || text.includes("быстр")) return uiText("Быстрых работ может быть многовато. Легкие дни должны оставаться действительно легкими.", "There may be too many hard efforts. Easy days should stay truly easy.")
  if (text.includes("volume") || text.includes("distance") || text.includes("объем") || text.includes("дистан")) return uiText("Объем меняется заметно. Лучше наращивать километры постепенно.", "Volume is changing noticeably. Build distance gradually.")
  return uiText("Это расчетная подсказка по последним тренировкам. Используйте ее как повод проверить самочувствие, а не как жесткий приказ.", "This is a calculated note from recent training. Use it as a reason to check how you feel, not as a strict command.")
}

function confidenceLabel(confidence: string) {
  if (confidence === "high") return uiText("данных достаточно", "enough data")
  if (confidence === "medium") return uiText("данных частично достаточно", "some data")
  if (confidence === "low") return uiText("данных мало", "limited data")
  return confidence || uiText("оценка по доступной истории", "based on available history")
}

function formatTargetTime(seconds?: number | null) {
  if (!seconds) return "--"
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}` : `${minutes}m`
}

function formatDateTime(value?: string | null) {
  if (!value) return "--"
  return dateValue(value).toLocaleString(languageLocale(), { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })
}

function planGoalLabel(plan: Plan) {
  return `${planGoalTypeLabel(plan.goal_type)}${plan.race_distance_km ? ` · ${plan.race_distance_km.toFixed(1)} ${kmUnit()}` : ""}`
}

function displayPlanTitle(plan: Pick<Plan, "title" | "goal_type" | "race_distance_km"> | null | undefined) {
  if (!plan) return uiText("Беговая программа", "Running program")
  const title = plan.title?.trim()
  if (!title || /\b(smoke|test|debug|completion)\b/i.test(title) || /\d{6,}/.test(title)) return `${planGoalTypeLabel(plan.goal_type)} ${uiText("программа", "program")}`
  return title
}

function planCurrentWeekIndex(plan: Plan) {
  const weekStart = startOfWeekISO()
  const weekEnd = addDays(weekStart, 6)
  const currentWorkout = plan.workouts.find((workout) => workout.scheduled_date && workout.scheduled_date >= weekStart && workout.scheduled_date <= weekEnd)
  if (currentWorkout) return currentWorkout.week_index
  const nextWorkout = plan.workouts.find((workout) => workout.scheduled_date && workout.scheduled_date > weekEnd)
  return nextWorkout?.week_index || null
}

function planNextWorkout(plan: Plan) {
  const today = toISODate(new Date())
  const upcoming = plan.workouts
    .filter((workout) => workout.scheduled_date && workout.scheduled_date >= today && ["planned", "rescheduled"].includes(workout.status))
    .sort((left, right) => String(left.scheduled_date).localeCompare(String(right.scheduled_date)) || left.day_index - right.day_index)
  return upcoming[0] || null
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

function planQualityWorkouts(plan: Plan) {
  return plan.workouts.filter((workout) => planWorkoutIntensityCategory(workout) === "hard")
}

function planReviewWarnings(plan: Plan) {
  const warnings: string[] = []
  const isLongGoal = (plan.race_distance_km || 0) >= 21 || plan.goal_type === "half_marathon" || plan.goal_type === "marathon"
  const isMarathon = (plan.race_distance_km || 0) >= 42 || plan.goal_type === "marathon"
  if (isMarathon && plan.available_days_per_week < 3) warnings.push(uiText("Марафонский план на 2 беговых дня - это компромисс. Для полноценной подготовки лучше 3+ беговых дня.", "A marathon plan with 2 running days is a compromise. For full preparation, 3+ running days are better."))
  if (isLongGoal && planQualityWorkouts(plan).length === 0) warnings.push(uiText("В плане нет быстрых или темповых тренировок. Он получится слишком мягким и однообразным.", "The plan has no fast or tempo workouts. It may be too soft and repetitive."))
  const weekIndexes = Array.from(new Set(plan.workouts.map((workout) => workout.week_index)))
  const weakLongWeek = weekIndexes.find((weekIndex) => {
    const runs = plan.workouts.filter((workout) => workout.week_index === weekIndex && !isSupportWorkoutType(workout.workout_type) && workout.distance_km)
    const longRun = runs.find((workout) => workout.workout_type === "long")
    const biggestOther = Math.max(...runs.filter((workout) => workout.workout_type !== "long").map((workout) => workout.distance_km || 0), 0)
    return longRun && biggestOther > (longRun.distance_km || 0) + 0.5
  })
  if (weakLongWeek) warnings.push(uiText(`Неделя ${weakLongWeek}: длинная пробежка короче другой беговой тренировки. Для длинной цели это подозрительно.`, `Week ${weakLongWeek}: the long run is shorter than another run. For a long goal, this looks suspicious.`))
  return warnings
}

function plainPlanWarning(warning: string) {
  if (isEnglishLanguage()) {
    return warning
      .replace(/Фактический объем заметно ниже плана/gi, "Actual volume is noticeably below plan")
      .replace(/Неделя\s+(\d+)/gi, "Week $1")
      .replace(/длинная пробежка/gi, "long run")
      .replace(/быстрые тренировки/gi, "hard workouts")
      .replace(/быстрых или темповых/gi, "fast or tempo")
  }
  return warning
    .replace(/interval\/tempo\/race-pace/gi, "быстрых или темповых")
    .replace(/\bWeek\s+(\d+)/gi, "Неделя $1")
    .replace(/long run/gi, "длинная пробежка")
    .replace(/hard workouts/gi, "быстрые тренировки")
}

const QUICK_PLAN_GOALS = [
  { value: "5k", label: "5 км", enLabel: "5K", distance: "5", title: "Программа на 5 км", enTitle: "5K program" },
  { value: "10k", label: "10 км", enLabel: "10K", distance: "10", title: "Программа на 10 км", enTitle: "10K program" },
  { value: "half_marathon", label: "Полумарафон", enLabel: "Half marathon", distance: "21.1", title: "Программа на полумарафон", enTitle: "Half marathon program" },
  { value: "marathon", label: "Марафон", enLabel: "Marathon", distance: "42.2", title: "Марафонская программа", enTitle: "Marathon program" },
  { value: "base_building", label: "Просто база", enLabel: "Just base", distance: "10", title: "Базовая беговая программа", enTitle: "Base running program" },
] as const

const QUICK_PLAN_DAYS = [2, 3, 4, 5, 6]

function quickGoalDefaults(goal: string) {
  return QUICK_PLAN_GOALS.find((item) => item.value === goal) || QUICK_PLAN_GOALS[3]
}

function quickGoalLabel(goal: (typeof QUICK_PLAN_GOALS)[number]) {
  return isEnglishLanguage() ? goal.enLabel : goal.label
}

function quickGoalTitle(goal: (typeof QUICK_PLAN_GOALS)[number]) {
  return isEnglishLanguage() ? goal.enTitle : goal.title
}

function dayChoiceLabel(days: number) {
  if (isEnglishLanguage()) return `${days} times per week`
  return days === 2 || days === 3 || days === 4 ? `${days} раза в неделю` : `${days} раз в неделю`
}

function plainRiskMessage(message: string) {
  const lower = message.toLowerCase()
  if (lower.includes("injury") || lower.includes("pain")) return uiText("Учтем боль или травму и сделаем план осторожнее.", "The plan will account for pain or injury and stay conservative.")
  if (lower.includes("volume") || lower.includes("load")) return uiText("Объем будет расти аккуратно, без резких скачков.", "Volume will increase carefully without sharp jumps.")
  if (lower.includes("long")) return uiText("Длинные пробежки будут ограничены до безопасного уровня.", "Long runs will be capped at a safe level.")
  if (/[а-яё]/i.test(message)) return plainPlanWarning(message)
  return uiText("План будет построен осторожнее из-за ограничений или нехватки данных.", "The plan will be more conservative because of constraints or limited data.")
}

function workoutTargetMode(workout: PlanWorkout) {
  if (workout.workout_type === "strength" || workout.workout_type === "ofp") return "ОФП"
  if (workout.workout_type === "mobility" || workout.workout_type === "prehab") return "мобилити"
  if (workout.intensity?.includes("HR") || workout.description?.includes("HR")) return "пульс"
  if (workout.intensity?.includes("RPE") || workout.description?.includes("RPE")) return "ощущения"
  if (workout.description?.includes("pace") || workout.description?.includes("пейс")) return "темп"
  return workout.duration_seconds ? "время" : "дистанция"
}

function workoutBlocks(workout: PlanWorkout) {
  if (workout.blocks?.length) {
    return workout.blocks
      .slice()
      .sort((first, second) => first.block_index - second.block_index)
      .map((block) => {
        const repeat = block.repeat_count > 1 ? `${block.repeat_count}x ` : ""
        const target = block.target_distance_km ? `${block.target_distance_km.toFixed(2)} ${kmUnit()}` : block.target_duration_seconds ? formatDurationMinutes(block.target_duration_seconds) : "target"
        const pace = block.target_pace_min_seconds_per_km && block.target_pace_max_seconds_per_km ? ` · ${uiText("темп", "pace")} ${formatPace(block.target_pace_min_seconds_per_km)}-${formatPace(block.target_pace_max_seconds_per_km)}${perKmUnit()}` : ""
        const hr = block.target_hr_min_bpm && block.target_hr_max_bpm ? ` · ${uiText("пульс", "HR")} ${block.target_hr_min_bpm}-${block.target_hr_max_bpm}` : ""
        const rpe = block.target_rpe_min !== null && block.target_rpe_max !== null ? ` · ${uiText("ощущение", "effort")} ${block.target_rpe_min}-${block.target_rpe_max}/10` : ""
        return `${repeat}${workoutBlockTypeLabel(block.block_type)}: ${target}${pace}${hr}${rpe}`
      })
  }
  if (workout.workout_type === "strength" || workout.workout_type === "ofp") return ["Разминка", "Икры/стопы", "Одна нога", "Ягодицы/кор", "Заминка"]
  if (workout.workout_type === "mobility" || workout.workout_type === "prehab") return ["Голеностоп", "Тазобедренные", "Активация ягодиц", "Дыхание"]
  if (workout.workout_type === "interval") return ["Разминка 10-15 мин", "Быстрые отрезки", "Легкое восстановление", "Заминка"]
  if (["tempo", "threshold", "race_pace"].includes(workout.workout_type)) return ["Разминка", "Контролируемая работа", "Заминка"]
  if (workout.workout_type === "long") return ["Легкое начало", "Ровная середина", "Питье/питание", "Легкий финиш"]
  if (workout.workout_type === "recovery") return ["Коротко и легко", "Мобилити", "Остановиться при усталости"]
  return ["Легкий непрерывный бег", "Расслабленная техника", "Ускорения по самочувствию"]
}

function workoutBlockTypeLabel(type: string) {
  if (type === "warmup") return uiText("разминка", "warm-up")
  if (type === "work") return uiText("основная часть", "main part")
  if (type === "recovery") return uiText("легкое восстановление", "easy recovery")
  if (type === "cooldown") return uiText("заминка", "cool-down")
  return uiText("блок", "block")
}

function workoutPurpose(workout: PlanWorkout) {
  if (workout.workout_type === "strength" || workout.workout_type === "ofp") return uiText("Сделать тело устойчивее к беговой нагрузке: стопы, икры, таз, ягодицы и кор.", "Make the body more resilient for running load: feet, calves, hips, glutes and core.")
  if (workout.workout_type === "mobility" || workout.workout_type === "prehab") return uiText("Снять зажатость и поддержать слабые места бегуна без лишней усталости.", "Loosen up and support weak spots without adding fatigue.")
  if (workout.workout_type === "long") return uiText("Развить выносливость и подготовить ноги к долгой работе.", "Build endurance and prepare the legs for longer work.")
  if (workout.workout_type === "interval") return uiText("Дать быстрый стимул, но оставить восстановление под контролем.", "Add a faster stimulus while keeping recovery controlled.")
  if (["tempo", "threshold", "race_pace"].includes(workout.workout_type)) return uiText("Потренировать устойчивый темп без гонки на тренировке.", "Practice steady pace without racing the workout.")
  if (workout.workout_type === "recovery") return uiText("Восстановить ноги и сохранить регулярность.", "Help the legs recover while keeping consistency.")
  return uiText("Набрать аэробный объем и поддержать стабильность.", "Build aerobic volume and keep consistency.")
}

function workoutSafetyNote(workout: PlanWorkout) {
  if (workout.workout_type === "strength" || workout.workout_type === "ofp") return uiText("Не делать до отказа и не добиваться сильной крепатуры.", "Do not train to failure or chase heavy soreness.")
  if (workout.workout_type === "mobility" || workout.workout_type === "prehab") return uiText("Легко и без боли: это должно улучшать готовность, а не утомлять.", "Keep it easy and pain-free: it should improve readiness, not add fatigue.")
  if (["interval", "tempo", "threshold", "race_pace", "long"].includes(workout.workout_type)) return uiText("Сократить или пропустить при боли, плохом сне, необычной усталости или странном пульсе.", "Shorten or skip if there is pain, poor sleep, unusual fatigue or odd heart rate.")
  return uiText("Держать разговорный темп; сократить, если восстановление хуже обычного.", "Keep a conversational pace; shorten it if recovery feels worse than usual.")
}

function Planning() {
  const [result, setResult] = useState<Plan | null>(null)
  const [builderPreview, setBuilderPreview] = useState<PlanBuilderPreview | null>(null)
  const [builderPreviewError, setBuilderPreviewError] = useState("")
  const [previewingBuilder, setPreviewingBuilder] = useState(false)
  const [creatingPlan, setCreatingPlan] = useState(false)
  const [planWeeks, setPlanWeeks] = useState<PlanWeekSummary[]>([])
  const [planWeeksPlanId, setPlanWeeksPlanId] = useState<number | null>(null)
  const [planWeeksError, setPlanWeeksError] = useState("")
  const [candidatesByWorkout, setCandidatesByWorkout] = useState<Record<number, PlanActivityMatchCandidate[]>>({})
  const [candidateErrors, setCandidateErrors] = useState<Record<number, string>>({})
  const [feedbackDrafts, setFeedbackDrafts] = useState<Record<number, FeedbackDraft>>({})
  const [completionDrafts, setCompletionDrafts] = useState<Record<number, CompletionDraft>>({})
  const [targetDrafts, setTargetDrafts] = useState<Record<number, WorkoutTargetDraft>>({})
  const [rescheduleDrafts, setRescheduleDrafts] = useState<Record<number, string>>({})
  const [missedWorkout, setMissedWorkout] = useState<PlanWorkout | null>(null)
  const [savingMissedWorkout, setSavingMissedWorkout] = useState(false)
  const [missedWorkoutError, setMissedWorkoutError] = useState("")
  const [coachAction, setCoachAction] = useState<CoachActionTarget | null>(null)
  const [recommendations, setRecommendations] = useState<PlanRecommendations | null>(null)
  const [recommendationPreview, setRecommendationPreview] = useState<PlanRecommendationPreview | null>(null)
  const [recommendationAudits, setRecommendationAudits] = useState<PlanRecommendationAudit[]>([])
  const [planVersions, setPlanVersions] = useState<PlanVersion[]>([])
  const [rollbackPreview, setRollbackPreview] = useState<PlanRollbackPreview | null>(null)
  const [previewingRollbackVersionId, setPreviewingRollbackVersionId] = useState<number | null>(null)
  const [applyingRollback, setApplyingRollback] = useState(false)
  const [rollbackError, setRollbackError] = useState("")
  const [recommendationError, setRecommendationError] = useState("")
  const [recommendationActionError, setRecommendationActionError] = useState("")
  const [loadingRecommendations, setLoadingRecommendations] = useState(false)
  const [previewingRecommendations, setPreviewingRecommendations] = useState(false)
  const [applyingRecommendations, setApplyingRecommendations] = useState(false)
  const [loadingCandidates, setLoadingCandidates] = useState<number | null>(null)
  const [quickGoal, setQuickGoal] = useState("marathon")
  const [quickDays, setQuickDays] = useState(4)
  const planBuilderForm = useRef<HTMLFormElement>(null)
  const recommendationsRequest = useRef(0)
  const planWeeksRequest = useRef(0)

  async function loadPlans(preferredPlanId?: number | null) {
    await devLogin()
    const nextPlans = await api.plans()
    setResult((current) => {
      if (preferredPlanId === null) return nextPlans[0] || null
      if (preferredPlanId !== undefined) return nextPlans.find((plan) => plan.id === preferredPlanId) || nextPlans[0] || null
      return nextPlans[0] || current
    })
  }

  async function generate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    await createPlan(true)
  }

  async function createPlan(activatePlan = false) {
    if (!planBuilderForm.current) return
    if (result && !window.confirm(uiText("Заменить текущую программу? Выполненные тренировки сохранятся в истории.", "Replace the current plan? Completed workouts will stay in your history."))) return
    setCreatingPlan(true)
    setBuilderPreviewError("")
    try {
      const plan = await api.generatePlan(planBuilderPayload(planBuilderForm.current, activatePlan))
      setResult(plan)
      await loadPlans(plan.id)
      if (plan.status === "active") await loadRecommendations(plan.id)
    } catch (error) {
      console.error(error)
      setBuilderPreviewError(activatePlan ? uiText("Не удалось создать и активировать программу", "Failed to create and activate the plan") : uiText("Не удалось создать черновик программы", "Failed to create draft plan"))
    } finally {
      setCreatingPlan(false)
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
      setBuilderPreviewError(uiText("Не удалось подготовить проверку программы", "Failed to prepare plan preview"))
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
    if (status === "skipped") {
      setCoachAction({ workoutId: workout.id, title: coachWorkoutTitle(workout), action: "skip" })
      return
    }
    if (status !== "missed") {
      await patchWorkout(workout, { status }, "Не удалось обновить статус")
      return
    }
    setMissedWorkoutError("")
    setMissedWorkout(workout)
  }

  async function saveMissedWorkout(reason: WorkoutMissReason, notes?: string) {
    if (!missedWorkout) return
    const target = missedWorkout
    setSavingMissedWorkout(true)
    setMissedWorkoutError("")
    setCandidateErrors((current) => ({ ...current, [missedWorkout.id]: "" }))
    try {
      const updated = await api.missWorkout(target.id, reason, notes)
      setResult((current) => current ? { ...current, workouts: current.workouts.map((workout) => workout.id === updated.id ? updated : workout) } : current)
      setPlanWeeks((current) => current.map((week) => ({ ...week, workouts: week.workouts.map((workout) => workout.id === updated.id ? updated : workout) })))
      setMissedWorkout(null)
    } catch (error) {
      console.error(error)
      setMissedWorkoutError(uiText("Не удалось сохранить пропуск", "Failed to save missed workout"))
      setSavingMissedWorkout(false)
      return
    }
    setSavingMissedWorkout(false)
    if (result) {
      try {
        await refreshPlanDetail(result.id)
      } catch (error) {
        console.error(error)
        setCandidateErrors((current) => ({ ...current, [target.id]: uiText("Пропуск сохранён, но данные плана не обновились", "Missed workout saved, but plan refresh failed") }))
      }
    }
  }

  async function rescheduleWorkout(workout: PlanWorkout, scheduledDate: string) {
    if (!scheduledDate) return
    setCoachAction({ workoutId: workout.id, title: coachWorkoutTitle(workout), action: "reschedule", targetDate: scheduledDate })
  }

  async function unlinkWorkoutActivity(workout: PlanWorkout) {
    if (!result) return
    try {
      await api.unlinkPlanWorkoutActivity(workout.id)
      await refreshPlanDetail(result.id)
    } catch (error) {
      console.error(error)
      setCandidateErrors((current) => ({ ...current, [workout.id]: apiErrorMessage(error, uiText("Не удалось исправить отметку о выполнении", "Could not correct workout completion")) }))
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
      await api.attachWorkoutActivity(workout.id, activityId)
      setCandidatesByWorkout((current) => ({ ...current, [workout.id]: [] }))
      if (result) await refreshPlanDetail(result.id)
    } catch (error) {
      console.error(error)
      setCandidateErrors((current) => ({ ...current, [workout.id]: uiText("Не удалось отметить тренировку в плане", "Could not mark the workout in the plan") }))
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

  function updateTargetDraft(workout: PlanWorkout, patch: Partial<WorkoutTargetDraft>) {
    setTargetDrafts((current) => ({
      ...current,
      [workout.id]: { ...targetDraftFromWorkout(workout), ...(current[workout.id] || {}), ...patch },
    }))
  }

  async function saveTarget(workout: PlanWorkout) {
    const draft = targetDrafts[workout.id] || targetDraftFromWorkout(workout)
    if (!targetDraftChanged(workout, draft)) return
    const saved = await patchWorkout(workout, targetPayload(draft), uiText("Не удалось сохранить цель тренировки", "Failed to save workout target"))
    if (saved) {
      setTargetDrafts((current) => {
        const next = { ...current }
        delete next[workout.id]
        return next
      })
    }
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
      setCandidateErrors((current) => ({ ...current, [workout.id]: uiText("Не удалось отметить тренировку", "Failed to mark workout done") }))
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
      setCandidateErrors((current) => ({ ...current, [workout.id]: uiText("Не удалось сохранить самочувствие", "Failed to save feedback") }))
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
      if (recommendationsRequest.current === requestId) setRecommendationError(uiText("Не удалось загрузить рекомендации тренера", "Failed to load coach recommendations"))
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

  async function previewRollback(version: PlanVersion) {
    if (!result || !version.rollback_supported) return
    setPreviewingRollbackVersionId(version.id)
    setRollbackError("")
    try {
      setRollbackPreview(await api.previewPlanRollback(result.id, version.id))
    } catch (error) {
      setRollbackError(apiErrorMessage(error, uiText("Эту версию нельзя безопасно отменить", "This version cannot be safely reversed")))
    } finally {
      setPreviewingRollbackVersionId(null)
    }
  }

  async function applyRollback() {
    if (!rollbackPreview) return
    setApplyingRollback(true)
    setRollbackError("")
    try {
      const applied = await api.applyPlanRollback(rollbackPreview.preview_id)
      setRollbackPreview(null)
      await refreshPlanDetail(applied.plan_id)
      await loadRecommendationAudits(applied.plan_id)
    } catch (error) {
      setRollbackError(apiErrorMessage(error, uiText("Preview устарел или rollback заблокирован safety-правилами", "The preview expired or safety rules blocked the rollback")))
    } finally {
      setApplyingRollback(false)
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
      setRecommendationActionError(uiText("Не удалось подготовить проверку корректировок", "Failed to prepare adjustment preview"))
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
      setRecommendationActionError(uiText("Не удалось применить корректировки", "Failed to apply adjustments"))
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
  const nextWorkout = result ? planNextWorkout(result) : null
  const intensitySplit = result ? planIntensitySplit(result) : []
  const visibleRecommendations = recommendations?.plan_id === result?.id ? recommendations : null
  const planWarnings = result ? planReviewWarnings(result) : []
  const hasSafetyInfo = result?.explanation?.includes("Safety gates:") || false
  const conservative = hasSafetyInfo && result?.explanation?.includes("Safety gates: no active safety gates") === false
  const planMode = !result || !hasSafetyInfo ? null : conservative ? "safety gated" : "standard"
  const goalDefaults = quickGoalDefaults(quickGoal)
  const visibleDetailWeeks = currentWeekIndex ? detailWeeks.filter((week) => week.week_index >= currentWeekIndex).slice(0, 4) : detailWeeks.slice(0, 4)
  const remainingDetailWeeks = detailWeeks.filter((week) => !visibleDetailWeeks.some((visible) => visible.week_index === week.week_index))
  return <div className="grid gap-4">
    {rollbackPreview ? <PlanRollbackDialog preview={rollbackPreview} applying={applyingRollback} error={rollbackError} onApply={applyRollback} onClose={() => { setRollbackPreview(null); setRollbackError("") }} /> : null}
    {missedWorkout ? <MissWorkoutDialog title={coachWorkoutTitle(missedWorkout)} busy={savingMissedWorkout} error={missedWorkoutError} onSubmit={saveMissedWorkout} onClose={() => setMissedWorkout(null)} /> : null}
    {coachAction ? <CoachActionDialog target={coachAction} onApplied={async () => { if (!result) return; await refreshPlanDetail(result.id); if (coachAction.action === "reschedule" && coachAction.targetDate) setRescheduleDrafts((current) => ({ ...current, [coachAction.workoutId]: coachAction.targetDate! })) }} onClose={() => setCoachAction(null)} /> : null}
    <Card className="overflow-hidden border-orange-400/25 bg-[radial-gradient(circle_at_top_left,rgba(251,146,60,0.14),transparent_32%),#0b0b0b] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><p className="text-xs font-semibold text-orange-200">{uiText("Моя программа", "My plan")}</p><h2 className="mt-2 text-2xl font-semibold tracking-tight text-white">{result ? uiText("Следующий шаг уже в плане", "Your next step is already in the plan") : uiText("Сначала создайте программу", "Create a plan first")}</h2><p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-300">{result ? uiText("У вас одна текущая программа. Здесь всегда показаны ближайшая тренировка и актуальная неделя.", "You have one current plan. The next workout and current week are always shown here.") : uiText("Ответьте на несколько вопросов, и программа появится здесь.", "Answer a few questions and the plan will appear here.")}</p></div>
        {result ? <Badge className={planStatusClass(result.status)}>{planStatusLabel(result.status)}</Badge> : null}
      </div>
      <div className="mt-4">
        {result ? <NextPlanWorkoutCard workout={nextWorkout} currentWeekIndex={currentWeekIndex} /> : <div className="rounded-xl border border-zinc-800 bg-zinc-950/70 p-3 text-sm text-zinc-400">{uiText("Ниже открыт мастер создания программы.", "The plan builder below is open.")}</div>}
      </div>
    </Card>

    <Card>
      <CardHeader><div><CardTitle>{uiText("Детали программы", "Plan details")}</CardTitle><p className="text-xs text-zinc-500">{uiText("Недели плана, отметки выполнения и дополнительные настройки.", "Plan weeks, completion actions and additional settings.")}</p></div>{planMode ? <Badge className={conservative ? "border-orange-400/40 bg-orange-400/15 text-orange-100" : undefined}>{conservative ? uiText("осторожный режим", "conservative mode") : uiText("обычный режим", "standard mode")}</Badge> : null}</CardHeader>
      <div className="grid gap-4 p-4 text-sm text-zinc-400">
        {result ? <>
          {planWarnings.length ? <div className="grid gap-2">{planWarnings.map((warning) => <div key={warning} className="rounded-md border border-orange-400/20 bg-orange-400/10 px-2 py-1.5 text-xs text-orange-100">{plainPlanWarning(warning)}</div>)}</div> : null}
          <PlanDetailHeader plan={result} currentWeekIndex={currentWeekIndex} />
          <div className="flex flex-wrap items-center gap-2">
            {result.status !== "active" ? <Button size="sm" onClick={() => activate(result.id)}>Сделать активной</Button> : <Badge>{uiText("активная программа", "active program")}</Badge>}
            <Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{uiText("выполнено", "done")} {Math.round((result.adherence?.completion_rate || 0) * 100)}%</Badge>
            <Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{result.adherence?.completed_distance_km || 0}/{result.adherence?.planned_distance_km || 0} {kmUnit()}</Badge>
          </div>
          {result.adherence?.warnings?.length ? <div className="grid gap-2">{result.adherence.warnings.map((warning) => <div key={warning} className="rounded-md border border-orange-400/20 bg-orange-400/10 px-2 py-1.5 text-xs text-orange-100">{plainPlanWarning(warning)}</div>)}</div> : null}
          {planWeeksError ? <p className="rounded-md border border-orange-400/20 bg-orange-400/10 px-2 py-1.5 text-xs text-orange-100">{planWeeksError}</p> : null}
          <div className="grid gap-3">{visibleDetailWeeks.map((week) => <PlanWeek key={week.week_index} summary={week} defaultOpen={week.week_index === currentWeekIndex || week.workouts.some((workout) => workout.id === nextWorkout?.id)} nextWorkoutId={nextWorkout?.id || null} candidatesByWorkout={candidatesByWorkout} candidateErrors={candidateErrors} feedbackDrafts={feedbackDrafts} completionDrafts={completionDrafts} targetDrafts={targetDrafts} rescheduleDrafts={rescheduleDrafts} loadingCandidates={loadingCandidates} onFindCandidates={loadCandidates} onLinkCandidate={linkCandidate} onUpdate={updateWorkout} onReschedule={rescheduleWorkout} onUnlinkActivity={unlinkWorkoutActivity} onRescheduleDraft={(workout, value) => setRescheduleDrafts((current) => ({ ...current, [workout.id]: value }))} onFeedbackDraft={updateFeedbackDraft} onCompletionDraft={updateCompletionDraft} onTargetDraft={updateTargetDraft} onSaveTarget={saveTarget} onCompleteWorkout={completeWorkoutManually} onSaveFeedback={saveFeedback} />)}</div>
          {remainingDetailWeeks.length ? <CollapsibleSection title={uiText("Остальные недели", "Other weeks")} summary={<Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{remainingDetailWeeks.length}</Badge>}>
            <div className="grid gap-3">{remainingDetailWeeks.map((week) => <PlanWeek key={week.week_index} summary={week} defaultOpen={false} nextWorkoutId={nextWorkout?.id || null} candidatesByWorkout={candidatesByWorkout} candidateErrors={candidateErrors} feedbackDrafts={feedbackDrafts} completionDrafts={completionDrafts} targetDrafts={targetDrafts} rescheduleDrafts={rescheduleDrafts} loadingCandidates={loadingCandidates} onFindCandidates={loadCandidates} onLinkCandidate={linkCandidate} onUpdate={updateWorkout} onReschedule={rescheduleWorkout} onUnlinkActivity={unlinkWorkoutActivity} onRescheduleDraft={(workout, value) => setRescheduleDrafts((current) => ({ ...current, [workout.id]: value }))} onFeedbackDraft={updateFeedbackDraft} onCompletionDraft={updateCompletionDraft} onTargetDraft={updateTargetDraft} onSaveTarget={saveTarget} onCompleteWorkout={completeWorkoutManually} onSaveFeedback={saveFeedback} />)}</div>
          </CollapsibleSection> : null}
          <CollapsibleSection title={uiText("Для продвинутых", "Advanced")} summary={<Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{uiText("детали", "details")}</Badge>}>
            <div className="grid gap-3">
              <CollapsibleSection title={uiText("Объяснение плана", "Plan explanation")}><p className="leading-6" translate="no">{result.explanation}</p></CollapsibleSection>
              <CoachRecommendations recommendations={visibleRecommendations} preview={recommendationPreview?.plan_id === result.id ? recommendationPreview : null} audits={recommendationAudits} error={recommendationError} actionError={recommendationActionError} loading={loadingRecommendations} previewing={previewingRecommendations} applying={applyingRecommendations} onRefresh={() => loadRecommendations(result.id)} onPreview={() => previewRecommendations(result.id)} onApply={() => applyRecommendations(result.id)} />
              <CollapsibleSection title="Графики и распределение" summary={<Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">опционально</Badge>}>
                <div className="grid gap-3"><PlanVolumeChart weeks={detailWeeks} /><PlanIntensitySplit split={intensitySplit} /></div>
              </CollapsibleSection>
              <PlanVersions versions={planVersions} previewingVersionId={previewingRollbackVersionId} error={rollbackPreview ? "" : rollbackError} onPreviewRollback={previewRollback} />
            </div>
          </CollapsibleSection>
        </> : <p>{uiText("Создайте программу, и здесь появятся ближайшая тренировка, недели и простые подсказки.", "Create a program, and the next workout, weeks and simple tips will appear here.")}</p>}
      </div>
    </Card>

    <CollapsibleSection key={result ? "secondary-plan-builder" : "primary-plan-builder"} title={result ? uiText("Пересобрать текущую программу", "Rebuild current plan") : uiText("Создать программу", "Create a plan")} summary={result ? <Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{uiText("заменит текущую", "replaces current")}</Badge> : <Badge>{uiText("начать", "start")}</Badge>} defaultOpen={!result}>
    <Card>
      <CardHeader><div><CardTitle>{result ? uiText("Пересобрать программу", "Rebuild plan") : uiText("Создать программу", "Create a plan")}</CardTitle><p className="text-xs text-zinc-500">{uiText("Мы берем только беговые тренировки, зоны и ограничения. Новая программа заменит текущую, а выполненные тренировки останутся в истории.", "Runforfan uses running workouts, zones and constraints. A new plan replaces the current one while completed workouts stay in history.")}</p></div>{result && <Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{uiText("одна программа", "one plan")}</Badge>}</CardHeader>
      <form ref={planBuilderForm} onSubmit={generate} className="grid gap-3 p-4 text-xs">
        <div className="grid gap-2">
          <p className="font-semibold text-white">{uiText("К чему готовимся?", "What are you preparing for?")}</p>
          <div className="grid gap-2 sm:grid-cols-2">
            {QUICK_PLAN_GOALS.map((goal) => <label key={goal.value} aria-label={quickGoalLabel(goal)} className={cn("cursor-pointer rounded-xl border px-3 py-3 transition", quickGoal === goal.value ? "border-orange-400/60 bg-orange-400/15 text-orange-100" : "border-zinc-800 bg-zinc-950 text-zinc-300 hover:border-zinc-700")}><input className="sr-only" name="goal_type" type="radio" value={goal.value} checked={quickGoal === goal.value} onChange={() => setQuickGoal(goal.value)} /><span className="text-sm font-semibold">{quickGoalLabel(goal)}</span></label>)}
          </div>
        </div>
        <div className="grid gap-2">
          <p className="font-semibold text-white">{uiText("Когда старт или сколько недель готовимся?", "When is the race, or how many weeks do you want?")}</p>
          <div className="grid gap-2 sm:grid-cols-2"><Field label={uiText("Дата старта", "Race date")}><Input name="target_date" type="date" /></Field><Field label={uiText("Если даты нет", "If no date")}><Input name="plan_length_weeks" type="number" min="4" max="24" step="1" placeholder={uiText("например, 12 недель", "for example, 12 weeks")} /></Field></div>
        </div>
        <div className="grid gap-2">
          <p className="font-semibold text-white">{uiText("Сколько раз в неделю реально бегать?", "How many times per week can you really run?")}</p>
          <div className="grid grid-cols-3 gap-2 min-[380px]:grid-cols-5">
            {QUICK_PLAN_DAYS.map((days) => <label key={days} aria-label={dayChoiceLabel(days)} className={cn("cursor-pointer rounded-xl border px-2 py-3 text-center transition", quickDays === days ? "border-orange-400/60 bg-orange-400/15 text-orange-100" : "border-zinc-800 bg-zinc-950 text-zinc-300 hover:border-zinc-700")}><input className="sr-only" name="available_days_per_week" type="radio" value={days} checked={quickDays === days} onChange={() => setQuickDays(days)} /><span className="text-base font-semibold">{days}</span></label>)}
          </div>
        </div>
        <div className="grid gap-2">
          <p className="font-semibold text-white">{uiText("Есть ограничения?", "Any limits?")}</p>
          <div className="grid gap-2 sm:grid-cols-2"><label className="flex min-h-11 items-center gap-2 rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2 text-zinc-300"><input name="injury" type="checkbox" /> {uiText("травма/боль", "injury/pain")}</label><label className="flex min-h-11 items-center gap-2 rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2 text-zinc-300"><input name="no_hard_workouts" type="checkbox" /> {uiText("пока без быстрых работ", "no hard workouts for now")}</label><label className="flex min-h-11 items-center gap-2 rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2 text-zinc-300"><input name="include_strength" type="checkbox" defaultChecked /> {uiText("ОФП", "strength")}</label><label className="flex min-h-11 items-center gap-2 rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2 text-zinc-300"><input name="include_mobility" type="checkbox" defaultChecked /> {uiText("мобилити", "mobility")}</label></div>
        </div>
        <CollapsibleSection title={uiText("Точные настройки (необязательно)", "Exact settings (optional)")} summary={<Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{uiText("можно не трогать", "safe to skip")}</Badge>}>
          <div className="grid gap-3">
            <div className="grid gap-2 sm:grid-cols-2"><Field label={uiText("Название", "Name")}><Input key={`title-${quickGoal}-${languageLocale()}`} name="title" defaultValue={quickGoalTitle(goalDefaults)} /></Field><Field label={uiText("Дистанция, км", "Distance, km")}><Input key={`distance-${quickGoal}`} name="race_distance_km" type="number" min="1" max="100" step="0.1" defaultValue={goalDefaults.distance} /></Field></div>
            <div className="grid gap-2 sm:grid-cols-2"><Field label={uiText("Целевое время, мин", "Target time, min")}><Input name="target_time_minutes" type="number" min="1" max="2880" step="1" placeholder={uiText("необязательно", "optional")} /></Field><Field label={uiText("Текущий объем, км/нед", "Current volume, km/week")}><Input name="current_weekly_distance_km" type="number" min="0" max="200" step="0.1" placeholder={uiText("если пусто, возьмем из истории", "if empty, use history")} /></Field></div>
            <Field label={uiText("Самая длинная недавняя пробежка, км", "Longest recent run, km")}><Input name="longest_recent_run_km" type="number" min="0" max="100" step="0.1" placeholder={uiText("необязательно", "optional")} /></Field>
            <div className="grid gap-2 sm:grid-cols-2"><Field label={uiText("Недавний старт, км", "Recent race, km")}><Input name="recent_race_distance_km" type="number" min="1" max="100" step="0.1" placeholder={uiText("необязательно", "optional")} /></Field><Field label={uiText("Время недавнего старта, мин", "Recent race time, min")}><Input name="recent_race_time_minutes" type="number" min="1" max="2880" step="1" placeholder={uiText("необязательно", "optional")} /></Field></div>
            <div className="grid gap-2 sm:grid-cols-2"><Field label={uiText("Удобные дни", "Preferred days")}><Input name="preferred_weekdays" placeholder={uiText("1,3,6 если важно", "1,3,6 if important")} /></Field><Field label={uiText("Лимит времени, мин/нед", "Time budget, min/week")}><Input name="time_budget_minutes_per_week" type="number" min="30" max="5000" step="5" placeholder={uiText("необязательно", "optional")} /></Field></div>
            <div className="grid gap-2 sm:grid-cols-2"><Field label={uiText("Макс. длинная, км", "Max long run, km")}><Input name="max_long_run_km" type="number" min="1" max="100" step="0.1" placeholder={uiText("необязательно", "optional")} /></Field><Field label={uiText("Макс. длинная, мин", "Max long run, min")}><Input name="max_long_run_duration_minutes" type="number" min="15" max="600" step="5" placeholder={uiText("необязательно", "optional")} /></Field></div>
            <Field label={uiText("Покрытие", "Surface")}><Input name="terrain" placeholder={uiText("асфальт, трейл, дорожка", "road, trail, treadmill")} /></Field>
            <div className="grid gap-2 sm:grid-cols-3"><Field label={uiText("ОФП в неделю", "Strength per week")}><Input name="strength_sessions_per_week" type="number" min="0" max="3" step="1" defaultValue="1" /></Field><Field label={uiText("Мобилити в неделю", "Mobility per week")}><Input name="mobility_sessions_per_week" type="number" min="0" max="4" step="1" defaultValue="1" /></Field><Field label={uiText("Оборудование", "Equipment")}><Select name="strength_equipment" defaultValue="bodyweight"><option value="bodyweight">{uiText("Вес тела", "Bodyweight")}</option><option value="bands">{uiText("Резинки", "Bands")}</option><option value="dumbbells">{uiText("Гантели", "Dumbbells")}</option><option value="gym">{uiText("Зал", "Gym")}</option></Select></Field></div>
            <div className="grid gap-2 sm:grid-cols-3"><Field label={uiText("Приоритет", "Priority")}><Select name="priority" defaultValue="b"><option value="a">{uiText("главный старт", "main race")}</option><option value="b">{uiText("обычный старт", "normal race")}</option><option value="c">{uiText("тренировочный старт", "training race")}</option></Select></Field><Field label={uiText("Рост нагрузки", "Load growth")}><Select name="aggressiveness" defaultValue="auto"><option value="auto">{uiText("авто", "auto")}</option><option value="beginner">{uiText("осторожнее", "more careful")}</option><option value="intermediate">{uiText("средне", "moderate")}</option><option value="advanced">{uiText("смелее, если история позволяет", "bolder if history allows")}</option></Select></Field><Field label={uiText("Ориентир", "Intensity guide")}><Select name="intensity_mode" defaultValue="mixed"><option value="mixed">{uiText("смешанный", "mixed")}</option><option value="pace">{uiText("темп", "pace")}</option><option value="hr">{uiText("пульс", "heart rate")}</option><option value="rpe">{uiText("ощущения", "feel")}</option></Select></Field></div>
          </div>
        </CollapsibleSection>
        <div className="grid gap-2 sm:grid-cols-[1fr_auto]"><Button type="submit" className="text-sm" disabled={creatingPlan}>{creatingPlan ? uiText("Сохраняем программу...", "Saving plan...") : result ? uiText("Заменить текущую программу", "Replace current plan") : uiText("Создать и открыть программу", "Create and open plan")}</Button><Button type="button" variant="secondary" disabled={previewingBuilder || creatingPlan} onClick={previewBuilder}>{previewingBuilder ? uiText("Готовим проверку...", "Preparing preview...") : uiText("Проверить план", "Preview plan")}</Button></div>
      </form>
      {builderPreviewError ? <div className="mx-4 mb-4 rounded-md border border-orange-400/20 bg-orange-400/10 px-2 py-1.5 text-xs text-orange-100">{builderPreviewError}</div> : null}
      {builderPreview ? <PlanBuilderPreviewCard preview={builderPreview} /> : null}
      {result ? <div className="border-t border-zinc-800 p-4 text-xs text-zinc-500">{uiText("После замены здесь останется только новая текущая программа. Прошлые выполненные тренировки не удаляются.", "After replacement, only the new current plan is shown here. Past completed workouts are not deleted.")}</div> : null}
    </Card>
    </CollapsibleSection>
  </div>
}

function PlanBuilderPreviewCard({ preview }: { preview: PlanBuilderPreview }) {
  const maxVolume = Math.max(...preview.weekly_volume_curve.map((week) => week.planned_distance_km), 1)
  const split = Object.entries(preview.intensity_split).map(([key, value]) => ({ key, value: Math.round(value * 100) }))
  const firstWorkouts = preview.workouts.slice(0, 3)
  const remainingWorkouts = preview.workouts.slice(3)
  const supportSessions = preview.weekly_volume_curve.reduce((sum, week) => sum + (week.support_sessions || 0), 0)
  const firstWeekDistance = preview.weekly_volume_curve[0]?.planned_distance_km
  const warningFlags = preview.risk_flags.filter((flag) => flag.severity === "critical" || flag.severity === "warning")
  return <div className="mx-4 mb-4 rounded-md border border-zinc-800 bg-zinc-950/70 p-3 text-xs">
    <div className="flex flex-wrap items-start justify-between gap-2">
      <div><p className="font-semibold text-white">{uiText("Проверка программы", "Plan preview")}</p><p className="mt-1 text-zinc-500">{uiText("Коротко о том, как стартует план до создания.", "A short look at how the plan starts before creating it.")}</p></div>
      <Badge className={warningFlags.length ? "border-orange-400/40 bg-orange-400/15 text-orange-100" : "border-zinc-700 bg-zinc-900 text-zinc-300"}>{warningFlags.length ? uiText("есть предупреждения", "needs attention") : uiText("выглядит спокойно", "looks calm")}</Badge>
    </div>
    <div className="mt-3 grid grid-cols-2 gap-2 text-center md:grid-cols-4">
      <Stat label={uiText("недель", "weeks")} value={preview.weeks} />
      <Stat label={uiText("сейчас", "now")} value={preview.current_weekly_distance_km.toFixed(1)} suffix={kmUnit()} />
      <Stat label={uiText("пик", "peak")} value={preview.peak_weekly_distance_km.toFixed(1)} suffix={kmUnit()} />
      <Stat label="ОФП" value={supportSessions} />
    </div>
    <div className="mt-3 grid gap-2 text-zinc-300">
      <p className="rounded-md border border-zinc-800 bg-zinc-950 px-2 py-1.5">{uiText("Стартуем от уровня", "Starting level")}: <span className="font-medium text-white">{trainingLevelLabel(preview.baseline.training_age_level)}</span>. {uiText("История", "History")}: <span className="font-medium text-white">{confidenceLabel(preview.baseline.confidence)}</span>.</p>
      <p className="rounded-md border border-zinc-800 bg-zinc-950 px-2 py-1.5">{uiText("Объем", "Volume")}: {preview.current_weekly_distance_km.toFixed(1)} - {preview.peak_weekly_distance_km.toFixed(1)} {kmUnit()} {uiText("в неделю", "per week")}.</p>
      <p className="rounded-md border border-zinc-800 bg-zinc-950 px-2 py-1.5">{uiText("Первая неделя", "First week")}: {firstWeekDistance?.toFixed(1) || "--"} {kmUnit()} {uiText("и ближайшие тренировки ниже.", "and the nearest workouts below.")}</p>
    </div>
    {preview.risk_flags.length ? <div className="mt-3 grid gap-1.5">{preview.risk_flags.slice(0, 3).map((flag) => <div key={flag.code} className={cn("rounded-md border px-2 py-1.5", signalClass(flag.severity))}><p className="font-medium">{plainRiskMessage(flag.message)}</p></div>)}</div> : <p className="mt-3 rounded-md border border-zinc-800 bg-zinc-950 px-2 py-1.5 text-zinc-500">{uiText("Серьезных предупреждений на проверке нет.", "No major preview warnings.")}</p>}
    <div className="mt-3 grid gap-1.5">{firstWorkouts.map((workout) => <div key={`${workout.week_index}-${workout.day_index}-${workout.title}`} className="rounded-md border border-zinc-900 bg-zinc-950 px-2 py-1.5"><div className="flex flex-wrap items-center justify-between gap-2"><p className="font-medium text-white">{uiText("Неделя", "Week")} {workout.week_index} · {coachPreviewWorkoutTitle(workout)}</p><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{workoutTypeLabel(workout.workout_type)}</Badge></div><p className="mt-1 text-zinc-500">{formatDate(workout.scheduled_date)} · {formatWorkoutTarget(workout)}</p></div>)}</div>
    <CollapsibleSection title={uiText("Для любопытных", "For curious runners")} className="mt-3" summary={<Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{uiText("технические детали", "technical details")}</Badge>}>
      <p className="leading-5 text-zinc-400" translate="no">{preview.explanation}</p>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2"><p className="font-medium text-white">Данные истории</p><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{preview.baseline.training_age_level} · {preview.baseline.confidence}</Badge></div>
      <div className="mt-2 grid grid-cols-2 gap-2 text-zinc-500" translate="no">
        <p>источник: <span className="text-zinc-300">{preview.baseline.current_weekly_volume_source}</span></p>
        <p>история: <span className="text-zinc-300">{preview.baseline.history_span_days} дн.</span></p>
        <p>стабильно: <span className="text-zinc-300">{preview.baseline.consistent_weeks || 0} нед.</span></p>
        <p>качество: <span className="text-zinc-300">{preview.baseline.quality_sessions_8w || 0}/8 нед.</span></p>
        <p>активности: <span className="text-zinc-300">{preview.baseline.activity_count}</span></p>
        <p>длинная: <span className="text-zinc-300">{preview.baseline.recent_long_run_km?.toFixed(1) || "--"} {kmUnit()}</span></p>
        <p>типичная: <span className="text-zinc-300">{preview.baseline.recent_run_distance_median_km?.toFixed(1) || "--"} {kmUnit()}</span></p>
        <p>пробежки 4 нед.: <span className="text-zinc-300">{preview.baseline.recent_run_count_4w || 0}</span></p>
      </div>
      <div className="mt-2 grid grid-cols-6 gap-1">{preview.baseline.observed_weekly_volume_km.map((volume, index) => <div key={`${index}-${volume}`} className="rounded bg-zinc-900 px-1.5 py-1 text-center"><p className="font-mono text-[10px] text-zinc-600">-{6 - index}w</p><p className="text-zinc-300">{volume.toFixed(1)}</p></div>)}</div>
      <div className="mt-3 grid gap-2">
        {preview.weekly_volume_curve.map((week) => <div key={week.week_index} className="grid grid-cols-[3.5rem_1fr_8.5rem] items-center gap-2 text-[11px]" translate="no"><span className="text-zinc-500">W{week.week_index}</span><div className="h-2 overflow-hidden rounded bg-zinc-900"><div className={cn("h-full rounded", week.is_taper ? "bg-orange-200/80" : "bg-orange-400/70")} style={{ width: `${Math.max(4, Math.round((week.planned_distance_km / maxVolume) * 100))}%` }} /></div><span className="text-right text-zinc-300">{week.planned_distance_km.toFixed(1)} {kmUnit()} · {week.phase}</span></div>)}
      </div>
      <div className="flex flex-wrap gap-2" translate="no"><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{preview.intensity_mode}</Badge><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">priority {preview.priority}</Badge>{preview.preferred_weekdays.length ? <Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">days {preview.preferred_weekdays.join(",")}</Badge> : null}{split.map((item) => <Badge key={item.key} className="border-zinc-700 bg-zinc-900 text-zinc-300">{item.key} {item.value}%</Badge>)}</div>
      {preview.risk_flags.length ? <div className="mt-3 grid gap-1.5" translate="no">{preview.risk_flags.map((flag) => <div key={flag.code} className={cn("rounded-md border px-2 py-1.5", signalClass(flag.severity))}><div className="flex flex-wrap items-center justify-between gap-2"><p className="font-medium">{flag.message}</p><Badge className="border-zinc-700 bg-zinc-950 text-zinc-300">{flag.code}</Badge></div>{flag.reasons.length ? <p className="mt-1 text-[11px] text-zinc-500">{flag.reasons.slice(0, 2).join(" · ")}</p> : null}</div>)}</div> : null}
    </CollapsibleSection>
    {remainingWorkouts.length ? <CollapsibleSection title={uiText("Остальные тренировки в проверке", "Other preview workouts")} className="mt-3" summary={<Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{remainingWorkouts.length}</Badge>}>
      <div className="grid gap-1.5">{remainingWorkouts.map((workout) => <div key={`${workout.week_index}-${workout.day_index}-${workout.title}`} className="rounded-md border border-zinc-900 bg-zinc-950 px-2 py-1.5"><div className="flex flex-wrap items-center justify-between gap-2"><p className="font-medium text-white">{uiText("Неделя", "Week")} {workout.week_index} · {coachPreviewWorkoutTitle(workout)}</p><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{workoutTypeLabel(workout.workout_type)}</Badge></div><p className="mt-1 text-zinc-500">{formatDate(workout.scheduled_date)} · {formatWorkoutTarget(workout)}</p></div>)}</div>
    </CollapsibleSection> : null}
  </div>
}

function PlanDetailHeader({ plan, currentWeekIndex }: { plan: Plan; currentWeekIndex: number | null }) {
  const history = [
    { label: uiText("создана", "created"), value: formatDateTime(plan.created_at) },
    { label: uiText("обновлена", "updated"), value: formatDateTime(plan.updated_at) },
  ]
  return <div className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 text-xs">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><p className="text-[11px] font-semibold text-zinc-500">{uiText("Программа", "Program")}</p><h3 className="mt-1 text-base font-semibold text-white">{displayPlanTitle(plan)}</h3><p className="mt-1 text-zinc-500">{planGoalLabel(plan)}</p></div>
      <div className="flex flex-wrap gap-2"><Badge className={planStatusClass(plan.status)}>{planStatusLabel(plan.status)}</Badge>{currentWeekIndex ? <Badge className="border-orange-400/40 bg-orange-400/15 text-orange-100">{uiText("неделя", "week")} {currentWeekIndex}</Badge> : <Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{uiText("неделя", "week")} --</Badge>}</div>
    </div>
    <CollapsibleSection title={uiText("Сводка программы", "Plan summary")} className="mt-3" summary={<Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{uiText("показать", "show")}</Badge>}>
      <div className="grid grid-cols-2 gap-2 text-center md:grid-cols-4">
        <Stat label={uiText("старт", "start")} value={formatDate(plan.target_date)} />
        <Stat label={uiText("цель", "target")} value={formatTargetTime(plan.target_time_seconds)} />
        <Stat label={uiText("план км", "planned km")} value={(plan.adherence?.planned_distance_km || planPlannedDistance(plan)).toFixed(1)} />
        <Stat label={uiText("сделано км", "done km")} value={(plan.adherence?.completed_distance_km || 0).toFixed(1)} />
      </div>
      <div className="grid gap-1.5 text-[11px] text-zinc-500 md:grid-cols-2">{history.map((item) => <div key={item.label} className="rounded border border-zinc-900 bg-zinc-950 px-2 py-1"><span className="font-mono uppercase tracking-[0.12em] text-zinc-600">{item.label}</span><span className="ml-2 text-zinc-300">{item.value}</span></div>)}</div>
      <div className="mt-2 grid grid-cols-2 gap-2 text-center"><Stat label="ОФП" value={planSupportWorkouts(plan)} /><Stat label={uiText("время", "time")} value={formatDuration(plan.adherence?.planned_duration_seconds || planPlannedDuration(plan))} /></div>
    </CollapsibleSection>
  </div>
}

function NextPlanWorkoutCard({ workout, currentWeekIndex }: { workout: PlanWorkout | null; currentWeekIndex: number | null }) {
  if (!workout) return <div className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 text-xs">
    <div className="flex flex-wrap items-center justify-between gap-2"><p className="font-semibold text-white">Следующая тренировка</p><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{uiText("нет в календаре", "not scheduled")}</Badge></div>
    <p className="mt-2 text-zinc-500">{uiText("В активной программе пока нет будущей запланированной тренировки.", "The active program has no future scheduled workout yet.")}</p>
  </div>
  const isCurrentWeek = currentWeekIndex === workout.week_index
  return <div className="rounded-md border border-orange-400/30 bg-orange-400/10 p-3 text-xs">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><p className="text-[11px] font-semibold text-orange-200">{uiText("Следующая тренировка", "Next workout")}</p><h3 className="mt-1 text-base font-semibold text-white">{coachWorkoutTitle(workout)}</h3><p className="mt-1 text-orange-100">{workout.scheduled_date ? formatLocalDate(workout.scheduled_date) : noDateLabel()} · {uiText("неделя", "week")} {workout.week_index}{isCurrentWeek ? ` · ${uiText("текущая", "current")}` : ""}</p></div>
      <div className="flex flex-wrap gap-1.5"><Badge className="border-orange-400/40 bg-orange-400/15 text-orange-100">{uiText("ближайшая", "nearest")}</Badge><Badge className="border-zinc-700 bg-zinc-950 text-zinc-300">{workoutTypeLabel(workout.workout_type)}</Badge></div>
    </div>
    <div className="mt-3 grid gap-2 md:grid-cols-2">
      <Stat label={uiText("цель", "target")} value={formatWorkoutTarget(workout)} />
      <Stat label={uiText("ощущение", "effort")} value={workoutIntensityLabel(workout.intensity)} />
    </div>
    <p className="mt-3 leading-5 text-zinc-300">{workoutPurpose(workout)}</p>
    <p className="mt-2 text-[11px] text-zinc-500">{uiText("Ниже автоматически раскрыта неделя с этой тренировкой. Если цель выглядит странно, ее можно поправить в карточке тренировки.", "The week with this workout is opened below. If the target looks wrong, you can adjust it in the workout card.")}</p>
  </div>
}

function PlanVolumeChart({ weeks }: { weeks: PlanWeekSummary[] }) {
  const maxVolume = Math.max(...weeks.map((week) => Math.max(week.planned_distance_km, week.completed_distance_km)), 1)
  if (!weeks.length) return null
  return <div className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 text-xs">
    <div className="flex flex-wrap items-center justify-between gap-2"><div><p className="font-semibold text-white">График объема</p><p className="mt-1 text-zinc-500">План/факт по неделям и отметки ОФП.</p></div><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{weeks.length} недель</Badge></div>
    <div className="mt-3 grid gap-2">{weeks.map((week) => <div key={week.week_index} className="grid grid-cols-[3.5rem_1fr_7rem] items-center gap-2 text-[11px]" translate="no"><span className="text-zinc-500">W{week.week_index}</span><div className="grid gap-1"><div className="h-2 overflow-hidden rounded bg-zinc-900"><div className="h-full rounded bg-orange-400/70" style={{ width: `${Math.max(3, Math.round((week.planned_distance_km / maxVolume) * 100))}%` }} /></div><div className="h-2 overflow-hidden rounded bg-zinc-900"><div className="h-full rounded bg-zinc-400/70" style={{ width: `${Math.round((week.completed_distance_km / maxVolume) * 100)}%` }} /></div></div><span className="text-right text-zinc-400">{week.completed_distance_km.toFixed(1)}/{week.planned_distance_km.toFixed(1)} {kmUnit()} · S{week.support_workouts}</span></div>)}</div>
  </div>
}

function PlanIntensitySplit({ split }: { split: { key: string; value: number; percent: number }[] }) {
  return <div className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 text-xs">
    <div className="flex flex-wrap items-center justify-between gap-2"><p className="font-semibold text-white">Распределение нагрузки</p><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">план</Badge></div>
    <div className="mt-3 grid gap-2 md:grid-cols-5">{split.map((item) => <div key={item.key} className="rounded-md border border-zinc-900 bg-zinc-950 p-2" translate="no"><div className="flex items-center justify-between"><span className="font-medium text-white">{item.key}</span><span className="text-zinc-400">{item.percent}%</span></div><div className="mt-2 h-2 overflow-hidden rounded bg-zinc-900"><div className="h-full rounded bg-orange-400/70" style={{ width: `${Math.max(2, item.percent)}%` }} /></div><p className="mt-1 text-[11px] text-zinc-500">{item.value.toFixed(1)}</p></div>)}</div>
  </div>
}

function PlanVersions({ versions, previewingVersionId, error, onPreviewRollback }: { versions: PlanVersion[]; previewingVersionId: number | null; error: string; onPreviewRollback: (version: PlanVersion) => void }) {
  return <div className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 text-xs">
    <div className="flex flex-wrap items-start justify-between gap-2"><div><p className="font-semibold text-white">История программы</p><p className="mt-1 text-zinc-500">Снимки после создания, ручных правок и адаптаций.</p></div><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{versions.length}</Badge></div>
    {versions.length ? <div className="mt-3 grid max-h-[32rem] gap-2 overflow-y-auto pr-1">{versions.map((version) => {
      const workoutCount = Array.isArray(version.snapshot_json?.workouts) ? version.snapshot_json.workouts.length : 0
      return <div key={version.id} className="grid gap-2 rounded-md border border-zinc-800 bg-zinc-950 p-2 md:grid-cols-[5rem_1fr_auto] md:items-center" translate="no">
        <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-zinc-500">v{version.version_number}</div>
        <div><p className="font-medium text-white">{version.summary || version.reason}</p><p className="mt-1 text-zinc-500">{version.reason} · {workoutCount} workouts · {formatLocalDateTime(version.created_at)}</p></div>
        <div className="flex items-center justify-end gap-2"><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{version.rollback_of_version_id ? "rollback" : "snapshot"}</Badge>{version.rollback_supported ? <Button size="sm" variant="ghost" disabled={previewingVersionId !== null} onClick={() => onPreviewRollback(version)}>{previewingVersionId === version.id ? uiText("Проверяем...", "Checking...") : uiText("Отменить", "Reverse")}</Button> : null}</div>
      </div>
    })}</div> : <p className="mt-3 text-zinc-500">История появится после создания или правок программы.</p>}{error ? <p role="alert" className="mt-3 rounded-md border border-orange-400/20 bg-orange-400/10 px-2 py-1.5 text-orange-100">{error}</p> : null}
  </div>
}

function riskLevel(risk: Record<string, unknown> | null | undefined) {
  return typeof risk?.level === "string" ? risk.level : "--"
}

function CoachRecommendations({ recommendations, preview, audits, error, actionError, loading, previewing, applying, onRefresh, onPreview, onApply }: { recommendations: PlanRecommendations | null; preview: PlanRecommendationPreview | null; audits: PlanRecommendationAudit[]; error: string; actionError: string; loading: boolean; previewing: boolean; applying: boolean; onRefresh: () => void; onPreview: () => void; onApply: () => void }) {
  const statusClass = recommendations?.status === "watch" ? "border-orange-400/40 bg-orange-400/15 text-orange-100" : recommendations?.status === "adjust" ? "border-rose-400/40 bg-rose-400/15 text-rose-100" : "border-zinc-700 bg-zinc-900 text-zinc-300"
  const statusLabel = recommendations?.status || (loading ? "загрузка" : error ? "ошибка" : "нет данных")
  const canApply = Boolean(preview?.changes.length) && !applying && !previewing
  return <div className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 text-xs">
    <div className="flex flex-wrap items-start justify-between gap-2">
      <div><p className="font-semibold text-white">Рекомендации тренера</p><p className="mt-1 text-zinc-500">Автоматическая адаптация программы с проверкой перед применением.</p></div>
      <div className="flex flex-wrap items-center gap-2"><Badge className={statusClass}>{statusLabel}</Badge><Button size="sm" variant="ghost" disabled={loading || previewing || applying} onClick={onRefresh}>{loading ? "Обновляем..." : "Обновить"}</Button><Button size="sm" variant="ghost" disabled={!recommendations || loading || previewing || applying} onClick={onPreview}>{previewing ? "Проверяем..." : "Проверить"}</Button><Button size="sm" disabled={!canApply} onClick={onApply}>{applying ? "Применяем..." : "Применить"}</Button></div>
    </div>
    {error ? <div className="mt-3 rounded-md border border-orange-400/20 bg-orange-400/10 px-2 py-1.5 text-orange-100" translate="no">{error}</div> : null}
    {actionError ? <div className="mt-3 rounded-md border border-rose-400/20 bg-rose-400/10 px-2 py-1.5 text-rose-100" translate="no">{actionError}</div> : null}
    {recommendations ? <>
      <p className="mt-3 leading-5 text-zinc-300" translate="no">{recommendations.adaptation_summary || recommendations.summary}</p>
      <CollapsibleSection title="Метрики рекомендации" className="mt-3">
        <div className="grid gap-2 md:grid-cols-4 xl:grid-cols-6">
          <Stat label="готово" value={`${Math.round(recommendations.metrics.completion_rate * 100)}%`} />
          <Stat label="км" value={`${Math.round(recommendations.metrics.distance_completion_rate * 100)}%`} />
          <Stat label="недавние км" value={recommendations.metrics.recent_completed_distance_km} />
          <Stat label="7 дней км" value={recommendations.metrics.upcoming_planned_distance_km} />
          <Stat label="риск" value={`${riskLevel(recommendations.risk_before)}→${riskLevel(preview?.risk_after || recommendations.risk_after)}`} />
          <Stat label="быстрые 7д" value={recommendations.metrics.upcoming_hard_workouts || 0} />
        </div>
      </CollapsibleSection>
      <div className="mt-3 grid gap-2" translate="no">{recommendations.recommendations.map((item) => <div key={`${item.type}-${item.title}-${item.workout_id || item.week_index || "plan"}`} className="rounded-md border border-zinc-800 bg-zinc-950 p-2"><div className="flex flex-wrap items-center justify-between gap-2"><p className="font-medium text-white">{item.title}</p><Badge className={item.severity === "warning" ? "border-orange-400/40 bg-orange-400/15 text-orange-100" : item.severity === "critical" ? "border-rose-400/40 bg-rose-400/15 text-rose-100" : "border-zinc-700 bg-zinc-900 text-zinc-300"}>{item.type}</Badge></div><p className="mt-1 leading-5 text-zinc-400">{item.message}</p>{item.reasons.length ? <p className="mt-1 text-[11px] text-zinc-600">{item.reasons.slice(0, 2).join(" · ")}</p> : null}</div>)}</div>
      {preview ? <CollapsibleSection title="Что изменится" className="mt-3 border-orange-400/20 bg-orange-400/10" summary={<Badge className="border-orange-400/40 bg-orange-400/15 text-orange-100">{preview.changes.length}</Badge>}>
        <div className="flex flex-wrap items-center justify-between gap-2"><p className="font-semibold text-orange-100">Что изменится</p><Badge className="border-orange-400/40 bg-orange-400/15 text-orange-100">{preview.changes.length}</Badge></div>
        {preview.changes.length ? <div className="mt-2 grid gap-1.5" translate="no">{preview.changes.map((change, index) => <div key={`${change.workout_id}-${change.field}-${index}`} className="grid gap-1 rounded-md border border-zinc-800 bg-zinc-950/80 p-2 md:grid-cols-[7rem_1fr]"><div className="font-mono text-[10px] uppercase tracking-[0.12em] text-zinc-500">#{change.workout_id || "план"} · {change.field}</div><div><p className="text-zinc-300"><span className="text-zinc-500">{formatChangeValue(change.before)}</span> <span className="text-orange-200">-&gt;</span> <span className="text-white">{formatChangeValue(change.after)}</span></p>{change.reason ? <p className="mt-1 text-[11px] text-zinc-500">{change.reason}</p> : null}</div></div>)}</div> : <p className="mt-2 text-zinc-500">Безопасных автоматических изменений нет.</p>}
        {preview.skipped.length ? <div className="mt-2 rounded-md border border-zinc-800 bg-zinc-950/80 p-2" translate="no"><p className="font-medium text-zinc-300">Пропущено</p><div className="mt-1 grid gap-1 text-[11px] text-zinc-500">{preview.skipped.slice(0, 4).map((item, index) => <p key={index}>{String(item.action || "нет действия")}: {String(item.reason || "нужна ручная проверка")}</p>)}</div></div> : null}
      </CollapsibleSection> : null}
      {audits.length ? <CollapsibleSection title="История корректировок" className="mt-3" summary={<Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{audits.length}</Badge>}><div className="grid gap-1 text-[11px] text-zinc-500" translate="no">{audits.slice(0, 3).map((audit) => <p key={audit.id}>#{audit.id} · {audit.status} · {formatLocalDateTime(audit.created_at)}</p>)}</div></CollapsibleSection> : null}
    </> : <p className="mt-3 text-zinc-500">{loading ? "Рекомендации загружаются..." : error ? "Рекомендации недоступны." : "Рекомендации еще не загружены."}</p>}
  </div>
}

function PlanWeek({ summary, defaultOpen, nextWorkoutId, candidatesByWorkout, candidateErrors, feedbackDrafts, completionDrafts, targetDrafts, rescheduleDrafts, loadingCandidates, onFindCandidates, onLinkCandidate, onUpdate, onReschedule, onUnlinkActivity, onRescheduleDraft, onFeedbackDraft, onCompletionDraft, onTargetDraft, onSaveTarget, onCompleteWorkout, onSaveFeedback }: { summary: PlanWeekSummary; defaultOpen: boolean; nextWorkoutId: number | null; candidatesByWorkout: Record<number, PlanActivityMatchCandidate[]>; candidateErrors: Record<number, string>; feedbackDrafts: Record<number, FeedbackDraft>; completionDrafts: Record<number, CompletionDraft>; targetDrafts: Record<number, WorkoutTargetDraft>; rescheduleDrafts: Record<number, string>; loadingCandidates: number | null; onFindCandidates: (workout: PlanWorkout) => Promise<void>; onLinkCandidate: (workout: PlanWorkout, activityId: number) => Promise<void>; onUpdate: (workout: PlanWorkout, status: string) => Promise<void>; onReschedule: (workout: PlanWorkout, scheduledDate: string) => Promise<void>; onUnlinkActivity: (workout: PlanWorkout) => Promise<void>; onRescheduleDraft: (workout: PlanWorkout, value: string) => void; onFeedbackDraft: (workout: PlanWorkout, patch: Partial<FeedbackDraft>) => void; onCompletionDraft: (workout: PlanWorkout, patch: Partial<CompletionDraft>) => void; onTargetDraft: (workout: PlanWorkout, patch: Partial<WorkoutTargetDraft>) => void; onSaveTarget: (workout: PlanWorkout) => Promise<void>; onCompleteWorkout: (workout: PlanWorkout) => Promise<void>; onSaveFeedback: (workout: PlanWorkout) => Promise<void> }) {
  const [isOpen, setIsOpen] = useState(defaultOpen)
  const [openCompletionWorkoutId, setOpenCompletionWorkoutId] = useState<number | null>(null)
  useEffect(() => { if (defaultOpen) setIsOpen(true) }, [defaultOpen])

  return <details open={isOpen} onToggle={(event) => setIsOpen(event.currentTarget.open)} className="group rounded-md border border-zinc-800 bg-zinc-950/60">
    <summary className="min-h-11 cursor-pointer list-none border-b border-transparent px-3 py-2 group-open:border-zinc-800 [&::-webkit-details-marker]:hidden">
      <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-xs font-semibold text-white">Неделя {summary.week_index}</p><div className="flex flex-wrap gap-1.5"><Badge>{summary.planned_distance_km.toFixed(1)} {kmUnit()}</Badge>{summary.support_workouts ? <Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">ОФП {summary.support_workouts}</Badge> : null}{summary.deload ? <Badge className="border-orange-400/40 bg-orange-400/15 text-orange-100">легче</Badge> : null}</div></div>
    </summary>
    <div className="border-b border-zinc-900 px-3 py-2">
      <CollapsibleSection title="Цифры недели" summary={<Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{summary.planned_time_label}</Badge>}>
        <div className="grid grid-cols-2 gap-2 text-[11px] md:grid-cols-6">
          <div className="rounded bg-zinc-950 px-2 py-1"><span className="text-zinc-600">время</span><div className="text-zinc-300">{summary.planned_time_label}</div></div>
          <div className="rounded bg-zinc-950 px-2 py-1"><span className="text-zinc-600">быстрые</span><div className="text-zinc-300">{summary.hard_sessions}</div></div>
          <div className="rounded bg-zinc-950 px-2 py-1"><span className="text-zinc-600">длинная</span><div className="text-zinc-300">{summary.long_run_km?.toFixed(1) || "--"} {kmUnit()}</div></div>
          <div className="rounded bg-zinc-950 px-2 py-1"><span className="text-zinc-600">ОФП</span><div className="text-zinc-300">{formatDuration(summary.support_duration_seconds)}</div></div>
          <div className="rounded bg-zinc-950 px-2 py-1"><span className="text-zinc-600">готово</span><div className="text-zinc-300">{Math.round(summary.completion_rate * 100)}%</div></div>
          <div className="rounded bg-zinc-950 px-2 py-1"><span className="text-zinc-600">факт</span><div className="text-zinc-300">{summary.completed_distance_km.toFixed(1)} {kmUnit()}</div></div>
        </div>
      </CollapsibleSection>
      {summary.warnings.length ? <div className="mt-2 grid gap-1">{summary.warnings.map((warning) => <p key={warning} className="rounded border border-orange-400/20 bg-orange-400/10 px-2 py-1 text-[11px] text-orange-100">{plainPlanWarning(warning)}</p>)}</div> : null}
    </div>
    <div className="grid gap-2 p-3">{summary.workouts.map((workout) => {
      const candidates = candidatesByWorkout[workout.id] || []
      const draft = feedbackDrafts[workout.id] || feedbackDraftFromWorkout(workout)
      const completionDraft = completionDrafts[workout.id] || completionDraftFromWorkout(workout)
      const targetDraft = targetDrafts[workout.id] || targetDraftFromWorkout(workout)
      const targetChanged = targetDraftChanged(workout, targetDraft)
      const rescheduleDraft = rescheduleDrafts[workout.id] || workout.scheduled_date || ""
      const isNextWorkout = workout.id === nextWorkoutId
      const canGiveFeedback = ["done", "missed", "skipped"].includes(workout.status)
      const canCompleteManually = !workout.completed_activity_id && ["planned", "rescheduled", "missed", "skipped"].includes(workout.status)
      const canReschedule = !workout.completed_activity_id && ["planned", "rescheduled", "missed", "skipped"].includes(workout.status)
      const canEditTarget = !workout.completed_activity_id && workout.status !== "done"
      const targetSupportWorkout = isSupportWorkoutType(targetDraft.workout_type)
      const actualSupportWorkout = isSupportWorkoutType(workout.workout_type)
      return <div key={workout.id} className={cn("rounded-md border bg-zinc-950 p-3 text-xs", isNextWorkout ? "border-orange-400/50 ring-1 ring-orange-400/30" : "border-zinc-900")}>
        <div className="flex flex-wrap items-start justify-between gap-2"><div className="min-w-0 flex-1"><p className="break-words font-medium text-white">{coachWorkoutTitle(workout)}</p><p className="mt-1 break-words text-zinc-500">{workout.scheduled_date ? formatLocalDate(workout.scheduled_date) : noDateLabel()} · {workoutPurpose(workout)}</p></div><div className="flex flex-wrap gap-1.5">{isNextWorkout ? <Badge className="border-orange-400/40 bg-orange-400/15 text-orange-100">{uiText("ближайшая", "nearest")}</Badge> : null}<Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{workoutTypeLabel(workout.workout_type)}</Badge><Badge className={workout.status === "done" ? "border-orange-400/40 bg-orange-400/15 text-orange-100" : "border-zinc-700 bg-zinc-900 text-zinc-300"}>{workoutStatusLabel(workout.status)}</Badge></div></div>
        <div className="mt-3 flex flex-wrap gap-2">
          {canCompleteManually ? <Button size="sm" onClick={() => setOpenCompletionWorkoutId(workout.id)}>{uiText("Отметить", "Mark done")}</Button> : null}
          {!workout.completed_activity_id ? <Button size="sm" variant="secondary" disabled={loadingCandidates === workout.id} onClick={() => onFindCandidates(workout)}>{loadingCandidates === workout.id ? uiText("Ищем...", "Searching...") : uiText("Найти выполненную тренировку", "Find completed workout")}</Button> : <Button size="sm" variant="secondary" onClick={() => onUnlinkActivity(workout)}>{uiText("Снять отметку", "Remove completion")}</Button>}
        </div>
        <CollapsibleSection title="Что внутри" className="mt-2" defaultOpen={isNextWorkout} summary={<Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">блоки</Badge>}>
          <div className="grid gap-2 md:grid-cols-4">
            <div className="rounded-md border border-zinc-900 bg-zinc-950/80 px-2 py-1.5"><span className="font-mono text-[10px] uppercase tracking-[0.12em] text-zinc-600">цель</span><p className="mt-1 text-zinc-300">{workoutTargetMode(workout)} · {formatWorkoutTarget(workout)}</p></div>
            <div className="rounded-md border border-zinc-900 bg-zinc-950/80 px-2 py-1.5"><span className="font-mono text-[10px] uppercase tracking-[0.12em] text-zinc-600">зачем</span><p className="mt-1 text-zinc-400">{workoutPurpose(workout)}</p></div>
            <div className="rounded-md border border-zinc-900 bg-zinc-950/80 px-2 py-1.5 md:col-span-2"><span className="font-mono text-[10px] uppercase tracking-[0.12em] text-zinc-600">безопасность</span><p className="mt-1 text-zinc-400">{workoutSafetyNote(workout)}</p></div>
          </div>
          <div className="mt-2 grid gap-1.5">{workoutBlocks(workout).map((block) => <p key={block} className="min-w-0 break-words rounded-md border border-zinc-800 bg-zinc-900 px-2 py-1.5 text-[11px] leading-4 text-zinc-300">{block}</p>)}</div>
          {workout.description ? <CollapsibleSection title={uiText("Текст из плана", "Original plan text")} className="mt-2" summary={<Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{uiText("детали", "details")}</Badge>}><p className="break-words leading-5 text-zinc-500" translate="no">{workout.description}</p></CollapsibleSection> : null}
        </CollapsibleSection>
        {workout.completed_activity_id ? <div className="mt-2 rounded-md border border-orange-400/20 bg-orange-400/10 px-2 py-1.5 text-[11px] text-orange-100">{uiText("Тренировка выполнена", "Workout completed")}: {formatWorkoutActual(workout)}</div> : null}
        {workout.execution_score?.score !== null && workout.execution_score ? <CollapsibleSection title="Оценка выполнения" className="mt-2" summary={<Badge className={workout.execution_score.score && workout.execution_score.score >= 0.8 ? "border-orange-400/40 bg-orange-400/15 text-orange-100" : workout.execution_score.subjective_risk === "high" ? "border-rose-400/40 bg-rose-400/15 text-rose-100" : "border-zinc-700 bg-zinc-900 text-zinc-300"}>{Math.round((workout.execution_score.score || 0) * 100)}% · {workout.execution_score.status}</Badge>}>
          <div className="flex flex-wrap gap-2 text-zinc-500"><span>объем {workout.execution_score.volume_score === null ? "--" : `${Math.round(workout.execution_score.volume_score * 100)}%`}</span><span>интенсивность {workout.execution_score.intensity_score === null ? "--" : `${Math.round(workout.execution_score.intensity_score * 100)}%`}</span><span>статус {workout.execution_score.adherence_status}</span></div>{workout.execution_score.flags.length ? <p className="mt-1 text-zinc-600">{workout.execution_score.flags.slice(0, 2).join(" · ")}</p> : null}
        </CollapsibleSection> : null}
        <CollapsibleSection title="Поправить цель" className="mt-2" summary={targetChanged ? <Badge className="border-orange-400/40 bg-orange-400/15 text-orange-100">не сохранено</Badge> : <Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">вручную</Badge>}>
          <p className="mb-2 text-[11px] text-zinc-500">Если план дал странную цель, поправьте ее здесь. После сохранения блоки тренировки пересчитаются от новой дистанции/длительности.</p>
          <div className="grid gap-2 md:grid-cols-3">
            <Input placeholder="название" value={targetDraft.title} disabled={!canEditTarget} onChange={(event) => onTargetDraft(workout, { title: event.target.value })} />
            <Select value={targetDraft.workout_type} disabled={!canEditTarget} onChange={(event) => onTargetDraft(workout, { workout_type: event.target.value })}><option value="easy">легкий бег</option><option value="recovery">восстановление</option><option value="strides">ускорения</option><option value="steady">ровная работа</option><option value="interval">интервалы</option><option value="tempo">темповая</option><option value="threshold">пороговая</option><option value="hill">горки</option><option value="long">длинная</option><option value="race_pace">темп старта</option><option value="strength">ОФП</option><option value="mobility">мобилити</option></Select>
            <Input placeholder="интенсивность" value={targetDraft.intensity} disabled={!canEditTarget} onChange={(event) => onTargetDraft(workout, { intensity: event.target.value })} />
          </div>
          <div className="mt-2 grid gap-2 md:grid-cols-[1fr_1fr_2fr_auto]">
            <Input type="number" min="0" max="250" step="0.1" placeholder="цель, км" value={targetDraft.distance_km} disabled={!canEditTarget || targetSupportWorkout} onChange={(event) => onTargetDraft(workout, { distance_km: event.target.value })} />
            <Input type="number" min="1" max="1440" step="1" placeholder="цель, мин" value={targetDraft.duration_minutes} disabled={!canEditTarget} onChange={(event) => onTargetDraft(workout, { duration_minutes: event.target.value })} />
            <Input placeholder="описание" value={targetDraft.description} disabled={!canEditTarget} onChange={(event) => onTargetDraft(workout, { description: event.target.value })} />
            <Button size="sm" disabled={!canEditTarget || !targetChanged} onClick={() => onSaveTarget(workout)}>Сохранить</Button>
          </div>
          <p className="mt-2 text-[11px] text-zinc-500">{uiText("Сохраним как", "Will save as")}: {formatWorkoutTarget(targetPayload(targetDraft))}</p>
          {!canEditTarget ? <p className="mt-2 text-[11px] text-zinc-600">Чтобы изменить выполненную тренировку, сначала снимите отметку о выполнении.</p> : null}
        </CollapsibleSection>
        {canCompleteManually ? <CollapsibleSection title="Отметить вручную" className="mt-2" defaultOpen={openCompletionWorkoutId === workout.id}>
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2"><p className="font-medium text-white">Отметить тренировку</p><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">вручную</Badge></div>
          <div className="grid gap-2 md:grid-cols-4">
            <Field label={uiText("Факт, км", "Actual, km")}>{actualSupportWorkout ? <div className="rounded-md border border-zinc-800 bg-zinc-950 px-2 py-1.5 text-zinc-500">{uiText("только время", "time only")}</div> : <Input type="number" min="0" max="250" step="0.1" value={completionDraft.actual_distance_km} onChange={(event) => onCompletionDraft(workout, { actual_distance_km: event.target.value })} />}</Field>
            <Field label={uiText("Минуты", "Minutes")}><Input type="number" min="1" max="2880" step="1" value={completionDraft.actual_duration_minutes} onChange={(event) => onCompletionDraft(workout, { actual_duration_minutes: event.target.value })} /></Field>
            <Field label="RPE"><Input type="number" min="0" max="10" step="1" value={completionDraft.rpe} onChange={(event) => onCompletionDraft(workout, { rpe: event.target.value })} /></Field>
            <Field label={uiText("Средний пульс", "Average HR")}><Input type="number" min="30" max="240" step="1" value={completionDraft.average_heart_rate_bpm} onChange={(event) => onCompletionDraft(workout, { average_heart_rate_bpm: event.target.value })} /></Field>
          </div>
          <div className="mt-2 grid gap-2 md:grid-cols-4">
            <Field label={uiText("Забитость", "Soreness")}><Input type="number" min="0" max="10" value={completionDraft.soreness_0_10} onChange={(event) => onCompletionDraft(workout, { soreness_0_10: event.target.value, fatigue: event.target.value })} /></Field>
            <Field label={uiText("Боль", "Pain")}><Input type="number" min="0" max="10" value={completionDraft.pain_level} onChange={(event) => onCompletionDraft(workout, { pain_level: event.target.value, pain: Number(event.target.value) > 0 })} /></Field>
            <Field label={uiText("Сон", "Sleep")}><Input type="number" min="0" max="10" value={completionDraft.sleep_quality_0_10} onChange={(event) => onCompletionDraft(workout, { sleep_quality_0_10: event.target.value, sleep_quality: event.target.value })} /></Field>
            <Field label={uiText("Когда сделано", "Completed at")}><Input type="datetime-local" value={completionDraft.completed_at} onChange={(event) => onCompletionDraft(workout, { completed_at: event.target.value })} /></Field>
          </div>
          <div className="mt-2 grid gap-2 md:grid-cols-[1fr_1fr_1fr_auto]"><Field label={uiText("Боль / заметки", "Pain notes")}><Input value={completionDraft.pain_notes} onChange={(event) => onCompletionDraft(workout, { pain_notes: event.target.value })} /></Field><Field label={uiText("Погода", "Weather")}><Input value={completionDraft.weather_notes} onChange={(event) => onCompletionDraft(workout, { weather_notes: event.target.value })} /></Field><Field label={uiText("Комментарий", "Comment")}><Input value={completionDraft.user_notes} onChange={(event) => onCompletionDraft(workout, { user_notes: event.target.value, notes: event.target.value })} /></Field><div className="flex items-end"><Button size="sm" onClick={() => onCompleteWorkout(workout)}>Готово</Button></div></div>
        </CollapsibleSection> : null}
        {canGiveFeedback ? <CollapsibleSection title="Самочувствие" className="mt-2" summary={workout.feedback ? <Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">сохранено</Badge> : <Badge>новое</Badge>}>
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2"><p className="font-medium text-white">Самочувствие после тренировки</p>{workout.feedback ? <Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">сохранено</Badge> : <Badge>новое</Badge>}</div>
          <div className="grid gap-2 md:grid-cols-5">
            <Field label="RPE"><Input type="number" min="0" max="10" value={draft.rpe} onChange={(event) => onFeedbackDraft(workout, { rpe: event.target.value })} /></Field>
            <Field label={uiText("Забитость", "Soreness")}><Input type="number" min="0" max="10" value={draft.soreness_0_10} onChange={(event) => onFeedbackDraft(workout, { soreness_0_10: event.target.value, fatigue: event.target.value })} /></Field>
            <Field label={uiText("Боль", "Pain")}><Input type="number" min="0" max="10" value={draft.pain_level} onChange={(event) => onFeedbackDraft(workout, { pain_level: event.target.value, pain: Number(event.target.value) > 0 })} /></Field>
            <Field label={uiText("Сон", "Sleep")}><Input type="number" min="0" max="10" value={draft.sleep_quality_0_10} onChange={(event) => onFeedbackDraft(workout, { sleep_quality_0_10: event.target.value, sleep_quality: event.target.value })} /></Field>
            <label className="flex min-h-11 items-center gap-2 rounded-md border border-zinc-800 bg-zinc-950 px-3 py-1.5 text-zinc-400 md:min-h-8 md:px-2"><input checked={draft.pain} type="checkbox" onChange={(event) => onFeedbackDraft(workout, { pain: event.target.checked })} /> есть боль</label>
          </div>
          <div className="mt-2 grid gap-2 md:grid-cols-[1fr_1fr_1fr_auto]"><Field label={uiText("Боль / заметки", "Pain notes")}><Input value={draft.pain_notes} onChange={(event) => onFeedbackDraft(workout, { pain_notes: event.target.value })} /></Field><Field label={uiText("Погода", "Weather")}><Input value={draft.weather_notes} onChange={(event) => onFeedbackDraft(workout, { weather_notes: event.target.value })} /></Field><Field label={uiText("Комментарий", "Comment")}><Input value={draft.user_notes} onChange={(event) => onFeedbackDraft(workout, { user_notes: event.target.value, notes: event.target.value })} /></Field><div className="flex items-end"><Button size="sm" onClick={() => onSaveFeedback(workout)}>Сохранить</Button></div></div>
        </CollapsibleSection> : null}
        <CollapsibleSection title="Действия" className="mt-2">
        {canReschedule ? <div className="mb-2 grid gap-2 md:grid-cols-[1fr_auto]"><Input type="date" value={rescheduleDraft} onChange={(event) => onRescheduleDraft(workout, event.target.value)} /><Button size="sm" variant="ghost" disabled={!rescheduleDraft || rescheduleDraft === workout.scheduled_date} onClick={() => onReschedule(workout, rescheduleDraft)}>Перенести</Button></div> : null}
        <div className="flex flex-wrap gap-2">{workout.completed_activity_id ? <><Badge className="border-orange-400/40 bg-orange-400/15 text-orange-100">{uiText("выполнено", "completed")}</Badge><Button size="sm" variant="ghost" onClick={() => onUnlinkActivity(workout)}>{uiText("Снять отметку", "Remove completion")}</Button></> : <>{["planned", "rescheduled"].includes(workout.status) ? <><Button size="sm" variant="ghost" onClick={() => onUpdate(workout, "missed")}>{uiText("Пропустил", "Missed")}</Button><Button size="sm" variant="ghost" onClick={() => onUpdate(workout, "skipped")}>{uiText("Отменить", "Cancel")}</Button></> : null}</>}<Button size="sm" variant="ghost" disabled={loadingCandidates === workout.id} onClick={() => onFindCandidates(workout)}>{loadingCandidates === workout.id ? uiText("Ищем...", "Searching...") : uiText("Найти выполненную тренировку", "Find completed workout")}</Button></div>
        </CollapsibleSection>
        {candidateErrors[workout.id] ? <p className="mt-2 text-[11px] text-orange-200" translate="no">{candidateErrors[workout.id]}</p> : null}
        {candidates.length ? <div className="mt-2 grid gap-1.5 rounded-md border border-zinc-800 bg-zinc-950/70 p-2">
          {candidates.map((candidate) => <div key={candidate.activity.id} className="grid gap-2 rounded-md bg-zinc-900/70 p-2 md:grid-cols-[1fr_auto] md:items-center">
            <div><p className="font-medium text-white">{runKindLabel(candidate.activity)} · {candidate.activity.started_at ? formatLocalDate(candidate.activity.started_at) : noDateLabel()}</p><p className="mt-1 text-zinc-500">{formatDistance(candidate.activity.distance_km)} · {formatDuration(candidate.activity.duration_seconds)}</p><CollapsibleSection title={uiText("Почему подходит", "Why it matches")} className="mt-2" summary={<Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{uiText("детали", "details")}</Badge>}><p className="text-[11px] text-zinc-500" translate="no">{candidate.reasons.slice(0, 2).join(" · ")} · {Math.round(candidate.score * 100)}% {candidate.confidence}</p></CollapsibleSection></div>
            <div className="flex flex-wrap items-center gap-2 md:justify-end"><Button size="sm" aria-label={uiText("Отметить тренировку выполненной", "Mark workout as completed")} onClick={() => onLinkCandidate(workout, candidate.activity.id)}>{uiText("Отметить выполненной", "Mark completed")}</Button></div>
          </div>)}
        </div> : null}
      </div>
    })}</div>
  </details>
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

  async function downloadActivitiesCsv() {
    setDataBusy(true)
    setDataMessage("")
    try {
      await devLogin()
      const csv = await api.exportActivitiesCsv()
      const blob = new Blob([csv], { type: "text/csv;charset=utf-8" })
      const url = URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = url
      link.download = `runforfan-activities-${new Date().toISOString().slice(0, 10)}.csv`
      link.click()
      URL.revokeObjectURL(url)
      setDataMessage("Activities CSV export generated.")
      await loadDataManagement()
    } catch (error) {
      setDataMessage(error instanceof Error ? error.message : "Failed to export activities CSV")
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

  const defaultProvider = providers.find((provider) => provider.is_default)
  const readyProviders = providers.filter((provider) => provider.has_api_key).length

  return <div className="grid gap-4">
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><p className="text-xs font-semibold text-orange-200">{uiText("Продвинутые настройки", "Advanced settings")}</p><h2 className="mt-1 text-lg font-semibold text-white">{uiText("Готовность тренера и данных", "Coach and data readiness")}</h2><p className="mt-2 max-w-2xl text-xs leading-5 text-zinc-500">{uiText("Эти настройки нужны редко: провайдеры распознавания, интеграции, экспорт и журнал действий.", "These settings are rarely needed: recognition providers, integrations, exports and audit log.")}</p></div>
        <div className="flex flex-wrap gap-2"><Badge className={readyProviders ? "border-zinc-700 bg-zinc-900 text-zinc-300" : "border-orange-400/40 bg-orange-400/15 text-orange-100"}>{readyProviders ? uiText("распознавание готово", "recognition ready") : uiText("нужен ключ", "key needed")}</Badge>{defaultProvider ? <Badge translate="no">{defaultProvider.display_name}</Badge> : null}</div>
      </div>
    </Card>
    <div className="grid gap-4 xl:grid-cols-[24rem_1fr]">
    <CollapsibleSection title="Add LLM provider" summary={<Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">advanced</Badge>}><form onSubmit={submit} className="grid gap-3 p-4 text-xs">
      <Field label="Provider"><Select name="provider"><option value="openai">OpenAI compatible</option><option value="anthropic">Anthropic</option></Select></Field>
      <Field label="Display name"><Input name="display_name" placeholder="Display name" required /></Field>
      <Field label="Base URL"><Input name="base_url" placeholder="Gateway root or /v1 URL optional" /></Field>
      <p className="text-[11px] text-zinc-500">For OpenAI-compatible gateways, enter root or /v1 URL. Runforfan calls /chat/completions automatically.</p>
      <Field label="Model"><Input name="model" placeholder="gpt-4o-mini, claude-3-5-sonnet..." required /></Field>
      <Field label="API key"><Input name="api_key" placeholder="API key" type="password" /></Field>
      <label className="flex items-center gap-2 text-xs text-zinc-400"><input name="is_default" type="checkbox" /> default provider</label>
      <Button type="submit">Save provider</Button>
      {message ? <p className="rounded-md border border-zinc-800 bg-zinc-950 px-2 py-1.5 text-xs text-zinc-300" translate="no">{message}</p> : null}
    </form></CollapsibleSection>
    <Card><CardHeader><div><CardTitle>Providers</CardTitle><p className="text-xs text-zinc-500">Edit, test with a safe prompt, set default or disable providers.</p></div><Badge>{providers.length} total</Badge></CardHeader><div className="divide-y divide-zinc-800">{providers.map((provider) => {
      const result = testResults[provider.id]
      const busy = busyProvider === provider.id
      return <div key={provider.id} className="grid gap-3 px-4 py-3 text-xs">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div translate="no"><p className="font-medium text-white">{provider.display_name}<span className="ml-2 font-mono text-[10px] text-zinc-500">#{provider.id}</span></p><p className="mt-1 text-zinc-500">{provider.provider} · {provider.model}</p></div>
          <div className="flex flex-wrap gap-1">{provider.is_default && <Badge>default</Badge>}<Badge className={provider.has_api_key ? "border-zinc-700 bg-zinc-900 text-zinc-300" : "border-orange-400/30 bg-orange-400/10 text-orange-200"}>key {provider.has_api_key ? "stored" : "missing"}</Badge><Badge className={provider.supports_vision ? "border-zinc-700 bg-zinc-900 text-zinc-300" : "border-zinc-800 bg-zinc-950 text-zinc-500"}>vision {provider.supports_vision ? "likely" : "unknown"}</Badge></div>
        </div>
        <CollapsibleSection title="Edit provider" className="mt-2">
        <form onSubmit={(event) => updateExisting(event, provider)} className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
          <Field label="Name"><Input name="display_name" defaultValue={provider.display_name} /></Field>
          <Field label="Base URL"><Input name="base_url" defaultValue={provider.base_url || ""} placeholder="gateway root or /v1 URL" /></Field>
          <Field label="Model"><Input name="model" defaultValue={provider.model} /></Field>
          <Field label="New API key"><Input name="api_key" type="password" placeholder={provider.has_api_key ? "leave blank to keep" : "optional"} /></Field>
          <label className="flex h-8 items-center gap-2 rounded-md border border-zinc-800 bg-zinc-950 px-2.5 text-zinc-400"><input name="clear_api_key" type="checkbox" /> clear key</label>
          <div className="flex flex-wrap gap-2 md:col-span-2 xl:col-span-3"><Button size="sm" type="submit" disabled={busy}>{busy ? "Saving..." : "Save changes"}</Button><Button size="sm" type="button" variant="secondary" disabled={busy || provider.is_default} onClick={() => setDefault(provider)}>Set default</Button><Button size="sm" type="button" variant="secondary" disabled={busy} onClick={() => testProvider(provider)}>{busy ? "Testing..." : "Test"}</Button><Button size="sm" type="button" variant="secondary" disabled={busy} onClick={() => deleteExisting(provider)}>Delete</Button></div>
        </form>
        </CollapsibleSection>
        {result ? <div className={`rounded-md border px-2 py-1.5 text-xs ${result.ok ? "border-zinc-700 bg-zinc-900 text-zinc-200" : "border-orange-400/20 bg-orange-400/10 text-orange-100"}`} translate="no">{result.status} · {result.response_ms ?? "--"} ms · vision {result.supports_vision ? "likely" : "unknown"}<div className="mt-1 text-zinc-500">{result.message}</div></div> : null}
      </div>
    })}{!providers.length ? <p className="p-4 text-xs text-zinc-500">No active providers yet.</p> : null}</div></Card>
    </div>
    <div className="grid gap-4 xl:grid-cols-[1fr_1fr]">
      <Card>
        <CardHeader><div><CardTitle>Integrations</CardTitle><p className="text-xs text-zinc-500">Configured and planned data sources.</p></div><Button size="sm" variant="secondary" onClick={loadDataManagement}>Refresh</Button></CardHeader>
        <div className="divide-y divide-zinc-800">{integrations.map((integration) => <div key={integration.id} className="grid gap-2 px-4 py-3 text-xs md:grid-cols-[1fr_auto] md:items-start" translate="no">
          <div><p className="font-medium text-white">{integration.name}</p><p className="mt-1 text-zinc-500">{integration.description}</p><p className="mt-1 font-mono text-[10px] uppercase tracking-[0.14em] text-zinc-600">{integration.category} · {integration.id}</p></div>
          <Badge className={integration.configured ? "border-zinc-700 bg-zinc-900 text-zinc-300" : integration.status === "planned" ? "border-zinc-800 bg-zinc-950 text-zinc-500" : "border-orange-400/30 bg-orange-400/10 text-orange-200"}>{integration.status}</Badge>
        </div>)}{!integrations.length ? <p className="p-4 text-xs text-zinc-500">No integration data loaded.</p> : null}</div>
      </Card>
      <Card>
        <CardHeader><div><CardTitle>Data management</CardTitle><p className="text-xs text-zinc-500">Export current user data or wipe account-scoped records.</p></div><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">advanced</Badge></CardHeader>
        <div className="grid gap-3 p-4 text-xs">
          <div className="flex flex-wrap gap-2"><Button type="button" disabled={dataBusy} onClick={downloadExport}>{dataBusy ? "Working..." : "Download JSON export"}</Button><Button type="button" variant="secondary" disabled={dataBusy} onClick={downloadActivitiesCsv}>{dataBusy ? "Working..." : "Download activities CSV"}</Button></div>
          <div className="rounded-md border border-zinc-800 bg-zinc-950 p-3 text-zinc-400">Export omits API keys and local screenshot file paths. It includes user-scoped activities, plans, goals, profile, providers without secrets, imports and audit log.</div>
          <CollapsibleSection title="Danger zone" className="border-orange-400/25 bg-orange-400/10">
            <p className="font-medium text-orange-100">Danger zone: delete account data</p>
            <p className="text-orange-100/80">This keeps the user/session but deletes activities, plans, goals, profile, zones, imports, provider settings and prior audit rows.</p>
            <Input value={deleteConfirm} onChange={(event) => setDeleteConfirm(event.target.value)} placeholder="Type DELETE to confirm" />
            <Button type="button" variant="secondary" disabled={dataBusy || deleteConfirm !== "DELETE"} onClick={deleteAccountData}>Delete user data</Button>
          </CollapsibleSection>
          {dataMessage ? <p className="rounded-md border border-zinc-800 bg-zinc-950 px-2 py-1.5 text-xs text-zinc-300" translate="no">{dataMessage}</p> : null}
        </div>
      </Card>
    </div>
    <CollapsibleSection title="Audit log" summary={<Badge>{auditLog.length} events</Badge>}>
    <Card>
      <CardHeader><div><CardTitle>Audit log</CardTitle><p className="text-xs text-zinc-500">Recent user-scoped import, provider, export and delete events.</p></div><Badge>{auditLog.length} events</Badge></CardHeader>
      <div className="grid min-w-0 gap-2 p-4 md:hidden">{auditLog.map((event) => <div key={`audit-mobile-${event.id}`} className="min-w-0 rounded-md border border-zinc-800 bg-zinc-950 p-3 text-xs" translate="no"><div className="flex min-w-0 flex-wrap items-start justify-between gap-2"><div className="min-w-0"><p className="break-words text-zinc-500">{formatLocalDateTime(event.created_at)}</p><p className="mt-1 break-words text-zinc-400">{event.entity_type}{event.entity_id ? ` #${event.entity_id}` : ""}</p></div><Badge className="max-w-full border-zinc-700 bg-zinc-900 text-zinc-300">{event.action}</Badge></div><p className="mt-2 max-w-full overflow-hidden break-all text-zinc-500">{event.metadata_json ? JSON.stringify(event.metadata_json) : "--"}</p></div>)}{!auditLog.length ? <p className="text-xs text-zinc-500">Audit log is empty.</p> : null}</div><div className="hidden overflow-x-auto md:block"><table className="w-full min-w-[720px] text-left text-xs"><thead className="border-b border-zinc-800 text-[10px] uppercase tracking-[0.14em] text-zinc-500"><tr><th className="px-4 py-2">Time</th><th>Action</th><th>Entity</th><th>Metadata</th></tr></thead><tbody>{auditLog.map((event) => <tr key={event.id} className="border-b border-zinc-900 last:border-0 align-top"><td className="px-4 py-2 text-zinc-500" translate="no">{formatLocalDateTime(event.created_at)}</td><td><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300" translate="no">{event.action}</Badge></td><td className="text-zinc-400" translate="no">{event.entity_type}{event.entity_id ? ` #${event.entity_id}` : ""}</td><td className="max-w-[28rem] break-words text-zinc-500" translate="no">{event.metadata_json ? JSON.stringify(event.metadata_json) : "--"}</td></tr>)}</tbody></table>{!auditLog.length ? <p className="p-4 text-xs text-zinc-500">Audit log is empty.</p> : null}</div>
    </Card>
    </CollapsibleSection>
  </div>
}

export default App
