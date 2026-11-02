import {
  Captions,
  Check,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  FileText,
  Film,
  LoaderCircle,
  PanelLeft,
  Pencil,
  Play,
  Sparkles,
} from "lucide-react";
import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Link, useBlocker, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { AppShell } from "@/components/AppShell";
import { AgentPanel } from "@/components/agent/AgentPanel";
import { Markdown } from "@/components/Markdown";
import { AskSelection } from "@/components/reader/AskSelection";
import { Filmstrip } from "@/components/reader/Filmstrip";
import { NoteChecks } from "@/components/reader/NoteChecks";
import { SlideStage } from "@/components/reader/SlideStage";
import { TranscriptList } from "@/components/reader/TranscriptList";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { ResizeHandle } from "@/components/ui/resize-handle";
import { EmptyState, LoadingState } from "@/components/ui/states";
import { Hint } from "@/components/ui/tooltip";
import { VideoPlayer } from "@/components/VideoPlayer";
import { data } from "@/lib/data";
import { checkSummary, noteDigest, reviewView } from "@/lib/review";
import type {
  ChatContext,
  CourseDetail,
  DeckDetail,
  Note,
  NoteStatus,
  Transcript,
  VideoTime,
} from "@/lib/types";
import { useMediaQuery, useStored, useViewportWidth } from "@/lib/use-stored";
import { cn, errorMessage } from "@/lib/utils";
import { formatTime, videoSource } from "@/lib/video";

const STATUS: Record<
  NoteStatus,
  {
    label: string;
    hint: string;
    tone: "neutral" | "success" | "brand" | "warning";
  }
> = {
  generated: {
    label: "AI 初稿",
    hint: "AI 寫好、還沒通過筆記檢查",
    tone: "warning",
  },
  reviewed: {
    label: "已檢查",
    hint: "通過三位 AI 檢查員的筆記檢查",
    tone: "success",
  },
  edited: {
    label: "你改過",
    hint: "你手動編輯過，之後重新產生也不會被覆蓋",
    tone: "brand",
  },
  skipped: { label: "略過", hint: "老師沒有講這一頁", tone: "neutral" },
};

// CodeMirror is only needed once someone edits; keep it out of the reading bundle.
const NoteEditor = lazy(() =>
  import("@/components/notes/NoteEditor").then((m) => ({
    default: m.NoteEditor,
  })),
);

type Part = Transcript & { video: string };

// A lecture transcript covers many slides; keep finished ones so paging through a deck fetches each video once.
const transcripts = new Map<
  string,
  Promise<{ segments: Transcript[]; partial: boolean }>
>();
function lectureTranscript(courseId: string, video: string) {
  const key = `${courseId}\n${video}`;
  const cached = transcripts.get(key);
  if (cached) return cached;
  const request = data.transcript(courseId, video);
  transcripts.set(key, request);
  // Partial transcripts are still being written; failures should be retried.
  request.then(
    (result) => result.partial && transcripts.delete(key),
    () => transcripts.delete(key),
  );
  return request;
}

const SLIDE_MIN = 360;
const EDIT_W = 760;
const NOTE_W = { min: 340, max: 860, default: 480 };
const AGENT_W = { min: 320, max: 560, default: 380 };
const between = (min: number, max: number) => (value: unknown) =>
  typeof value === "number" && value >= min && value <= max;
const isPanes = (value: unknown) =>
  !!value &&
  typeof value === "object" &&
  "slides" in value &&
  "notes" in value &&
  "agent" in value;

type Panes = { slides: boolean; notes: boolean; agent: boolean };
type Tab = "note" | "transcript" | "checks";

