import { readEventStream } from "./events";
import type {
  Account,
  Alignment,
  Chat,
  ChatEvent,
  ChatRequest,
  ChatSummary,
  Course,
  CourseDetail,
  DeckDetail,
  Job,
  Note,
  Slide,
  StaticDeck,
  Transcript,
} from "./types";

export type DataAdapter = {
  readonly editable: boolean;
  readonly mode: "local" | "static" | "mock";
  courses(): Promise<Course[]>;
  createCourse(title: string): Promise<unknown>;
  course(courseId: string): Promise<CourseDetail>;
  deck(courseId: string, deckId: string): Promise<DeckDetail>;
  note(courseId: string, deckId: string, slide: number): Promise<Note>;
  saveNote(
    courseId: string,
    deckId: string,
    slide: number,
    markdown: string,
  ): Promise<Note["meta"]>;
  transcript(
    courseId: string,
    videoId: string,
  ): Promise<{ segments: Transcript[]; partial: boolean }>;
  alignment(courseId: string): Promise<Alignment>;
  updateSegment(
    courseId: string,
    segment: Alignment["segments"][number],
  ): Promise<Alignment>;
  upload(courseId: string, files: File[]): Promise<unknown>;
  /** Saves an image into notes/<deck>/assets/ and returns the markdown path (`assets/<name>`). */
  uploadAsset(
    courseId: string,
    deckId: string,
    file: File,
    signal?: AbortSignal,
  ): Promise<string>;
  scan(courseId: string): Promise<unknown>;
  createJob(courseId: string, decks: string[]): Promise<{ id: string }>;
  job(id: string): Promise<Job>;
  accounts(): Promise<Account[]>;
  chat(
    request: ChatRequest,
    onEvent: (event: ChatEvent) => void,
    signal: AbortSignal,
  ): Promise<void>;
  chats(courseId: string): Promise<ChatSummary[]>;
  conversation(courseId: string, chatId: string): Promise<Chat>;
};

const call = async <T>(path: string, init?: RequestInit): Promise<T> => {
  const response = await fetch(path, {
    ...init,
    headers:
      init?.body instanceof FormData
        ? undefined
        : { "Content-Type": "application/json" },
  });
  if (!response.ok)
    throw new Error(
      (await response.json().catch(() => null))?.detail || "讀取資料失敗",
    );
  return response.json() as Promise<T>;
};
const pathSegment = (value: string) => encodeURIComponent(value);
const coursePath = (c: string) => `/api/courses/${pathSegment(c)}`;
const notePath = (c: string, d: string, i: number) =>
  `${coursePath(c)}/decks/${pathSegment(d)}/notes/${i}`;
const readOnly = async (): Promise<never> => {
  throw new Error("靜態閱讀模式無法修改資料");
};
export const emptyNote = (): Note => ({
  markdown: "",
  meta: { status: "skipped" },
  review: null,
});

