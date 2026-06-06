import * as React from "react"

import { cn } from "@/lib/utils"

export function Badge({ className, ...props }: React.HTMLAttributes<HTMLSpanElement>) {
  return <span className={cn("inline-flex h-5 items-center rounded-md border border-orange-400/25 bg-orange-400/10 px-1.5 text-[10px] font-medium text-orange-200", className)} {...props} />
}
