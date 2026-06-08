import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"
import * as React from "react"

import { cn } from "@/lib/utils"

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-400/70 disabled:pointer-events-none disabled:opacity-55 [&_svg]:h-3.5 [&_svg]:w-3.5",
  {
    variants: {
      variant: {
        default: "bg-orange-500 text-black hover:bg-orange-400",
        secondary: "border border-white/10 bg-zinc-900 text-zinc-100 hover:bg-zinc-800",
        ghost: "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-100",
        destructive: "border border-rose-400/30 bg-rose-500/15 text-rose-100 hover:bg-rose-500/25",
      },
      size: {
        default: "h-9 px-3 md:h-8",
        sm: "h-8 px-2.5 md:h-7",
        lg: "h-9 px-4",
        icon: "h-9 w-9 p-0 md:h-8 md:w-8",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  }
)

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  asChild?: boolean
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(({ className, variant, size, asChild = false, ...props }, ref) => {
  const Comp = asChild ? Slot : "button"
  return <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />
})
Button.displayName = "Button"
