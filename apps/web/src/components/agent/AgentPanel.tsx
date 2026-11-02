// Layout and interaction adapted from open-slide's agent/agent-panel.tsx (MIT, Copyright (c) 2026 Yiwei Ho).
import {
  ChevronLeft,
  ClipboardCheck,
  GraduationCap,
  History,
  MessageCircleQuestion,
  Plus,
  X,
} from "lucide-react";
import { type ReactNode, useRef, useState } from "react";
import { toast } from "sonner";
import type { NoteSource } from "@/components/Markdown";
import { Button } from "@/components/ui/button";
import { LoadingState } from "@/components/ui/states";
import { Hint } from "@/components/ui/tooltip";
import type { DataAdapter } from "@/lib/adapter";
import type { ChatContext, VideoTime } from "@/lib/types";
import { errorMessage } from "@/lib/utils";
import { Composer, ContextChip } from "./Composer";
import { ConnectView } from "./ConnectView";
import { HistoryView } from "./HistoryView";
import { ModelMenu } from "./ModelMenu";
import { Transcript } from "./Transcript";
import { type ChatMode, MODES, useChat } from "./use-chat";

const QUICK: {
  mode: ChatMode;
  icon: ReactNode;
  label: string;
  hint: string;
  prompt: string;
}[] = [
  {
    mode: "qa",
    icon: <MessageCircleQuestion />,
    label: "這頁在講什麼？",
    hint: "用白話把這頁的重點講一遍",
    prompt: "用白話幫我整理這一頁在講什麼，重點是哪幾個？",
  },
  {
    mode: "interview",
    icon: <GraduationCap />,
    label: "用口試考我這頁",
    hint: "一次問一題，答完會給回饋",
    prompt: "用這一頁的內容考我，一次問一題。",
  },
  {
    mode: "review",
    icon: <ClipboardCheck />,
    label: "檢查這頁筆記",
    hint: "找出錯誤、缺漏和看不懂的地方",
    prompt: "幫我檢查這一頁的筆記：有沒有錯、漏了什麼、哪裡寫得不好懂？",
  },
];

