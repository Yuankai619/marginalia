import {
  Bot,
  ChevronLeft,
  ChevronRight,
  FilePlus2,
  Moon,
  PanelRightClose,
  Pencil,
  Play,
  Search,
  Sun,
  Upload,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import {
  Link,
  Navigate,
  Route,
  Routes,
  useBlocker,
  useNavigate,
  useParams,
} from "react-router-dom";
import { toast } from "sonner";
import { AgentPanel } from "./components/AgentPanel";
import { Markdown } from "./components/Markdown";
import { SlideCanvas } from "./components/SlideCanvas";
import { VideoPlayer } from "./components/VideoPlayer";
import { adapter, emptyNote } from "./lib/adapter";
import { subscribeJob } from "./lib/events";
import type {
  Alignment,
  ChatContext,
  Course,
  CourseDetail,
  DeckDetail,
  Job,
  Note,
  Transcript,
  VideoTime,
} from "./lib/types";
import { formatTime as time, videoSource } from "./lib/video";

const data = adapter();
const statusLabel = {
  generated: "生成",
  reviewed: "審過",
  edited: "已編輯",
  skipped: "略過",
};

function Shell({ children }: { children: React.ReactNode }) {
  const [dark, setDark] = useState(false);
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);
  return (
    <main>
      <header className="topbar">
        <Link to="/" className="brand">
          MARGINALIA
        </Link>
        <span className="eyebrow">LECTURE NOTES / LOCAL-FIRST</span>
        <div className="top-actions">
          <button
            className="icon-button"
            onClick={() => setDark(!dark)}
            aria-label="切換主題"
          >
            {dark ? <Sun /> : <Moon />}
          </button>
          <Link className="button quiet" to="/">
            所有課程
          </Link>
        </div>
      </header>
      {children}
    </main>
  );
}

function Loading() {
  return <div className="empty">載入課程資料中…</div>;
}

function Courses() {
  const [query, setQuery] = useState("");
  const [courses, setCourses] = useState<Course[] | null>(null);
  useEffect(() => {
    data
      .courses()
      .then(setCourses)
      .catch((error: Error) => toast.error(error.message));
  }, []);
  if (!courses) return <Loading />;
  return (
    <Shell>
      <section className="page intro">
        <p className="eyebrow">YOUR LIBRARY</p>
        <div className="title-row">
          <div>
            <h1>課程筆記庫</h1>
            <p>把上課影片、投影片與你的理解，收在同一個閱讀空間。</p>
          </div>
          {data.editable && (
            <button
              className="button"
              onClick={async () => {
                const title = prompt("課程名稱");
                if (!title?.trim()) return;
                try {
                  await data.createCourse(title.trim());
                  setCourses(await data.courses());
                } catch (error) {
                  toast.error((error as Error).message);
                }
              }}
            >
              <FilePlus2 /> 新增課程
            </button>
          )}
        </div>
        <label className="search">
          <Search />
          <input
            placeholder="搜尋課程"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <div className="course-grid">
          {courses
            .filter((course) =>
              `${course.title} ${course.subtitle ?? ""}`.includes(query),
            )
            .map((course) => (
              <Link
                to={`/c/${course.id}`}
                className="course-card"
                key={course.id}
              >
                <p className="eyebrow">COURSE / {course.id}</p>
                <h2>{course.title}</h2>
                <p>{course.subtitle}</p>
                <footer>
                  <span>{course.deckCount} 份簡報</span>
                  <span>{course.videoCount} 部影片</span>
                  <span>
                    {course.updatedAt
                      ? new Date(course.updatedAt).toLocaleDateString("zh-TW")
                      : "尚未更新"}
                  </span>
                </footer>
              </Link>
            ))}
        </div>
      </section>
    </Shell>
  );
}

