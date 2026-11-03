import {
  CircleCheck,
  CircleX,
  ClipboardList,
  History,
  LoaderCircle,
  RotateCcw,
  Sparkles,
  Timer,
} from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { ModelMenu } from "@/components/agent/ModelMenu";
import { useAgentChoice } from "@/components/agent/use-chat";
import { Markdown } from "@/components/Markdown";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState, LoadingState } from "@/components/ui/states";
import type { ImageSource } from "@/lib/assets";
import { data } from "@/lib/data";
import { SUBJECTIVE } from "@/lib/exam-grade";
import type {
  Answer,
  Attempt,
  AttemptSummary,
  ExamDetail,
  Grading,
  Question,
  Quiz,
  ResultStatus,
} from "@/lib/exam-types";
import { type Strings, useT } from "@/lib/i18n";
import { cn, errorMessage } from "@/lib/utils";

type Draft = {
  hash: string;
  answers: Record<string, Answer>;
  startedAt: string;
  timer: boolean;
};

const draftKey = (c: string, e: string) => `marginalia:exam-draft:${c}:${e}`;
function loadDraft(c: string, e: string, hash: string): Draft {
  try {
    const value = JSON.parse(localStorage.getItem(draftKey(c, e)) ?? "null");
    if (value?.hash === hash && value.answers) return value;
  } catch {}
  return {
    hash,
    answers: {},
    startedAt: new Date().toISOString(),
    timer: false,
  };
}

const answered = (value: Answer | undefined) =>
  Array.isArray(value)
    ? value.some((v) => v.trim())
    : typeof value === "string" && value.trim() !== "";

const TONES: Record<
  ResultStatus,
  "success" | "warning" | "danger" | "neutral" | "brand"
> = {
  correct: "success",
  partial: "warning",
  incorrect: "danger",
  blank: "neutral",
  pending: "brand",
};

/** `{{n}}` blanks shown as numbered gaps; the inputs sit under the prompt. */
const showBlanks = (prompt: string) =>
  prompt.replace(/\{\{(\d+)\}\}/g, (_, n) => ` **(${n})** ＿＿＿ `);

const clock = (seconds: number) => {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const mm = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
  const ss = String(s % 60).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
};

