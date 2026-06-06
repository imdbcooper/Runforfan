import { Activity, Bot, ChartSpline, Goal, Menu, Moon, Settings, Shield, X, Zap } from "lucide-react"
import { FormEvent, useEffect, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { api, type Activity as ActivityType, devLogin, type LlmProvider } from "@/lib/api"
import { cn } from "@/lib/utils"

type Page = "overview" | "activities" | "analytics" | "planning" | "settings"

const nav = [
  ["overview", "Dashboard", Zap],
  ["activities", "Activities", Activity],
  ["analytics", "Analytics", ChartSpline],
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

function App() {
  const [page, setPage] = useState<Page>("overview")
  const [mobileOpen, setMobileOpen] = useState(false)
  const [activities, setActivities] = useState<ActivityType[]>([])
  const [analytics, setAnalytics] = useState<Record<string, any>>({})
  const [providers, setProviders] = useState<LlmProvider[]>([])
  const [status, setStatus] = useState("LOADING")

  async function refresh() {
    try {
      await devLogin()
      const [nextActivities, nextAnalytics, nextProviders] = await Promise.all([api.activities(), api.analytics(), api.providers()])
      setActivities(nextActivities)
      setAnalytics(nextAnalytics)
      setProviders(nextProviders)
      setStatus("DEMO USER")
    } catch (error) {
      setStatus("API ERROR")
      console.error(error)
    }
  }

  useEffect(() => { void refresh() }, [])

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
            {page === "planning" && <Planning />}
            {page === "settings" && <SettingsPage providers={providers} onChanged={refresh} />}
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
        <thead className="border-b border-zinc-800 text-[10px] uppercase tracking-[0.14em] text-zinc-500"><tr><th className="px-4 py-2">Name</th><th>Distance</th><th>Pace</th><th>HR</th><th>Segments</th><th>ID</th></tr></thead>
        <tbody>{activities.slice(0, compact ? 6 : undefined).map((activity) => <tr key={activity.id} className="border-b border-zinc-900 last:border-0 hover:bg-zinc-900/60"><td className="px-4 py-3 font-medium text-white">{activity.title}<div className="text-[11px] text-zinc-500">{activity.started_at ? new Date(activity.started_at).toLocaleString("ru-RU") : "без даты"}</div></td><td>{formatDistance(activity.distance_km)}</td><td>{formatPace(activity.average_pace_seconds_per_km)}/км</td><td>{activity.average_heart_rate_bpm || "--"}</td><td>{activity.segments.length}</td><td className="font-mono text-zinc-500">#{activity.id}</td></tr>)}</tbody>
      </table>
    </div>
  </Card>
}

function Analytics({ analytics }: { analytics: Record<string, any> }) {
  const months = analytics.months || []
  const max = Math.max(1, ...months.map((month: any) => month.distance_km))
  return <Card><CardHeader><CardTitle>Monthly volume</CardTitle><Badge>{analytics.total_distance_km || 0} km total</Badge></CardHeader><div className="space-y-3 p-4">{months.map((month: any) => <div key={month.month} className="grid grid-cols-[110px_1fr_90px] items-center gap-3 text-xs"><span className="text-zinc-400">{month.month}</span><div className="h-2 rounded bg-zinc-900"><div className="h-full rounded bg-orange-400" style={{ width: `${Math.max(6, month.distance_km / max * 100)}%` }} /></div><strong>{month.distance_km.toFixed(1)} км</strong></div>)}</div></Card>
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
