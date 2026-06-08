import * as React from "react"

import { cn } from "@/lib/utils"

type CalculationExplainerProps = {
  title?: string
  className?: string
  children: React.ReactNode
}

export function CalculationExplainer({ title = "Why?", className, children }: CalculationExplainerProps) {
  return <details className={cn("group relative text-left", className)}>
    <summary className="inline-flex cursor-pointer list-none items-center rounded-md border border-orange-400/25 bg-orange-400/10 px-1.5 py-0.5 text-[10px] font-medium text-orange-200 transition-colors hover:bg-orange-400/15 [&::-webkit-details-marker]:hidden">{title}</summary>
    <div className="absolute right-0 z-20 mt-1 w-72 max-w-[calc(100vw-2rem)] break-words rounded-md border border-zinc-800 bg-zinc-950 p-3 text-[11px] leading-5 text-zinc-300 shadow-xl shadow-black/40 max-sm:static max-sm:mt-2 max-sm:w-full">
      {children}
    </div>
  </details>
}
