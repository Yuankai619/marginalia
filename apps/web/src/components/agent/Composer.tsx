// Adapted from open-slide's agent/composer.tsx (MIT, Copyright (c) 2026 Yiwei Ho).
import { ArrowUp, Square, X } from "lucide-react";
import { type ReactNode, type RefObject, useLayoutEffect } from "react";
import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/ui/segmented";
import { type ChatMode, MODES } from "./use-chat";

function useAutoGrow(
  ref: RefObject<HTMLTextAreaElement | null>,
  value: string,
  max: number,
) {
  // biome-ignore lint/correctness/useExhaustiveDependencies: re-measure whenever the text changes
  useLayoutEffect(() => {
    const node = ref.current;
    if (!node) return;
    node.style.height = "0px";
    node.style.height = `${Math.min(max, Math.max(44, node.scrollHeight))}px`;
  }, [ref, value, max]);
}

export function Composer({
  value,
  onChange,
  onSend,
  onStop,
  running,
  disabled,
  placeholder,
  chips,
  mode,
  onMode,
  textareaRef,
}: {
  value: string;
  onChange: (next: string) => void;
  onSend: () => void;
  onStop: () => void;
  running: boolean;
  disabled?: boolean;
  placeholder: string;
  chips?: ReactNode;
  mode: ChatMode;
  onMode: (mode: ChatMode) => void;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
}) {
  const canSend = !running && !disabled && value.trim().length > 0;
  useAutoGrow(textareaRef, value, 180);
  return (
    <div className="relative z-10 shrink-0 bg-sidebar px-3 pt-1 pb-3">
      <span
        aria-hidden
        className="pointer-events-none absolute inset-x-0 bottom-full h-5 bg-gradient-to-t from-sidebar to-transparent"
      />
      {chips && (
        <div className="mb-1.5 flex min-w-0 flex-wrap gap-1">{chips}</div>
      )}
      <div className="flex flex-col rounded-[10px] border border-border bg-background shadow-edge transition-colors focus-within:border-foreground/35 focus-within:ring-2 focus-within:ring-ring/25">
        <textarea
          ref={textareaRef}
          value={value}
          rows={1}
          aria-label="輸入問題"
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.nativeEvent.isComposing || event.keyCode === 229) return;
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              if (canSend) onSend();
            }
          }}
          placeholder={placeholder}
          className="w-full resize-none bg-transparent px-3 pt-2.5 text-[13.5px] leading-[1.6] outline-none placeholder:text-muted-foreground/70 disabled:opacity-60"
        />
        <div className="flex items-center justify-between gap-2 px-2 pb-2">
          <Segmented
            title="對話模式"
            options={(Object.keys(MODES) as ChatMode[]).map((id) => ({
              id,
              label: MODES[id].label,
              hint: MODES[id].hint,
            }))}
            value={mode}
            onChange={onMode}
            disabled={running}
          />
          {running ? (
            <Button
              size="icon-sm"
              variant="outline"
              aria-label="停止"
              title="停止回覆"
              onClick={onStop}
            >
              <Square className="size-3 fill-current" />
            </Button>
          ) : (
            <Button
              size="icon-sm"
              aria-label="送出"
              title="送出（Enter）"
              disabled={!canSend}
              onClick={onSend}
            >
              <ArrowUp />
            </Button>
          )}
        </div>
      </div>
      <p className="mt-1.5 px-1 text-[11px] text-muted-foreground/80">
        Enter 送出，Shift＋Enter 換行
      </p>
    </div>
  );
}

export function ContextChip({
  children,
  title,
  onRemove,
}: {
  children: ReactNode;
  title?: string;
  onRemove?: () => void;
}) {
  return (
    <span
      title={title}
      className="inline-flex h-6 max-w-full min-w-0 items-center gap-1 rounded-[5px] border border-hairline bg-muted/60 pr-1 pl-1.5 text-[11.5px] text-muted-foreground"
    >
      <span className="min-w-0 truncate">{children}</span>
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          aria-label="移除"
          className="grid size-4 shrink-0 place-items-center rounded-[3px] hover:bg-foreground/10 hover:text-foreground"
        >
          <X className="size-3" />
        </button>
      )}
    </span>
  );
}
