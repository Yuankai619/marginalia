import { X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import type { Transcript, VideoTime } from "../lib/types";
import { formatTime as time } from "../lib/video";

export function VideoPlayer({
  target,
  src,
  onClose,
  captions,
}: {
  captions: Transcript[];
  target: VideoTime;
  src: string;
  onClose: () => void;
}) {
  const video = useRef<HTMLVideoElement>(null);
  const [track, setTrack] = useState("");
  useEffect(() => {
    const stamp = (seconds: number) =>
      new Date(seconds * 1000).toISOString().slice(11, 23);
    const text =
      "WEBVTT\n\n" +
      captions
        .map(
          (part) =>
            `${stamp(part.start)} --> ${stamp(part.end)}\n${part.text.replace(/-->/g, "→")}\n`,
        )
        .join("\n");
    const url = URL.createObjectURL(new Blob([text], { type: "text/vtt" }));
    setTrack(url);
    return () => URL.revokeObjectURL(url);
  }, [captions]);
  const seek = () => {
    const element = video.current;
    if (!element?.readyState) return;
    element.currentTime = target.time;
    void element.play().catch(() => {
      toast("請按播放鍵開始播放影片");
    });
  };
  useEffect(seek, [target]);
  return (
    <aside className="player">
      <button className="icon-button" onClick={onClose} aria-label="關閉播放器">
        <X />
      </button>
      <p>
        {target.video} · {time(target.time)}
      </p>
      <video
        ref={video}
        src={src}
        controls
        playsInline
        preload="metadata"
        onLoadedMetadata={seek}
        onError={() => toast.error("影片無法播放，請確認檔案與瀏覽器格式支援")}
      >
        <track kind="captions" src={track} srcLang="zh-TW" label="本頁逐字稿" />
      </video>
    </aside>
  );
}
