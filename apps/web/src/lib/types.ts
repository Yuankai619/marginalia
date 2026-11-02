export type NoteStatus = "generated" | "reviewed" | "edited" | "skipped";

export type Course = {
  id: string;
  title: string;
  subtitle?: string;
  deckCount: number;
  videoCount: number;
  updatedAt?: string;
};

export type Deck = {
  id: string;
  title: string;
  slideCount: number;
  hidden?: boolean;
  date?: string;
  width?: number;
  height?: number;
  rendered?: boolean;
};
export type Video = {
  id: string;
  title: string;
  duration: number;
  transcriptStatus?: string;
  source?: string;
  date?: string;
};
export type Range = { video: string; start: number; end: number };
export type Slide = {
  index: number;
  title: string;
  text?: string;
  image?: string;
  thumb?: string;
  ranges: Range[];
  note: { status: NoteStatus; updatedAt: string } | null;
};
export type CourseDetail = {
  info: Pick<Course, "id" | "title" | "subtitle" | "updatedAt"> & {
    videoUrls?: Record<string, string>;
    hiddenDecks?: string[];
  };
  decks: Deck[];
  videos: Video[];
  status?: string | Record<string, unknown>;
};
export type DeckDetail = { deck: Deck; slides: Slide[] };
export type Note = {
  markdown: string;
  meta: { status: NoteStatus; updatedAt?: string };
  review: unknown;
};
export type Transcript = { start: number; end: number; text: string };
export type AlignmentSegment = {
  video: string;
  start: number;
  end: number;
  deck: string | null;
  slide: number | null;
  score?: number;
  manual?: boolean;
};
export type Alignment = {
  videos: Record<string, unknown>;
  segments: AlignmentSegment[];
};
export type Job = {
  id: string;
  course: string;
  kind: string;
  state: "queued" | "running" | "done" | "failed" | "cancelled";
  progress: number;
  message: string;
  steps: { name: string; state: string; progress: number; message: string }[];
};
export type Account = {
  id: string;
  provider: "claude" | "codex";
  label: string;
  plan?: string;
  loggedIn: boolean;
  models: { id: string; label: string }[];
  efforts: string[];
};

export type Region = { x: number; y: number; w: number; h: number };
export type VideoTime = { video: string; time: number };
export type ChatContext = {
  deck: string;
  slide: number;
  selection?: { text: string; source: "note" | "transcript" };
  region?: Region;
};
export type ChatRequest = {
  course: string;
  chatId: string | null;
  mode: string;
  account: string;
  model: string;
  effort: string;
  context: ChatContext;
  message: string;
};
export type ChatEvent = {
  type: "start" | "text" | "tool" | "done" | "error";
  chatId?: string;
  delta?: string;
  title?: string;
  detail?: string;
  message?: string;
  cost?: number;
};
export type ChatMessage = { role: string; content: string; createdAt?: string };
export type ChatSummary = {
  id: string;
  title: string;
  mode: string;
  updatedAt?: string;
};
export type Chat = ChatSummary & { messages: ChatMessage[] };
export type StaticDeck = DeckDetail & {
  notes: Record<
    string,
    { markdown: string; meta?: Note["meta"]; review?: Note["review"] }
  >;
};
