// Adapted from open-slide (MIT, Copyright (c) 2026 Yiwei Ho).
import { Tooltip as TooltipPrimitive } from "@base-ui/react/tooltip";
import type * as React from "react";
import { cn } from "@/lib/utils";

export const TooltipProvider = TooltipPrimitive.Provider;

/** A hover / focus hint for an icon-only control. `label` doubles as the accessible name. */
export function Hint({
  label,
  side = "bottom",
  children,
  className,
}: {
  label: React.ReactNode;
  side?: "top" | "bottom" | "left" | "right";
  children: React.ReactElement;
  className?: string;
}) {
  return (
    <TooltipPrimitive.Root>
      <TooltipPrimitive.Trigger render={children} />
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Positioner
          side={side}
          sideOffset={6}
          className="isolate z-50"
        >
          <TooltipPrimitive.Popup
            className={cn(
              "max-w-64 origin-(--transform-origin) rounded-[6px] bg-foreground px-2 py-1 text-[11.5px] leading-snug text-background shadow-floating",
              "transition-[transform,scale,opacity] data-ending-style:scale-95 data-ending-style:opacity-0 data-starting-style:scale-95 data-starting-style:opacity-0 data-[instant]:duration-0",
              className,
            )}
          >
            {label}
          </TooltipPrimitive.Popup>
        </TooltipPrimitive.Positioner>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}
