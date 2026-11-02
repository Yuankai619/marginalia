// Adapted from open-slide's agent/history-view.tsx (MIT, Copyright (c) 2026 Yiwei Ho).
import { Check, MessageSquare } from "lucide-react";
import type { ChatSummary } from "@/lib/types";
import { cn } from "@/lib/utils";
import { type ChatMode, MODES } from "./use-chat";

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 365 * 24 * 3600],
  ["month", 30 * 24 * 3600],
  ["week", 7 * 24 * 3600],
  ["day", 24 * 3600],
  ["hour", 3600],
  ["minute", 60],
];

export function relativeTime(iso: string, now = Date.now()) {
  const seconds = (Date.parse(iso) - now) / 1000;
  if (!Number.isFinite(seconds)) return "";
  const format = new Intl.RelativeTimeFormat("zh-TW", {
    numeric: "auto",
    style: "short",
  });
  for (const [unit, size] of UNITS)
    if (Math.abs(seconds) >= size)
      return format.format(Math.round(seconds / size), unit);
  return "剛剛";
}

export function HistoryView({
  sessions,
  activeId,
  onSelect,
}: {
  sessions: ChatSummary[];
  activeId: string | null;
  onSelect: (id: string) => void;
}) {
  if (!sessions.length)
    return (
      <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-2 px-6 text-center">
        <MessageSquare
          className="size-5 text-muted-foreground/60"
          strokeWidth={1.5}
          aria-hidden
        />
        <p className="text-[13px] font-medium">還沒有對話紀錄</p>
        <p className="text-[12px] leading-relaxed text-muted-foreground">
          和助教的對話會存在這門課裡，之後可以回來接著問。
        </p>
      </div>
    );
  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
      <p className="px-2 pt-1 pb-1.5 text-[12px] font-medium text-muted-foreground">
        這門課的對話
      </p>
      <ul className="flex flex-col gap-px">
        {sessions.map((session) => {
          const active = session.id === activeId;
          return (
            <li key={session.id}>
              <button
                type="button"
                onClick={() => onSelect(session.id)}
                aria-current={active ? "true" : undefined}
                className={cn(
                  "flex w-full flex-col gap-0.5 rounded-[6px] px-2.5 py-2 text-left outline-none transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring/30",
                  active && "bg-muted",
                )}
              >
                <span className="flex min-w-0 items-center gap-1.5 text-[13px] font-medium">
                  <span className="min-w-0 truncate">
                    {session.title || "未命名的對話"}
                  </span>
                  {active && (
                    <Check
                      className="size-3 shrink-0 text-muted-foreground"
                      aria-hidden
                    />
                  )}
                </span>
                <span className="flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
                  <span>
                    {MODES[session.mode as ChatMode]?.label ?? "問答"}
                  </span>
                  {session.updatedAt && (
                    <>
                      <span aria-hidden>·</span>
                      <span className="nums">
                        {relativeTime(session.updatedAt)}
                      </span>
                    </>
                  )}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
