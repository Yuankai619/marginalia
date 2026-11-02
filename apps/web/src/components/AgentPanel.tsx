import { Send } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import type { DataAdapter } from "../lib/adapter";
import type {
  Account,
  Chat,
  ChatContext,
  ChatMessage,
  VideoTime,
} from "../lib/types";
import { Markdown } from "./Markdown";

export function AgentPanel({
  data,
  courseId,
  label,
  context,
  onClearContext,
  onTime,
  canPlay,
}: {
  data: DataAdapter;
  courseId: string;
  label: string;
  context: ChatContext;
  onClearContext: () => void;
  onTime: (target: VideoTime) => void;
  canPlay: (video: string) => boolean;
}) {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [accountId, setAccountId] = useState("");
  const [model, setModel] = useState("");
  const [effort, setEffort] = useState("");
  const [message, setMessage] = useState("");
  const [mode, setMode] = useState("qa");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [chatId, setChatId] = useState<string | null>(null);
  const [chats, setChats] = useState<Omit<Chat, "messages">[]>([]);
  const [busy, setBusy] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const account = accounts.find((item) => item.id === accountId);
  useEffect(() => {
    let active = true;
    data
      .accounts()
      .then((items) => {
        if (!active) return;
        setAccounts(items);
        const first = items.find((item) => item.loggedIn);
        if (first) {
          setAccountId(first.id);
          setModel(first.models[0]?.id ?? "");
          setEffort(
            first.efforts.includes("medium")
              ? "medium"
              : (first.efforts[0] ?? ""),
          );
        }
      })
      .catch((error: Error) => toast.error(error.message));
    data
      .chats(courseId)
      .then((items) => {
        if (active) setChats(items);
      })
      .catch((error: Error) => toast.error(error.message));
    return () => {
      active = false;
      controller.current?.abort();
    };
  }, [courseId, data]);
  const send = async () => {
    if (busy || !message.trim() || !account?.loggedIn || !model || !effort)
      return;
    const text = message.trim();
    const abort = new AbortController();
    controller.current = abort;
    setBusy(true);
    setMessage("");
    setMessages((all) => [
      ...all,
      { role: "user", content: text },
      { role: "assistant", content: "" },
    ]);
    try {
      await data.chat(
        {
          course: courseId,
          chatId,
          mode,
          account: accountId,
          model,
          effort,
          context,
          message: text,
        },
        (event) => {
          if (event.chatId) setChatId(event.chatId);
          if (event.type === "text")
            setMessages((all) =>
              all.map((item, index) =>
                index === all.length - 1
                  ? { ...item, content: item.content + (event.delta ?? "") }
                  : item,
              ),
            );
          if (event.type === "tool")
            toast(event.title ?? "Agent 正在讀取課程資料");
          if (event.type === "error")
            throw new Error(event.message ?? event.detail ?? "Agent 回覆失敗");
        },
        abort.signal,
      );
      setChats(await data.chats(courseId));
    } catch (error) {
      if ((error as Error).name !== "AbortError")
        toast.error((error as Error).message);
    } finally {
      if (!abort.signal.aborted) setBusy(false);
    }
  };
  return (
    <aside className="agent">
      <div className="agent-head">
        <div>
          <p className="eyebrow">STUDY AGENT</p>
          <strong>本機 Agent</strong>
        </div>
        <span className="online">
          {account?.loggedIn ? "已登入" : "未登入"}
        </span>
      </div>
      <p className="context">{label}</p>
      <div className="agent-settings">
        <label>
          帳號
          <select
            aria-label="帳號"
            value={accountId}
            disabled={busy}
            onChange={(event) => {
              const next = accounts.find(
                (item) => item.id === event.target.value,
              );
              setAccountId(event.target.value);
              setModel(next?.models[0]?.id ?? "");
              setEffort(next?.efforts[0] ?? "");
            }}
          >
            <option value="">選擇已登入帳號</option>
            {accounts.map((item) => (
              <option key={item.id} value={item.id} disabled={!item.loggedIn}>
                {item.label}
                {item.loggedIn ? "" : "（未登入）"}
              </option>
            ))}
          </select>
        </label>
        <label>
          模型
          <select
            aria-label="模型"
            value={model}
            disabled={busy}
            onChange={(event) => setModel(event.target.value)}
          >
            {account?.models.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          推理強度
          <select
            aria-label="推理強度"
            value={effort}
            disabled={busy}
            onChange={(event) => setEffort(event.target.value)}
          >
            {account?.efforts.map((item) => (
              <option key={item} value={item}>
                {(
                  {
                    low: "低",
                    medium: "中",
                    high: "高",
                    xhigh: "最高",
                  } as Record<string, string>
                )[item] ?? item}
              </option>
            ))}
          </select>
        </label>
        <label>
          對話
          <select
            aria-label="對話"
            value={chatId ?? ""}
            disabled={busy}
            onChange={async (event) => {
              const id = event.target.value;
              if (!id) {
                setChatId(null);
                setMessages([]);
                return;
              }
              setBusy(true);
              try {
                const chat = await data.conversation(courseId, id);
                setChatId(id);
                setMode(chat.mode);
                setMessages(chat.messages);
              } catch (error) {
                toast.error((error as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            <option value="">新對話</option>
            {chatId && !chats.some((chat) => chat.id === chatId) && (
              <option value={chatId}>目前對話</option>
            )}
            {chats.map((chat) => (
              <option value={chat.id} key={chat.id}>
                {chat.title}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="modes">
        {[
          ["qa", "問答"],
          ["interview", "口試"],
          ["review", "審稿"],
        ].map(([id, name]) => (
          <button
            key={id}
            disabled={busy}
            className={mode === id ? "active" : ""}
            onClick={() => setMode(id)}
          >
            {name}
          </button>
        ))}
      </div>
      {(context.region || context.selection) && (
        <div className="context">
          {context.selection
            ? `已選取${context.selection.source === "note" ? "筆記" : "逐字稿"}：${context.selection.text}`
            : "已帶入投影片圈選範圍"}
          <button className="button quiet" onClick={onClearContext}>
            清除選取
          </button>
        </div>
      )}
      <div className="messages" aria-live="polite">
        {messages.length ? (
          messages.map((item, index) => (
            <div key={index}>
              <strong>{item.role === "user" ? "你" : "Agent"}</strong>
              <Markdown
                markdown={item.content}
                onTime={onTime}
                canPlay={canPlay}
              />
            </div>
          ))
        ) : (
          <p>圈選投影片，或選取筆記、逐字稿文字，即可帶入提問。</p>
        )}
        {busy && <p>回覆中…</p>}
      </div>
      <div className="chat-input">
        <textarea
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          placeholder="問這一頁的概念…"
          disabled={busy}
          onKeyDown={(event) => {
            if (
              event.key === "Enter" &&
              !event.shiftKey &&
              !event.nativeEvent.isComposing
            ) {
              event.preventDefault();
              void send();
            }
          }}
        />
        <button
          className="icon-button"
          disabled={busy || !account?.loggedIn || !message.trim()}
          onClick={() => void send()}
          aria-label="傳送"
        >
          <Send />
        </button>
      </div>
    </aside>
  );
}
