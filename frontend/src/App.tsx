import { Activity, Bot, ChartSpline, Goal, HeartPulse, Menu, Moon, Settings, Shield, X, Zap } from "lucide-react"
import { type FormEvent, type ReactNode, useEffect, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { api, type Activity as ActivityType, type AthleteMeasurement, type AthleteProfile, devLogin, type LlmProvider, type ProfileCompleteness, type SafetyCheck, type Zone, type Zones } from "@/lib/api"
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
  const [result, setResult] = useState<Record<string, any> | null>(null)
  async function generate() { setResult(await api.generatePlan({ title: "Марафонская программа", goal_type: "marathon", race_distance_km: 42.2, available_days_per_week: 4, current_weekly_distance_km: 15.5 })) }
  return <Card><CardHeader><CardTitle>Program planner</CardTitle><Button onClick={generate}>Generate</Button></CardHeader><div className="p-4 text-sm text-zinc-400">{result ? <><p>{result.explanation}</p><p className="mt-3 font-mono text-orange-300">{result.workouts?.length} planned workouts</p></> : "Hybrid planner: rules first, LLM explanations later."}</div></Card>
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
