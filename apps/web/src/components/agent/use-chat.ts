import { useCallback, useEffect, useRef, useState } from "react";
import type { DataAdapter } from "@/lib/adapter";
import type { Account, ChatContext, ChatSummary } from "@/lib/types";
import { useStored } from "@/lib/use-stored";
import { errorMessage } from "@/lib/utils";

export type ChatMode = "qa" | "interview" | "review";
export const MODES: Record<ChatMode, { label: string; hint: string }> = {
  qa: {
    label: "問答",
    hint: "問這門課的任何問題，助教會引用投影片和老師的講解回答",
  },
  interview: {
    label: "口試練習",
    hint: "助教一次問一題，等你回答再追問、給回饋",
  },
  review: {
    label: "檢查筆記",
    hint: "請助教找出這頁筆記的錯誤、缺漏和看不懂的地方",
  },
};
export const EFFORTS: Record<string, string> = {
  low: "快速",
  medium: "標準",
  high: "深入",
  xhigh: "更深入",
  max: "最深入",
};

export type AgentItem =
  | { kind: "user"; id: string; text: string; context?: string }
  | { kind: "assistant"; id: string; text: string; streaming: boolean }
  | {
      kind: "tool";
      id: string;
      title: string;
      detail: string;
      running: boolean;
    }
  | { kind: "error"; id: string; text: string }
  | { kind: "result"; id: string; aborted: boolean; seconds: number };

export type Choice = { account: string; model: string; effort: string };

let counter = 0;
const nextId = () => `item-${++counter}`;

const TOOL_NAMES: Record<string, string> = {
  Read: "讀取",
  Grep: "搜尋",
  Glob: "尋找檔案",
};

/** Tool calls name files by basename; say what they are in course terms. */
function describeTool(title: string, detail: string) {
  const page = /^(\d{3})\.(md|json|webp)$/.exec(detail);
  const what = page
    ? `第 ${Number(page[1])} 頁${page[2] === "md" ? "筆記" : page[2] === "json" ? "檢查紀錄" : "投影片"}`
    : detail === "transcript.json"
      ? "逐字稿"
      : detail === "slides.json"
        ? "投影片文字"
        : detail;
  return { title: TOOL_NAMES[title] ?? title, detail: what };
}

const validChoice = (value: unknown) =>
  !!value &&
  typeof value === "object" &&
  typeof (value as Choice).account === "string";

