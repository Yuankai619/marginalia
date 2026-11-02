import type { ReactNode } from "react";
import { Hint } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

export type SegmentedOption<T extends string> = {
  id: T;
  label: ReactNode;
  icon?: ReactNode;
  hint?: string;
};

/** A pill row of mutually exclusive toggles (mode, layout, effort), styled like open-slide's. */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  disabled,
  title,
  stretch,
  className,
}: {
  options: SegmentedOption<T>[];
  value: T;
  onChange: (value: T) => void;
  disabled?: boolean;
  title?: string;
  /** Equal-width segments filling the row. */
  stretch?: boolean;
  className?: string;
}) {
  return (
    <div
      title={title}
      className={cn(
        "flex min-w-0 gap-0.5 rounded-[6px] bg-muted p-0.5",
        className,
      )}
    >
      {options.map((option) => {
        const button = (
          <button
            key={option.id}
            type="button"
            aria-pressed={value === option.id}
            disabled={disabled}
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => onChange(option.id)}
            className={cn(
              "flex h-6 items-center justify-center gap-1 rounded-[4px] px-2 text-[11.5px] whitespace-nowrap text-muted-foreground outline-none transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/30 disabled:opacity-60 [&_svg]:size-3",
              stretch && "min-w-0 flex-1 truncate px-1",
              value === option.id &&
                "bg-background font-medium text-foreground shadow-edge",
            )}
          >
            {option.icon}
            {option.label}
          </button>
        );
        return option.hint ? (
          <Hint key={option.id} label={option.hint} side="top">
            {button}
          </Hint>
        ) : (
          button
        );
      })}
    </div>
  );
}
