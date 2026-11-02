// Adapted from open-slide (MIT, Copyright (c) 2026 Yiwei Ho).
import { Popover as PopoverPrimitive } from "@base-ui/react/popover";
import type * as React from "react";
import { cn } from "@/lib/utils";

export const Popover = PopoverPrimitive.Root;
export const PopoverTrigger = PopoverPrimitive.Trigger;

export function PopoverContent({
  className,
  side,
  align = "center",
  sideOffset = 6,
  ...props
}: React.ComponentProps<typeof PopoverPrimitive.Popup> &
  Pick<
    React.ComponentProps<typeof PopoverPrimitive.Positioner>,
    "side" | "sideOffset" | "align"
  >) {
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Positioner
        side={side}
        align={align}
        sideOffset={sideOffset}
        collisionPadding={8}
        className="isolate z-50"
      >
        <PopoverPrimitive.Popup
          className={cn(
            "w-72 origin-(--transform-origin) rounded-[8px] border border-border bg-popover p-3 text-foreground shadow-floating outline-hidden",
            "transition-[transform,scale,opacity] data-ending-style:scale-95 data-ending-style:opacity-0 data-starting-style:scale-95 data-starting-style:opacity-0",
            className,
          )}
          {...props}
        />
      </PopoverPrimitive.Positioner>
    </PopoverPrimitive.Portal>
  );
}
