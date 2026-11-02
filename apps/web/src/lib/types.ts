export type NoteStatus = "generated" | "reviewed" | "edited" | "skipped";

export type Course = {
  id: string;
  title: string;
  subtitle?: string;
  deckCount: number;
  videoCount: number;
  updatedAt: string;
};

export type Deck = {
  id: string;
  title: string;
  slideCount: number;
  hidden?: boolean;
};
export type Video = {
  id: string;
  title: string;
  duration: number;
  transcriptStatus?: string;
  url?: string;
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
  info: Course;
  decks: Deck[];
  videos: Video[];
  status?: string;
};
export type DeckDetail = { deck: Deck; slides: Slide[] };
export type Note = {
  markdown: string;
  meta: { status: NoteStatus; updatedAt?: string };
  review: string | null;
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
  loggedIn: boolean;
  models: { id: string; label: string }[];
  efforts: string[];
};
