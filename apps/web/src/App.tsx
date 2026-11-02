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
  Send,
  Sun,
  Upload,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import {
  Link,
  Navigate,
  Route,
  Routes,
  useNavigate,
  useParams,
} from "react-router-dom";
import rehypeKatex from "rehype-katex";
import rehypeRaw from "rehype-raw";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { toast } from "sonner";
import { adapter } from "./lib/adapter";
import type {
  Alignment,
  Course,
  CourseDetail,
  DeckDetail,
  Job,
  Note,
  Slide,
  Transcript,
} from "./lib/types";

const data = adapter();
const time = (seconds: number) =>
  `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
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
            <button className="button">
              <FilePlus2 /> 新增課程
            </button>
          )}
        </div>
        <label className="search">
          <Search />
          <input placeholder="搜尋課程、簡報或筆記" />
        </label>
        <div className="course-grid">
          {courses.map((course) => (
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
                  {new Date(course.updatedAt).toLocaleDateString("zh-TW")}
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
  const [drop, setDrop] = useState(false);
  useEffect(() => {
    data
      .course(courseId)
      .then(setCourse)
      .catch((error: Error) => toast.error(error.message));
    data
      .alignment(courseId)
      .then(setAlignment)
      .catch(() => null);
  }, [courseId]);
  useEffect(() => {
    if (!job || !data.editable || !window.EventSource) return;
    const events = new EventSource("/api/events");
    events.addEventListener("job", (event) => {
      const next = JSON.parse((event as MessageEvent).data) as Job;
      if (next.id === job.id) setJob(next);
    });
    return () => events.close();
  }, [job]);
  if (!course) return <Loading />;
  const run = async () => {
    try {
      setJob(
        await data.createJob(
          courseId,
          course.decks.filter((deck) => !deck.hidden).map((deck) => deck.id),
        ),
      );
    } catch (error) {
      toast.error((error as Error).message);
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
              {course.info.subtitle} · {course.status}
            </p>
          </div>
          {data.editable && (
            <button className="button" onClick={run}>
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
              toast.success(
                `已準備匯入 ${event.dataTransfer.files.length} 個檔案`,
              );
            }}
          >
            <Upload />
            <div>
              <strong>拖放 pptx、pdf、mp4 或 zip 到這裡</strong>
              <p>也可以將檔案放進本機課程資料夾，再重新掃描。</p>
            </div>
            <button className="button quiet">重新掃描</button>
          </section>
        )}
        {job && <JobProgress job={job} />}
        <div className="overview-grid">
          <section>
            <p className="eyebrow">DECKS</p>
            <div className="stack">
              {course.decks.map((deck) => (
                <article className="deck-row" key={deck.id}>
                  <div className="deck-preview">{deck.title.slice(0, 2)}</div>
                  <div>
                    <h3>{deck.title}</h3>
                    <p>{deck.slideCount} 頁 · 筆記生成中</p>
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
                      {time(video.duration)} · 轉錄{video.transcriptStatus}
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
      <div className="timeline">
        {segments.map((segment) => (
          <button
            title={`${time(segment.start)}–${time(segment.end)}`}
            onClick={() => edit(segment)}
            key={`${segment.video}-${segment.start}-${segment.end}`}
            style={{ flex: Math.max(1, segment.end - segment.start) }}
          >
            L1 / {segment.slide ?? "—"}
          </button>
        ))}
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
  const [transcript, setTranscript] = useState<Transcript[]>([]);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [playerTime, setPlayerTime] = useState<number | null>(null);
  const [agentOpen, setAgentOpen] = useState(data.editable);
  useEffect(() => {
    data
      .deck(courseId, deckId)
      .then(setDeck)
      .catch((error: Error) => toast.error(error.message));
  }, [courseId, deckId]);
  useEffect(() => {
    data
      .note(courseId, deckId, slideIndex)
      .then((value) => {
        setNote(value);
        setDraft(value.markdown);
      })
      .catch((error: Error) => toast.error(error.message));
  }, [courseId, deckId, slideIndex]);
  useEffect(() => {
    if (!deck) return;
    const current = deck.slides.find((item) => item.index === slideIndex);
    const video = current?.ranges[0]?.video;
    if (video)
      data
        .transcript(courseId, video)
        .then(({ segments }) => setTranscript(segments))
        .catch(() => setTranscript([]));
  }, [courseId, deck, slideIndex]);
  useEffect(() => {
    const keyboard = (event: KeyboardEvent) => {
      if (event.key === "ArrowLeft" && slideIndex > 1)
        navigate(`/c/${courseId}/d/${deckId}/${slideIndex - 1}`);
      if (event.key === "ArrowRight" && deck && slideIndex < deck.slides.length)
        navigate(`/c/${courseId}/d/${deckId}/${slideIndex + 1}`);
      if ((event.ctrlKey || event.metaKey) && event.key === "s") {
        event.preventDefault();
        void save();
      }
    };
    window.addEventListener("keydown", keyboard);
    return () => window.removeEventListener("keydown", keyboard);
  });
  const save = async () => {
    try {
      const meta = await data.saveNote(courseId, deckId, slideIndex, draft);
      setNote((old) => (old ? { ...old, markdown: draft, meta } : old));
      setEditing(false);
      toast.success("筆記已儲存");
    } catch (error) {
      toast.error((error as Error).message);
    }
  };
  if (!deck || !note) return <Loading />;
  const current =
    deck.slides.find((item) => item.index === slideIndex) ?? deck.slides[0];
  const go = (index: number) => navigate(`/c/${courseId}/d/${deckId}/${index}`);
  return (
    <Shell>
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
            onRegion={() =>
              toast("已帶入投影片圈選範圍", {
                description: "可在 Agent 面板繼續提問。",
              })
            }
          />
          <div className="thumbnails">
            {deck.slides.map((item) => (
              <button
                className={item.index === slideIndex ? "selected" : ""}
                onClick={() => go(item.index)}
                key={item.index}
              >
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
            <span className={`status ${note.meta.status}`}>
              {statusLabel[note.meta.status]}
            </span>
          </div>
          <div className="note-tools">
            {data.editable && (
              <button
                className="button quiet"
                onClick={() => (editing ? void save() : setEditing(true))}
              >
                <Pencil /> {editing ? "儲存" : "編輯"}
              </button>
            )}{" "}
            {editing && (
              <button
                className="icon-button"
                onClick={() => {
                  setDraft(note.markdown);
                  setEditing(false);
                }}
                aria-label="取消編輯"
              >
                <X />
              </button>
            )}
          </div>
          {editing ? (
            <textarea
              className="editor"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
            />
          ) : (
            <Markdown markdown={note.markdown} onTime={setPlayerTime} />
          )}
          <section className="sources">
            <p className="eyebrow">VIDEO RANGES</p>
            {current.ranges.map((range) => (
              <button
                onClick={() => setPlayerTime(range.start)}
                key={`${range.video}-${range.start}`}
              >
                {range.video} · {time(range.start)}–{time(range.end)}
              </button>
            ))}
          </section>
          {note.review && (
            <details className="review" open>
              <summary>審稿意見</summary>
              <p>{note.review}</p>
            </details>
          )}
          <section className="transcript">
            <p className="eyebrow">TRANSCRIPT</p>
            {transcript.map((part) => (
              <button
                key={`${part.start}-${part.text}`}
                onClick={() => setPlayerTime(part.start)}
              >
                <time>{time(part.start)}</time>
                {part.text}
              </button>
            ))}
          </section>
        </aside>
        {data.editable && agentOpen && (
          <AgentPanel
            context={`目前在：${deck.deck.title} 第 ${slideIndex} 頁`}
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
        {playerTime !== null && (
          <VideoPlayer time={playerTime} onClose={() => setPlayerTime(null)} />
        )}
      </section>
    </Shell>
  );
}

function SlideCanvas({
  slide,
  onRegion,
}: {
  slide: Slide;
  onRegion: () => void;
}) {
  const [origin, setOrigin] = useState<{ x: number; y: number } | null>(null);
  const [region, setRegion] = useState<{
    x: number;
    y: number;
    w: number;
    h: number;
  } | null>(null);
  const point = (event: React.PointerEvent) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    return {
      x: ((event.clientX - bounds.left) / bounds.width) * 100,
      y: ((event.clientY - bounds.top) / bounds.height) * 100,
    };
  };
  return (
    <div
      className="slide-canvas"
      onPointerDown={(event) => {
        event.currentTarget.setPointerCapture(event.pointerId);
        setOrigin(point(event));
        setRegion(null);
      }}
      onPointerMove={(event) => {
        if (!origin) return;
        const next = point(event);
        setRegion({
          x: Math.min(origin.x, next.x),
          y: Math.min(origin.y, next.y),
          w: Math.abs(next.x - origin.x),
          h: Math.abs(next.y - origin.y),
        });
      }}
      onPointerUp={() => {
        if (region && region.w > 3 && region.h > 3) onRegion();
        setOrigin(null);
      }}
    >
      <div className="slide-content">
        <p className="eyebrow">OPERATING SYSTEMS · L1</p>
        <h1>{slide.title}</h1>
        <p>{slide.text}</p>
        <div className="slide-diagram">
          <span>使用者</span>
          <i>應用程式</i>
          <b>作業系統</b>
          <i>硬體</i>
        </div>
        <small>拖曳圈選區域後可詢問 Agent</small>
      </div>
      {region && (
        <i
          className="selection"
          style={{
            left: `${region.x}%`,
            top: `${region.y}%`,
            width: `${region.w}%`,
            height: `${region.h}%`,
          }}
        />
      )}
    </div>
  );
}

type HtmlNode = {
  type: string;
  tagName?: string;
  properties?: Record<string, unknown>;
  children?: HtmlNode[];
};

const safeTags = new Set([
  "a",
  "blockquote",
  "br",
  "code",
  "del",
  "details",
  "em",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "hr",
  "li",
  "ol",
  "p",
  "pre",
  "strong",
  "summary",
  "table",
  "tbody",
  "td",
  "th",
  "thead",
  "tr",
  "ul",
]);
const removeWithChildren = new Set(["iframe", "script", "style", "svg"]);

const sanitizeNoteHtml = () => (tree: HtmlNode) => {
  const clean = (node: HtmlNode): HtmlNode[] => {
    if (node.type === "comment") return [];
    if (node.children) node.children = node.children.flatMap(clean);
    if (node.type !== "element") return [node];
    if (removeWithChildren.has(node.tagName ?? "")) return [];
    if (!safeTags.has(node.tagName ?? "")) return node.children ?? [];
    if (node.tagName === "a" && typeof node.properties?.href === "string") {
      const href = node.properties.href;
      node.properties = /^(https?:|mailto:|video:|#|\/)/i.test(href)
        ? { href }
        : {};
    } else {
      node.properties = {};
    }
    return [node];
  };
  tree.children = tree.children?.flatMap(clean);
};

function Markdown({
  markdown,
  onTime,
}: {
  markdown: string;
  onTime: (time: number) => void;
}) {
  return (
    <div className="markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeRaw, sanitizeNoteHtml, rehypeKatex]}
        components={{
          a: ({ href, children }) => {
            const found = href?.match(/^video:([^?]+)\?t=(\d+(?:\.\d+)?)$/);
            return found ? (
              <button
                className="timestamp"
                onClick={() => onTime(Number(found[2]))}
              >
                {children}
              </button>
            ) : (
              <a href={href}>{children}</a>
            );
          },
        }}
      >
        {markdown}
      </ReactMarkdown>
    </div>
  );
}

function AgentPanel({ context }: { context: string }) {
  const [message, setMessage] = useState("");
  const [mode, setMode] = useState("qa");
  const [messages, setMessages] = useState<string[]>([]);
  const send = () => {
    if (!message.trim()) return;
    setMessages((all) => [
      ...all,
      `你：${message}`,
      "Agent：我會根據這一頁的投影片、筆記與逐字稿來回答。開發預覽模式未連接模型。",
    ]);
    setMessage("");
  };
  return (
    <aside className="agent">
      <div className="agent-head">
        <div>
          <p className="eyebrow">STUDY AGENT</p>
          <strong>本機 Agent</strong>
        </div>
        <span className="online">已登入</span>
      </div>
      <p className="context">{context}</p>
      <div className="modes">
        {[
          ["qa", "問答"],
          ["interview", "口試"],
          ["review", "審稿"],
        ].map(([id, label]) => (
          <button
            key={id}
            className={mode === id ? "active" : ""}
            onClick={() => setMode(id)}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="messages">
        {messages.length ? (
          messages.map((item, index) => <p key={index}>{item}</p>)
        ) : (
          <p>圈選投影片、筆記或逐字稿文字，讓我以目前頁面為脈絡協助你複習。</p>
        )}
      </div>
      <div className="chat-input">
        <textarea
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          placeholder="問這一頁的概念…"
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              send();
            }
          }}
        />
        <button className="icon-button" onClick={send} aria-label="傳送">
          <Send />
        </button>
      </div>
    </aside>
  );
}

function VideoPlayer({
  time: at,
  onClose,
}: {
  time: number;
  onClose: () => void;
}) {
  return (
    <aside className="player">
      <button className="icon-button" onClick={onClose} aria-label="關閉播放器">
        <X />
      </button>
      <div>
        <Play fill="currentColor" />
        <p>影片播放器</p>
        <strong>跳至 {time(at)}</strong>
      </div>
    </aside>
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
