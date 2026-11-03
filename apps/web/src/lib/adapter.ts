import { siteUrl } from "./assets";
import { readEventStream } from "./events";
import { gradeObjective, totals } from "./exam-grade";
import type {
  Attempt,
  AttemptSummary,
  ExamDetail,
  ExamInfo,
  ExamSummary,
  ExamUpload,
  Grading,
  Quiz,
  Section,
  SectionMeta,
  StaticExam,
} from "./exam-types";
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
  // Exam prep (docs/architecture.md, Exam prep)
  exams(courseId: string): Promise<ExamSummary[]>;
  createExam(courseId: string, title: string): Promise<ExamInfo>;
  exam(courseId: string, examId: string): Promise<ExamDetail>;
  updateExam(
    courseId: string,
    examId: string,
    patch: Partial<Pick<ExamInfo, "title" | "scope" | "options">>,
  ): Promise<ExamInfo>;
  uploadExamFiles(
    courseId: string,
    examId: string,
    files: File[],
  ): Promise<ExamUpload[]>;
  uploadExamText(
    courseId: string,
    examId: string,
    text: string,
  ): Promise<ExamUpload>;
  deleteExamUpload(
    courseId: string,
    examId: string,
    name: string,
  ): Promise<ExamUpload[]>;
  handout(courseId: string, examId: string): Promise<Section[]>;
  saveSection(
    courseId: string,
    examId: string,
    section: number,
    markdown: string,
  ): Promise<SectionMeta>;
  uploadExamAsset(
    courseId: string,
    examId: string,
    file: File,
    signal?: AbortSignal,
  ): Promise<string>;
  quiz(courseId: string, examId: string): Promise<Quiz | null>;
  /** Submitted attempts, newest first, as summaries; `attempt` loads one in full. */
  attempts(courseId: string, examId: string): Promise<AttemptSummary[]>;
  attempt(
    courseId: string,
    examId: string,
    attemptId: string,
  ): Promise<Attempt>;
  submitAttempt(
    courseId: string,
    examId: string,
    quiz: Quiz,
    body: Pick<Attempt, "answers" | "startedAt" | "durationSec">,
  ): Promise<Attempt>;
  gradeAnswer(
    courseId: string,
    examId: string,
    attemptId: string,
    body: {
      question: string;
      answer: string;
      account: string;
      model?: string;
      effort?: string;
    },
  ): Promise<{ grading: Grading; attempt: Attempt }>;
  createExamJob(
    courseId: string,
    examId: string,
    parts: ("handout" | "quiz")[],
    agent: { account: string; model?: string; effort?: string },
  ): Promise<{ id: string }>;
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
const examPath = (c: string, e: string) =>
  `${coursePath(c)}/exams/${pathSegment(e)}`;
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
  exams: (c) => call(`${coursePath(c)}/exams`),
  createExam: (c, title) =>
    call(`${coursePath(c)}/exams`, {
      method: "POST",
      body: JSON.stringify({ title }),
    }),
  exam: (c, e) => call(examPath(c, e)),
  updateExam: (c, e, patch) =>
    call(examPath(c, e), { method: "PUT", body: JSON.stringify(patch) }),
  uploadExamFiles: async (c, e, files) => {
    const body = new FormData();
    for (const file of files) body.append("files", file);
    const { uploads } = await call<{ uploads: ExamUpload[] }>(
      `${examPath(c, e)}/uploads`,
      { method: "POST", body },
    );
    return uploads;
  },
  uploadExamText: (c, e, text) =>
    call(`${examPath(c, e)}/uploads/text`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  deleteExamUpload: async (c, e, name) =>
    (
      await call<{ uploads: ExamUpload[] }>(
        `${examPath(c, e)}/uploads/${pathSegment(name)}`,
        { method: "DELETE" },
      )
    ).uploads,
  handout: (c, e) => call(`${examPath(c, e)}/handout`),
  saveSection: async (c, e, n, markdown) =>
    (
      await call<{ meta: SectionMeta }>(`${examPath(c, e)}/handout/${n}`, {
        method: "PUT",
        body: JSON.stringify({ markdown }),
      })
    ).meta,
  uploadExamAsset: async (c, e, file, signal) => {
    const body = new FormData();
    body.append("file", file);
    const { path } = await call<{ path: string }>(`${examPath(c, e)}/assets`, {
      method: "POST",
      body,
      signal,
    });
    return path;
  },
  quiz: async (c, e) => {
    const response = await fetch(`${examPath(c, e)}/quiz`);
    if (response.status === 404) return null;
    if (!response.ok) throw new Error("讀取題目失敗");
    return response.json();
  },
  attempts: (c, e) => call(`${examPath(c, e)}/attempts`),
  attempt: (c, e, a) => call(`${examPath(c, e)}/attempts/${pathSegment(a)}`),
  submitAttempt: (c, e, _quiz, body) =>
    call(`${examPath(c, e)}/attempts`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  gradeAnswer: (c, e, a, body) =>
    call(`${examPath(c, e)}/attempts/${pathSegment(a)}/grade`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  createExamJob: (c, e, parts, agent) =>
    call(`${coursePath(c)}/jobs`, {
      method: "POST",
      body: JSON.stringify({
        kind: "exam",
        options: { exam: e, parts, ...agent },
      }),
    }),
};

// Static mode: the exam file holds the handout and quiz (fetched once); answers live in this browser only.
const staticExams = new Map<string, Promise<StaticExam>>();
const staticExam = (c: string, e: string) => {
  const url = siteUrl(`/data/${pathSegment(c)}/exams/${pathSegment(e)}.json`);
  let exam = staticExams.get(url);
  if (!exam) {
    exam = call<StaticExam>(url);
    staticExams.set(url, exam);
    exam.catch(() => staticExams.delete(url));
  }
  return exam;
};
const attemptsKey = (c: string, e: string) => `marginalia.exam.${c}.${e}`;
const storedAttempts = (c: string, e: string): Attempt[] => {
  try {
    const value = JSON.parse(localStorage.getItem(attemptsKey(c, e)) ?? "[]");
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
};

// The static deck file holds every slide's note; fetch it once per deck, not once per slide.
const staticDecks = new Map<string, Promise<StaticDeck>>();
const staticDeck = (url: string) => {
  let deck = staticDecks.get(url);
  if (!deck) {
    deck = call<StaticDeck>(siteUrl(url)).then((value) => ({
      ...value,
      slides: value.slides.map((slide) => ({
        ...slide,
        image: slide.image ? siteUrl(slide.image) : undefined,
        thumb: slide.thumb ? siteUrl(slide.thumb) : undefined,
      })),
    }));
    staticDecks.set(url, deck);
    deck.catch(() => staticDecks.delete(url));
  }
  return deck;
};

const staticAdapter: DataAdapter = {
  ...local,
  editable: false,
  mode: "static",
  courses: () => call(siteUrl("/data/courses.json")),
  course: (c) => call(siteUrl(`/data/${pathSegment(c)}/course.json`)),
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
    call(siteUrl(`/data/${pathSegment(c)}/transcripts/${pathSegment(v)}.json`)),
  alignment: (c) => call(siteUrl(`/data/${pathSegment(c)}/alignment.json`)),
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
  exams: (c) =>
    call<ExamSummary[]>(siteUrl(`/data/${pathSegment(c)}/exams.json`)).catch(
      () => [],
    ),
  exam: async (c, e) => {
    const value = await staticExam(c, e);
    return {
      exam: value.exam,
      uploads: [],
      handout: value.handout.map(({ markdown: _, ...meta }) => meta),
      quiz: value.quiz
        ? { hash: value.quiz.hash, questionCount: value.quiz.questions.length }
        : null,
    };
  },
  handout: async (c, e) => (await staticExam(c, e)).handout,
  quiz: async (c, e) => (await staticExam(c, e)).quiz,
  attempts: async (c, e) => storedAttempts(c, e),
  attempt: async (c, e, a) => {
    const found = storedAttempts(c, e).find((item) => item.id === a);
    if (!found) throw new Error("找不到作答紀錄");
    return found;
  },
  submitAttempt: async (c, e, quiz, body) => {
    const results = Object.fromEntries(
      quiz.questions.map((q) => [q.id, gradeObjective(q, body.answers[q.id])]),
    );
    const attempt: Attempt = {
      ...body,
      id: crypto.randomUUID().replaceAll("-", ""),
      quizHash: quiz.hash,
      questions: quiz.questions,
      submittedAt: new Date().toISOString(),
      results,
      gradings: {},
      ...totals(results),
    };
    try {
      localStorage.setItem(
        attemptsKey(c, e),
        JSON.stringify([attempt, ...storedAttempts(c, e)].slice(0, 20)),
      );
    } catch {}
    return attempt;
  },
  createExam: readOnly,
  updateExam: readOnly,
  uploadExamFiles: readOnly,
  uploadExamText: readOnly,
  deleteExamUpload: readOnly,
  saveSection: readOnly,
  uploadExamAsset: readOnly,
  gradeAnswer: readOnly,
  createExamJob: readOnly,
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
