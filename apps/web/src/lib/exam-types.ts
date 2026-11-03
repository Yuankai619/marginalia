// Shapes from docs/architecture.md (Exam prep).

export type QuestionType = "choice" | "fill" | "short" | "essay" | "calc";
export type Answer = string | string[];

export type Question = {
  id: string;
  type: QuestionType;
  origin: "past" | "new";
  prompt: string;
  points: number;
  options?: { id: string; text: string }[];
  multiple?: boolean;
  answer?: string[];
  blanks?: string[][];
  solution?: string;
  rubric?: { point: string; points: number }[];
  sources?: { deck: string; slide: number }[];
  topic?: string;
};
export type Quiz = {
  hash: string;
  generatedAt?: string;
  questions: Question[];
};

export type ResultStatus =
  | "correct"
  | "partial"
  | "incorrect"
  | "blank"
  | "pending";
export type QuestionResult = {
  status: ResultStatus;
  score: number | null;
  maxScore: number;
};
export type Grading = {
  id: string;
  answer: string;
  score: number;
  maxScore: number;
  verdict: "correct" | "partial" | "incorrect";
  summary: string;
  issues: { quote: string; problem: string; fix: string }[];
  missing: string[];
  account?: string;
  model?: string | null;
  createdAt: string;
};
export type Attempt = {
  id: string;
  quizHash: string;
  startedAt?: string;
  submittedAt: string;
  durationSec?: number;
  answers: Record<string, Answer>;
  results: Record<string, QuestionResult>;
  score: number;
  maxScore: number;
  gradings: Record<string, Grading[]>;
};

export type ExamScope = { decks: string[]; videos?: string[] };
export type ExamOptions = {
  questionCount?: number;
  types?: QuestionType[];
  minutes?: number;
};
export type ExamInfo = {
  id: string;
  title: string;
  createdAt?: string;
  updatedAt?: string;
  scope: ExamScope;
  options?: ExamOptions;
  hidden?: boolean;
};
export type ExamSummary = {
  id: string;
  title: string;
  updatedAt?: string;
  uploadCount?: number;
  sectionCount: number;
  questionCount: number;
};
export type ExamUpload = {
  name: string;
  kind: "image" | "text";
  size: number;
  url: string;
};
export type SectionMeta = {
  section: number;
  title: string;
  status: "generated" | "reviewed" | "edited";
  updatedAt?: string | null;
  sources?: string[];
};
export type ExamDetail = {
  exam: ExamInfo;
  uploads: ExamUpload[];
  handout: SectionMeta[];
  quiz: { questionCount: number; hash: string; generatedAt?: string } | null;
};
export type Section = SectionMeta & { markdown: string };
export type StaticExam = {
  exam: ExamInfo;
  handout: {
    section: number;
    title: string;
    markdown: string;
    meta: { status: SectionMeta["status"]; updatedAt?: string };
  }[];
  quiz: Quiz | null;
};
