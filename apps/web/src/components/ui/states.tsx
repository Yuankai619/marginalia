import type { LucideIcon } from "lucide-react";
import type * as React from "react";
import { cn } from "@/lib/utils";

/** Indeterminate hairline loader with a short label, used for every loading state. */
export function LoadingState({
  label = "載入中",
  className,
}: {
  label?: string;
  className?: string;
}) {
  return (
    <div
      role="status"
      className={cn(
        "flex flex-1 flex-col items-center justify-center gap-3 px-6 py-16 text-center",
        className,
      )}
    >
      <span className="relative block h-px w-24 overflow-hidden bg-hairline">
        <span className="line-loader-bar absolute inset-y-0 left-0 w-1/4 bg-foreground/60" />
      </span>
      <span className="text-[12.5px] text-muted-foreground">{label}…</span>
    </div>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  tone = "default",
  className,
}: {
  icon?: LucideIcon;
  title: string;
  description?: React.ReactNode;
  action?: React.ReactNode;
  tone?: "default" | "error";
  className?: string;
}) {
  return (
    <div
      role={tone === "error" ? "alert" : undefined}
      className={cn(
        "flex flex-1 flex-col items-center justify-center gap-2 px-6 py-16 text-center",
        className,
      )}
    >
      {Icon && (
        <Icon
          className={cn(
            "mb-1 size-6",
            tone === "error" ? "text-destructive" : "text-muted-foreground/60",
          )}
          strokeWidth={1.5}
          aria-hidden
        />
      )}
      <p className="text-[14px] font-medium">{title}</p>
      {description && (
        <p className="max-w-sm text-[12.5px] leading-relaxed text-muted-foreground">
          {description}
        </p>
      )}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}
