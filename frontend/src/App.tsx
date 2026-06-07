import { Activity, Bot, ChartSpline, Goal, HeartPulse, Menu, Moon, Settings, Shield, X, Zap } from "lucide-react"
import { type FormEvent, type ReactNode, useEffect, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { api, type Activity as ActivityType, type AthleteMeasurement, type AthleteProfile, devLogin, type LlmProvider, type Plan, type PlanActivityMatchCandidate, type PlanWorkout, type ProfileCompleteness, type SafetyCheck, type Zone, type Zones } from "@/lib/api"
import { cn } from "@/lib/utils"

type Page = "overview" | "activities" | "analytics" | "profile" | "planning" | "settings"

const nav = [
  ["overview", "Dashboard", Zap],
  ["activities", "Activities", Activity],
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
      const [nextActivities, nextAnalytics, nextProviders] = await Promise.all([
        api.activities(),
        api.analytics(),
        api.providers(),
      ])
      setActivities(nextActivities)
      setAnalytics(nextAnalytics)
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
            {page === "overview" && <Overview activities={activities} analytics={analytics} providers={providers} />}
            {page === "activities" && <Activities activities={activities} />}
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

function Overview({ activities, analytics, providers }: { activities: ActivityType[]; analytics: Record<string, any>; providers: LlmProvider[] }) {
  return <div className="grid gap-4">
    <div className="grid min-w-0 gap-4 xl:grid-cols-[1fr_1.35fr]">
      <Card className="p-4"><p className="font-mono text-[10px] uppercase tracking-[0.18em] text-zinc-500">Dashboard</p><h2 className="mt-2 text-lg font-semibold text-white">Runforfan overview</h2><Button className="mt-3">+ Add screenshots</Button></Card>
      <Card className="grid grid-cols-4 divide-x divide-zinc-800 p-3 max-md:grid-cols-2 max-md:divide-x-0 max-md:divide-y">
        <Stat label="activities" value={activities.length} />
        <Stat label="distance" value={analytics.total_distance_km || 0} suffix="km" />
        <Stat label="providers" value={providers.length} />
        <Stat label="pace" value={formatPace(analytics.weighted_average_pace_seconds_per_km)} />
      </Card>
    </div>
    <Activities activities={activities} compact />
  </div>
}

function Stat({ label, value, suffix }: { label: string; value: string | number; suffix?: string }) {
  return <div className="px-4 py-3 text-center"><strong className="block text-lg text-white">{value}{suffix ? ` ${suffix}` : ""}</strong><span className="font-mono text-[10px] uppercase tracking-[0.16em] text-zinc-500">{label}</span></div>
}

function Activities({ activities, compact = false }: { activities: ActivityType[]; compact?: boolean }) {
  return <Card>
    <CardHeader><div><CardTitle>Activities</CardTitle><p className="text-xs text-zinc-500">{activities.length} total</p></div><Button size="sm">+ Import</Button></CardHeader>
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

function Planning() {
  const [plans, setPlans] = useState<Plan[]>([])
  const [result, setResult] = useState<Plan | null>(null)
  const [candidatesByWorkout, setCandidatesByWorkout] = useState<Record<number, PlanActivityMatchCandidate[]>>({})
  const [candidateErrors, setCandidateErrors] = useState<Record<number, string>>({})
  const [loadingCandidates, setLoadingCandidates] = useState<number | null>(null)

  async function loadPlans() {
    await devLogin()
    const nextPlans = await api.plans()
    setPlans(nextPlans)
    setResult((current) => current ? nextPlans.find((plan) => plan.id === current.id) || current : nextPlans.find((plan) => plan.status === "active") || nextPlans[0] || null)
  }

  async function generate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    const plan = await api.generatePlan({
      title: stringOrNull(data.get("title")) || "Марафонская программа",
      goal_type: stringOrNull(data.get("goal_type")) || "marathon",
      race_distance_km: numberOrNull(data.get("race_distance_km")) || 42.2,
      target_date: stringOrNull(data.get("target_date")),
      available_days_per_week: numberOrNull(data.get("available_days_per_week")) || 4,
      current_weekly_distance_km: numberOrNull(data.get("current_weekly_distance_km")),
    })
    setResult(plan)
    await loadPlans()
  }

  async function activate(id: number) {
    setResult(await api.activatePlan(id))
    await loadPlans()
  }

  async function updateWorkout(workout: PlanWorkout, status: string) {
    await api.updatePlanWorkout(workout.id, { status })
    if (result) setResult(await api.plan(result.id))
    await loadPlans()
  }

  async function loadCandidates(workout: PlanWorkout) {
    setLoadingCandidates(workout.id)
    setCandidateErrors((current) => ({ ...current, [workout.id]: "" }))
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
    await api.linkPlanWorkoutActivity(workout.id, activityId)
    setCandidatesByWorkout((current) => ({ ...current, [workout.id]: [] }))
    if (result) setResult(await api.plan(result.id))
    await loadPlans()
  }

  useEffect(() => { void loadPlans() }, [])

  const weeks = Array.from(new Set(result?.workouts.map((workout) => workout.week_index) || [])).slice(0, 4)
  const hasSafetyInfo = result?.explanation?.includes("Safety gates:") || false
  const conservative = hasSafetyInfo && result?.explanation?.includes("Safety gates: no active safety gates") === false
  const planMode = !result ? null : !hasSafetyInfo ? "legacy" : conservative ? "safety gated" : "standard"
  const weeklyAdherence = result?.weekly_adherence?.slice(0, 4) || []
  return <div className="grid gap-4 xl:grid-cols-[24rem_1fr]">
    <Card>
      <CardHeader><div><CardTitle>Program planner</CardTitle><p className="text-xs text-zinc-500">Profile-aware rules, zones and safety gates.</p></div>{result && <Badge>#{result.id}</Badge>}</CardHeader>
      <form onSubmit={generate} className="grid gap-3 p-4 text-xs">
        <Field label="Название"><Input name="title" defaultValue="Марафонская программа" /></Field>
        <Field label="Цель"><Select name="goal_type" defaultValue="marathon"><option value="5k">5K</option><option value="10k">10K</option><option value="half_marathon">Half marathon</option><option value="marathon">Marathon</option><option value="custom">Custom</option></Select></Field>
        <Field label="Дистанция, км"><Input name="race_distance_km" type="number" min="1" max="100" step="0.1" defaultValue="42.2" /></Field>
        <Field label="Дата старта"><Input name="target_date" type="date" /></Field>
        <Field label="Дней в неделю"><Input name="available_days_per_week" type="number" min="2" max="7" defaultValue="4" /></Field>
        <Field label="Текущий объем, км/нед"><Input name="current_weekly_distance_km" type="number" min="0" max="200" step="0.1" placeholder="если пусто, возьмем из истории" /></Field>
        <Button type="submit">Generate profile-aware plan</Button>
      </form>
      <div className="border-t border-zinc-800 p-4">
        <div className="mb-2 flex items-center justify-between"><p className="text-xs font-semibold text-white">Saved plans</p><Badge>{plans.length} total</Badge></div>
        <div className="grid gap-2">{plans.slice(0, 6).map((plan) => <button key={plan.id} onClick={() => setResult(plan)} className={cn("rounded-md border px-2 py-2 text-left text-xs", result?.id === plan.id ? "border-orange-400/40 bg-orange-400/10" : "border-zinc-800 bg-zinc-950 hover:bg-zinc-900")}><span className="font-medium text-white">{plan.title}</span><span className="ml-2 text-zinc-500">#{plan.id}</span><div className="mt-1 flex items-center gap-2"><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{plan.status}</Badge><span className="text-zinc-500">{plan.workouts.length} workouts</span></div></button>)}</div>
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
          <div className="grid grid-cols-3 gap-2 text-center text-xs">
            <Stat label="weeks" value={Math.max(...result.workouts.map((workout) => workout.week_index))} />
            <Stat label="workouts" value={result.workouts.length} />
            <Stat label="days/week" value={result.available_days_per_week} />
          </div>
          {weeklyAdherence.length ? <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">{weeklyAdherence.map((week) => <div key={week.week_index} className="rounded-md border border-zinc-800 bg-zinc-950 px-3 py-2 text-xs"><div className="flex items-center justify-between"><span className="font-medium text-white">Week {week.week_index}</span><Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{Math.round(week.completion_rate * 100)}%</Badge></div><div className="mt-2 text-zinc-500">{week.done_workouts}/{week.planned_workouts} done</div><div className="text-zinc-500">{week.completed_distance_km}/{week.planned_distance_km} км</div></div>)}</div> : null}
          <div className="grid gap-3">{weeks.map((week) => <PlanWeek key={week} week={week} workouts={result.workouts.filter((workout) => workout.week_index === week)} candidatesByWorkout={candidatesByWorkout} candidateErrors={candidateErrors} loadingCandidates={loadingCandidates} onFindCandidates={loadCandidates} onLinkCandidate={linkCandidate} onUpdate={updateWorkout} />)}</div>
        </> : <p>Generate a plan to see how profile completeness, safety gates and zones change the weekly structure.</p>}
      </div>
    </Card>
  </div>
}

function PlanWeek({ week, workouts, candidatesByWorkout, candidateErrors, loadingCandidates, onFindCandidates, onLinkCandidate, onUpdate }: { week: number; workouts: PlanWorkout[]; candidatesByWorkout: Record<number, PlanActivityMatchCandidate[]>; candidateErrors: Record<number, string>; loadingCandidates: number | null; onFindCandidates: (workout: PlanWorkout) => Promise<void>; onLinkCandidate: (workout: PlanWorkout, activityId: number) => Promise<void>; onUpdate: (workout: PlanWorkout, status: string) => Promise<void> }) {
  const plannedDistance = workouts.reduce((sum, workout) => sum + (workout.distance_km || 0), 0)
  return <div className="rounded-md border border-zinc-800 bg-zinc-950/60">
    <div className="flex items-center justify-between border-b border-zinc-800 px-3 py-2"><p className="text-xs font-semibold text-white">Week {week}</p><Badge>{plannedDistance.toFixed(1)} км</Badge></div>
    <div className="grid gap-2 p-3">{workouts.map((workout) => {
      const candidates = candidatesByWorkout[workout.id] || []
      return <div key={workout.id} className="rounded-md border border-zinc-900 bg-zinc-950 p-3 text-xs">
        <div className="flex flex-wrap items-start justify-between gap-2"><div><p className="font-medium text-white">{workout.title}</p><p className="mt-1 text-zinc-500">{workout.scheduled_date ? new Date(workout.scheduled_date).toLocaleDateString("ru-RU") : "no date"} · {workout.distance_km?.toFixed(1) || "--"} км · {workout.intensity}</p></div><Badge className={workout.status === "done" ? "border-orange-400/40 bg-orange-400/15 text-orange-100" : "border-zinc-700 bg-zinc-900 text-zinc-300"}>{workout.status}</Badge></div>
        <p className="mt-2 leading-5 text-zinc-400">{workout.description}</p>
        {workout.completed_activity_id ? <div className="mt-2 rounded-md border border-orange-400/20 bg-orange-400/10 px-2 py-1.5 text-[11px] text-orange-100">Linked activity #{workout.completed_activity_id}: {formatDistance(workout.actual_distance_km)} · {formatDuration(workout.actual_duration_seconds)}</div> : null}
        <div className="mt-2 flex flex-wrap gap-2"><Button size="sm" variant="secondary" onClick={() => onUpdate(workout, "done")}>Done</Button><Button size="sm" variant="ghost" onClick={() => onUpdate(workout, "missed")}>Missed</Button><Button size="sm" variant="ghost" onClick={() => onUpdate(workout, "skipped")}>Skipped</Button><Button size="sm" variant="ghost" disabled={loadingCandidates === workout.id} onClick={() => onFindCandidates(workout)}>{loadingCandidates === workout.id ? "Matching..." : "Find activity"}</Button></div>
        {candidateErrors[workout.id] ? <p className="mt-2 text-[11px] text-orange-200">{candidateErrors[workout.id]}</p> : null}
        {candidates.length ? <div className="mt-2 grid gap-1.5 rounded-md border border-zinc-800 bg-zinc-950/70 p-2">
          {candidates.map((candidate) => <div key={candidate.activity.id} className="grid gap-2 rounded-md bg-zinc-900/70 p-2 md:grid-cols-[1fr_auto] md:items-center">
            <div><p className="font-medium text-white">{candidate.activity.title}<span className="ml-2 font-mono text-[10px] text-zinc-500">#{candidate.activity.id}</span></p><p className="mt-1 text-zinc-500">{candidate.activity.started_at ? new Date(candidate.activity.started_at).toLocaleDateString("ru-RU") : "без даты"} · {formatDistance(candidate.activity.distance_km)} · {formatDuration(candidate.activity.duration_seconds)}</p><p className="mt-1 text-[11px] text-zinc-500">{candidate.reasons.slice(0, 2).join(" · ")}</p></div>
            <div className="flex flex-wrap items-center gap-2 md:justify-end"><Badge className="border-zinc-700 bg-zinc-950 text-zinc-300">{Math.round(candidate.score * 100)}% {candidate.confidence}</Badge><Button size="sm" onClick={() => onLinkCandidate(workout, candidate.activity.id)}>Link</Button></div>
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
