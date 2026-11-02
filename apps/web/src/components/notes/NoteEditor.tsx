import {
  defaultKeymap,
  history,
  historyKeymap,
  indentWithTab,
} from "@codemirror/commands";
import { markdown } from "@codemirror/lang-markdown";
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { EditorState } from "@codemirror/state";
import {
  Decoration,
  EditorView,
  keymap,
  MatchDecorator,
  placeholder,
  ViewPlugin,
  type ViewUpdate,
} from "@codemirror/view";
import { tags } from "@lezer/highlight";
import {
  Bold,
  ChevronDown,
  Clock,
  Columns2,
  Eye,
  Heading2,
  Highlighter,
  ImagePlus,
  List,
  ListOrdered,
  MessageSquareWarning,
  PenLine,
  Table,
  Workflow,
} from "lucide-react";
import {
  useDeferredValue,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { toast } from "sonner";
import { Markdown, type NoteSource } from "@/components/Markdown";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Segmented } from "@/components/ui/segmented";
import { Hint } from "@/components/ui/tooltip";
import { IMAGE_FORMATS } from "@/lib/assets";
import { ALERTS, type AlertKind } from "@/lib/remark-notes";
import type { VideoTime } from "@/lib/types";
import { cn, errorMessage } from "@/lib/utils";
import { timestampLabel, timestampLink } from "@/lib/video";

const IMAGE_MIME = new Set(Object.values(IMAGE_FORMATS));
const imageFiles = (list: FileList | undefined | null) =>
  Array.from(list ?? []).filter((file) => file.type.startsWith("image/"));

const highlightMarks = new MatchDecorator({
  regexp: /==[^=\n]+==/g,
  decoration: Decoration.mark({ class: "cm-note-mark" }),
});
const highlightPlugin = ViewPlugin.define(
  (view) => ({
    decorations: highlightMarks.createDeco(view),
    update(update: ViewUpdate) {
      this.decorations = highlightMarks.updateDeco(update, this.decorations);
    },
  }),
  { decorations: (plugin) => plugin.decorations },
);

const noteHighlight = HighlightStyle.define([
  { tag: tags.heading, fontWeight: "650", color: "var(--foreground)" },
  { tag: tags.strong, fontWeight: "650" },
  { tag: tags.emphasis, fontStyle: "italic" },
  { tag: [tags.link, tags.url], color: "var(--brand)" },
  {
    tag: [tags.processingInstruction, tags.monospace],
    color: "var(--muted-foreground)",
    fontFamily: "var(--font-mono)",
  },
  { tag: tags.quote, color: "var(--muted-foreground)" },
  { tag: tags.meta, color: "var(--muted-foreground)" },
]);

const editorTheme = EditorView.theme({
  "&": {
    height: "100%",
    fontSize: "14px",
    backgroundColor: "transparent",
    color: "var(--foreground)",
  },
  "&.cm-focused": { outline: "none" },
  ".cm-scroller": {
    fontFamily: "var(--font-mono)",
    lineHeight: "1.75",
    padding: "12px 0",
  },
  ".cm-content": { padding: "0 16px", caretColor: "var(--foreground)" },
  ".cm-line": { padding: "0" },
  ".cm-cursor": { borderLeftColor: "var(--foreground)" },
  "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, ::selection":
    {
      backgroundColor: "var(--brand-soft) !important",
    },
  ".cm-placeholder": { color: "var(--muted-foreground)" },
  ".cm-note-mark": { backgroundColor: "var(--mark)", borderRadius: "2px" },
});

type Insert = (text: string, select?: [number, number]) => void;

