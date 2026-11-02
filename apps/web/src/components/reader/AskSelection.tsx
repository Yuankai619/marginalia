import { MessageCircleQuestion } from "lucide-react";
import { type RefObject, useEffect, useState } from "react";

/** A small「問助教」button that follows a text selection inside `scope`. */
export function AskSelection({
  scope,
  onAsk,
}: {
  scope: RefObject<HTMLElement | null>;
  onAsk: (text: string, source: "note" | "transcript") => void;
}) {
  const [at, setAt] = useState<{
    x: number;
    y: number;
    text: string;
    source: "note" | "transcript";
  } | null>(null);
  useEffect(() => {
    // selectionchange fires on every caret move anywhere (also while typing in the chat box): check the scope
    // before doing any work, and keep the previous state object when nothing moved.
    const update = () => {
      const selection = window.getSelection();
      const root = scope.current;
      const anchor = selection?.rangeCount
        ? selection.getRangeAt(0).commonAncestorContainer
        : null;
      const element =
        anchor instanceof Element ? anchor : anchor?.parentElement;
      if (!selection || !root || !element || !root.contains(element))
        return setAt(null);
      const text = selection.toString().trim();
      if (!text) return setAt(null);
      const range = selection.getRangeAt(0);
      const source = element.closest("[data-select-source='transcript']")
        ? "transcript"
        : "note";
      const rect = range.getBoundingClientRect();
      const next = {
        x: rect.left + rect.width / 2,
        y: rect.top,
        text: text.slice(0, 2000),
        source,
      } as const;
      setAt((old) =>
        old && old.x === next.x && old.y === next.y && old.text === next.text
          ? old
          : next,
      );
    };
    const hide = () => setAt(null);
    document.addEventListener("selectionchange", update);
    window.addEventListener("resize", hide);
    const root = scope.current;
    root?.addEventListener("scroll", hide, true);
    return () => {
      document.removeEventListener("selectionchange", update);
      window.removeEventListener("resize", hide);
      root?.removeEventListener("scroll", hide, true);
    };
  }, [scope]);
  if (!at) return null;
  return (
    <button
      type="button"
      onMouseDown={(event) => event.preventDefault()}
      onClick={() => {
        onAsk(at.text, at.source);
        window.getSelection()?.removeAllRanges();
        setAt(null);
      }}
      style={{ left: at.x, top: Math.max(8, at.y - 38) }}
      className="rise-in fixed z-40 flex h-8 -translate-x-1/2 items-center gap-1.5 rounded-[7px] bg-foreground px-2.5 text-[12.5px] font-medium text-background shadow-overlay outline-none hover:bg-foreground/90"
    >
      <MessageCircleQuestion className="size-3.5" aria-hidden /> 問助教
    </button>
  );
}
