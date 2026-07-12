import * as React from "react"

import { cn } from "@/lib/utils"

export const Select = React.forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement>>(({ className, ...props }, ref) => (
  <select ref={ref} className={cn("h-11 w-full rounded-md border border-zinc-800 bg-zinc-950 px-3 text-xs text-zinc-100 outline-none hover:border-zinc-700 focus:border-orange-400 focus:ring-2 focus:ring-orange-400/15 md:h-8 md:px-2.5", className)} {...props} />
))
Select.displayName = "Select"
