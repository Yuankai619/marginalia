import { Dialog as DialogPrimitive } from "@base-ui/react/dialog";
import { X } from "lucide-react";
import type * as React from "react";

/** Full-screen viewer for note figures and diagrams. */
export function Lightbox({
  open,
  onOpenChange,
  label,
  caption,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  label: string;
  caption?: string;
  children: React.ReactNode;
}) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Backdrop className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm transition-opacity data-ending-style:opacity-0 data-starting-style:opacity-0" />
        <DialogPrimitive.Popup
          aria-label={label}
          className="fixed inset-3 z-50 flex flex-col overflow-hidden rounded-[10px] bg-card shadow-overlay outline-none transition-[opacity,scale] duration-200 data-ending-style:scale-[0.98] data-ending-style:opacity-0 data-starting-style:scale-[0.98] data-starting-style:opacity-0 sm:inset-8"
        >
          <header className="flex h-11 shrink-0 items-center justify-between gap-3 border-b border-hairline px-4">
            <DialogPrimitive.Title className="truncate text-[13px] font-medium">
              {caption || label}
            </DialogPrimitive.Title>
            <DialogPrimitive.Close
              aria-label="關閉"
              className="grid size-7 place-items-center rounded-[5px] text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <X className="size-4" />
            </DialogPrimitive.Close>
          </header>
          <div className="min-h-0 flex-1 overflow-auto p-4 sm:p-8">
            {children}
          </div>
        </DialogPrimitive.Popup>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
