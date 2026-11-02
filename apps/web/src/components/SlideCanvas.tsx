import { useState } from "react";
import type { Region, Slide } from "../lib/types";

export function SlideCanvas({
  slide,
  onRegion,
  selectable,
}: {
  slide: Slide;
  onRegion: (region: Region) => void;
  selectable: boolean;
}) {
  const [origin, setOrigin] = useState<{ x: number; y: number } | null>(null);
  const [region, setRegion] = useState<Region | null>(null);
  const [failed, setFailed] = useState(false);
  const point = (event: React.PointerEvent) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    return {
      x: Math.min(1, Math.max(0, (event.clientX - bounds.left) / bounds.width)),
      y: Math.min(1, Math.max(0, (event.clientY - bounds.top) / bounds.height)),
    };
  };
  const rectangle = (next: { x: number; y: number }): Region | null =>
    origin && {
      x: Math.min(origin.x, next.x),
      y: Math.min(origin.y, next.y),
      w: Math.abs(next.x - origin.x),
      h: Math.abs(next.y - origin.y),
    };
  if (!slide.image || failed)
    return <div className="slide-missing">此頁投影片圖片尚未產生</div>;
  return (
    <div
      className="slide-canvas"
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
        }
        setOrigin(null);
      }}
      onPointerCancel={() => {
        setOrigin(null);
        setRegion(null);
      }}
    >
      <img
        src={slide.image}
        alt={slide.title}
        draggable={false}
        onError={() => setFailed(true)}
      />
      {region && (
        <i
          className="selection"
          style={{
            left: `${region.x * 100}%`,
            top: `${region.y * 100}%`,
            width: `${region.w * 100}%`,
            height: `${region.h * 100}%`,
          }}
        />
      )}
    </div>
  );
}
