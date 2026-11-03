// Adapted from open-slide's agent/transcript.tsx (MIT, Copyright (c) 2026 Yiwei Ho).
import { Check, ChevronRight, CircleAlert, Copy } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Markdown, type NoteSource } from "@/components/Markdown";
import type { VideoTime } from "@/lib/types";
import { cn } from "@/lib/utils";
import type { AgentItem } from "./use-chat";

type ToolItem = Extract<AgentItem, { kind: "tool" }>;
type Block =
  | { key: string; item: AgentItem }
  | { key: string; tools: ToolItem[] };

function toBlocks(items: AgentItem[]): Block[] {
  const blocks: Block[] = [];
  for (const item of items) {
    const last = blocks.at(-1);
    if (item.kind === "tool" && last && "tools" in last) last.tools.push(item);
    else if (item.kind === "tool") blocks.push({ key: item.id, tools: [item] });
    else blocks.push({ key: item.id, item });
  }
  return blocks;
}

// One reply spans every assistant text between a user message and the turn's result; copy takes them all.
function replyTexts(items: AgentItem[]) {
  const replies = new Map<string, string>();
  let parts: { id: string; text: string }[] = [];
  const flush = () => {
    const last = parts.at(-1);
    const text = parts
      .map((part) => part.text.trim())
      .filter(Boolean)
      .join("\n\n");
    if (last && text) replies.set(last.id, text);
    parts = [];
  };
  for (const item of items) {
    if (item.kind === "assistant" && !item.streaming)
      parts.push({ id: item.id, text: item.text });
    else if (item.kind === "user" || item.kind === "result") flush();
  }
  flush();
  return replies;
}

function Working({ label = "思考中" }: { label?: string }) {
  return (
    <p className="text-[12px]">
      <span className="agent-shimmer">{label}…</span>
    </p>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(timer);
  }, [copied]);
  return (
    <button
      type="button"
      aria-label={copied ? "已複製" : "複製回覆"}
      title={copied ? "已複製" : "複製回覆"}
      onClick={() =>
        navigator.clipboard?.writeText(text).then(
          () => setCopied(true),
          () => undefined,
        )
      }
      className="grid size-6 place-items-center rounded-[5px] text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/30 [&_svg]:size-3"
    >
      {copied ? <Check /> : <Copy />}
    </button>
  );
}

function ToolRow({ tool }: { tool: ToolItem }) {
  return (
    <div className="flex min-w-0 items-center gap-2 text-[12px] leading-5 text-muted-foreground">
      <span
        aria-hidden
        className={cn(
          "size-1 shrink-0 rounded-full",
          tool.running
            ? "animate-pulse bg-foreground/70"
            : "bg-muted-foreground/40",
        )}
      />
      <span className={cn("shrink-0", tool.running && "agent-shimmer")}>
        {tool.title}
      </span>
      {tool.detail && (
        <span
          className="min-w-0 truncate text-muted-foreground/75"
          title={tool.detail}
        >
          {tool.detail}
        </span>
      )}
    </div>
  );
}

function ToolGroup({ tools }: { tools: ToolItem[] }) {
  const [open, setOpen] = useState(false);
  if (tools.length === 1) return <ToolRow tool={tools[0]} />;
  const live = [...tools].reverse().find((tool) => tool.running);
  return (
    <div>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1 rounded-[4px] text-[12px] leading-5 text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/30"
      >
        <ChevronRight
          aria-hidden
          className={cn("size-3 transition-transform", open && "rotate-90")}
        />
        查閱了 {tools.length} 份課程資料
      </button>
      {(open || live) && (
        <div className="mt-0.5 ml-1.5 flex flex-col border-l border-hairline pl-3">
          {open
            ? tools.map((tool) => <ToolRow key={tool.id} tool={tool} />)
            : live && <ToolRow tool={live} />}
        </div>
      )}
    </div>
  );
}

export function Transcript({
  items,
  running,
  source,
  onTime,
  canPlay,
}: {
  items: AgentItem[];
  running: boolean;
  source: NoteSource;
  onTime: (target: VideoTime) => void;
  canPlay: (video: string) => boolean;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const last = items.at(-1);
  const lastLength = last?.kind === "assistant" ? last.text.length : 0;
  const replies = replyTexts(items);

  // Follow the stream while the reader is parked at the bottom; stop once they scroll up.
  // biome-ignore lint/correctness/useExhaustiveDependencies: re-run as the transcript grows or streams
  useLayoutEffect(() => {
    const node = scroller.current;
    if (node && stick.current) node.scrollTop = node.scrollHeight;
  }, [items.length, lastLength, running]);

  return (
    <div
      ref={scroller}
      onScroll={(event) => {
        const node = event.currentTarget;
        stick.current =
          node.scrollHeight - node.scrollTop - node.clientHeight < 48;
      }}
      className="min-h-0 flex-1 overflow-y-auto px-4 py-4"
      aria-live="polite"
    >
      <ol className="flex flex-col gap-3.5">
        {toBlocks(items).map((block) => (
          <li key={block.key}>
            {"tools" in block ? (
              <ToolGroup tools={block.tools} />
            ) : block.item.kind === "user" ? (
              <div className="flex flex-col items-end gap-1">
                {block.item.context && (
                  <span className="max-w-[88%] truncate text-[11px] text-muted-foreground">
                    {block.item.context}
                  </span>
                )}
                <div className="max-w-[88%] rounded-[10px] rounded-br-[3px] bg-muted px-3 py-2 text-[13px] leading-relaxed whitespace-pre-wrap">
                  {block.item.text}
                </div>
              </div>
            ) : block.item.kind === "assistant" ? (
              <div className="group/message">
                <Markdown
                  markdown={block.item.text}
                  variant="chat"
                  source={source}
                  onTime={onTime}
                  canPlay={canPlay}
                />
                {replies.get(block.item.id) && (
                  <div className="-mb-2 -ml-1.5 flex opacity-0 transition-opacity focus-within:opacity-100 group-hover/message:opacity-100">
                    <CopyButton text={replies.get(block.item.id) ?? ""} />
                  </div>
                )}
              </div>
            ) : block.item.kind === "error" ? (
              <div className="rounded-[8px] border border-destructive/30 bg-destructive/5 px-3 py-2">
                <p className="flex items-center gap-1.5 text-[12px] font-medium text-destructive">
                  <CircleAlert className="size-3.5" aria-hidden />
                  助教沒有完成回覆
                </p>
                <p className="mt-1 text-[12.5px] leading-relaxed text-foreground/85">
                  {block.item.text}
                </p>
              </div>
            ) : block.item.kind === "result" ? (
              <p className="nums text-[11.5px] text-muted-foreground/75">
                {block.item.aborted ? "已停止" : "完成"} · {block.item.seconds}{" "}
                秒
              </p>
            ) : null}
          </li>
        ))}
        {running && !(last?.kind === "assistant" && last.streaming) && (
          <li>
            <Working label={last?.kind === "tool" ? "查資料中" : "思考中"} />
          </li>
        )}
      </ol>
    </div>
  );
}
