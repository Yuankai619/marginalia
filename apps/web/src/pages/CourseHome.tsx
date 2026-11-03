import {
  ChevronDown,
  CircleAlert,
  CircleCheck,
  FileUp,
  Film,
  FolderSearch,
  LoaderCircle,
  Presentation,
  Sparkles,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import { AppShell } from "@/components/AppShell";
import { ExamList } from "@/components/exam/ExamList";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { EmptyState, LoadingState } from "@/components/ui/states";
import { Hint } from "@/components/ui/tooltip";
import { fileUrl } from "@/lib/assets";
import { data } from "@/lib/data";
import { jobFinished, subscribeJob } from "@/lib/events";
import type {
  Alignment,
  AlignmentSegment,
  CourseDetail,
  Deck,
  Job,
} from "@/lib/types";
import { cn, errorMessage } from "@/lib/utils";
import { formatTime } from "@/lib/video";

const thumbUrl = (courseId: string, deckId: string) =>
  fileUrl(courseId, "generated", "decks", deckId, "thumbs", "001.webp");

const STEP_NAMES: Record<string, string> = {
  scan: "掃描教材",
  render: "轉出投影片",
  align: "對齊錄影",
  transcribe: "語音轉文字",
  generate: "撰寫筆記",
  review: "筆記檢查",
};

const formatDuration = (seconds: number) => {
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return h ? `${h} 小時 ${m} 分` : `${m} 分鐘`;
};

function DeckCard({ courseId, deck }: { courseId: string; deck: Deck }) {
  const [thumb, setThumb] = useState(true);
  return (
    <Link
      to={`/c/${encodeURIComponent(courseId)}/d/${encodeURIComponent(deck.id)}/1`}
      className="group flex flex-col overflow-hidden rounded-[10px] border border-border bg-card shadow-edge outline-none transition-[border-color,box-shadow] hover:border-foreground/20 hover:shadow-floating focus-visible:ring-2 focus-visible:ring-ring/40"
    >
      <div className="relative aspect-video overflow-hidden border-b border-hairline bg-muted">
        {thumb && deck.rendered !== false ? (
          <img
            src={thumbUrl(courseId, deck.id)}
            alt=""
            loading="lazy"
            onError={() => setThumb(false)}
            className="size-full object-cover transition-transform duration-300 group-hover:scale-[1.015]"
          />
        ) : (
          <div className="grid size-full place-items-center text-muted-foreground/60">
            <Presentation className="size-6" strokeWidth={1.5} aria-hidden />
          </div>
        )}
      </div>
      <div className="flex flex-1 flex-col gap-1 p-3.5">
        <h3 className="line-clamp-2 text-[14px] font-medium leading-snug">
          {deck.title}
        </h3>
        <p className="mt-auto flex flex-wrap gap-x-3 pt-1 text-[12px] text-muted-foreground">
          <span>{deck.slideCount ?? "—"} 頁</span>
          {deck.date && (
            <span className="nums">{deck.date.replaceAll("-", "/")}</span>
          )}
        </p>
      </div>
    </Link>
  );
}

function JobCard({ job }: { job: Job }) {
  const done = job.state === "done";
  const failed = job.state === "failed" || job.state === "cancelled";
  return (
    <section
      aria-live="polite"
      className={cn(
        "rounded-[10px] border bg-card p-4 shadow-edge",
        failed ? "border-destructive/40" : "border-border",
      )}
    >
      <div className="flex items-center gap-2.5">
        {done ? (
          <CircleCheck className="size-4 text-success" aria-hidden />
        ) : failed ? (
          <CircleAlert className="size-4 text-destructive" aria-hidden />
        ) : (
          <LoaderCircle
            className="size-4 animate-spin text-brand"
            aria-hidden
          />
        )}
        <p className="min-w-0 flex-1 truncate text-[13.5px] font-medium">
          {done
            ? "筆記產生完成"
            : failed
              ? "產生筆記失敗"
              : job.message || "準備中"}
        </p>
        <span className="nums text-[12.5px] text-muted-foreground">
          {Math.round(job.progress * 100)}%
        </span>
      </div>
      <div className="mt-3 h-1 overflow-hidden rounded-full bg-muted">
        <div
          className={cn(
            "h-full rounded-full transition-[width] duration-500",
            failed ? "bg-destructive" : "bg-brand",
          )}
          style={{ width: `${Math.max(2, job.progress * 100)}%` }}
        />
      </div>
      {job.steps.length > 0 && (
        <ol className="mt-3 flex flex-wrap gap-1.5">
          {job.steps.map((step) => (
            <li key={step.name}>
              <Badge
                tone={
                  step.state === "done"
                    ? "success"
                    : step.state === "failed"
                      ? "danger"
                      : step.state === "running"
                        ? "brand"
                        : "neutral"
                }
              >
                {STEP_NAMES[step.name] ?? step.name}
                {step.state === "running" &&
                  ` ${Math.round(step.progress * 100)}%`}
              </Badge>
            </li>
          ))}
        </ol>
      )}
      {failed && job.message && (
        <p className="mt-2 text-[12.5px] text-destructive">{job.message}</p>
      )}
    </section>
  );
}

function GenerateDialog({
  open,
  onOpenChange,
  decks,
  onStart,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  decks: Deck[];
  onStart: (decks: string[]) => Promise<void>;
}) {
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  // Pick the defaults when the dialog opens; later re-renders of the page must not reset the reader's choice.
  // biome-ignore lint/correctness/useExhaustiveDependencies: decks is read once per opening
  useEffect(() => {
    if (open)
      setSelected(decks.filter((deck) => !deck.hidden).map((deck) => deck.id));
  }, [open]);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <div className="grid gap-1.5">
          <DialogTitle>產生筆記</DialogTitle>
          <DialogDescription>
            會依序轉出投影片、對齊錄影、把老師的講解轉成文字、逐頁寫筆記，最後做筆記檢查。逐字稿最花時間，一部兩小時的錄影大約要半小時以上。
          </DialogDescription>
        </div>
        <fieldset className="grid max-h-[min(18rem,35dvh)] gap-0.5 overflow-y-auto rounded-[8px] border border-border p-1">
          <legend className="sr-only">要產生筆記的投影片</legend>
          {decks.map((deck) => (
            <label
              key={deck.id}
              className="flex cursor-pointer items-center gap-2.5 rounded-[6px] px-2.5 py-2 text-[13px] hover:bg-muted"
            >
              <input
                type="checkbox"
                className="size-3.5 accent-[var(--brand)]"
                checked={selected.includes(deck.id)}
                onChange={(event) =>
                  setSelected((old) =>
                    event.target.checked
                      ? [...old, deck.id]
                      : old.filter((id) => id !== deck.id),
                  )
                }
              />
              <span className="min-w-0 flex-1 truncate">{deck.title}</span>
              <span className="text-[12px] text-muted-foreground">
                {deck.slideCount} 頁
              </span>
            </label>
          ))}
        </fieldset>
        <div className="flex items-center justify-between gap-2">
          <span className="text-[12px] text-muted-foreground">
            已選 {selected.length} 份
          </span>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              取消
            </Button>
            <Button
              disabled={!selected.length || busy}
              onClick={async () => {
                setBusy(true);
                try {
                  await onStart(selected);
                  onOpenChange(false);
                } finally {
                  setBusy(false);
                }
              }}
            >
              <Sparkles /> 開始
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function ImportZone({
  busy,
  onFiles,
  onScan,
}: {
  busy: boolean;
  onFiles: (files: File[]) => void;
  onScan: () => void;
}) {
  const [over, setOver] = useState(false);
  const picker = useRef<HTMLInputElement>(null);
  return (
    <section
      aria-label="匯入教材"
      onDragOver={(event) => {
        event.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(event) => {
        event.preventDefault();
        setOver(false);
        const files = Array.from(event.dataTransfer.files);
        if (files.length) onFiles(files);
      }}
      className={cn(
        "flex flex-wrap items-center gap-x-4 gap-y-3 rounded-[10px] border border-dashed px-4 py-3.5 transition-colors",
        over ? "border-brand bg-brand-soft" : "border-border",
      )}
    >
      <FileUp className="size-5 shrink-0 text-muted-foreground" aria-hidden />
      <div className="min-w-0 flex-1 basis-64">
        <p className="text-[13px] font-medium">拖放投影片或錄影到這裡</p>
        <p className="text-[12px] text-muted-foreground">
          支援 pptx、pdf、mp4，也可以整包 zip；放進課程的 materials
          資料夾後按「重新掃描」也行。
        </p>
      </div>
      <div className="flex gap-1.5">
        <Button
          variant="outline"
          size="sm"
          disabled={busy}
          onClick={() => picker.current?.click()}
        >
          {busy ? "處理中…" : "選擇檔案"}
        </Button>
        <input
          ref={picker}
          type="file"
          multiple
          hidden
          tabIndex={-1}
          accept=".pptx,.pdf,.mp4,.zip"
          onChange={(event) => {
            const files = Array.from(event.target.files ?? []);
            if (files.length) onFiles(files);
            event.target.value = "";
          }}
        />
        <Button variant="ghost" size="sm" disabled={busy} onClick={onScan}>
          <FolderSearch /> 重新掃描
        </Button>
      </div>
    </section>
  );
}

const DECK_TONES = [
  "bg-brand/70",
  "bg-[oklch(0.7_0.1_75)]",
  "bg-[oklch(0.62_0.1_300)]",
  "bg-[oklch(0.62_0.11_250)]",
  "bg-[oklch(0.65_0.12_25)]",
];

function AlignmentView({
  courseId,
  alignment,
  decks,
}: {
  courseId: string;
  alignment: Alignment;
  decks: Deck[];
}) {
  const [segments, setSegments] = useState(alignment.segments);
  const [editing, setEditing] = useState<AlignmentSegment | null>(null);
  const [slide, setSlide] = useState("");
  useEffect(() => setSegments(alignment.segments), [alignment]);
  const videos = useMemo(
    () => [...new Set(segments.map((s) => s.video))],
    [segments],
  );
  const deckIndex = (id: string | null) =>
    decks.findIndex((deck) => deck.id === id);
  const deckTitle = (id: string | null) =>
    decks.find((deck) => deck.id === id)?.title ?? "沒有投影片";
  const save = async () => {
    const value = Number(slide);
    if (!editing || !Number.isInteger(value) || value < 1) return;
    try {
      await data.updateSegment(courseId, {
        ...editing,
        slide: value,
        manual: true,
      });
      setSegments((all) =>
        all.map((item) =>
          item === editing ? { ...item, slide: value, manual: true } : item,
        ),
      );
      setEditing(null);
      toast.success("已更新對齊");
    } catch (error) {
      toast.error("更新失敗", { description: errorMessage(error) });
    }
  };
  if (!videos.length) return null;
  return (
    <details className="group rounded-[10px] border border-border bg-card shadow-edge">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 text-[13.5px] font-medium">
        <ChevronDown
          className="size-4 -rotate-90 text-muted-foreground transition-transform group-open:rotate-0"
          aria-hidden
        />
        錄影與投影片的對應
        <span className="text-[12px] font-normal text-muted-foreground">
          每一段代表錄影中那段時間畫面上的投影片
        </span>
      </summary>
      <div className="grid gap-4 border-t border-hairline px-4 py-4">
        {videos.map((video) => {
          const parts = segments.filter((s) => s.video === video);
          return (
            <div key={video}>
              <p className="mb-1.5 text-[12.5px] font-medium">{video}</p>
              <div className="flex h-8 overflow-hidden rounded-[6px] bg-muted">
                {parts.map((segment) => (
                  <Hint
                    key={`${segment.start}-${segment.end}`}
                    label={`${formatTime(segment.start)}–${formatTime(segment.end)} · ${deckTitle(segment.deck)}${segment.slide ? ` 第 ${segment.slide} 頁` : ""}${data.editable && segment.deck ? "（點一下修正）" : ""}`}
                  >
                    <button
                      type="button"
                      disabled={!data.editable || !segment.deck}
                      onClick={() => {
                        setEditing(segment);
                        setSlide(String(segment.slide ?? 1));
                      }}
                      style={{
                        flexGrow: Math.max(1, segment.end - segment.start),
                      }}
                      className={cn(
                        "min-w-1 basis-0 border-r border-background/70 text-[10px] text-white/95 outline-none hover:brightness-110 focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-default",
                        segment.deck
                          ? DECK_TONES[
                              Math.max(0, deckIndex(segment.deck)) %
                                DECK_TONES.length
                            ]
                          : "bg-transparent",
                        segment.manual &&
                          "ring-1 ring-inset ring-foreground/50",
                      )}
                    >
                      <span className="sr-only">{deckTitle(segment.deck)}</span>
                      {segment.end - segment.start > 120 && segment.slide
                        ? segment.slide
                        : ""}
                    </button>
                  </Hint>
                ))}
              </div>
            </div>
          );
        })}
      </div>
      <Dialog
        open={editing !== null}
        onOpenChange={(open) => !open && setEditing(null)}
      >
        <DialogContent>
          <DialogTitle>修正這段的投影片</DialogTitle>
          <DialogDescription>
            {editing &&
              `${editing.video} ${formatTime(editing.start)}–${formatTime(editing.end)}，${deckTitle(editing.deck)}`}
          </DialogDescription>
          <label className="grid gap-1.5 text-[12.5px] font-medium">
            投影片頁碼
            <input
              type="number"
              min={1}
              value={slide}
              onChange={(event) => setSlide(event.target.value)}
              className="h-9 w-32 rounded-[6px] border border-border bg-background px-3 text-[14px] outline-none focus-visible:border-foreground/40"
            />
          </label>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setEditing(null)}>
              取消
            </Button>
            <Button onClick={save}>儲存</Button>
          </div>
        </DialogContent>
      </Dialog>
    </details>
  );
}

export function CourseHome() {
  const { courseId = "" } = useParams();
  const [course, setCourse] = useState<CourseDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [alignment, setAlignment] = useState<Alignment | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [showHidden, setShowHidden] = useState(false);
  const refresh = async () => {
    const [next, nextAlignment] = await Promise.all([
      data.course(courseId),
      data.alignment(courseId).catch(() => null),
    ]);
    setCourse(next);
    setAlignment(nextAlignment);
  };
  // biome-ignore lint/correctness/useExhaustiveDependencies: reload when the course changes
  useEffect(() => {
    setCourse(null);
    setError(null);
    refresh().catch((reason) => setError(errorMessage(reason)));
  }, [courseId]);
  useEffect(() => {
    if (!jobId) return;
    return subscribeJob(jobId, data.job, setJob, data.mode === "local");
  }, [jobId]);
  const importFiles = async (files?: File[]) => {
    if (busy) return;
    setBusy(true);
    try {
      if (files?.length) await data.upload(courseId, files);
      else await data.scan(courseId);
      await refresh();
      toast.success(
        files?.length ? `已匯入 ${files.length} 個檔案` : "掃描完成",
      );
    } catch (reason) {
      toast.error(files?.length ? "匯入失敗" : "掃描失敗", {
        description: errorMessage(reason),
      });
    } finally {
      setBusy(false);
    }
  };
  const hidden = new Set(course?.info.hiddenDecks ?? []);
  const decks =
    course?.decks.map((deck) => ({
      ...deck,
      hidden: deck.hidden || hidden.has(deck.id),
    })) ?? [];
  const visible = decks.filter((deck) => !deck.hidden);
  const others = decks.filter((deck) => deck.hidden);
  const running = job !== null && !jobFinished(job);
  return (
    <AppShell
      readOnly={!data.editable}
      crumbs={[{ label: course?.info.title ?? "課程" }]}
    >
      {error ? (
        <EmptyState
          tone="error"
          icon={CircleAlert}
          title="無法讀取課程"
          description={error}
          action={
            <Button variant="outline" render={<Link to="/" />}>
              回到課程列表
            </Button>
          }
        />
      ) : !course ? (
        <LoadingState label="讀取課程" />
      ) : (
        <main className="mx-auto grid w-full max-w-6xl gap-8 px-4 py-8 sm:px-6 sm:py-10">
          <header className="flex flex-wrap items-end justify-between gap-4">
            <div className="min-w-0">
              <h1 className="text-[26px] font-semibold tracking-tight sm:text-[30px]">
                {course.info.title}
              </h1>
              <p className="mt-1.5 text-[14px] text-muted-foreground">
                {[
                  course.info.subtitle,
                  `${visible.length} 份投影片`,
                  `${course.videos.length} 部錄影`,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            </div>
            {data.editable && decks.length > 0 && (
              <Button
                onClick={() => setGenerating(true)}
                disabled={running || (jobId !== null && !job)}
              >
                <Sparkles /> 產生筆記
              </Button>
            )}
          </header>
          {job && <JobCard job={job} />}
          {data.editable && (
            <ImportZone
              busy={busy}
              onFiles={(files) => void importFiles(files)}
              onScan={() => void importFiles()}
            />
          )}
          <section aria-labelledby="decks-title">
            <h2 id="decks-title" className="mb-3 text-[15px] font-semibold">
              投影片
            </h2>
            {visible.length ? (
              <ul className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
                {visible.map((deck) => (
                  <li key={deck.id}>
                    <DeckCard courseId={courseId} deck={deck} />
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState
                className="rounded-[10px] border border-dashed border-border py-10"
                icon={Presentation}
                title="還沒有投影片"
                description={
                  data.editable ? "把 pptx 或 pdf 拖進上方的區塊。" : undefined
                }
              />
            )}
            {others.length > 0 && (
              <div className="mt-3">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setShowHidden(!showHidden)}
                  aria-expanded={showHidden}
                >
                  <ChevronDown
                    className={cn(
                      "transition-transform",
                      !showHidden && "-rotate-90",
                    )}
                  />
                  其他 {others.length} 份（課程說明等，不產生筆記）
                </Button>
                {showHidden && (
                  <ul className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
                    {others.map((deck) => (
                      <li key={deck.id}>
                        <DeckCard courseId={courseId} deck={deck} />
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </section>
          <ExamList courseId={courseId} />
          <section aria-labelledby="videos-title">
            <h2 id="videos-title" className="mb-3 text-[15px] font-semibold">
              上課錄影
            </h2>
            {course.videos.length ? (
              <ul className="divide-y divide-hairline overflow-hidden rounded-[10px] border border-border bg-card shadow-edge">
                {course.videos.map((video) => (
                  <li
                    key={video.id}
                    className="flex items-center gap-3 px-4 py-3"
                  >
                    <Film
                      className="size-4 shrink-0 text-muted-foreground"
                      aria-hidden
                    />
                    <span className="min-w-0 flex-1 truncate text-[13.5px] font-medium">
                      {video.title}
                    </span>
                    {video.date && (
                      <span className="nums text-[12.5px] text-muted-foreground max-sm:hidden">
                        {video.date.replaceAll("-", "/")}
                      </span>
                    )}
                    <span className="nums w-24 text-right text-[12.5px] text-muted-foreground">
                      {video.duration ? formatDuration(video.duration) : "—"}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState
                className="rounded-[10px] border border-dashed border-border py-10"
                icon={Film}
                title="還沒有錄影"
                description="有錄影才能把筆記對到老師講解的時間點。"
              />
            )}
          </section>
          {alignment && (
            <AlignmentView
              courseId={courseId}
              alignment={alignment}
              decks={decks}
            />
          )}
        </main>
      )}
      <GenerateDialog
        open={generating}
        onOpenChange={setGenerating}
        decks={visible.length ? visible : decks}
        onStart={async (selected) => {
          try {
            const { id } = await data.createJob(courseId, selected);
            setJob(null);
            setJobId(id);
          } catch (reason) {
            toast.error("無法開始", { description: errorMessage(reason) });
            throw reason;
          }
        }}
      />
    </AppShell>
  );
}
