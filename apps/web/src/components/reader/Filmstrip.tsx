import { useEffect, useRef } from "react";
import type { Slide } from "@/lib/types";
import { cn } from "@/lib/utils";

export function Filmstrip({
  slides,
  current,
  onSelect,
}: {
  slides: Slide[];
  current: number;
  onSelect: (index: number) => void;
}) {
  const list = useRef<HTMLOListElement>(null);
  useEffect(() => {
    list.current
      ?.querySelector<HTMLElement>(`[data-index="${current}"]`)
      ?.scrollIntoView({
        block: "nearest",
        inline: "nearest",
        behavior: "smooth",
      });
  }, [current]);
  return (
    <nav
      aria-label="投影片縮圖"
      className="shrink-0 border-t border-hairline bg-sidebar"
    >
      <ol
        ref={list}
        className="flex gap-2 overflow-x-auto px-3 py-2.5 [scrollbar-width:thin]"
      >
        {slides.map((slide) => {
          const active = slide.index === current;
          return (
            <li key={slide.index} data-index={slide.index} className="shrink-0">
              <button
                type="button"
                onClick={() => onSelect(slide.index)}
                aria-current={active ? "page" : undefined}
                aria-label={`第 ${slide.index} 頁：${slide.title}`}
                title={`${slide.index}. ${slide.title}`}
                className={cn(
                  "group block w-[104px] rounded-[6px] p-1 text-left outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring/40",
                  active ? "bg-brand-soft" : "hover:bg-muted",
                )}
              >
                <span
                  className={cn(
                    "relative block aspect-video overflow-hidden rounded-[3px] border bg-card",
                    active ? "border-brand" : "border-hairline",
                  )}
                >
                  {slide.thumb && (
                    <img
                      src={slide.thumb}
                      alt=""
                      loading="lazy"
                      className="size-full object-cover"
                    />
                  )}
                </span>
                <span className="mt-1 flex items-center gap-1 px-0.5 text-[11px] leading-4">
                  <span
                    className={cn(
                      "nums shrink-0",
                      active
                        ? "font-semibold text-brand"
                        : "text-muted-foreground",
                    )}
                  >
                    {slide.index}
                  </span>
                  <span className="min-w-0 truncate text-muted-foreground">
                    {slide.title}
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
