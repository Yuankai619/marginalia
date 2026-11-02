// Adapted from open-slide's panel/resize-handle.tsx (MIT, Copyright (c) 2026 Yiwei Ho).
import { useEffect, useRef, useState } from "react";
import { clamp, cn } from "@/lib/utils";

/** A vertical splitter on one edge of a panel; dragging away from the panel makes it wider. */
export function ResizeHandle({
  width,
  min,
  max,
  defaultWidth,
  edge,
  label,
  onResize,
  className,
}: {
  width: number;
  min: number;
  max: number;
  defaultWidth: number;
  edge: "left" | "right";
  label: string;
  onResize: (width: number) => void;
  className?: string;
}) {
  const [resizing, setResizing] = useState(false);
  const drag = useRef<{ startX: number; startWidth: number } | null>(null);
  const direction = edge === "right" ? 1 : -1;

  useEffect(() => {
    if (!resizing) return;
    const previous = {
      cursor: document.body.style.cursor,
      userSelect: document.body.style.userSelect,
    };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    return () => {
      document.body.style.cursor = previous.cursor;
      document.body.style.userSelect = previous.userSelect;
    };
  }, [resizing]);

  return (
    // biome-ignore lint/a11y/useSemanticElements: focusable splitter, not a static <hr>
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuenow={Math.round(width)}
      aria-valuemin={min}
      aria-valuemax={max}
      tabIndex={0}
      onPointerDown={(event) => {
        event.preventDefault();
        event.currentTarget.setPointerCapture(event.pointerId);
        drag.current = { startX: event.clientX, startWidth: width };
        setResizing(true);
      }}
      onPointerMove={(event) => {
        if (!drag.current) return;
        onResize(
          clamp(
            drag.current.startWidth +
              (event.clientX - drag.current.startX) * direction,
            min,
            max,
          ),
        );
      }}
      onPointerUp={(event) => {
        if (event.currentTarget.hasPointerCapture(event.pointerId))
          event.currentTarget.releasePointerCapture(event.pointerId);
        drag.current = null;
        setResizing(false);
      }}
      onPointerCancel={() => {
        drag.current = null;
        setResizing(false);
      }}
      onKeyDown={(event) => {
        const step = (event.shiftKey ? 48 : 12) * direction;
        let next: number | null = null;
        if (event.key === "ArrowLeft") next = width - step;
        else if (event.key === "ArrowRight") next = width + step;
        else if (event.key === "Home") next = defaultWidth;
        if (next === null) return;
        event.preventDefault();
        event.stopPropagation();
        onResize(clamp(next, min, max));
      }}
      onDoubleClick={() => onResize(defaultWidth)}
      title="拖曳調整寬度，連按兩下還原"
      className={cn(
        "group/resize relative z-20 w-0 shrink-0 cursor-col-resize touch-none outline-none",
        "before:absolute before:inset-y-0 before:-left-1 before:w-2 before:content-['']",
        className,
      )}
    >
      <span
        aria-hidden
        className={cn(
          "pointer-events-none absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-hairline transition-[background-color,width] duration-150",
          "group-hover/resize:w-0.5 group-hover/resize:bg-brand group-focus-visible/resize:w-0.5 group-focus-visible/resize:bg-brand",
          resizing && "w-0.5 bg-brand",
        )}
      />
    </div>
  );
}
