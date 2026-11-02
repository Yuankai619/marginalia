import { Film, Minimize2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import type { Transcript, VideoTime } from "@/lib/types";
import { cn } from "@/lib/utils";
import { formatTime } from "@/lib/video";

/** Floating lecture player. Reports where it is so the editor can insert the current time. */
export function VideoPlayer({
  target,
  src,
  title,
  onClose,
  onProgress,
  captions,
}: {
  captions: Transcript[];
  target: VideoTime;
  src: string;
  title: string;
  onClose: () => void;
  /** Only while someone may insert the current time; the reader re-renders on every report. */
  onProgress?: (at: VideoTime | null) => void;
}) {
  const video = useRef<HTMLVideoElement>(null);
  const [track, setTrack] = useState("");
  const [small, setSmall] = useState(false);
  const [now, setNow] = useState(target.time);
  const reported = useRef(-1);
  useEffect(() => {
    const stamp = (seconds: number) =>
      new Date(seconds * 1000).toISOString().slice(11, 23);
    const text = `WEBVTT\n\n${captions
      .map(
        (part) =>
          `${stamp(part.start)} --> ${stamp(part.end)}\n${part.text.replace(/-->/g, "→")}\n`,
      )
      .join("\n")}`;
    const url = URL.createObjectURL(new Blob([text], { type: "text/vtt" }));
    setTrack(url);
    return () => URL.revokeObjectURL(url);
  }, [captions]);
  const seek = () => {
    const element = video.current;
    if (!element?.readyState) return;
    element.currentTime = target.time;
    void element.play().catch(() => toast("按播放鍵開始播放"));
  };
  useEffect(seek, [target]);
  useEffect(() => () => onProgress?.(null), [onProgress]);
  return (
    <aside
      aria-label="上課錄影"
      className={cn(
        "rise-in fixed right-4 bottom-4 z-40 overflow-hidden rounded-[10px] border border-border bg-card shadow-overlay",
        small ? "w-[260px]" : "w-[min(440px,calc(100vw-2rem))]",
      )}
    >
      <header className="flex h-9 items-center gap-2 border-b border-hairline px-2.5">
        <Film className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
        <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium">
          {title}
        </span>
        <span className="nums text-[12px] text-muted-foreground">
          {formatTime(now)}
        </span>
        <Button
          variant="ghost"
          size="icon-xs"
          onClick={() => setSmall(!small)}
          aria-label={small ? "放大播放器" : "縮小播放器"}
        >
          <Minimize2 />
        </Button>
        <Button
          variant="ghost"
          size="icon-xs"
          onClick={onClose}
          aria-label="關閉播放器"
        >
          <X />
        </Button>
      </header>
      {/* biome-ignore lint/a11y/useMediaCaption: captions come from the transcript track below */}
      <video
        ref={video}
        src={src}
        controls
        playsInline
        preload="metadata"
        onLoadedMetadata={seek}
        onTimeUpdate={(event) => {
          // timeupdate fires ~4×/s; the reader only needs whole seconds (timestamps are whole seconds).
          const time = Math.floor(event.currentTarget.currentTime);
          if (time === reported.current) return;
          reported.current = time;
          setNow(time);
          onProgress?.({ video: target.video, time });
        }}
        onError={() =>
          toast.error("錄影無法播放", {
            description: "請確認檔案存在、瀏覽器支援這個格式。",
          })
        }
        className="block aspect-video w-full bg-black"
      >
        {track && (
          <track
            kind="captions"
            src={track}
            srcLang="zh-TW"
            label="本頁逐字稿"
          />
        )}
      </video>
    </aside>
  );
}