/** The mock exam: answer like an online test, then 對答案 to see mistakes, solutions and agent grading. */
export function QuizView({
  courseId,
  detail,
  source,
}: {
  courseId: string;
  detail: ExamDetail;
  source: ImageSource;
}) {
  const { t } = useT();
  const examId = detail.exam.id;
  const [quiz, setQuiz] = useState<Quiz | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [attempt, setAttempt] = useState<Attempt | null>(null);
  const [history, setHistory] = useState<AttemptSummary[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [onlyWrong, setOnlyWrong] = useState(false);

  useEffect(() => {
    setQuiz(undefined);
    data.quiz(courseId, examId).then(
      (value) => {
        setQuiz(value);
        if (value) setDraft(loadDraft(courseId, examId, value.hash));
      },
      (reason) => setError(errorMessage(reason)),
    );
    data.attempts(courseId, examId).then(setHistory, () => setHistory([]));
  }, [courseId, examId]);
  useEffect(() => {
    if (!draft) return;
    try {
      localStorage.setItem(draftKey(courseId, examId), JSON.stringify(draft));
    } catch {}
  }, [draft, courseId, examId]);

  if (error)
    return <EmptyState tone="error" title={t.saveFailed} description={error} />;
  if (quiz === undefined) return <LoadingState label={t.loading} />;
  if (!quiz || !draft)
    return (
      <EmptyState
        icon={ClipboardList}
        title={t.noQuiz}
        description={data.editable ? t.noQuizHint : undefined}
        className="py-16"
      />
    );

  // A past attempt shows the questions it answered: regenerated quizzes reuse ids q1, q2, ….
  const questions = attempt
    ? (attempt.questions ??
      (attempt.quizHash === quiz.hash ? quiz.questions : []))
    : quiz.questions;
  const count = questions.filter((q) => answered(draft.answers[q.id])).length;
  const limit = (detail.exam.options?.minutes ?? 60) * 60;
  const setAnswer = (id: string, value: Answer) =>
    setDraft({ ...draft, answers: { ...draft.answers, [id]: value } });

  const submit = async () => {
    const missing = questions.length - count;
    if (missing && !window.confirm(t.submitConfirm(missing))) return;
    setSubmitting(true);
    try {
      const result = await data.submitAttempt(courseId, examId, quiz, {
        answers: draft.answers,
        startedAt: draft.startedAt,
        durationSec: Math.round(
          (Date.now() - Date.parse(draft.startedAt)) / 1000,
        ),
      });
      setAttempt(result);
      setHistory((old) => [
        summary(result),
        ...old.filter((a) => a.id !== result.id),
      ]);
      window.scrollTo({ top: 0 });
    } catch (reason) {
      toast.error(t.saveFailed, { description: errorMessage(reason) });
    } finally {
      setSubmitting(false);
    }
  };
  const restart = () => {
    setAttempt(null);
    setOnlyWrong(false);
    setDraft({
      hash: quiz.hash,
      answers: {},
      startedAt: new Date().toISOString(),
      timer: draft.timer,
    });
    window.scrollTo({ top: 0 });
  };

  const review = attempt !== null;
  const stale = review && attempt.quizHash !== quiz.hash && !attempt.questions;
  const shown =
    review && onlyWrong
      ? questions.filter((q) => attempt.results[q.id]?.status !== "correct")
      : questions;
  const pending =
    review &&
    questions.some((q) => attempt.results[q.id]?.status === "pending");

  return (
    <main className="mx-auto grid w-full max-w-3xl gap-4 px-4 pb-28 pt-6 sm:px-6 sm:pt-8">
      {review ? (
        <section className="rounded-[10px] border border-border bg-card p-4 shadow-edge sm:p-5">
          <div className="flex flex-wrap items-end gap-x-4 gap-y-2">
            <div>
              <p className="text-[12.5px] text-muted-foreground">{t.score}</p>
              <p className="nums text-[30px] font-semibold tracking-tight">
                {attempt.score}
                <span className="text-[16px] font-normal text-muted-foreground">
                  {" "}
                  / {attempt.maxScore}
                </span>
              </p>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {(
                ["correct", "partial", "incorrect", "blank", "pending"] as const
              ).map((status) => {
                const n = questions.filter(
                  (q) => attempt.results[q.id]?.status === status,
                ).length;
                return n ? (
                  <Badge key={status} tone={TONES[status]}>
                    {t.status[status]} {n}
                  </Badge>
                ) : null;
              })}
            </div>
            <div className="ml-auto flex gap-2">
              <Button
                variant={onlyWrong ? "default" : "outline"}
                size="sm"
                aria-pressed={onlyWrong}
                onClick={() => setOnlyWrong(!onlyWrong)}
              >
                {t.onlyWrong}
              </Button>
              <Button variant="outline" size="sm" onClick={restart}>
                <RotateCcw /> {t.retry}
              </Button>
            </div>
          </div>
          {pending && (
            <p className="mt-3 text-[12.5px] text-muted-foreground">
              {data.editable ? t.pendingNote : t.pendingStatic}
            </p>
          )}
          {stale && (
            <p className="mt-3 text-[12.5px] text-warning">{t.quizChanged}</p>
          )}
        </section>
      ) : (
        <div className="flex flex-wrap items-center gap-2 text-[12.5px] text-muted-foreground">
          <span>{t.questions(questions.length)}</span>
          <span>·</span>
          <span>
            {t.points(questions.reduce((sum, q) => sum + q.points, 0))}
          </span>
          {history.length > 0 && (
            <HistoryMenu
              t={t}
              history={history}
              onOpen={async (id) => {
                try {
                  setAttempt(await data.attempt(courseId, examId, id));
                  window.scrollTo({ top: 0 });
                } catch (reason) {
                  toast.error(t.saveFailed, {
                    description: errorMessage(reason),
                  });
                }
              }}
            />
          )}
        </div>
      )}
      <ol className="grid gap-4">
        {shown.map((question) => (
          <li key={question.id}>
            <QuestionCard
              number={questions.indexOf(question) + 1}
              question={question}
              answer={
                review
                  ? attempt.answers[question.id]
                  : draft.answers[question.id]
              }
              onAnswer={(value) => setAnswer(question.id, value)}
              attempt={review ? attempt : null}
              canGrade={data.editable && review && !stale}
              onGraded={(next) => {
                setAttempt(next);
                setHistory((old) =>
                  old.map((item) =>
                    item.id === next.id ? summary(next) : item,
                  ),
                );
              }}
              courseId={courseId}
              examId={examId}
              source={source}
            />
          </li>
        ))}
      </ol>
      {!review && (
        <div className="fixed inset-x-0 bottom-0 z-20 border-t border-hairline bg-background/95 backdrop-blur-md">
          <div className="mx-auto flex max-w-3xl flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2.5 sm:px-6">
            <span className="nums text-[12.5px] text-muted-foreground">
              {t.answered(count, questions.length)}
            </span>
            <label className="flex items-center gap-1.5 text-[12.5px]">
              <input
                type="checkbox"
                className="size-3.5 accent-[var(--brand)]"
                checked={draft.timer}
                onChange={(event) => {
                  setDraft({
                    ...draft,
                    timer: event.target.checked,
                    startedAt: event.target.checked
                      ? new Date().toISOString()
                      : draft.startedAt,
                  });
                }}
              />
              <Timer className="size-3.5" aria-hidden /> {t.timer}
            </label>
            {draft.timer && (
              <Countdown startedAt={draft.startedAt} limit={limit} t={t} />
            )}
            <Button
              className="ml-auto"
              disabled={submitting}
              onClick={() => void submit()}
            >
              {submitting && <LoaderCircle className="animate-spin" />}
              {t.submit}
            </Button>
          </div>
        </div>
      )}
    </main>
  );
}

const summary = ({ id, submittedAt, score, maxScore }: Attempt) => ({
  id,
  submittedAt,
  score,
  maxScore,
});

/** Its own component so the per-second tick re-renders only the clock, not every question. */
function Countdown({
  startedAt,
  limit,
  t,
}: {
  startedAt: string;
  limit: number;
  t: Strings;
}) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const left = limit - (now - Date.parse(startedAt)) / 1000;
  return (
    <>
      <span
        role="timer"
        className={cn(
          "nums text-[13px] font-medium",
          left < 0 && "text-destructive",
        )}
      >
        {t.timeLeft} {clock(left)}
      </span>
      {left < 0 && (
        <span className="text-[12px] text-destructive max-sm:hidden">
          {t.timeUp}
        </span>
      )}
    </>
  );
}

