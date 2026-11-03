import { ImageOff } from "lucide-react";
import { type ReactNode, useLayoutEffect, useRef, useState } from "react";
import type { Region, Slide } from "@/lib/types";
import { clamp, cn } from "@/lib/utils";

const fraction = (value: number) => clamp(value, 0, 1);
const BELOW_MIN = 180; // spare height worth filling with `below` instead of leaving it blank
const GAP = 16;

/**
 * The current slide, scaled to fit the space it is given. Drag on it to ask the assistant about a region.
 * A wide slide in a tall column leaves height over; when there is enough, the slide moves to the top and `below`
 * fills the rest instead of blank space.
 */
export function SlideStage({
  slide,
  aspect,
  selectable,
  onRegion,
  below,
}: {
  slide: Slide;
  aspect: number;
  selectable: boolean;
  onRegion: (region: Region) => void;
  below?: ReactNode;
}) {
  const frame = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState<{
    width: number;
    height: number;
    spare: number;
  } | null>(null);
  const [origin, setOrigin] = useState<{ x: number; y: number } | null>(null);
  const [region, setRegion] = useState<Region | null>(null);
  const [failed, setFailed] = useState(false);

  useLayoutEffect(() => {
    const node = frame.current;
    if (!node) return;
    const measure = () => {
      const { width, height } = node.getBoundingClientRect();
      if (!width || !height) return;
      const fitted = Math.min(width, height * aspect);
      const slideHeight = Math.floor(fitted / aspect);
      setSize({
        width: Math.floor(fitted),
        height: slideHeight,
        spare: Math.floor(height - slideHeight - GAP),
      });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [aspect]);
  const showBelow = !!below && !!size && size.spare >= BELOW_MIN;

  const point = (event: React.PointerEvent) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    return {
      x: fraction((event.clientX - bounds.left) / bounds.width),
      y: fraction((event.clientY - bounds.top) / bounds.height),
    };
  };
  const rectangle = (next: { x: number; y: number }): Region | null =>
    origin && {
      x: Math.min(origin.x, next.x),
      y: Math.min(origin.y, next.y),
      w: Math.abs(next.x - origin.x),
      h: Math.abs(next.y - origin.y),
    };

  return (
    <div
      ref={frame}
      className={cn(
        "flex min-h-0 min-w-0 flex-1 flex-col items-center",
        showBelow ? "justify-start" : "justify-center",
      )}
    >
      {size && (
        <div
          style={{ width: size.width, height: size.height }}
          className={cn(
            "relative overflow-hidden rounded-[4px] bg-card shadow-floating select-none",
            selectable && "cursor-crosshair touch-none",
          )}
          onPointerDown={(event) => {
            if (!selectable || event.button !== 0) return;
            event.currentTarget.setPointerCapture(event.pointerId);
            setOrigin(point(event));
            setRegion(null);
          }}
          onPointerMove={(event) => {
            if (origin) setRegion(rectangle(point(event)));
          }}
          onPointerUp={(event) => {
            const next = rectangle(point(event));
            if (next && next.w > 0.01 && next.h > 0.01) {
              setRegion(next);
              onRegion(next);
            } else setRegion(null);
            setOrigin(null);
          }}
          onPointerCancel={() => {
            setOrigin(null);
            setRegion(null);
          }}
        >
          {slide.image && !failed ? (
            <img
              src={slide.image}
              alt={`第 ${slide.index} 頁：${slide.title}`}
              draggable={false}
              onError={() => setFailed(true)}
              className="size-full object-contain"
            />
          ) : (
            <div className="grid size-full place-items-center bg-muted text-center text-[13px] text-muted-foreground">
              <span className="flex flex-col items-center gap-2">
                <ImageOff className="size-5" strokeWidth={1.5} aria-hidden />
                這一頁的投影片圖片還沒轉出來
              </span>
            </div>
          )}
          {region && (
            <i
              aria-hidden
              className="pointer-events-none absolute rounded-[2px] border-2 border-brand bg-brand/15"
              style={{
                left: `${region.x * 100}%`,
                top: `${region.y * 100}%`,
                width: `${region.w * 100}%`,
                height: `${region.h * 100}%`,
              }}
            />
          )}
        </div>
      )}
      {showBelow && size && (
        <div
          style={{ width: size.width, height: size.spare, marginTop: GAP }}
          className="flex min-h-0 flex-col"
        >
          {below}
        </div>
      )}
    </div>
  );
}