export function Reader() {
  const { courseId = "", deckId = "", slide: slideParam = "1" } = useParams();
  const navigate = useNavigate();
  const slideIndex = Number(slideParam) || 1;
  const desktop = useMediaQuery("(min-width: 1100px)");
  const mobile = !useMediaQuery("(min-width: 768px)");
  // Portrait phones pin the slide above the notes; a phone on its side has room for them side by side.
  const landscape = useMediaQuery("(orientation: landscape)");
  const pinned = mobile && !landscape;

  const [deck, setDeck] = useState<DeckDetail | null>(null);
  const [course, setCourse] = useState<CourseDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<Note | null>(null);
  const [noteError, setNoteError] = useState<string | null>(null);
  const [transcript, setTranscript] = useState<Part[] | null>(null); // null while loading
  const [editing, setEditing] = useState(false);
  const [draft, setDraftState] = useState("");
  // save() may wait for uploads; it reads the draft as it is then, not as it was when save started.
  const draftRef = useRef("");
  const setDraft = useCallback((value: string) => {
    draftRef.current = value;
    setDraftState(value);
  }, []);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const [discarding, setDiscarding] = useState(false);
  const [tab, setTab] = useState<Tab>("note");
  const [player, setPlayer] = useState<VideoTime | null>(null);
  const [playback, setPlayback] = useState<VideoTime | null>(null);
  const [selection, setSelection] = useState<ChatContext["selection"]>();
  const [region, setRegion] = useState<ChatContext["region"]>();
  const [panes, setPanes] = useStored<Panes>(
    "marginalia:panes",
    {
      slides: true,
      notes: true,
      agent: data.editable && window.innerWidth >= 1680,
    },
    isPanes,
  );
  // Phones show the slide pinned above the notes (「閱讀」) or the assistant on its own.
  const [mobilePane, setMobilePane] = useState<"read" | "agent">("read");
  const [noteWidth, setNoteWidth] = useStored(
    "marginalia:note-width",
    NOTE_W.default,
    between(NOTE_W.min, NOTE_W.max),
  );
  const [editWidth, setEditWidth] = useStored(
    "marginalia:edit-width",
    EDIT_W,
    between(NOTE_W.min, NOTE_W.max),
  );
  const [agentWidth, setAgentWidth] = useStored(
    "marginalia:agent-width",
    AGENT_W.default,
    between(AGENT_W.min, AGENT_W.max),
  );
  const notesScope = useRef<HTMLDivElement>(null);
  const agentOpen =
    data.editable && (mobile ? mobilePane === "agent" : panes.agent);
  const [agentMounted, setAgentMounted] = useState(agentOpen);
  useEffect(() => {
    if (agentOpen) setAgentMounted(true);
  }, [agentOpen]);

  // Stored widths come from whatever window they were set in; fit them to this one so no pane is pushed off-screen.
  const viewport = useViewportWidth();
  const agentDocked = desktop && agentOpen;
  const agentMax = Math.max(
    AGENT_W.min,
    Math.min(AGENT_W.max, viewport - SLIDE_MIN - NOTE_W.min),
  );
  const agentShown = agentDocked ? Math.min(agentWidth, agentMax) : 0;
  const noteMax = Math.max(
    NOTE_W.min,
    Math.min(NOTE_W.max, viewport - agentShown - SLIDE_MIN),
  );
  // Editing keeps its own width (default wide enough for the side-by-side preview), so it never disturbs reading.
  const noteShown = Math.min(
    editing && desktop ? editWidth : noteWidth,
    noteMax,
  );
  const setNoteShown = editing && desktop ? setEditWidth : setNoteWidth;

  const dirty = editing && !!note && draft !== note.markdown;
  const blocker = useBlocker(dirty || saving);

  useEffect(() => {
    if (!dirty && !saving) return;
    const unload = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", unload);
    return () => window.removeEventListener("beforeunload", unload);
  }, [dirty, saving]);

  useEffect(() => {
    setError(null);
    data.course(courseId).then(setCourse, () => setCourse(null));
    data
      .deck(courseId, deckId)
      .then(setDeck, (reason) => setError(errorMessage(reason)));
  }, [courseId, deckId]);

  useEffect(() => {
    let active = true;
    setNote(null);
    setNoteError(null);
    setEditing(false);
    setSavedAt(null);
    setSelection(undefined);
    setRegion(undefined);
    data.note(courseId, deckId, slideIndex).then(
      (value) => {
        if (!active) return;
        setNote(value);
        setDraft(value.markdown);
      },
      (reason) => active && setNoteError(errorMessage(reason)),
    );
    return () => {
      active = false;
    };
  }, [courseId, deckId, slideIndex, setDraft]);

  const digest = useMemo(() => note && noteDigest(note.markdown), [note]);

  const current =
    deck?.slides.find((item) => item.index === slideIndex) ?? deck?.slides[0];
  const ranges = current?.ranges ?? [];
  const rangeKey = ranges
    .map((range) => `${range.video}@${range.start}-${range.end}`)
    .join(",");

  // biome-ignore lint/correctness/useExhaustiveDependencies: rangeKey captures the ranges
  useEffect(() => {
    let active = true;
    setTranscript(null);
    const videos = [...new Set(ranges.map((range) => range.video))];
    Promise.all(
      videos.map(async (video) => {
        const { segments } = await lectureTranscript(courseId, video);
        return segments
          .filter((part) =>
            ranges.some(
              (range) =>
                range.video === video &&
                part.end >= range.start &&
                part.start <= range.end,
            ),
          )
          .map((part) => ({ ...part, video }));
      }),
    )
      .then((parts) => active && setTranscript(parts.flat()))
      .catch(() => active && setTranscript([]));
    return () => {
      active = false;
    };
  }, [courseId, rangeKey]);

  const playerVideo = player?.video;
  const captions = useMemo(
    () => (transcript ?? []).filter((part) => part.video === playerVideo),
    [transcript, playerVideo],
  );
  const playable = useCallback(
    (video: string) => videoSource(course, courseId, video, data.editable),
    [course, courseId],
  );
  const canPlay = useCallback((video: string) => !!playable(video), [playable]);
  const go = (index: number) =>
    navigate(
      `/c/${encodeURIComponent(courseId)}/d/${encodeURIComponent(deckId)}/${index}`,
    );
  const setAgent = (open: boolean) =>
    mobile
      ? setMobilePane(open ? "agent" : "read")
      : setPanes((old) => ({ ...old, agent: open }));
  const openAgent = () => setAgent(true);
  const source = useMemo(() => ({ courseId, deckId }), [courseId, deckId]);

  const save = async () => {
    if (!editing || saving || !data.editable) return false;
    setSaving(true);
    try {
      // A pasted image is a placeholder until its upload finishes; saving it would lose the image.
      while (uploads.current.size)
        await Promise.allSettled([...uploads.current]);
      const markdown = draftRef.current;
      // Saving marks the note `edited` (generation never overwrites it again), so only save real changes.
      if (markdown === note?.markdown) return true;
      const meta = await data.saveNote(courseId, deckId, slideIndex, markdown);
      setNote((old) => (old ? { ...old, markdown, meta } : old));
      setSavedAt(new Date());
      setDeck(
        (old) =>
          old && {
            ...old,
            slides: old.slides.map((item) =>
              item.index === slideIndex
                ? {
                    ...item,
                    note: {
                      status: meta.status,
                      updatedAt: meta.updatedAt ?? "",
                    },
                  }
                : item,
            ),
          },
      );
      return true;
    } catch (reason) {
      toast.error("儲存失敗", { description: errorMessage(reason) });
      return false;
    } finally {
      setSaving(false);
    }
  };
  const saveRef = useRef(save);

  const uploads = useRef(new Set<Promise<unknown>>());
  const [uploading, setUploading] = useState(0);
  const uploadImage = (file: File, signal: AbortSignal) => {
    const request = data.uploadAsset(courseId, deckId, file, signal);
    uploads.current.add(request);
    setUploading(uploads.current.size);
    const settle = () => {
      uploads.current.delete(request);
      setUploading(uploads.current.size);
    };
    request.then(settle, settle);
    return request;
  };
  saveRef.current = save;

  const keyboard = (event: KeyboardEvent) => {
    if (blocker.state === "blocked" || editing) return;
    const target = event.target as HTMLElement | null;
    if (
      target?.closest(
        "input, textarea, select, video, [contenteditable]:not([contenteditable='false']), [role='separator'], [role='dialog']",
      ) ||
      event.altKey ||
      event.ctrlKey ||
      event.metaKey ||
      event.shiftKey
    )
      return;
    if (event.key === "ArrowLeft" && slideIndex > 1) {
      event.preventDefault();
      go(slideIndex - 1);
    }
    if (event.key === "ArrowRight" && deck && slideIndex < deck.slides.length) {
      event.preventDefault();
      go(slideIndex + 1);
    }
  };
  // Registered once; the ref always points at this render's handler (current slide, editing state).
  const keyboardRef = useRef(keyboard);
  keyboardRef.current = keyboard;
  useEffect(() => {
    const listener = (event: KeyboardEvent) => keyboardRef.current(event);
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, []);

  const crumbs = [
    {
      label: course?.info.title ?? "課程",
      to: `/c/${encodeURIComponent(courseId)}`,
    },
    { label: deck?.deck.title ?? "投影片" },
  ];

  if (error)
    return (
      <AppShell crumbs={crumbs} readOnly={!data.editable}>
        <EmptyState
          tone="error"
          icon={CircleAlert}
          title="無法開啟這份投影片"
          description={error}
          action={
            <Button
              variant="outline"
              render={<Link to={`/c/${encodeURIComponent(courseId)}`} />}
            >
              回到課程
            </Button>
          }
        />
      </AppShell>
    );
  if (!deck || !current)
    return (
      <AppShell crumbs={crumbs} readOnly={!data.editable} fill>
        {deck && !deck.slides.length ? (
          <EmptyState
            icon={FileText}
            title="這份投影片還沒轉出來"
            description="回到課程頁按「產生筆記」，會先把投影片轉成圖片。"
          />
        ) : (
          <LoadingState label="讀取投影片" />
        )}
      </AppShell>
    );

  const view = digest ? reviewView(note?.review, digest) : null;
  const summary = view && !view.stale ? checkSummary(view) : null;
  const status = note ? (STATUS[note.meta.status] ?? STATUS.generated) : null;
  const hasNote = !!note?.markdown.trim();
  const aspect =
    deck.deck.width && deck.deck.height
      ? deck.deck.width / deck.deck.height
      : 16 / 9;
  const videoTitle = (id: string) =>
    course?.videos.find((video) => video.id === id)?.title ?? id;

  const slidesPane = (
    <section
      aria-label="投影片"
      className={cn(
        "flex min-w-0 flex-col bg-canvas",
        pinned ? "shrink-0 border-b border-hairline" : "min-h-0 flex-1",
      )}
    >
      <div className="flex h-11 shrink-0 items-center gap-2 border-b border-hairline px-3">
        <p className="min-w-0 flex-1 truncate text-[13px]">
          <span className="nums mr-1.5 text-muted-foreground">
            第 {slideIndex} 頁
          </span>
          <span className="font-medium">{current.title}</span>
        </p>
        {data.editable && (
          <span className="shrink-0 text-[11.5px] text-muted-foreground/80 max-xl:hidden">
            拖曳框選投影片可以問助教
          </span>
        )}
        <div className="flex shrink-0 items-center gap-0.5">
          <Hint label="上一頁（←）">
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="上一頁"
              disabled={slideIndex <= 1}
              onClick={() => go(slideIndex - 1)}
            >
              <ChevronLeft />
            </Button>
          </Hint>
          <span className="nums min-w-12 text-center text-[12.5px] text-muted-foreground">
            {slideIndex} / {deck.slides.length}
          </span>
          <Hint label="下一頁（→）">
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="下一頁"
              disabled={slideIndex >= deck.slides.length}
              onClick={() => go(slideIndex + 1)}
            >
              <ChevronRight />
            </Button>
          </Hint>
        </div>
      </div>
      <div
        className={cn(
          "flex",
          pinned
            ? "px-3 py-2"
            : mobile
              ? "min-h-0 flex-1 p-3"
              : "min-h-0 flex-1 p-4 sm:p-6",
        )}
        style={pinned ? { aspectRatio: aspect, maxHeight: "45dvh" } : undefined}
      >
        <SlideStage
          key={`${deckId}-${slideIndex}`}
          slide={current}
          aspect={aspect}
          selectable={data.editable}
          onRegion={(next) => {
            setRegion(next);
            openAgent();
          }}
          below={
            !pinned && (
              <section
                aria-label="老師這頁說了什麼"
                className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-[8px] border border-hairline bg-background"
              >
                <header className="flex h-9 shrink-0 items-center gap-2 border-b border-hairline px-3 text-[12.5px]">
                  <Captions
                    className="size-3.5 text-muted-foreground"
                    aria-hidden
                  />
                  <span className="font-medium">老師這頁說了什麼</span>
                  {transcript && transcript.length > 0 && (
                    <span className="nums text-muted-foreground">
                      {transcript.length} 段
                    </span>
                  )}
                </header>
                <div className="min-h-0 flex-1 overflow-y-auto px-3">
                  <TranscriptList
                    parts={transcript ?? []}
                    loading={transcript === null}
                    onTime={setPlayer}
                    canPlay={canPlay}
                    compact
                  />
                </div>
              </section>
            )
          }
        />
      </div>
      {!mobile && (
        <Filmstrip slides={deck.slides} current={slideIndex} onSelect={go} />
      )}
    </section>
  );

  const tabs: { id: Tab; label: string; badge?: React.ReactNode }[] = [
    { id: "note", label: "筆記" },
    {
      id: "transcript",
      label: "逐字稿",
      badge: transcript?.length ? (
        <span className="nums text-muted-foreground">{transcript.length}</span>
      ) : undefined,
    },
    {
      id: "checks",
      label: "筆記檢查",
      badge: summary ? (
        summary.tone === "warning" ? (
          <Badge tone="warning" className="h-4 px-1">
            {summary.count}
          </Badge>
        ) : (
          <CircleCheck className="size-3.5 text-success" aria-label="已通過" />
        )
      ) : undefined,
    },
  ];

  const notesPane = (
    <section
      aria-label="筆記"
      ref={notesScope}
      style={!mobile && panes.slides ? { width: noteShown } : undefined}
      className={cn(
        "flex min-h-0 min-w-0 flex-col bg-background",
        !mobile && panes.slides ? "shrink-0" : "flex-1",
      )}
    >
      <header className="shrink-0 border-b border-hairline px-5 pt-4">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <p className="nums text-[12px] text-muted-foreground">
              第 {slideIndex} 頁
            </p>
            <h1 className="mt-0.5 text-[17px] leading-snug font-semibold text-pretty">
              {current.title}
            </h1>
          </div>
          {status && (hasNote || editing) && (
            <Hint label={status.hint}>
              <Badge tone={status.tone} className="mt-1">
                {status.label}
              </Badge>
            </Hint>
          )}
          {data.editable && note && !editing && (
            <Button
              variant="outline"
              size="sm"
              className="mt-0.5"
              onClick={() => {
                setDraft(note.markdown);
                setEditing(true);
                setTab("note");
              }}
            >
              <Pencil /> 編輯
            </Button>
          )}
        </div>
        {ranges.length > 0 && !editing && (
          <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
            {ranges.map((range) => (
              <Hint
                key={`${range.video}-${range.start}`}
                label={
                  canPlay(range.video)
                    ? "播放老師講這一頁的片段"
                    : "錄影檔不在這裡，只顯示時間"
                }
              >
                <button
                  type="button"
                  disabled={!canPlay(range.video)}
                  onClick={() =>
                    setPlayer({ video: range.video, time: range.start })
                  }
                  className="inline-flex h-6 items-center gap-1.5 rounded-[5px] border border-hairline bg-card px-2 text-[12px] text-muted-foreground outline-none hover:border-foreground/20 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/30 disabled:cursor-default disabled:hover:border-hairline disabled:hover:text-muted-foreground"
                >
                  {canPlay(range.video) ? (
                    <Play className="size-3 fill-current" aria-hidden />
                  ) : (
                    <Film className="size-3" aria-hidden />
                  )}
                  <span className="nums">
                    {formatTime(range.start)}–{formatTime(range.end)}
                  </span>
                  <span className="max-w-28 truncate">
                    {videoTitle(range.video)}
                  </span>
                </button>
              </Hint>
            ))}
          </div>
        )}
        {editing ? (
          <div className="mt-3 flex h-10 items-center gap-2">
            <p
              className="flex min-w-0 flex-1 items-center gap-1.5 text-[12.5px] text-muted-foreground"
              aria-live="polite"
            >
              {saving || uploading ? (
                <>
                  <LoaderCircle className="size-3.5 animate-spin" aria-hidden />{" "}
                  {saving && uploading
                    ? "等圖片上傳完成再儲存…"
                    : saving
                      ? "儲存中…"
                      : "圖片上傳中…"}
                </>
              ) : dirty ? (
                <>
                  <span
                    aria-hidden
                    className="size-1.5 rounded-full bg-warning"
                  />{" "}
                  有尚未儲存的修改
                </>
              ) : savedAt ? (
                <>
                  <Check className="size-3.5 text-success" aria-hidden /> 已儲存{" "}
                  {savedAt.toLocaleTimeString("zh-TW", {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </>
              ) : (
                "編輯中"
              )}
            </p>
            <Button
              variant="ghost"
              size="sm"
              disabled={saving}
              onClick={() => (dirty ? setDiscarding(true) : setEditing(false))}
            >
              {dirty ? "放棄修改" : "完成"}
            </Button>
            <Hint label="儲存（Ctrl+S）">
              <Button
                size="sm"
                disabled={saving || !dirty}
                onClick={() => void save()}
              >
                儲存
              </Button>
            </Hint>
          </div>
        ) : (
          <div
            role="tablist"
            aria-label="這一頁的內容"
            className="mt-3 -mb-px flex gap-4"
          >
            {tabs.map((item) => (
              <button
                key={item.id}
                type="button"
                role="tab"
                aria-selected={tab === item.id}
                onClick={() => setTab(item.id)}
                className={cn(
                  "flex h-9 items-center gap-1.5 border-b-2 text-[13px] outline-none transition-colors focus-visible:text-foreground",
                  tab === item.id
                    ? "border-foreground font-medium text-foreground"
                    : "border-transparent text-muted-foreground hover:text-foreground",
                )}
              >
                {item.label}
                {item.badge}
              </button>
            ))}
          </div>
        )}
      </header>
      {editing && note ? (
        <Suspense fallback={<LoadingState label="開啟編輯器" />}>
          <NoteEditor
            value={draft}
            onChange={setDraft}
            onSave={() => void saveRef.current()}
            source={source}
            playback={playback}
            uploadImage={uploadImage}
            onTime={setPlayer}
            canPlay={canPlay}
          />
        </Suspense>
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto max-w-[720px] px-5 py-5 pb-16">
            {tab === "note" ? (
              noteError ? (
                <EmptyState
                  tone="error"
                  icon={CircleAlert}
                  title="讀不到這頁筆記"
                  description={noteError}
                />
              ) : !note ? (
                <LoadingState label="讀取筆記" />
              ) : hasNote ? (
                <>
                  {summary && (
                    <button
                      type="button"
                      onClick={() => setTab("checks")}
                      className={cn(
                        "mb-4 flex w-full items-center gap-2 rounded-[7px] border px-3 py-2 text-left text-[12.5px] outline-none transition-colors hover:bg-muted/60 focus-visible:ring-2 focus-visible:ring-ring/30",
                        summary.tone === "warning"
                          ? "border-warning/40 text-foreground"
                          : "border-hairline text-muted-foreground",
                      )}
                    >
                      {summary.tone === "warning" ? (
                        <CircleAlert
                          className="size-3.5 shrink-0 text-warning"
                          aria-hidden
                        />
                      ) : (
                        <CircleCheck
                          className="size-3.5 shrink-0 text-success"
                          aria-hidden
                        />
                      )}
                      <span className="min-w-0 flex-1">
                        筆記檢查：{summary.title}
                      </span>
                      <ChevronRight className="size-3.5 shrink-0" aria-hidden />
                    </button>
                  )}
                  <Markdown
                    markdown={note.markdown}
                    source={source}
                    onTime={setPlayer}
                    canPlay={canPlay}
                  />
                </>
              ) : (
                <EmptyState
                  icon={FileText}
                  title="這頁還沒有筆記"
                  description={
                    data.editable
                      ? "可以回課程頁產生筆記，或自己動手寫。"
                      : undefined
                  }
                  action={
                    data.editable && (
                      <Button
                        variant="outline"
                        onClick={() => {
                          setDraft("");
                          setEditing(true);
                        }}
                      >
                        <Pencil /> 開始寫
                      </Button>
                    )
                  }
                />
              )
            ) : tab === "transcript" ? (
              <TranscriptList
                parts={transcript ?? []}
                loading={transcript === null}
                onTime={setPlayer}
                canPlay={canPlay}
              />
            ) : (
              <NoteChecks
                view={view}
                source={source}
                onTime={setPlayer}
                canPlay={canPlay}
              />
            )}
          </div>
        </div>
      )}
      {data.editable && !editing && (
        <AskSelection
          scope={notesScope}
          onAsk={(text, from) => {
            setSelection({ text, source: from });
            openAgent();
          }}
        />
      )}
    </section>
  );

  const agentPane = (
    <AgentPanel
      data={data}
      courseId={courseId}
      source={source}
      slideLabel={`第 ${slideIndex} 頁 · ${current.title}`}
      context={{
        deck: deckId,
        slide: slideIndex,
        ...(selection ? { selection } : {}),
        ...(region ? { region } : {}),
      }}
      onClearSelection={() => setSelection(undefined)}
      onClearRegion={() => setRegion(undefined)}
      onClose={() => setAgent(false)}
      onTime={setPlayer}
      canPlay={canPlay}
    />
  );

  const togglePane = (key: keyof Panes) =>
    setPanes((old) => {
      const next = { ...old, [key]: !old[key] };
      return next.slides || next.notes
        ? next
        : { ...next, [key === "slides" ? "notes" : "slides"]: true };
    });

  const actions = !mobile && (
    <div className="mr-1 flex items-center gap-0.5 rounded-[7px] border border-hairline p-0.5">
      {(
        [
          ["slides", "投影片", <PanelLeft key="s" />],
          ["notes", "筆記", <FileText key="n" />],
          ...(data.editable
            ? [["agent", "AI 助教", <Sparkles key="a" />]]
            : []),
        ] as [keyof Panes, string, React.ReactNode][]
      ).map(([key, label, icon]) => (
        <Hint key={key} label={panes[key] ? `收起${label}` : `打開${label}`}>
          <Button
            variant="ghost"
            size="xs"
            aria-pressed={panes[key]}
            onClick={() => togglePane(key)}
            className="aria-pressed:bg-muted"
          >
            {icon}
            <span className="max-lg:sr-only">{label}</span>
          </Button>
        </Hint>
      ))}
    </div>
  );

  return (
    <AppShell crumbs={crumbs} actions={actions} readOnly={!data.editable} fill>
      {mobile && data.editable && (
        <div
          role="tablist"
          aria-label="切換畫面"
          className="flex shrink-0 gap-1 border-b border-hairline px-3 py-1.5"
        >
          {(
            [
              ["read", "閱讀"],
              ["agent", "AI 助教"],
            ] as ["read" | "agent", string][]
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={mobilePane === key}
              onClick={() => setMobilePane(key)}
              className={cn(
                "h-8 flex-1 rounded-[6px] text-[13px] text-muted-foreground",
                mobilePane === key && "bg-muted font-medium text-foreground",
              )}
            >
              {label}
            </button>
          ))}
        </div>
      )}
      <div className="flex min-h-0 flex-1">
        {mobile ? (
          mobilePane === "read" && (
            <div
              className={cn(
                "flex min-h-0 min-w-0 flex-1",
                pinned ? "flex-col" : "[&>section]:basis-1/2",
              )}
            >
              {slidesPane}
              {notesPane}
            </div>
          )
        ) : (
          <>
            {panes.slides && slidesPane}
            {panes.slides && panes.notes && (
              <ResizeHandle
                width={noteShown}
                min={NOTE_W.min}
                max={noteMax}
                defaultWidth={NOTE_W.default}
                edge="left"
                label="調整筆記欄寬度"
                onResize={setNoteShown}
              />
            )}
            {panes.notes && notesPane}
          </>
        )}
        {agentDocked && (
          <ResizeHandle
            width={agentShown}
            min={AGENT_W.min}
            max={agentMax}
            defaultWidth={AGENT_W.default}
            edge="left"
            label="調整助教欄寬度"
            onResize={setAgentWidth}
          />
        )}
        {/* Stays mounted once opened, so closing the panel or resizing the window keeps the conversation. */}
        {agentMounted && (
          <aside
            aria-label="AI 助教"
            hidden={!agentOpen}
            style={agentDocked ? { width: agentShown } : undefined}
            className={cn(
              "min-h-0 flex-col",
              agentOpen && "flex",
              mobile
                ? "flex-1"
                : desktop
                  ? "shrink-0"
                  : "rise-in fixed top-12 right-0 bottom-0 z-30 w-[min(400px,100vw)] border-l border-border shadow-overlay",
            )}
          >
            {agentPane}
          </aside>
        )}
      </div>
      {player && playable(player.video) && (
        <VideoPlayer
          target={player}
          src={playable(player.video) ?? ""}
          title={videoTitle(player.video)}
          captions={captions}
          onClose={() => setPlayer(null)}
          onProgress={editing ? setPlayback : undefined}
        />
      )}
      <Dialog open={discarding} onOpenChange={setDiscarding}>
        <DialogContent showClose={false}>
          <DialogTitle>放棄這次的修改？</DialogTitle>
          <DialogDescription>
            筆記會回到上次儲存的樣子，這次的修改不會保留。
          </DialogDescription>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setDiscarding(false)}>
              繼續編輯
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                setDraft(note?.markdown ?? "");
                setEditing(false);
                setDiscarding(false);
              }}
            >
              放棄修改
            </Button>
          </div>
        </DialogContent>
      </Dialog>
      <Dialog
        open={blocker.state === "blocked"}
        onOpenChange={(open) =>
          !open && blocker.state === "blocked" && blocker.reset()
        }
      >
        <DialogContent showClose={false}>
          <DialogTitle>筆記還沒儲存</DialogTitle>
          <DialogDescription>
            {uploading
              ? "還有圖片在上傳。選「儲存並離開」會等上傳完成再儲存；「不儲存」會取消上傳。"
              : "離開這一頁前，要先儲存剛剛的修改嗎？"}
          </DialogDescription>
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="ghost" onClick={() => blocker.reset?.()}>
              繼續編輯
            </Button>
            <Button
              variant="outline"
              disabled={saving}
              onClick={() => blocker.proceed?.()}
            >
              不儲存
            </Button>
            <Button
              disabled={saving}
              onClick={async () => {
                if (await save()) blocker.proceed?.();
              }}
            >
              儲存並離開
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </AppShell>
  );
}
