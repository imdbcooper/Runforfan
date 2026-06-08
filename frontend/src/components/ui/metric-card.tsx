import * as React from "react"

import { cn } from "@/lib/utils"

type MetricCardProps = {
  label: string
  value: React.ReactNode
  suffix?: string
  hint?: React.ReactNode
  explainer?: React.ReactNode
  className?: string
}

export function MetricCard({ label, value, suffix, hint, explainer, className }: MetricCardProps) {
  return <div className={cn("rounded-md border border-zinc-800 bg-zinc-950 p-3", className)}>
    <div className="flex items-start justify-between gap-2">
      <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-zinc-500">{label}</span>
      {explainer}
    </div>
    <strong className="mt-2 block text-lg leading-none text-white">{value}{suffix ? <span className="ml-1 text-sm text-zinc-400">{suffix}</span> : null}</strong>
    {hint ? <p className="mt-2 text-[11px] leading-4 text-zinc-500">{hint}</p> : null}
  </div>
}