function CourseHome() {
  const { courseId = "" } = useParams();
  const [course, setCourse] = useState<CourseDetail | null>(null);
  const [alignment, setAlignment] = useState<Alignment | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [drop, setDrop] = useState(false);
  const [busy, setBusy] = useState(false);
  const [starting, setStarting] = useState(false);
  const [selectedDecks, setSelectedDecks] = useState<string[]>([]);
  const refresh = async () => {
    const [next, alignment] = await Promise.all([
      data.course(courseId),
      data.alignment(courseId),
    ]);
    setCourse(next);
    setAlignment(alignment);
  };
  useEffect(() => {
    data
      .course(courseId)
      .then((next) => {
        setCourse(next);
        setSelectedDecks(
          next.decks
            .filter(
              (deck) =>
                !deck.hidden && !next.info.hiddenDecks?.includes(deck.id),
            )
            .map((deck) => deck.id),
        );
      })
      .catch((error: Error) => toast.error(error.message));
    data
      .alignment(courseId)
      .then(setAlignment)
      .catch(() => null);
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
      toast.success(files?.length ? "檔案已匯入" : "掃描完成");
    } catch (error) {
      toast.error((error as Error).message);
    } finally {
      setBusy(false);
    }
  };
  if (!course) return <Loading />;
  const run = async () => {
    if (starting) return;
    setStarting(true);
    try {
      const { id } = await data.createJob(courseId, selectedDecks);
      setJob(null);
      setJobId(id);
    } catch (error) {
      toast.error((error as Error).message);
    } finally {
      setStarting(false);
    }
  };
  return (
    <Shell>
      <section className="page">
        <Link className="back" to="/">
          <ChevronLeft /> 所有課程
        </Link>
        <p className="eyebrow">COURSE OVERVIEW</p>
        <div className="title-row">
          <div>
            <h1>{course.info.title}</h1>
            <p>
              {course.info.subtitle} ·{" "}
              {typeof course.status === "string"
                ? course.status
                : `${course.decks.length} 份簡報、${course.videos.length} 部影片`}
            </p>
          </div>
          {data.editable && (
            <button
              className="button"
              onClick={run}
              disabled={
                starting ||
                (jobId !== null && !job) ||
                !selectedDecks.length ||
                job?.state === "running" ||
                job?.state === "queued"
              }
            >
              <Bot /> 開始生成
            </button>
          )}
        </div>
        {data.editable && (
          <section
            className={`import-zone ${drop ? "active" : ""}`}
            onDragOver={(event) => {
              event.preventDefault();
              setDrop(true);
            }}
            onDragLeave={() => setDrop(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDrop(false);
              const files = Array.from(event.dataTransfer.files);
              if (files.length) void importFiles(files);
            }}
          >
            <Upload />
            <div>
              <strong>拖放 pptx、pdf、mp4 或 zip 到這裡</strong>
              <p>也可以將檔案放進本機課程資料夾，再重新掃描。</p>
            </div>
            <label className="button quiet">
              {busy ? "處理中…" : "選擇檔案"}
              <input
                type="file"
                multiple
                accept=".pptx,.pdf,.mp4,.zip"
                disabled={busy}
                onChange={(event) => {
                  const files = Array.from(event.target.files ?? []);
                  if (files.length) void importFiles(files);
                  event.target.value = "";
                }}
                hidden
              />
            </label>
            <button
              className="button quiet"
              disabled={busy}
              onClick={() => void importFiles()}
            >
              重新掃描
            </button>
          </section>
        )}
        {job && <JobProgress job={job} />}
        {jobId && !job && <p>取得工作進度中…</p>}
        <div className="overview-grid">
          <section>
            <p className="eyebrow">DECKS</p>
            <div className="stack">
              {course.decks.map((deck) => (
                <article className="deck-row" key={deck.id}>
                  {data.editable && (
                    <input
                      type="checkbox"
                      aria-label={`生成 ${deck.title}`}
                      checked={selectedDecks.includes(deck.id)}
                      onChange={(event) =>
                        setSelectedDecks((old) =>
                          event.target.checked
                            ? [...old, deck.id]
                            : old.filter((id) => id !== deck.id),
                        )
                      }
                    />
                  )}
                  <div className="deck-preview">{deck.title.slice(0, 2)}</div>
                  <div>
                    <h3>{deck.title}</h3>
                    <p>{deck.slideCount ?? "—"} 頁</p>
                    <p className="muted">
                      對應{" "}
                      {course.videos.map((video) => video.title).join("、")}
                    </p>
                  </div>
                  <Link
                    className="button quiet"
                    to={`/c/${courseId}/d/${deck.id}/1`}
                  >
                    閱讀
                  </Link>
                </article>
              ))}
            </div>
          </section>
          <section>
            <p className="eyebrow">RECORDINGS</p>
            <div className="stack">
              {course.videos.map((video) => (
                <article className="video-row" key={video.id}>
                  <Play />
                  <div>
                    <h3>{video.title}</h3>
                    <p>
                      {time(video.duration)} · 轉錄狀態：
                      {video.transcriptStatus ?? "尚未提供"}
                    </p>
                  </div>
                </article>
              ))}
            </div>
          </section>
        </div>
        {alignment && (
          <AlignmentView alignment={alignment} courseId={courseId} />
        )}
      </section>
    </Shell>
  );
}