const local: DataAdapter = {
  editable: true,
  mode: "local",
  courses: () => call("/api/courses"),
  createCourse: (title) =>
    call("/api/courses", { method: "POST", body: JSON.stringify({ title }) }),
  course: (c) => call(coursePath(c)),
  deck: (c, d) => call(`${coursePath(c)}/decks/${pathSegment(d)}`),
  note: async (c, d, i) => {
    const response = await fetch(notePath(c, d, i));
    if (response.status === 404) return emptyNote();
    if (!response.ok) throw new Error("讀取筆記失敗");
    return response.json();
  },
  saveNote: async (c, d, i, markdown) => {
    const { meta } = await call<{ meta: Note["meta"] }>(notePath(c, d, i), {
      method: "PUT",
      body: JSON.stringify({ markdown }),
    });
    return meta;
  },
  transcript: (c, v) =>
    call(`${coursePath(c)}/videos/${pathSegment(v)}/transcript`),
  alignment: (c) => call(`${coursePath(c)}/alignment`),
  updateSegment: (c, segment) =>
    call(`${coursePath(c)}/alignment/segments`, {
      method: "PUT",
      body: JSON.stringify(segment),
    }),
  upload: async (c, files) => {
    const body = new FormData();
    for (const file of files) body.append("files[]", file);
    let response = await fetch(`${coursePath(c)}/upload`, {
      method: "POST",
      body,
    });
    if (response.status === 422) {
      const error = await response
        .clone()
        .json()
        .catch(() => null);
      // PR #4 originally names the multipart field `files`; retry only pre-write validation failures.
      if (
        Array.isArray(error?.detail) &&
        error.detail.some(
          (item: { type?: string; loc?: string[] }) =>
            item.type === "missing" && item.loc?.join(".") === "body.files",
        )
      ) {
        const legacy = new FormData();
        for (const file of files) legacy.append("files", file);
        response = await fetch(`${coursePath(c)}/upload`, {
          method: "POST",
          body: legacy,
        });
      }
    }
    if (!response.ok) throw new Error("匯入檔案失敗，請確認檔案格式並重試");
    return response.json();
  },
  uploadAsset: async (c, d, file, signal) => {
    const body = new FormData();
    body.append("file", file);
    const { path } = await call<{ path: string }>(
      `${coursePath(c)}/decks/${pathSegment(d)}/assets`,
      { method: "POST", body, signal },
    );
    return path;
  },
  scan: (c) => call(`${coursePath(c)}/scan`, { method: "POST" }),
  createJob: (c, decks) =>
    call(`${coursePath(c)}/jobs`, {
      method: "POST",
      body: JSON.stringify({ kind: "pipeline", decks }),
    }),
  job: (id) => call(`/api/jobs/${pathSegment(id)}`),
  accounts: () => call("/api/agents/accounts"),
  chat: async (request, onEvent, signal) => {
    const response = await fetch("/api/agents/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal,
    });
    if (!response.ok)
      throw new Error(
        (await response.json().catch(() => null))?.detail || "無法連上助教",
      );
    await readEventStream(response, onEvent);
  },
  chats: (c) => call(`${coursePath(c)}/chats`),
  conversation: (c, id) => call(`${coursePath(c)}/chats/${pathSegment(id)}`),
};

// The static deck file holds every slide's note; fetch it once per deck, not once per slide.
const staticDecks = new Map<string, Promise<StaticDeck>>();
const staticDeck = (url: string) => {
  let deck = staticDecks.get(url);
  if (!deck) {
    deck = call<StaticDeck>(url);
    staticDecks.set(url, deck);
    deck.catch(() => staticDecks.delete(url));
  }
  return deck;
};

const staticAdapter: DataAdapter = {
  ...local,
  editable: false,
  mode: "static",
  courses: () => call("/data/courses.json"),
  course: (c) => call(`/data/${pathSegment(c)}/course.json`),
  deck: (c, d) =>
    staticDeck(`/data/${pathSegment(c)}/decks/${pathSegment(d)}.json`),
  note: async (c, d, i) => {
    const deck = await staticDeck(
      `/data/${pathSegment(c)}/decks/${pathSegment(d)}.json`,
    );
    const note = deck.notes?.[i];
    if (!note) return emptyNote();
    return {
      markdown: note.markdown,
      meta: note.meta ??
        deck.slides.find((slide) => slide.index === i)?.note ?? {
          status: "skipped",
        },
      review: note.review ?? null,
    };
  },
  transcript: (c, v) =>
    call(`/data/${pathSegment(c)}/transcripts/${pathSegment(v)}.json`),
  alignment: async () => ({ videos: {}, segments: [] }),
  createCourse: readOnly,
  saveNote: readOnly,
  updateSegment: readOnly,
  upload: readOnly,
  uploadAsset: readOnly,
  scan: readOnly,
  createJob: readOnly,
  job: readOnly,
  chat: readOnly,
  accounts: async () => [],
  chats: async () => [],
  conversation: readOnly,
};