export function AgentPanel({
  data,
  courseId,
  source,
  slideLabel,
  context,
  onClearSelection,
  onClearRegion,
  onClose,
  onTime,
  canPlay,
}: {
  data: DataAdapter;
  courseId: string;
  source: NoteSource;
  slideLabel: string;
  context: ChatContext;
  onClearSelection: () => void;
  onClearRegion: () => void;
  onClose: () => void;
  onTime: (target: VideoTime) => void;
  canPlay: (video: string) => boolean;
}) {
  const chat = useChat(data, courseId);
  const [draft, setDraft] = useState("");
  const [view, setView] = useState<"chat" | "history" | "connect">("chat");
  const textarea = useRef<HTMLTextAreaElement>(null);
  const loading = chat.accounts === null;
  const connected = !!chat.account;
  const showConnect = !loading && (!connected || view === "connect");

  const contextLabel = [
    slideLabel,
    context.selection &&
      `選取的${context.selection.source === "note" ? "筆記" : "逐字稿"}`,
    context.region && "投影片框選範圍",
  ]
    .filter(Boolean)
    .join("・");

  const send = (text: string, mode?: ChatMode) => {
    if (!text.trim() || chat.running) return;
    setDraft("");
    onClearSelection();
    onClearRegion();
    // The request carries the context as it was when sent; clearing the chips right away is safe.
    void chat.send(text, context, contextLabel, mode);
  };

  const chips = (
    <>
      <ContextChip title="助教會以這一頁的投影片、筆記和老師的講解為主回答">
        {slideLabel}
      </ContextChip>
      {context.selection && (
        <ContextChip title={context.selection.text} onRemove={onClearSelection}>
          {context.selection.source === "note" ? "筆記" : "逐字稿"}：「
          {context.selection.text}」
        </ContextChip>
      )}
      {context.region && (
        <ContextChip onRemove={onClearRegion}>投影片框選範圍</ContextChip>
      )}
    </>
  );

  return (
    <div
      data-agent-provider={chat.account?.provider}
      className="relative flex h-full min-h-0 flex-col bg-sidebar"
    >
      {chat.running && <span aria-hidden className="agent-progress z-20" />}
      <header className="relative z-10 flex h-11 shrink-0 items-center justify-between gap-1 border-b border-hairline px-2">
        <div className="flex min-w-0 items-center gap-0.5">
          {showConnect && connected ? (
            <Button size="xs" variant="ghost" onClick={() => setView("chat")}>
              <ChevronLeft /> 回到對話
            </Button>
          ) : view === "history" ? (
            <Button size="xs" variant="ghost" onClick={() => setView("chat")}>
              <ChevronLeft /> 對話紀錄
            </Button>
          ) : connected ? (
            <ModelMenu
              accounts={chat.accounts ?? []}
              account={chat.account}
              model={chat.model}
              effort={chat.effort}
              onChoose={chat.choose}
              onManage={() => setView("connect")}
              disabled={chat.running}
            />
          ) : (
            <span className="px-2 text-[13px] font-medium">AI 助教</span>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          {connected && !showConnect && (
            <>
              <Hint label="對話紀錄">
                <Button
                  size="icon-sm"
                  variant="ghost"
                  aria-label="對話紀錄"
                  aria-pressed={view === "history"}
                  onClick={() =>
                    setView(view === "history" ? "chat" : "history")
                  }
                >
                  <History />
                </Button>
              </Hint>
              <Hint label="新對話">
                <Button
                  size="icon-sm"
                  variant="ghost"
                  aria-label="新對話"
                  disabled={chat.running}
                  onClick={() => {
                    chat.newChat();
                    setView("chat");
                    setDraft("");
                    queueMicrotask(() => textarea.current?.focus());
                  }}
                >
                  <Plus />
                </Button>
              </Hint>
            </>
          )}
          <Hint label="收起助教">
            <Button
              size="icon-sm"
              variant="ghost"
              aria-label="收起助教"
              onClick={onClose}
            >
              <X />
            </Button>
          </Hint>
        </div>
      </header>

      {loading ? (
        <LoadingState label="檢查 AI 帳號" />
      ) : showConnect ? (
        <div className="min-h-0 flex-1 overflow-y-auto">
          <ConnectView
            accounts={chat.accounts ?? []}
            error={chat.accountError}
            onRefresh={chat.loadAccounts}
          />
        </div>
      ) : view === "history" ? (
        <HistoryView
          sessions={chat.sessions}
          activeId={chat.chatId}
          onSelect={async (id) => {
            try {
              await chat.openChat(id);
              setView("chat");
            } catch (error) {
              toast.error("無法開啟對話", { description: errorMessage(error) });
            }
          }}
        />
      ) : (
        <>
          {chat.items.length ? (
            <Transcript
              items={chat.items}
              running={chat.running}
              source={source}
              onTime={onTime}
              canPlay={canPlay}
            />
          ) : (
            <div className="flex min-h-0 flex-1 flex-col justify-end overflow-y-auto px-4 py-5">
              <h2 className="text-[15px] font-semibold">有什麼想問的？</h2>
              <p className="mt-1 text-[12.5px] leading-relaxed text-muted-foreground">
                助教讀得到整門課的投影片、筆記和老師的講解。在投影片上拖曳框選，或選取筆記、逐字稿裡的文字，就能針對那一塊發問。
              </p>
              <div className="mt-4 flex flex-col gap-1.5">
                {QUICK.map((item) => (
                  <button
                    key={item.mode}
                    type="button"
                    onClick={() => send(item.prompt, item.mode)}
                    className="flex items-start gap-2.5 rounded-[8px] border border-border bg-card px-3 py-2.5 text-left outline-none transition-colors hover:border-foreground/25 hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring/30"
                  >
                    <span className="mt-0.5 grid size-5 shrink-0 place-items-center text-muted-foreground [&_svg]:size-3.5">
                      {item.icon}
                    </span>
                    <span className="min-w-0">
                      <span className="block text-[13px] font-medium">
                        {item.label}
                      </span>
                      <span className="mt-0.5 block text-[11.5px] leading-snug text-muted-foreground">
                        {item.hint}
                      </span>
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}
          <Composer
            value={draft}
            onChange={setDraft}
            onSend={() => send(draft)}
            onStop={chat.stop}
            running={chat.running}
            placeholder={
              chat.mode === "interview"
                ? "回答助教的問題，或說「開始」…"
                : chat.mode === "review"
                  ? "想請助教特別看哪裡？"
                  : "問這一頁的任何問題…"
            }
            chips={chips}
            mode={chat.mode}
            onMode={(mode) => {
              if (chat.items.length && mode !== chat.mode)
                toast(`切換成「${MODES[mode].label}」，開始新的對話`);
              chat.setMode(mode);
            }}
            textareaRef={textarea}
          />
        </>
      )}
    </div>
  );
}
