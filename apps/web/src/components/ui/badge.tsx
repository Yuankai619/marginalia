import type * as React from "react";
import { cn } from "@/lib/utils";

const tones = {
  neutral: "bg-muted text-muted-foreground",
  brand: "bg-brand-soft text-brand",
  success: "bg-success/12 text-success",
  warning: "bg-warning/14 text-warning",
  danger: "bg-destructive/10 text-destructive",
} as const;

export function Badge({
  tone = "neutral",
  className,
  ...props
}: React.ComponentProps<"span"> & { tone?: keyof typeof tones }) {
  return (
    <span
      className={cn(
        "inline-flex h-5 shrink-0 items-center gap-1 rounded-[4px] px-1.5 text-[11px] font-medium whitespace-nowrap [&_svg]:size-3",
        tones[tone],
        className,
      )}
      {...props}
    />
  );
}