function JobProgress({ job }: { job: Job }) {
  return (
    <section className="job">
      <div>
        <span className="eyebrow">GENERATION JOB</span>
        <strong>{job.message}</strong>
      </div>
      <span>{Math.round(job.progress * 100)}%</span>
      <div className="progress">
        <i style={{ width: `${job.progress * 100}%` }} />
      </div>
      {job.steps.map((step) => (
        <p key={step.name}>
          {step.name} · {step.message}
        </p>
      ))}
    </section>
  );
}

function AlignmentView({
  alignment,
  courseId,
}: {
  alignment: Alignment;
  courseId: string;
}) {
  const [segments, setSegments] = useState(alignment.segments);
  useEffect(() => setSegments(alignment.segments), [alignment]);
  const edit = async (segment: Alignment["segments"][number]) => {
    const slide = Number(prompt("改成投影片頁碼", String(segment.slide ?? 1)));
    if (!Number.isInteger(slide) || slide < 1) return;
    try {
      await data.updateSegment(courseId, { ...segment, slide, manual: true });
      setSegments((all) =>
        all.map((item) =>
          item === segment ? { ...item, slide, manual: true } : item,
        ),
      );
    } catch (error) {
      toast.error((error as Error).message);
    }
  };
  return (
    <section className="alignment">
      <p className="eyebrow">ALIGNMENT</p>
      <h2>影片對齊</h2>
      <p>每個色塊代表影片時間內顯示的投影片；點擊可手動校正頁碼。</p>
      <div className="timeline-scroll">
        <div className="timeline">
          {segments.map((segment) => (
            <button
              title={`${time(segment.start)}–${time(segment.end)}`}
              disabled={!data.editable || !segment.deck}
              onClick={() => edit(segment)}
              key={`${segment.video}-${segment.start}-${segment.end}`}
              style={{ flex: Math.max(1, segment.end - segment.start) }}
            >
              {segment.video} / {segment.slide ?? "—"}
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}

function Reader() {
  const { courseId = "", deckId = "", slide: slideParam = "1" } = useParams();
  const navigate = useNavigate();
  const slideIndex = Number(slideParam);
  const [deck, setDeck] = useState<DeckDetail | null>(null);
  const [note, setNote] = useState<Note | null>(null);
  const [transcript, setTranscript] = useState<
    (Transcript & { video: string })[]
  >([]);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [course, setCourse] = useState<CourseDetail | null>(null);
  const [playerTime, setPlayerTime] = useState<VideoTime | null>(null);
  const [context, setContext] = useState<
    Pick<ChatContext, "region" | "selection">
  >({});
  const [saving, setSaving] = useState(false);
  const dirty = editing && !!note && draft !== note.markdown;
  const blocker = useBlocker(dirty || saving);
  useEffect(() => {
    if (!dirty && !saving) return;
    const unload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", unload);
    return () => window.removeEventListener("beforeunload", unload);
  }, [dirty, saving]);
  useEffect(() => {
    data
      .course(courseId)
      .then(setCourse)
      .catch((error: Error) => toast.error(error.message));
  }, [courseId]);
  const [agentOpen, setAgentOpen] = useState(data.editable);
  useEffect(() => {
    data
      .deck(courseId, deckId)
      .then(setDeck)
      .catch((error: Error) => toast.error(error.message));
  }, [courseId, deckId]);
  useEffect(() => {
    let active = true;
    setNote(null);
    setEditing(false);
    setContext({});
    setPlayerTime(null);
    setTranscript([]);
    data
      .note(courseId, deckId, slideIndex)
      .then((value) => {
        if (active) {
          setNote(value);
          setDraft(value.markdown);
        }
      })
      .catch((error: Error) => {
        if (active) toast.error(error.message);
      });
    return () => {
      active = false;
    };
  }, [courseId, deckId, slideIndex]);
  useEffect(() => {
    let active = true;
    const ranges =
      deck?.slides.find((item) => item.index === slideIndex)?.ranges ?? [];
    const videos = [...new Set(ranges.map((range) => range.video))];
    Promise.all(
      videos.map(async (video) => {
        const { segments } = await data.transcript(courseId, video);
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
      .then((parts) => {
        if (active) setTranscript(parts.flat());
      })
      .catch(() => {
        if (active) setTranscript([]);
      });
    return () => {
      active = false;
    };
  }, [courseId, deck, slideIndex]);
  useEffect(() => {
    const keyboard = (event: KeyboardEvent) => {
      if (blocker.state === "blocked") return;
      if (
        (event.ctrlKey || event.metaKey) &&
        event.key === "s" &&
        editing &&
        data.editable
      ) {
        event.preventDefault();
        void save();
        return;
      }
      const target = event.target as HTMLElement | null;
      if (
        target?.closest(
          "input, textarea, select, video, [contenteditable]:not([contenteditable='false'])",
        ) ||
        event.altKey ||
        event.ctrlKey ||
        event.metaKey ||
        event.shiftKey
      )
        return;
      if (["ArrowLeft", "ArrowRight"].includes(event.key))
        event.preventDefault();
      if (event.key === "ArrowLeft" && slideIndex > 1)
        navigate(`/c/${courseId}/d/${deckId}/${slideIndex - 1}`);
      if (event.key === "ArrowRight" && deck && slideIndex < deck.slides.length)
        navigate(`/c/${courseId}/d/${deckId}/${slideIndex + 1}`);
    };
    window.addEventListener("keydown", keyboard);
    return () => window.removeEventListener("keydown", keyboard);
  });
  const save = async () => {
    if (!editing || saving || !data.editable) return false;
    setSaving(true);
    try {
      const meta = await data.saveNote(courseId, deckId, slideIndex, draft);
      setNote((old) => (old ? { ...old, markdown: draft, meta } : old));
      setEditing(false);
      toast.success("筆記已儲存");
      return true;
    } catch (error) {
      toast.error((error as Error).message);
      return false;
    } finally {
      setSaving(false);
    }
  };
  if (!deck) return <Loading />;
  if (!deck.slides.length)
    return (
      <Shell>
        <div className="empty">這份簡報尚無投影片，請先完成轉檔。</div>
      </Shell>
    );
  const currentNote = note ?? emptyNote();
  const current =
    deck.slides.find((item) => item.index === slideIndex) ?? deck.slides[0];
  const go = (index: number) => navigate(`/c/${courseId}/d/${deckId}/${index}`);
  const playable = (video: string) =>
    videoSource(course, courseId, video, data.editable);
  const selectText = (source: "note" | "transcript") => {
    const text = window.getSelection()?.toString().trim();
    if (data.editable && text) {
      setContext({ selection: { text, source } });
      setAgentOpen(true);
    }
  };
  return (
    <Shell>
      {blocker.state === "blocked" && (
        <div className="dialog-backdrop">
          <section
            role="dialog"
            aria-modal="true"
            aria-label="尚未儲存的筆記"
            className="unsaved-dialog"
          >
            <h2>筆記尚未儲存</h2>
            <p>離開前要如何處理修改？</p>
            <button
              className="button"
              disabled={saving || !note}
              onClick={async () => {
                if (await save()) blocker.proceed();
              }}
            >
              儲存並離開
            </button>
            <button
              className="button quiet"
              disabled={saving || !note}
              onClick={() => blocker.proceed()}
            >
              放棄修改
            </button>
            <button className="button quiet" onClick={() => blocker.reset()}>
              繼續編輯
            </button>
          </section>
        </div>
      )}
      <section className={`reader ${agentOpen ? "agent-open" : ""}`}>
        <div className="slide-column">
          <div className="reader-heading">
            <Link to={`/c/${courseId}`}>
              <ChevronLeft /> {deck.deck.title}
            </Link>
            <span>
              {slideIndex} / {deck.slides.length}
            </span>
          </div>
          <SlideCanvas
            slide={current}
            selectable={data.editable}
            key={`${deckId}-${slideIndex}`}
            onRegion={(region) => {
              setContext({ region });
              setAgentOpen(true);
            }}
          />
          <div className="thumbnails">
            {deck.slides.map((item) => (
              <button
                className={item.index === slideIndex ? "selected" : ""}
                onClick={() => go(item.index)}
                key={item.index}
              >
                {item.thumb && (
                  <img src={item.thumb} alt={item.title} loading="lazy" />
                )}
                <span>{item.index}</span>
                <small>{item.title}</small>
              </button>
            ))}
          </div>
          <div className="slide-nav">
            <button
              className="button quiet"
              disabled={slideIndex <= 1}
              onClick={() => go(slideIndex - 1)}
            >
              <ChevronLeft /> 上一頁
            </button>
            <button
              className="button quiet"
              disabled={slideIndex >= deck.slides.length}
              onClick={() => go(slideIndex + 1)}
            >
              下一頁 <ChevronRight />
            </button>
          </div>
        </div>
        <aside className="note-column">
          <div className="note-header">
            <div>
              <p className="eyebrow">
                SLIDE {String(slideIndex).padStart(2, "0")}
              </p>
              <h2>{current.title}</h2>
            </div>
            <span className={`status ${currentNote.meta.status}`}>
              {statusLabel[currentNote.meta.status]}
            </span>
          </div>
          <div className="note-tools">
            {data.editable && (
              <button
                className="button quiet"
                disabled={saving || !note}
                onClick={() => (editing ? void save() : setEditing(true))}
              >
                <Pencil /> {editing ? "儲存" : "編輯"}
              </button>
            )}{" "}
            {editing && (
              <button
                className="icon-button"
                onClick={() => {
                  if (dirty && !confirm("放棄尚未儲存的修改？")) return;
                  setDraft(currentNote.markdown);
                  setEditing(false);
                }}
                disabled={saving}
                aria-label="取消編輯"
              >
                <X />
              </button>
            )}
          </div>
          {!note ? (
            <Loading />
          ) : editing ? (
            <textarea
              className="editor"
              disabled={saving}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
            />
          ) : (
            <div onMouseUp={() => selectText("note")}>
              <Markdown
                markdown={currentNote.markdown}
                onTime={setPlayerTime}
                canPlay={(video) => !!playable(video)}
              />
            </div>
          )}
          <section className="sources">
            <p className="eyebrow">VIDEO RANGES</p>
            {current.ranges.map((range) => (
              <button
                disabled={!playable(range.video)}
                onClick={() =>
                  setPlayerTime({ video: range.video, time: range.start })
                }
                key={`${range.video}-${range.start}`}
              >
                {range.video} · {time(range.start)}–{time(range.end)}
              </button>
            ))}
          </section>
          {currentNote.review && (
            <details className="review" open>
              <summary>審稿意見</summary>
              <p>
                {typeof currentNote.review === "string"
                  ? currentNote.review
                  : JSON.stringify(currentNote.review, null, 2)}
              </p>
            </details>
          )}
          <section
            className="transcript"
            onMouseUp={() => selectText("transcript")}
          >
            <p className="eyebrow">TRANSCRIPT</p>
            {transcript.map((part) => (
              <button
                key={`${part.video}-${part.start}-${part.text}`}
                disabled={!playable(part.video)}
                onClick={() => {
                  if (!window.getSelection()?.toString())
                    setPlayerTime({ video: part.video, time: part.start });
                }}
              >
                <time>{time(part.start)}</time>
                {part.text}
              </button>
            ))}
          </section>
        </aside>
        {data.editable && agentOpen && (
          <AgentPanel
            key={courseId}
            data={data}
            courseId={courseId}
            label={`目前在：${deck.deck.title} 第 ${slideIndex} 頁`}
            context={{ deck: deckId, slide: slideIndex, ...context }}
            onClearContext={() => setContext({})}
            onTime={setPlayerTime}
            canPlay={(video) => !!playable(video)}
          />
        )}
        {data.editable && (
          <button
            className="agent-toggle"
            onClick={() => setAgentOpen(!agentOpen)}
            aria-label="切換 Agent 面板"
          >
            {agentOpen ? <PanelRightClose /> : <Bot />}
          </button>
        )}
        {playerTime && playable(playerTime.video) && (
          <VideoPlayer
            captions={transcript.filter(
              (part) => part.video === playerTime.video,
            )}
            target={playerTime}
            src={playable(playerTime.video) ?? ""}
            onClose={() => setPlayerTime(null)}
          />
        )}
      </section>
    </Shell>
  );
}

export function App() {
  return (
    <Routes>
      <Route path="/" element={<Courses />} />
      <Route path="/c/:courseId" element={<CourseHome />} />
      <Route path="/c/:courseId/d/:deckId/:slide" element={<Reader />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
