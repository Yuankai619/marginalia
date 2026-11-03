// UI strings of the exam-prep pages in Traditional Chinese and English. The reader stays zh-TW; these pages
// carry a language switch because exam material often mixes both.
import { useSyncExternalStore } from "react";

export type Lang = "zh-TW" | "en";

const zh = {
  examPrep: "考前複習",
  examPrepHint: "選範圍、上傳考古題，產生衝刺講義與模擬考",
  newExam: "新增考試",
  examTitle: "考試名稱",
  examTitlePlaceholder: "例如：期中考",
  create: "建立",
  cancel: "取消",
  noExams: "還沒有考試",
  noExamsHint: "建立一份考試，選好範圍後就能產生講義與模擬考。",
  sections: (n: number) => `${n} 節講義`,
  questions: (n: number) => `${n} 題`,
  tabSetup: "準備",
  tabHandout: "講義",
  tabQuiz: "模擬考",
  scope: "範圍",
  scopeHint: "勾選這次考試涵蓋的投影片；全部不勾等於整門課。",
  selectedDecks: (n: number) => `已選 ${n} 份`,
  pastPapers: "考古題與練習題",
  pastPapersHint:
    "拖放考卷照片（png、jpg、webp，每張 10 MB 內）或文字檔，也可以直接貼上題目文字。",
  chooseFiles: "選擇檔案",
  pasteText: "貼上題目文字",
  pastePlaceholder: "把考古題的文字貼在這裡…",
  addText: "加入",
  remove: "移除",
  noUploads: "還沒有上傳，沒有考古題也能出題。",
  options: "出題設定",
  questionCount: "題數",
  minutes: "作答時間（分鐘）",
  types: "題型",
  typeNames: {
    choice: "選擇",
    fill: "填空",
    short: "簡答",
    essay: "問答",
    calc: "計算",
  },
  save: "儲存設定",
  saved: "已儲存",
  generate: "產生講義與模擬考",
  generateHandout: "只產生講義",
  generateQuiz: "只產生題目",
  generateHint:
    "會讀範圍內的投影片、筆記與逐字稿。已編輯過的講義段落不會被覆寫。",
  generating: "產生中",
  generated: "產生完成",
  generateFailed: "產生失敗",
  contents: "目錄",
  noHandout: "還沒有講義",
  noHandoutHint: "到「準備」分頁產生講義。",
  edit: "編輯",
  done: "完成",
  saving: "儲存中…",
  saveFailed: "儲存失敗",
  unsavedLeave: "還有沒儲存的修改，確定要離開嗎？",
  addSection: "新增一節",
  insertSlide: "插入投影片截圖",
  filterSlides: "搜尋投影片標題",
  noQuiz: "還沒有題目",
  noQuizHint: "到「準備」分頁產生模擬考。",
  timer: "計時",
  timeLeft: "剩餘",
  timeUp: "時間到，可以繼續作答或交卷。",
  submit: "交卷並對答案",
  submitConfirm: (n: number) => `還有 ${n} 題沒作答，確定要交卷嗎？`,
  retry: "重新作答",
  answered: (a: number, n: number) => `已作答 ${a} / ${n}`,
  score: "得分",
  pendingNote:
    "簡答、問答、計算題還沒計分：可以請 Agent 批改，或對照參考答案自評。",
  pendingStatic: "簡答、問答、計算題請對照參考答案與評分要點自評。",
  onlyWrong: "只看錯題",
  status: {
    correct: "答對",
    partial: "部分正確",
    incorrect: "答錯",
    blank: "未作答",
    pending: "待批改",
  },
  yourAnswer: "你的答案",
  correctAnswer: "正確答案",
  solution: "解答與詳解",
  rubric: "評分要點",
  points: (n: number) => `${n} 分`,
  pastTag: "考古題",
  newTag: "新題",
  choiceMultiple: "多選",
  answerPlaceholder: "寫下你的答案…",
  agentGrade: "請 Agent 批改",
  regrade: "改寫後再批改",
  grading: "批改中…（約 30 秒）",
  gradeFailed: "批改失敗",
  gradings: "批改紀錄",
  gradingN: (n: number) => `第 ${n} 次批改`,
  issues: "可能被扣分的地方",
  missing: "沒寫到的要點",
  fix: "建議",
  rewrite: "改寫答案",
  history: "作答紀錄",
  quizChanged: "題目已重新產生，這份紀錄只能檢視。",
  quizOutdated:
    "這份模擬考在你作答期間重新產生了，題目已經不同，答案無法交卷。請載入新題目重新開始。",
  reloadQuiz: "載入新題目重新開始",
  slide: (n: number) => `第 ${n} 頁`,
  language: "English",
  backToCourse: "回到課程",
  notFound: "找不到這份考試",
  loading: "讀取中",
};