/** Accounts, the chosen model, chat history and the streaming conversation for one course. */
export function useChat(data: DataAdapter, courseId: string) {
  const [accounts, setAccounts] = useState<Account[] | null>(null);
  const [accountError, setAccountError] = useState<string | null>(null);
  const [stored, setStored] = useStored<Choice | null>(
    "marginalia:agent",
    null,
    validChoice,
  );
  const [sessions, setSessions] = useState<ChatSummary[]>([]);
  const [chatId, setChatId] = useState<string | null>(null);
  const [mode, setMode] = useState<ChatMode>("qa");
  const [items, setItems] = useState<AgentItem[]>([]);
  const [running, setRunning] = useState(false);
  const controller = useRef<AbortController | null>(null);

  const loadAccounts = useCallback(async () => {
    setAccountError(null);
    try {
      setAccounts(await data.accounts());
    } catch (error) {
      setAccountError(errorMessage(error));
      setAccounts([]);
    }
  }, [data]);

  useEffect(() => {
    void loadAccounts();
    data.chats(courseId).then(setSessions, () => setSessions([]));
    return () => controller.current?.abort();
  }, [data, courseId, loadAccounts]);

  const ready = accounts?.filter((account) => account.loggedIn) ?? [];
  const account =
    ready.find((item) => item.id === stored?.account) ?? ready[0] ?? null;
  const model =
    account?.models.find(
      (item) => item.id === stored?.model && stored.account === account.id,
    ) ??
    account?.models.find((item) => item.id === "sonnet") ??
    account?.models[0] ??
    null;
  const effort =
    account &&
    stored?.account === account.id &&
    account.efforts.includes(stored.effort)
      ? stored.effort
      : account?.efforts.includes("medium")
        ? "medium"
        : (account?.efforts[0] ?? "");
  const choose = (next: Partial<Choice>) =>
    setStored({
      account: next.account ?? account?.id ?? "",
      model:
        next.model ??
        (next.account && next.account !== account?.id ? "" : (model?.id ?? "")),
      effort:
        next.effort ??
        (next.account && next.account !== account?.id ? "" : effort),
    });

  const newChat = () => {
    if (running) return;
    setChatId(null);
    setItems([]);
  };

  const openChat = async (id: string) => {
    if (running) return;
    const chat = await data.conversation(courseId, id);
    setChatId(chat.id);
    setMode((chat.mode as ChatMode) in MODES ? (chat.mode as ChatMode) : "qa");
    setItems(
      chat.messages.map((message) =>
        message.role === "user"
          ? { kind: "user", id: nextId(), text: message.content }
          : {
              kind: "assistant",
              id: nextId(),
              text: message.content,
              streaming: false,
            },
      ),
    );
  };

  const stop = () => controller.current?.abort();

  const send = async (
    text: string,
    context: ChatContext,
    contextLabel?: string,
    asMode?: ChatMode,
  ) => {
    const message = text.trim();
    if (!message || running || !account || !model) return false;
    const useMode = asMode ?? mode;
    // A chat keeps the mode it started with; switching modes starts a fresh conversation.
    const id = asMode && asMode !== mode ? null : chatId;
    if (asMode && asMode !== mode) {
      setMode(asMode);
      setChatId(null);
    }
    const abort = new AbortController();
    controller.current = abort;
    const started = Date.now();
    setRunning(true);
    setItems((all) => [
      ...(id === chatId ? all : []),
      { kind: "user", id: nextId(), text: message, context: contextLabel },
    ]);
    const update = (fn: (all: AgentItem[]) => AgentItem[]) => setItems(fn);
    const settleTools = (all: AgentItem[]) =>
      all.map((item) =>
        item.kind === "tool" && item.running
          ? { ...item, running: false }
          : item,
      );
    let failed = false;
    try {
      await data.chat(
        {
          course: courseId,
          chatId: id,
          mode: useMode,
          account: account.id,
          model: model.id,
          effort,
          context,
          message,
        },
        (event) => {
          if (event.chatId) setChatId(event.chatId);
          if (event.type === "text" && event.delta) {
            const delta = event.delta;
            update((all) => {
              const last = all.at(-1);
              if (last?.kind === "assistant" && last.streaming)
                return [
                  ...all.slice(0, -1),
                  { ...last, text: last.text + delta },
                ];
              return [
                ...settleTools(all),
                {
                  kind: "assistant",
                  id: nextId(),
                  text: delta,
                  streaming: true,
                },
              ];
            });
          } else if (event.type === "tool") {
            const tool = describeTool(event.title ?? "", event.detail ?? "");
            update((all) => [
              ...settleTools(all).map((item) =>
                item.kind === "assistant"
                  ? { ...item, streaming: false }
                  : item,
              ),
              {
                kind: "tool",
                id: nextId(),
                title: tool.title,
                detail: tool.detail,
                running: true,
              },
            ]);
          } else if (event.type === "error") {
            failed = true;
            const text = event.message ?? "助教回覆失敗";
            update((all) => [
              ...settleTools(all),
              { kind: "error", id: nextId(), text },
            ]);
          }
        },
        abort.signal,
      );
    } catch (error) {
      if (!abort.signal.aborted && !failed) {
        failed = true;
        update((all) => [
          ...settleTools(all),
          { kind: "error", id: nextId(), text: errorMessage(error) },
        ]);
      }
    } finally {
      const seconds = Math.max(1, Math.round((Date.now() - started) / 1000));
      update((all) => [
        ...settleTools(all).map((item) =>
          item.kind === "assistant" ? { ...item, streaming: false } : item,
        ),
        ...(failed
          ? []
          : [
              {
                kind: "result" as const,
                id: nextId(),
                aborted: abort.signal.aborted,
                seconds,
              },
            ]),
      ]);
      controller.current = null;
      setRunning(false);
      data.chats(courseId).then(setSessions, () => undefined);
    }
    return true;
  };

  return {
    accounts,
    accountError,
    loadAccounts,
    account,
    model,
    effort,
    choose,
    sessions,
    chatId,
    mode,
    setMode: (next: ChatMode) => {
      if (next === mode || running) return;
      setMode(next);
      if (items.length) newChat();
    },
    items,
    running,
    send,
    stop,
    newChat,
    openChat,
  };
}
