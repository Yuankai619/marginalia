// Adapted from open-slide (MIT, Copyright (c) 2026 Yiwei Ho).
import { Button as ButtonPrimitive } from "@base-ui/react/button";
import { cva, type VariantProps } from "class-variance-authority";
import type * as React from "react";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  [
    "relative inline-flex shrink-0 items-center justify-center whitespace-nowrap select-none",
    "rounded-[6px] text-[13px] font-medium",
    "outline-none transition-[background-color,color,border-color,box-shadow,transform] duration-100",
    "focus-visible:ring-2 focus-visible:ring-ring/40 focus-visible:ring-offset-1 focus-visible:ring-offset-background",
    "active:not-aria-[haspopup]:translate-y-px",
    "disabled:pointer-events-none disabled:opacity-45",
    "[&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-3.5",
  ].join(" "),
  {
    variants: {
      variant: {
        default:
          "bg-foreground text-background shadow-[inset_0_1px_0_oklch(1_0_0/0.12),0_1px_0_oklch(0_0_0/0.12)] hover:bg-foreground/88",
        brand:
          "bg-brand text-brand-foreground shadow-[inset_0_1px_0_oklch(1_0_0/0.18),0_1px_0_oklch(0_0_0/0.16)] hover:brightness-105",
        outline:
          "border border-border bg-card text-foreground hover:border-foreground/20 hover:bg-muted/60 aria-expanded:bg-muted",
        ghost:
          "text-foreground/75 hover:bg-muted hover:text-foreground aria-expanded:bg-muted aria-expanded:text-foreground aria-pressed:bg-muted aria-pressed:text-foreground",
        destructive: "bg-destructive text-white hover:brightness-105",
      },
      size: {
        default: "h-8 gap-1.5 px-3",
        xs: "h-6 gap-1 rounded-[5px] px-2 text-[11.5px]",
        sm: "h-7 gap-1.5 rounded-[5px] px-2.5 text-[12px]",
        lg: "h-9 gap-2 px-4 text-[13.5px]",
        icon: "size-8",
        "icon-xs": "size-6 rounded-[5px]",
        "icon-sm": "size-7 rounded-[5px]",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export function Button({
  className,
  variant,
  size,
  ...props
}: React.ComponentProps<typeof ButtonPrimitive> &
  VariantProps<typeof buttonVariants>) {
  return (
    <ButtonPrimitive
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  );
}

export { buttonVariants };