const mockCourse: Course = {
  id: "operating-system",
  title: "作業系統",
  subtitle: "Operating Systems · 2026 秋季",
  deckCount: 2,
  videoCount: 1,
  updatedAt: "2026-11-03T10:00:00+08:00",
};
const mockDeck = {
  id: "l1-operating-systems",
  title: "L1 · Operating Systems",
  slideCount: 12,
};
const mockSlides: Slide[] = Array.from({ length: 12 }, (_, index) => ({
  index: index + 1,
  title: [
    "課程導論",
    "什麼是作業系統？",
    "作業系統的角色",
    "使用者與硬體",
    "核心服務",
    "資源管理",
    "系統呼叫",
    "作業系統架構",
    "程序概念",
    "記憶體管理",
    "檔案系統",
    "本週小結",
  ][index],
  text: "作業系統是使用者與硬體之間的中介層。",
  ranges: [{ video: "os20260916", start: index * 75, end: index * 75 + 65 }],
  note: {
    status: index % 4 === 0 ? "reviewed" : "generated",
    updatedAt: "2026-11-03T10:00:00+08:00",
  },
}));
const mock: DataAdapter = {
  ...local,
  editable: true,
  mode: "mock",
  createCourse: async () => ({}),
  upload: async () => ({ saved: [], manifest: { decks: [], videos: [] } }),
  uploadAsset: async (_c, _d, file) => `assets/${file.name}`,
  scan: async () => ({ decks: [], videos: [] }),
  chats: async () => [],
  chat: async (_request, onEvent) => {
    onEvent({ type: "start", chatId: "mock" });
    onEvent({ type: "text", delta: "模擬模式：這是示範回覆。" });
    onEvent({ type: "done", chatId: "mock" });
  },
  courses: async () => [mockCourse],
  course: async () => ({
    info: mockCourse,
    decks: [
      mockDeck,
      { id: "l2-processes", title: "L2 · Processes", slideCount: 18 },
    ],
    videos: [
      {
        id: "os20260916",
        title: "第一週課程錄影",
        duration: 920,
        transcriptStatus: "完成",
      },
    ],
    status: "已生成 12 / 30 頁筆記",
  }),
  deck: async () => ({ deck: mockDeck, slides: mockSlides }),
  note: async (_c, _d, i) => ({
    markdown: `# ${mockSlides[i - 1]?.title ?? "筆記"}\n\n作業系統是管理電腦資源、提供服務的**中介層**。老師以櫃檯為例，說明應用程式不需直接處理硬體。\n\n> 可回看 [${String(Math.floor(((i - 1) * 75) / 60)).padStart(2, "0")}:${String((i - 1) * 15).padStart(2, "0")}](video:os20260916?t=${(i - 1) * 75})\n\n## 重點\n\n- 抽象化硬體細節\n- 協調 CPU、記憶體與 I/O\n- 提供受保護的系統呼叫\n\n\`\`\`c\nint main(void) { return 0; }\n\`\`\`\n\n$$\nT = T_{cpu} + T_{io}\n$$`,
    meta: { status: "generated", updatedAt: "2026-11-03T10:00:00+08:00" },
    review: i === 3 ? "建議補充 kernel mode 與 user mode 的差別。" : null,
  }),
  saveNote: async () => ({
    status: "edited",
    updatedAt: new Date().toISOString(),
  }),
  transcript: async () => ({
    segments: Array.from({ length: 8 }, (_, i) => ({
      start: i * 12,
      end: i * 12 + 10,
      text: [
        "今天先說明作業系統的角色。",
        "它是應用程式和硬體中間的一層。",
        "我們會從資源管理開始看。",
        "接著是程序與記憶體。",
      ][i % 4],
    })),
    partial: false,
  }),
  alignment: async () => ({
    videos: { os20260916: {} },
    segments: mockSlides.map((slide) => ({
      video: "os20260916",
      start: (slide.index - 1) * 75,
      end: slide.index * 75 - 10,
      deck: mockDeck.id,
      slide: slide.index,
      score: 0.8,
    })),
  }),
  updateSegment: async (_c, segment) => ({
    videos: { os20260916: {} },
    segments: [segment],
  }),
  createJob: async () => ({ id: "mock-job" }),
  job: async (id) => ({
    id,
    course: mockCourse.id,
    kind: "pipeline",
    state: "done",
    progress: 1,
    message: "模擬工作完成",
    steps: [],
  }),
  accounts: async () => [
    {
      id: "claude",
      provider: "claude",
      label: "Claude Code",
      loggedIn: true,
      models: [{ id: "sonnet", label: "Sonnet" }],
      efforts: ["low", "medium", "high"],
    },
  ],
};

export const adapter = (): DataAdapter => {
  if (import.meta.env.VITE_MARGINALIA_MODE === "static") return staticAdapter;
  return import.meta.env.VITE_MARGINALIA_MODE === "mock" ? mock : local;
};