function HistoryMenu({
  t,
  history,
  onOpen,
}: {
  t: Strings;
  history: AttemptSummary[];
  onOpen: (id: string) => void;
}) {
  return (
    <details className="relative ml-auto">
      <summary className="flex cursor-pointer list-none items-center gap-1 rounded-[5px] px-2 py-1 hover:bg-muted">
        <History className="size-3.5" aria-hidden /> {t.history} (
        {history.length})
      </summary>
      <ul className="absolute right-0 z-10 mt-1 grid w-64 gap-0.5 rounded-[8px] border border-border bg-popover p-1 shadow-floating">
        {history.map((item) => (
          <li key={item.id}>
            <button
              type="button"
              onClick={() => onOpen(item.id)}
              className="flex w-full items-center justify-between rounded-[5px] px-2 py-1.5 text-left text-[12.5px] hover:bg-muted"
            >
              <span>{new Date(item.submittedAt).toLocaleString()}</span>
              <span className="nums font-medium">
                {item.score} / {item.maxScore}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </details>
  );
}

function AnswerInput({
  question,
  value,
  onChange,
  disabled,
  source,
}: {
  question: Question;
  value: Answer | undefined;
  onChange: (value: Answer) => void;
  disabled: boolean;
  source: ImageSource;
}) {
  const { t } = useT();
  if (question.type === "choice") {
    const picked = Array.isArray(value) ? value : [];
    return (
      <fieldset className="grid gap-1.5" disabled={disabled}>
        <legend className="sr-only">{t.yourAnswer}</legend>
        {question.multiple && (
          <p className="text-[12px] text-muted-foreground">
            {t.choiceMultiple}
          </p>
        )}
        {question.options?.map((option) => {
          const checked = picked.includes(option.id);
          return (
            <label
              key={option.id}
              className={cn(
                "flex cursor-pointer items-start gap-2.5 rounded-[8px] border px-3 py-2.5 text-[14px] transition-colors",
                checked
                  ? "border-brand bg-brand-soft"
                  : "border-border hover:bg-muted",
                disabled && "cursor-default",
              )}
            >
              <input
                type={question.multiple ? "checkbox" : "radio"}
                name={`q-${question.id}`}
                className="mt-1 size-3.5 accent-[var(--brand)]"
                checked={checked}
                onChange={(event) =>
                  onChange(
                    question.multiple
                      ? event.target.checked
                        ? [...picked, option.id]
                        : picked.filter((id) => id !== option.id)
                      : [option.id],
                  )
                }
              />
              <span className="font-medium">{option.id}.</span>
              <Markdown
                markdown={option.text}
                source={source}
                variant="inline"
                className="min-w-0 flex-1"
              />
            </label>
          );
        })}
      </fieldset>
    );
  }
  if (question.type === "fill") {
    const values = Array.isArray(value) ? value : [];
    return (
      <div className="grid gap-2 sm:grid-cols-2">
        {question.blanks?.map((_, i) => (
          <label
            // biome-ignore lint/suspicious/noArrayIndexKey: blanks are numbered positions
            key={i}
            className="flex items-center gap-2 text-[13px]"
          >
            <span className="nums w-7 shrink-0 font-medium">({i + 1})</span>
            <input
              value={values[i] ?? ""}
              disabled={disabled}
              onChange={(event) => {
                const next =
                  question.blanks?.map((__, j) => values[j] ?? "") ?? [];
                next[i] = event.target.value;
                onChange(next);
              }}
              className="h-9 min-w-0 flex-1 rounded-[6px] border border-border bg-background px-3 text-[14px] outline-none focus-visible:border-foreground/40 disabled:opacity-80"
            />
          </label>
        ))}
      </div>
    );
  }
  return (
    <textarea
      value={typeof value === "string" ? value : ""}
      disabled={disabled}
      onChange={(event) => onChange(event.target.value)}
      placeholder={t.answerPlaceholder}
      rows={question.type === "essay" ? 9 : question.type === "calc" ? 7 : 5}
      aria-label={t.yourAnswer}
      className="w-full rounded-[8px] border border-border bg-background px-3 py-2.5 text-[14px] leading-relaxed outline-none focus-visible:border-foreground/40 disabled:opacity-80"
    />
  );
}

function correctAnswer(question: Question) {
  if (question.type === "choice") return (question.answer ?? []).join("、");
  if (question.type === "fill")
    return (question.blanks ?? [])
      .map((accepted, i) => `(${i + 1}) ${accepted.join(" / ")}`)
      .join("　");
  return "";
}

function QuestionCard({
  number,
  question,
  answer,
  onAnswer,
  attempt,
  canGrade,
  onGraded,
  courseId,
  examId,
  source,
}: {
  number: number;
  question: Question;
  answer: Answer | undefined;
  onAnswer: (value: Answer) => void;
  attempt: Attempt | null;
  canGrade: boolean;
  onGraded: (attempt: Attempt) => void;
  courseId: string;
  examId: string;
  source: ImageSource;
}) {
  const { t } = useT();
  const result = attempt?.results[question.id];
  const subjective = SUBJECTIVE.has(question.type);
  return (
    <article
      aria-labelledby={`q-${question.id}-title`}
      className={cn(
        "rounded-[10px] border bg-card p-4 shadow-edge sm:p-5",
        result?.status === "incorrect" || result?.status === "blank"
          ? "border-destructive/40"
          : result?.status === "partial"
            ? "border-warning/50"
            : "border-border",
      )}
    >
      <header className="mb-2.5 flex flex-wrap items-center gap-1.5">
        <h3
          id={`q-${question.id}-title`}
          className="nums mr-1 text-[14px] font-semibold"
        >
          {number}.
        </h3>
        <Badge>{t.typeNames[question.type]}</Badge>
        <Badge tone={question.origin === "past" ? "warning" : "neutral"}>
          {question.origin === "past" ? t.pastTag : t.newTag}
        </Badge>
        {question.topic && (
          <span className="text-[12px] text-muted-foreground">
            {question.topic}
          </span>
        )}
        <span className="ml-auto flex items-center gap-1.5 text-[12px] text-muted-foreground">
          {result && (
            <Badge tone={TONES[result.status]}>
              {result.status === "correct" ? (
                <CircleCheck />
              ) : result.status === "incorrect" ? (
                <CircleX />
              ) : null}
              {t.status[result.status]}
            </Badge>
          )}
          <span className="nums">
            {result?.score != null ? `${result.score} / ` : ""}
            {t.points(question.points)}
          </span>
        </span>
      </header>
      <Markdown
        markdown={
          question.type === "fill"
            ? showBlanks(question.prompt)
            : question.prompt
        }
        source={source}
      />
      <div className="mt-3">
        <AnswerInput
          question={question}
          value={answer}
          onChange={onAnswer}
          disabled={attempt !== null}
          source={source}
        />
      </div>
      {attempt && (
        <div className="mt-4 grid gap-3 border-t border-hairline pt-3">
          {!subjective && (
            <p className="text-[13.5px]">
              <span className="font-medium">{t.correctAnswer}：</span>
              {correctAnswer(question)}
            </p>
          )}
          {question.solution && (
            <div>
              <p className="mb-1 text-[12.5px] font-medium text-muted-foreground">
                {t.solution}
              </p>
              <Markdown markdown={question.solution} source={source} />
            </div>
          )}
          {question.rubric && question.rubric.length > 0 && (
            <div>
              <p className="mb-1 text-[12.5px] font-medium text-muted-foreground">
                {t.rubric}
              </p>
              <ul className="list-disc pl-5 text-[13.5px]">
                {question.rubric.map((item) => (
                  <li key={item.point}>
                    {item.point}（{t.points(item.points)}）
                  </li>
                ))}
              </ul>
            </div>
          )}
          {subjective && (
            <AgentGrading
              question={question}
              attempt={attempt}
              canGrade={canGrade}
              onGraded={onGraded}
              courseId={courseId}
              examId={examId}
            />
          )}
        </div>
      )}
    </article>
  );
}

function GradingView({ grading, n }: { grading: Grading; n: number }) {
  const { t } = useT();
  return (
    <div className="rounded-[8px] border border-border bg-background p-3">
      <div className="flex flex-wrap items-center gap-2 text-[12.5px]">
        <span className="font-medium">{t.gradingN(n)}</span>
        <Badge tone={TONES[grading.verdict]}>{t.status[grading.verdict]}</Badge>
        <span className="nums font-medium">
          {grading.score} / {grading.maxScore}
        </span>
        <span className="ml-auto text-muted-foreground">
          {new Date(grading.createdAt).toLocaleString()}
        </span>
      </div>
      {grading.summary && (
        <p className="mt-2 text-[13.5px]">{grading.summary}</p>
      )}
      {grading.issues.length > 0 && (
        <div className="mt-2">
          <p className="text-[12px] font-medium text-muted-foreground">
            {t.issues}
          </p>
          <ul className="mt-1 grid gap-1.5">
            {grading.issues.map((issue) => (
              <li
                key={`${issue.quote}-${issue.problem}`}
                className="rounded-[6px] bg-muted/60 px-2.5 py-2 text-[13px]"
              >
                {issue.quote && (
                  <q className="block text-muted-foreground">{issue.quote}</q>
                )}
                <span className="block">{issue.problem}</span>
                {issue.fix && (
                  <span className="block text-success">
                    {t.fix}：{issue.fix}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      {grading.missing.length > 0 && (
        <div className="mt-2">
          <p className="text-[12px] font-medium text-muted-foreground">
            {t.missing}
          </p>
          <ul className="list-disc pl-5 text-[13px]">
            {grading.missing.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      )}
      <details className="mt-2 text-[12.5px]">
        <summary className="cursor-pointer text-muted-foreground">
          {t.yourAnswer}
        </summary>
        <p className="mt-1 whitespace-pre-wrap">{grading.answer}</p>
      </details>
    </div>
  );
}

function AgentGrading({
  question,
  attempt,
  canGrade,
  onGraded,
  courseId,
  examId,
}: {
  question: Question;
  attempt: Attempt;
  canGrade: boolean;
  onGraded: (attempt: Attempt) => void;
  courseId: string;
  examId: string;
}) {
  const { t } = useT();
  const gradings = attempt.gradings[question.id] ?? [];
  const original = attempt.answers[question.id];
  const latest =
    gradings.at(-1)?.answer ?? (typeof original === "string" ? original : "");
  const [text, setText] = useState(latest);
  const [busy, setBusy] = useState(false);
  const agent = useAgentChoice(data);
  useEffect(() => setText(latest), [latest]);
  if (!canGrade && !gradings.length) return null;
  const grade = async () => {
    if (!agent.account) return;
    setBusy(true);
    try {
      const { attempt: next } = await data.gradeAnswer(
        courseId,
        examId,
        attempt.id,
        {
          question: question.id,
          answer: text,
          account: agent.account.id,
          model: agent.model?.id,
          effort: agent.effort || undefined,
        },
      );
      onGraded(next);
    } catch (reason) {
      toast.error(t.gradeFailed, { description: errorMessage(reason) });
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="grid gap-2">
      {gradings.length > 0 && (
        <p className="text-[12.5px] font-medium text-muted-foreground">
          {t.gradings}
        </p>
      )}
      {gradings.map((grading, i) => (
        <GradingView key={grading.id} grading={grading} n={i + 1} />
      ))}
      {canGrade && (
        <>
          {gradings.length > 0 && (
            <label className="grid gap-1.5 text-[12.5px] font-medium">
              {t.rewrite}
              <textarea
                value={text}
                onChange={(event) => setText(event.target.value)}
                rows={6}
                className="w-full rounded-[8px] border border-border bg-background px-3 py-2.5 text-[14px] font-normal leading-relaxed outline-none focus-visible:border-foreground/40"
              />
            </label>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <ModelMenu
              accounts={agent.accounts ?? []}
              account={agent.account}
              model={agent.model}
              effort={agent.effort}
              onChoose={agent.choose}
              onManage={() => void agent.loadAccounts()}
              disabled={busy}
            />
            <Button
              size="sm"
              className="ml-auto"
              disabled={busy || !text.trim() || !agent.account}
              onClick={() => void grade()}
            >
              {busy ? <LoaderCircle className="animate-spin" /> : <Sparkles />}
              {busy ? t.grading : gradings.length ? t.regrade : t.agentGrade}
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