const en: typeof zh = {
  examPrep: "Exam prep",
  examPrepHint:
    "Pick a scope, upload past papers, get a cram handout and a mock exam",
  newExam: "New exam",
  examTitle: "Exam name",
  examTitlePlaceholder: "e.g. Midterm",
  create: "Create",
  cancel: "Cancel",
  noExams: "No exams yet",
  noExamsHint:
    "Create an exam and pick its scope to generate a handout and a mock exam.",
  sections: (n) => `${n} section${n === 1 ? "" : "s"}`,
  questions: (n) => `${n} question${n === 1 ? "" : "s"}`,
  tabSetup: "Setup",
  tabHandout: "Handout",
  tabQuiz: "Mock exam",
  scope: "Scope",
  scopeHint:
    "Tick the decks this exam covers; none ticked means the whole course.",
  selectedDecks: (n) => `${n} selected`,
  pastPapers: "Past papers & practice questions",
  pastPapersHint:
    "Drop photos of past papers (png, jpg, webp, up to 10 MB each) or text files, or paste the questions as text.",
  chooseFiles: "Choose files",
  pasteText: "Paste question text",
  pastePlaceholder: "Paste past-paper text here…",
  addText: "Add",
  remove: "Remove",
  noUploads: "Nothing uploaded. Questions can be written without past papers.",
  options: "Question settings",
  questionCount: "Questions",
  minutes: "Time limit (minutes)",
  types: "Types",
  typeNames: {
    choice: "Multiple choice",
    fill: "Fill in",
    short: "Short answer",
    essay: "Essay",
    calc: "Calculation",
  },
  save: "Save settings",
  saved: "Saved",
  generate: "Generate handout and mock exam",
  generateHandout: "Handout only",
  generateQuiz: "Questions only",
  generateHint:
    "Reads the slides, notes and transcripts in scope. Handout sections you edited are never overwritten.",
  generating: "Generating",
  generated: "Done",
  generateFailed: "Generation failed",
  contents: "Contents",
  noHandout: "No handout yet",
  noHandoutHint: "Generate one in the Setup tab.",
  edit: "Edit",
  done: "Done",
  saving: "Saving…",
  saveFailed: "Save failed",
  unsavedLeave: "You have unsaved changes. Leave anyway?",
  addSection: "Add a section",
  insertSlide: "Insert slide image",
  filterSlides: "Search slide titles",
  noQuiz: "No questions yet",
  noQuizHint: "Generate the mock exam in the Setup tab.",
  timer: "Timer",
  timeLeft: "Left",
  timeUp: "Time is up. You can keep answering or submit.",
  submit: "Submit and check",
  submitConfirm: (n) => `${n} unanswered. Submit anyway?`,
  retry: "Try again",
  answered: (a, n) => `${a} / ${n} answered`,
  score: "Score",
  pendingNote:
    "Short answer, essay and calculation questions are not scored yet: ask the agent to grade them or compare with the reference answer.",
  pendingStatic:
    "Compare short answer, essay and calculation questions with the reference answer and rubric yourself.",
  onlyWrong: "Mistakes only",
  status: {
    correct: "Correct",
    partial: "Partly right",
    incorrect: "Wrong",
    blank: "Unanswered",
    pending: "Not graded",
  },
  yourAnswer: "Your answer",
  correctAnswer: "Correct answer",
  solution: "Solution",
  rubric: "Rubric",
  points: (n) => `${n} pt${n === 1 ? "" : "s"}`,
  pastTag: "Past paper",
  newTag: "New",
  choiceMultiple: "Select all that apply",
  answerPlaceholder: "Write your answer…",
  agentGrade: "Ask the agent to grade",
  regrade: "Grade the rewrite",
  grading: "Grading… (about 30 s)",
  gradeFailed: "Grading failed",
  gradings: "Gradings",
  gradingN: (n) => `Grading ${n}`,
  issues: "Where you would lose points",
  missing: "Points you missed",
  fix: "Fix",
  rewrite: "Rewrite the answer",
  history: "Past attempts",
  quizChanged: "The questions were regenerated; this attempt is view-only.",
  quizOutdated:
    "This mock exam was regenerated while you were answering, so your answers no longer match its questions. Load the new questions and start again.",
  reloadQuiz: "Load the new questions",
  slide: (n) => `slide ${n}`,
  language: "中文",
  backToCourse: "Back to course",
  notFound: "Exam not found",
  loading: "Loading",
};

const STRINGS = { "zh-TW": zh, en };
const KEY = "marginalia:lang";
const listeners = new Set<() => void>();

function current(): Lang {
  try {
    return localStorage.getItem(KEY) === "en" ? "en" : "zh-TW";
  } catch {
    return "zh-TW";
  }
}

export function setLang(lang: Lang) {
  try {
    localStorage.setItem(KEY, lang);
  } catch {}
  for (const notify of listeners) notify();
}

const subscribe = (notify: () => void) => {
  listeners.add(notify);
  return () => listeners.delete(notify);
};

/** The strings for the chosen language and a toggle between the two. */
export function useT() {
  const lang = useSyncExternalStore(subscribe, current, () => "zh-TW" as Lang);
  return {
    t: STRINGS[lang],
    lang,
    toggle: () => setLang(lang === "en" ? "zh-TW" : "en"),
  };
}
export type Strings = typeof zh;
