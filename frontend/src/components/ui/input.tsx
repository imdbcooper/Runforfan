import * as React from "react"

import { cn } from "@/lib/utils"

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(({ className, ...props }, ref) => (
  <input ref={ref} className={cn("h-8 w-full rounded-md border border-zinc-800 bg-zinc-950 px-2.5 text-xs text-zinc-100 outline-none placeholder:text-zinc-600 hover:border-zinc-700 focus:border-orange-400 focus:ring-2 focus:ring-orange-400/15", className)} {...props} />
))
Input.displayName = "Input"
