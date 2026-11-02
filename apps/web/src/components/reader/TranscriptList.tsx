import { Captions } from "lucide-react";
import { EmptyState } from "@/components/ui/states";
import type { Transcript, VideoTime } from "@/lib/types";
import { formatTime } from "@/lib/video";

export function TranscriptList({
  parts,
  loading,
  onTime,
  canPlay,
}: {
  parts: (Transcript & { video: string })[];
  loading: boolean;
  onTime: (target: VideoTime) => void;
  canPlay: (video: string) => boolean;
}) {
  if (!parts.length)
    return (
      <EmptyState
        icon={Captions}
        title={loading ? "讀取逐字稿…" : "這頁沒有逐字稿"}
        description={
          loading ? undefined : "錄影還沒轉成文字，或老師沒有在這頁停留。"
        }
        className="py-12"
      />
    );
  return (
    <ol data-select-source="transcript" className="flex flex-col">
      {parts.map((part) => (
        <li
          key={`${part.video}-${part.start}`}
          className="group flex gap-3 border-b border-hairline py-2.5 last:border-0"
        >
          <button
            type="button"
            disabled={!canPlay(part.video)}
            onClick={() => onTime({ video: part.video, time: part.start })}
            className="nums h-6 shrink-0 rounded-[5px] px-1.5 font-mono text-[11.5px] text-brand outline-none hover:bg-brand-soft focus-visible:ring-2 focus-visible:ring-ring/30 disabled:text-muted-foreground"
            title="從這裡播放"
          >
            {formatTime(part.start)}
          </button>
          <p className="min-w-0 text-[13.5px] leading-relaxed">{part.text}</p>
        </li>
      ))}
    </ol>
  );
}
