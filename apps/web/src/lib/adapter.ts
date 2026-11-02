import type {
  Account,
  Alignment,
  Course,
  CourseDetail,
  DeckDetail,
  Job,
  Note,
  Slide,
  Transcript,
} from "./types";

export type DataAdapter = {
  readonly editable: boolean;
  courses(): Promise<Course[]>;
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
  createJob(courseId: string, decks: string[]): Promise<Job>;
  accounts(): Promise<Account[]>;
};

const call = async <T>(path: string, init?: RequestInit): Promise<T> => {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok)
    throw new Error(
      (await response.json().catch(() => null))?.detail || "讀取資料失敗",
    );
  return response.json() as Promise<T>;
};

const pathSegment = (value: string) => encodeURIComponent(value);

const local: DataAdapter = {
  editable: true,
  courses: () => call("/api/courses"),
  course: (c) => call(`/api/courses/${pathSegment(c)}`),
  deck: (c, d) =>
    call(`/api/courses/${pathSegment(c)}/decks/${pathSegment(d)}`),
  note: (c, d, i) =>
    call(`/api/courses/${pathSegment(c)}/decks/${pathSegment(d)}/notes/${i}`),
  saveNote: (c, d, i, markdown) =>
    call(`/api/courses/${pathSegment(c)}/decks/${pathSegment(d)}/notes/${i}`, {
      method: "PUT",
      body: JSON.stringify({ markdown }),
    }),
  transcript: (c, v) =>
    call(`/api/courses/${pathSegment(c)}/videos/${pathSegment(v)}/transcript`),
  alignment: (c) => call(`/api/courses/${pathSegment(c)}/alignment`),
  updateSegment: (c, segment) =>
    call(`/api/courses/${pathSegment(c)}/alignment/segments`, {
      method: "PUT",
      body: JSON.stringify(segment),
    }),
  createJob: async (c, decks) => {
    const { id } = await call<{ id: string }>(
      `/api/courses/${pathSegment(c)}/jobs`,
      {
        method: "POST",
        body: JSON.stringify({ kind: "pipeline", decks }),
      },
    );
    return {
      id,
      course: c,
      kind: "pipeline",
      state: "queued",
      progress: 0,
      message: "等待開始",
      steps: [],
    };
  },
  accounts: () => call("/api/agents/accounts"),
};

const staticAdapter: DataAdapter = {
  editable: false,
  courses: () => call("/data/courses.json"),
  course: (c) => call(`/data/${pathSegment(c)}/course.json`),
  deck: (c, d) => call(`/data/${pathSegment(c)}/decks/${pathSegment(d)}.json`),
  note: async (c, d, i) => {
    const deck = await call<{ slides: { index: number; note: Note | null }[] }>(
      `/data/${pathSegment(c)}/decks/${pathSegment(d)}.json`,
    );
    return (
      deck.slides.find((slide) => slide.index === i)?.note ?? {
        markdown: "尚無筆記",
        meta: { status: "skipped" },
        review: null,
      }
    );
  },
  saveNote: async () => {
    throw new Error("靜態閱讀模式無法編輯筆記");
  },
  transcript: (c, v) =>
    call(`/data/${pathSegment(c)}/transcripts/${pathSegment(v)}.json`),
  alignment: async () => ({ videos: {}, segments: [] }),
  updateSegment: async () => {
    throw new Error("靜態閱讀模式無法修改對齊");
  },
  createJob: async () => {
    throw new Error("靜態閱讀模式無法生成");
  },
  accounts: async () => [],
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
  editable: true,
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
  createJob: async (course, decks) => ({
    id: crypto.randomUUID(),
    course,
    kind: "pipeline",
    state: "queued",
    progress: 0,
    message: `準備生成 ${decks.length} 份簡報`,
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
  return import.meta.env.VITE_MARGINALIA_MOCK === "true" ? mock : local;
};