/** Markdown source editor with a live preview rendered by the same component the reader uses. */
export function NoteEditor({
  value,
  onChange,
  onSave,
  source,
  playback,
  uploadImage,
  onTime,
  canPlay,
}: {
  value: string;
  onChange: (value: string) => void;
  onSave: () => void;
  source: NoteSource;
  /** Where the lecture player is right now, for「插入目前時間」. */
  playback: VideoTime | null;
  uploadImage: (file: File, signal: AbortSignal) => Promise<string>;
  onTime: (target: VideoTime) => void;
  canPlay: (video: string) => boolean;
}) {
  const host = useRef<HTMLDivElement>(null);
  const frame = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const picker = useRef<HTMLInputElement>(null);
  // Uploads belong to one editor instance: destroying it aborts them, so a late reply never edits another note.
  // Made in the mount effect: StrictMode mounts twice, and the first cleanup's aborted controller must not stay.
  const uploads = useRef<AbortController | null>(null);
  const latest = useRef({ onChange, onSave, uploadImage });
  latest.current = { onChange, onSave, uploadImage };
  const [wide, setWide] = useState(false);
  const [layout, setLayout] = useState<"split" | "edit" | "preview">("split");
  const preview = useDeferredValue(value);
  const shown = wide ? layout : layout === "split" ? "edit" : layout;

  useLayoutEffect(() => {
    const node = frame.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) =>
      setWide(entry.contentRect.width >= 720),
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const upload = async (files: File[]) => {
    const editor = view.current;
    if (!editor) return;
    for (const file of files) {
      if (!IMAGE_MIME.has(file.type)) {
        toast.error("只能插入 png、jpg、webp 或 svg 圖片");
        continue;
      }
      const marker = `![上傳中：${file.name}]()`;
      // The document may change while uploading, so find the placeholder again before replacing it.
      const replaceMarker = (text: string, select?: number) => {
        const start = editor.state.doc.toString().indexOf(marker);
        if (start < 0) return;
        editor.dispatch({
          changes: { from: start, to: start + marker.length, insert: text },
          selection:
            select === undefined
              ? undefined
              : { anchor: start + 2, head: start + 2 + select },
        });
      };
      const at = editor.state.selection.main.from;
      editor.dispatch({
        changes: {
          from: at,
          to: editor.state.selection.main.to,
          insert: marker,
        },
      });
      try {
        const signal = uploads.current?.signal ?? AbortSignal.abort();
        const path = await latest.current.uploadImage(file, signal);
        if (view.current !== editor) return;
        // Brackets, parentheses and newlines in a file name would break the inserted ![caption](path).
        const caption =
          file.name
            .replace(/\.[^.]+$/, "")
            .replace(/[[\]()\\\r\n]+/g, " ")
            .trim() || "圖片";
        replaceMarker(`![${caption}](${path})`, caption.length);
      } catch (error) {
        if (view.current !== editor) return;
        replaceMarker("");
        toast.error("圖片上傳失敗", { description: errorMessage(error) });
      }
    }
    if (view.current === editor) editor.focus();
  };
  const uploadRef = useRef(upload);
  uploadRef.current = upload;

  // biome-ignore lint/correctness/useExhaustiveDependencies: the editor owns the document after mount
  useEffect(() => {
    if (!host.current) return;
    const editor = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: value,
        extensions: [
          history(),
          keymap.of([
            {
              key: "Mod-s",
              preventDefault: true,
              run: () => {
                latest.current.onSave();
                return true;
              },
            },
            { key: "Mod-b", run: (v) => wrap(v, "**", "粗體") },
            {
              key: "Mod-Shift-h",
              run: (v) => wrap(v, "==", "重點"),
            },
            ...defaultKeymap,
            ...historyKeymap,
            indentWithTab,
          ]),
          markdown(),
          syntaxHighlighting(noteHighlight),
          highlightPlugin,
          EditorView.lineWrapping,
          editorTheme,
          placeholder("用 Markdown 寫這一頁的筆記…"),
          EditorView.contentAttributes.of({
            "aria-label": "筆記內容（Markdown）",
            spellcheck: "false",
          }),
          EditorView.updateListener.of((update) => {
            if (update.docChanged)
              latest.current.onChange(update.state.doc.toString());
          }),
          EditorView.domEventHandlers({
            paste: (event) => {
              const files = imageFiles(event.clipboardData?.files);
              if (!files.length) return false;
              event.preventDefault();
              void uploadRef.current(files);
              return true;
            },
            drop: (event, v) => {
              const files = imageFiles(event.dataTransfer?.files);
              if (!files.length) return false;
              event.preventDefault();
              const at = v.posAtCoords({ x: event.clientX, y: event.clientY });
              if (at !== null) v.dispatch({ selection: { anchor: at } });
              void uploadRef.current(files);
              return true;
            },
          }),
        ],
      }),
    });
    view.current = editor;
    const controller = new AbortController();
    uploads.current = controller;
    editor.focus();
    return () => {
      controller.abort();
      editor.destroy();
      view.current = null;
    };
  }, []);

  const insert: Insert = (text, select) => {
    const editor = view.current;
    if (!editor) return;
    const { from, to } = editor.state.selection.main;
    editor.dispatch({
      changes: { from, to, insert: text },
      selection: select
        ? { anchor: from + select[0], head: from + select[1] }
        : { anchor: from + text.length },
      scrollIntoView: true,
    });
    editor.focus();
  };
  const block = (text: string, select?: [number, number]) => {
    const editor = view.current;
    if (!editor) return;
    const line = editor.state.doc.lineAt(editor.state.selection.main.from);
    const before = line.text.trim() ? "\n\n" : line.from === 0 ? "" : "\n";
    insert(
      `${before}${text}\n`,
      select && [select[0] + before.length, select[1] + before.length],
    );
  };
  const prefixLines = (prefix: (index: number) => string) => {
    const editor = view.current;
    if (!editor) return;
    const { from, to } = editor.state.selection.main;
    const first = editor.state.doc.lineAt(from).number;
    const last = editor.state.doc.lineAt(to).number;
    const changes = [];
    for (let n = first; n <= last; n++)
      changes.push({
        from: editor.state.doc.line(n).from,
        insert: prefix(n - first),
      });
    editor.dispatch({ changes });
    editor.focus();
  };

  const tool = (
    label: string,
    icon: React.ReactNode,
    run: () => void,
    shortcut?: string,
  ) => (
    <Hint label={shortcut ? `${label}（${shortcut}）` : label}>
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label={label}
        onMouseDown={(event) => event.preventDefault()}
        onClick={run}
      >
        {icon}
      </Button>
    </Hint>
  );
  const mod = /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘" : "Ctrl+";

  return (
    <div ref={frame} className="flex min-h-0 flex-1 flex-col">
      <div
        role="toolbar"
        aria-label="格式工具"
        className="flex shrink-0 flex-wrap items-center gap-0.5 border-b border-hairline px-2 py-1"
      >
        {tool(
          "粗體",
          <Bold />,
          () => view.current && wrap(view.current, "**", "粗體"),
          `${mod}B`,
        )}
        {tool(
          "螢光筆重點",
          <Highlighter />,
          () => view.current && wrap(view.current, "==", "重點"),
          `${mod}Shift+H`,
        )}
        {tool("小標題", <Heading2 />, () => prefixLines(() => "## "))}
        {tool("列點", <List />, () => prefixLines(() => "- "))}
        {tool("編號清單", <ListOrdered />, () =>
          prefixLines((i) => `${i + 1}. `),
        )}
        <Popover>
          <Hint label="提示框">
            <PopoverTrigger
              aria-label="提示框"
              onMouseDown={(event) => event.preventDefault()}
              className="flex h-7 items-center gap-0.5 rounded-[5px] px-1.5 text-foreground/75 outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/30 aria-expanded:bg-muted"
            >
              <MessageSquareWarning className="size-3.5" />
              <ChevronDown className="size-3 text-muted-foreground" />
            </PopoverTrigger>
          </Hint>
          <PopoverContent align="start" className="w-44 p-1">
            {(Object.keys(ALERTS) as AlertKind[]).map((kind) => (
              <button
                key={kind}
                type="button"
                onClick={() => {
                  const head = `> [!${kind.toUpperCase()}]\n> `;
                  block(`${head}內容`, [head.length, head.length + 2]);
                }}
                className="flex h-8 w-full items-center gap-2 rounded-[5px] px-2 text-left text-[12.5px] hover:bg-muted"
              >
                <span
                  aria-hidden
                  className="size-2 rounded-full"
                  style={{ background: `var(--alert-${kind})` }}
                />
                {ALERTS[kind]}
              </button>
            ))}
          </PopoverContent>
        </Popover>
        {tool("表格", <Table />, () =>
          block("| 項目 | 說明 |\n| --- | --- |\n| 內容 | 內容 |", [2, 4]),
        )}
        {tool("流程圖（mermaid）", <Workflow />, () =>
          block('```mermaid\nflowchart LR\n  A["開始"] --> B["結束"]\n```'),
        )}
        <Hint label="插入圖片（也可以直接貼上或拖進來）">
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="插入圖片"
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => picker.current?.click()}
          >
            <ImagePlus />
          </Button>
        </Hint>
        <input
          ref={picker}
          type="file"
          hidden
          tabIndex={-1}
          accept={Object.keys(IMAGE_FORMATS)
            .map((type) => `.${type}`)
            .join(",")}
          onChange={(event) => {
            const files = Array.from(event.target.files ?? []);
            event.target.value = "";
            if (files.length) void upload(files);
          }}
        />
        <span aria-hidden className="mx-1 h-4 w-px bg-hairline" />
        <Hint
          label={
            playback
              ? "把錄影目前播放到的時間插進筆記"
              : "先點筆記裡的時間點或右下角播放錄影，就能插入目前時間"
          }
        >
          <Button
            variant="ghost"
            size="sm"
            disabled={!playback}
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => playback && insert(`${timestampLink(playback)} `)}
            className="disabled:pointer-events-auto"
          >
            <Clock />{" "}
            {playback
              ? `插入 ${timestampLabel(playback.time)}`
              : "插入目前時間"}
          </Button>
        </Hint>
        <Segmented
          title="編輯畫面"
          className="ml-auto"
          options={[
            { id: "edit", label: "編輯", icon: <PenLine /> },
            ...(wide
              ? [{ id: "split" as const, label: "並排", icon: <Columns2 /> }]
              : []),
            { id: "preview", label: "預覽", icon: <Eye /> },
          ]}
          value={shown}
          onChange={setLayout}
        />
      </div>
      <div
        className={cn(
          "grid min-h-0 flex-1",
          shown === "split" && "grid-cols-2 divide-x divide-hairline",
        )}
      >
        <div
          ref={host}
          className={cn(
            "min-h-0 overflow-hidden bg-card",
            shown === "preview" && "hidden",
          )}
        />
        {shown !== "edit" && (
          <section
            className="min-h-0 overflow-y-auto px-5 py-4"
            aria-label="預覽"
          >
            {preview.trim() ? (
              <Markdown
                markdown={preview}
                source={source}
                onTime={onTime}
                canPlay={canPlay}
              />
            ) : (
              <p className="text-[13px] text-muted-foreground">
                開始輸入後，這裡會即時顯示筆記的樣子。
              </p>
            )}
          </section>
        )}
      </div>
    </div>
  );
}

/** Surrounds the selection (or `fallback`) with `mark` on both sides, e.g. `**` or `==`. */
function wrap(view: EditorView, mark: string, fallback: string) {
  const { from, to } = view.state.selection.main;
  const selected = view.state.sliceDoc(from, to) || fallback;
  view.dispatch({
    changes: { from, to, insert: `${mark}${selected}${mark}` },
    selection: {
      anchor: from + mark.length,
      head: from + mark.length + selected.length,
    },
  });
  view.focus();
  return true;
}
