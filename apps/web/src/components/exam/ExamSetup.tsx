import {
  CircleAlert,
  CircleCheck,
  FileText,
  FileUp,
  LoaderCircle,
  Sparkles,
  Trash2,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { ModelMenu } from "@/components/agent/ModelMenu";
import { useAgentChoice } from "@/components/agent/use-chat";
import { Button } from "@/components/ui/button";
import { data } from "@/lib/data";
import { jobFinished, subscribeJob } from "@/lib/events";
import type { ExamDetail, ExamOptions, QuestionType } from "@/lib/exam-types";
import { useT } from "@/lib/i18n";
import type { CourseDetail, Job } from "@/lib/types";
import { cn, errorMessage } from "@/lib/utils";

const TYPES: QuestionType[] = ["choice", "fill", "short", "essay", "calc"];
const ACCEPT = ".png,.jpg,.jpeg,.webp,.txt,.md";

function Panel({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-[10px] border border-border bg-card p-4 shadow-edge sm:p-5">
      <h2 className="text-[15px] font-semibold">{title}</h2>
      {hint && (
        <p className="mt-1 text-[12.5px] text-muted-foreground">{hint}</p>
      )}
      <div className="mt-3.5">{children}</div>
    </section>
  );
}

/** Scope, past papers, question settings and the generation job (local mode only). */
export function ExamSetup({
  courseId,
  course,
  detail,
  onChange,
  onRefresh,
}: {
  courseId: string;
  course: CourseDetail;
  detail: ExamDetail;
  onChange: (detail: ExamDetail) => void;
  onRefresh: () => Promise<void>;
}) {
  const { t } = useT();
  const examId = detail.exam.id;
  const hidden = new Set(course.info.hiddenDecks ?? []);
  const decks = course.decks.filter(
    (deck) => !deck.hidden && !hidden.has(deck.id),
  );
  const [scope, setScope] = useState<string[]>(detail.exam.scope.decks);
  const [options, setOptions] = useState<ExamOptions>(
    detail.exam.options ?? {},
  );
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [text, setText] = useState("");
  const [over, setOver] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const picker = useRef<HTMLInputElement>(null);
  const agent = useAgentChoice(data);

  useEffect(() => {
    if (!jobId) return;
    return subscribeJob(jobId, data.job, setJob, data.mode === "local");
  }, [jobId]);
  const running = jobId !== null && (!job || !jobFinished(job));
  // biome-ignore lint/correctness/useExhaustiveDependencies: refresh once when the job ends
  useEffect(() => {
    if (job && jobFinished(job)) void onRefresh();
  }, [job?.state]);

  const dirty =
    JSON.stringify(scope) !== JSON.stringify(detail.exam.scope.decks) ||
    JSON.stringify(options) !== JSON.stringify(detail.exam.options ?? {});
  const save = async () => {
    setSaving(true);
    try {
      const exam = await data.updateExam(courseId, examId, {
        scope: { decks: scope, videos: detail.exam.scope.videos ?? [] },
        options,
      });
      onChange({ ...detail, exam });
      toast.success(t.saved);
    } catch (error) {
      toast.error(t.saveFailed, { description: errorMessage(error) });
      throw error;
    } finally {
      setSaving(false);
    }
  };
  const upload = async (files: File[]) => {
    if (!files.length || uploading) return;
    setUploading(true);
    try {
      const uploads = await data.uploadExamFiles(courseId, examId, files);
      onChange({ ...detail, uploads });
    } catch (error) {
      toast.error(t.saveFailed, { description: errorMessage(error) });
    } finally {
      setUploading(false);
    }
  };
  const addText = async () => {
    if (!text.trim()) return;
    setUploading(true);
    try {
      await data.uploadExamText(courseId, examId, text);
      setText("");
      await onRefresh();
    } catch (error) {
      toast.error(t.saveFailed, { description: errorMessage(error) });
    } finally {
      setUploading(false);
    }
  };
  const start = async (parts: ("handout" | "quiz")[]) => {
    try {
      if (dirty) await save();
      const { id } = await data.createExamJob(courseId, examId, parts, {
        account: agent.account?.id ?? "claude",
        model: agent.model?.id,
        effort: agent.effort || undefined,
      });
      setJob(null);
      setJobId(id);
    } catch (error) {
      toast.error(t.generateFailed, { description: errorMessage(error) });
    }
  };
  const types = options.types ?? TYPES;

  return (
    <main className="mx-auto grid w-full max-w-4xl gap-5 px-4 py-6 sm:px-6 sm:py-8">
      <Panel title={t.scope} hint={t.scopeHint}>
        <fieldset className="grid max-h-72 gap-0.5 overflow-y-auto rounded-[8px] border border-border p-1 sm:grid-cols-2">
          <legend className="sr-only">{t.scope}</legend>
          {decks.map((deck) => (
            <label
              key={deck.id}
              className="flex cursor-pointer items-center gap-2.5 rounded-[6px] px-2.5 py-2 text-[13px] hover:bg-muted"
            >
              <input
                type="checkbox"
                className="size-3.5 accent-[var(--brand)]"
                checked={scope.includes(deck.id)}
                onChange={(event) =>
                  setScope((old) =>
                    event.target.checked
                      ? decks
                          .map((d) => d.id)
                          .filter((id) => id === deck.id || old.includes(id))
                      : old.filter((id) => id !== deck.id),
                  )
                }
              />
              <span className="min-w-0 flex-1 truncate">{deck.title}</span>
              <span className="text-[12px] text-muted-foreground">
                {deck.slideCount}
              </span>
            </label>
          ))}
        </fieldset>
        <p className="mt-2 text-[12px] text-muted-foreground">
          {t.selectedDecks(scope.length || decks.length)}
        </p>
      </Panel>

      <Panel title={t.pastPapers} hint={t.pastPapersHint}>
        {/* biome-ignore lint/a11y/noStaticElementInteractions: drop target; the button below is the keyboard path */}
        <div
          onDragOver={(event) => {
            event.preventDefault();
            setOver(true);
          }}
          onDragLeave={() => setOver(false)}
          onDrop={(event) => {
            event.preventDefault();
            setOver(false);
            void upload(Array.from(event.dataTransfer.files));
          }}
          className={cn(
            "flex flex-wrap items-center gap-3 rounded-[8px] border border-dashed px-4 py-4 transition-colors",
            over ? "border-brand bg-brand-soft" : "border-border",
          )}
        >
          <FileUp className="size-5 text-muted-foreground" aria-hidden />
          <Button
            variant="outline"
            size="sm"
            disabled={uploading}
            onClick={() => picker.current?.click()}
          >
            {uploading ? <LoaderCircle className="animate-spin" /> : null}
            {t.chooseFiles}
          </Button>
          <input
            ref={picker}
            type="file"
            multiple
            hidden
            tabIndex={-1}
            accept={ACCEPT}
            onChange={(event) => {
              const files = Array.from(event.target.files ?? []);
              event.target.value = "";
              void upload(files);
            }}
          />
        </div>
        <label className="mt-3 grid gap-1.5 text-[12.5px] font-medium">
          {t.pasteText}
          <textarea
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder={t.pastePlaceholder}
            rows={4}
            className="rounded-[6px] border border-border bg-background px-3 py-2 text-[13.5px] font-normal outline-none focus-visible:border-foreground/40"
          />
        </label>
        <div className="mt-2 flex justify-end">
          <Button
            size="sm"
            variant="outline"
            disabled={!text.trim() || uploading}
            onClick={() => void addText()}
          >
            {t.addText}
          </Button>
        </div>
        {detail.uploads.length ? (
          <ul className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
            {detail.uploads.map((upload) => (
              <li
                key={upload.name}
                className="group relative overflow-hidden rounded-[8px] border border-border bg-muted"
              >
                <a
                  href={upload.url}
                  target="_blank"
                  rel="noreferrer"
                  className="block aspect-[4/3]"
                >
                  {upload.kind === "image" ? (
                    <img
                      src={upload.url}
                      alt={upload.name}
                      loading="lazy"
                      className="size-full object-cover"
                    />
                  ) : (
                    <span className="grid size-full place-items-center text-muted-foreground">
                      <FileText className="size-6" aria-hidden />
                    </span>
                  )}
                </a>
                <div className="flex items-center gap-1 border-t border-hairline bg-card px-2 py-1">
                  <span className="min-w-0 flex-1 truncate text-[11.5px]">
                    {upload.name}
                  </span>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`${t.remove} ${upload.name}`}
                    onClick={async () => {
                      try {
                        const uploads = await data.deleteExamUpload(
                          courseId,
                          examId,
                          upload.name,
                        );
                        onChange({ ...detail, uploads });
                      } catch (error) {
                        toast.error(t.saveFailed, {
                          description: errorMessage(error),
                        });
                      }
                    }}
                  >
                    <Trash2 />
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-3 text-[12.5px] text-muted-foreground">
            {t.noUploads}
          </p>
        )}
      </Panel>

      <Panel title={t.options}>
        <div className="flex flex-wrap gap-4">
          {(
            [
              ["questionCount", t.questionCount, 100, "15"],
              ["minutes", t.minutes, 600, "60"],
            ] as const
          ).map(([key, label, max, placeholder]) => (
            <label key={key} className="grid gap-1.5 text-[12.5px] font-medium">
              {label}
              <input
                type="number"
                min={1}
                max={max}
                value={options[key] ?? ""}
                placeholder={placeholder}
                onChange={(event) =>
                  setOptions({
                    ...options,
                    [key]: event.target.value
                      ? Math.max(1, Math.min(max, Number(event.target.value)))
                      : undefined,
                  })
                }
                className="h-9 w-28 rounded-[6px] border border-border bg-background px-3 text-[14px] font-normal outline-none focus-visible:border-foreground/40"
              />
            </label>
          ))}
        </div>
        <fieldset className="mt-3 flex flex-wrap gap-x-4 gap-y-2">
          <legend className="mb-1.5 text-[12.5px] font-medium">
            {t.types}
          </legend>
          {TYPES.map((type) => (
            <label key={type} className="flex items-center gap-1.5 text-[13px]">
              <input
                type="checkbox"
                className="size-3.5 accent-[var(--brand)]"
                checked={types.includes(type)}
                onChange={(event) => {
                  const next = event.target.checked
                    ? TYPES.filter((x) => x === type || types.includes(x))
                    : types.filter((x) => x !== type);
                  if (next.length) setOptions({ ...options, types: next });
                }}
              />
              {t.typeNames[type]}
            </label>
          ))}
        </fieldset>
        <div className="mt-4 flex justify-end">
          <Button
            variant="outline"
            size="sm"
            disabled={!dirty || saving}
            onClick={() => void save().catch(() => {})}
          >
            {t.save}
          </Button>
        </div>
      </Panel>

      <Panel title={t.generate} hint={t.generateHint}>
        <div className="flex flex-wrap items-center gap-2">
          <ModelMenu
            accounts={agent.accounts ?? []}
            account={agent.account}
            model={agent.model}
            effort={agent.effort}
            onChoose={agent.choose}
            onManage={() => void agent.loadAccounts()}
            disabled={running}
          />
          <span className="flex-1" />
          <Button
            variant="ghost"
            size="sm"
            disabled={running}
            onClick={() => void start(["handout"])}
          >
            {t.generateHandout}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            disabled={running}
            onClick={() => void start(["quiz"])}
          >
            {t.generateQuiz}
          </Button>
          <Button
            disabled={running}
            onClick={() => void start(["handout", "quiz"])}
          >
            <Sparkles /> {t.generate}
          </Button>
        </div>
        {jobId && (
          <div aria-live="polite" className="mt-4">
            <div className="flex items-center gap-2 text-[13px]">
              {job?.state === "done" ? (
                <CircleCheck className="size-4 text-success" aria-hidden />
              ) : job && jobFinished(job) ? (
                <CircleAlert className="size-4 text-destructive" aria-hidden />
              ) : (
                <LoaderCircle
                  className="size-4 animate-spin text-brand"
                  aria-hidden
                />
              )}
              <span className="min-w-0 flex-1 truncate">
                {job?.state === "done"
                  ? `${t.generated}：${job.message}`
                  : job && jobFinished(job)
                    ? `${t.generateFailed}${job.error ? `：${job.error}` : ""}`
                    : job?.message || t.generating}
              </span>
              <span className="nums text-[12px] text-muted-foreground">
                {Math.round((job?.progress ?? 0) * 100)}%
              </span>
            </div>
            <div className="mt-2 h-1 overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-brand transition-[width] duration-500"
                style={{ width: `${Math.max(2, (job?.progress ?? 0) * 100)}%` }}
              />
            </div>
          </div>
        )}
      </Panel>
    </main>
  );
}
