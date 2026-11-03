import { ClipboardList, GraduationCap, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { data } from "@/lib/data";
import type { ExamSummary } from "@/lib/exam-types";
import { useT } from "@/lib/i18n";
import { errorMessage } from "@/lib/utils";

/** The course page's「考前複習」section: one card per exam, plus creating one in local mode. */
export function ExamList({ courseId }: { courseId: string }) {
  const { t } = useT();
  const navigate = useNavigate();
  const [exams, setExams] = useState<ExamSummary[] | null>(null);
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    data.exams(courseId).then(setExams, () => setExams([]));
  }, [courseId]);
  if (exams === null || (!exams.length && !data.editable)) return null;
  const base = `/c/${encodeURIComponent(courseId)}/exam`;
  const create = async () => {
    if (!title.trim()) return;
    setBusy(true);
    try {
      const exam = await data.createExam(courseId, title.trim());
      navigate(`${base}/${encodeURIComponent(exam.id)}/setup`);
    } catch (error) {
      toast.error(t.saveFailed, { description: errorMessage(error) });
    } finally {
      setBusy(false);
    }
  };
  return (
    <section aria-labelledby="exams-title">
      <div className="mb-3 flex items-center gap-2">
        <h2 id="exams-title" className="text-[15px] font-semibold">
          {t.examPrep}
        </h2>
        <span className="text-[12.5px] text-muted-foreground max-sm:hidden">
          {t.examPrepHint}
        </span>
        {data.editable && (
          <Button
            variant="outline"
            size="sm"
            className="ml-auto"
            onClick={() => setCreating(true)}
          >
            <Plus /> {t.newExam}
          </Button>
        )}
      </div>
      {exams.length ? (
        <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {exams.map((exam) => (
            <li key={exam.id}>
              <Link
                to={`${base}/${encodeURIComponent(exam.id)}`}
                className="flex items-center gap-3 rounded-[10px] border border-border bg-card p-3.5 shadow-edge outline-none transition-[border-color,box-shadow] hover:border-foreground/20 hover:shadow-floating focus-visible:ring-2 focus-visible:ring-ring/40"
              >
                <span className="grid size-9 shrink-0 place-items-center rounded-[8px] bg-brand-soft text-brand">
                  <GraduationCap className="size-4.5" aria-hidden />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[14px] font-medium">
                    {exam.title}
                  </span>
                  <span className="block text-[12px] text-muted-foreground">
                    {t.sections(exam.sectionCount)} ·{" "}
                    {t.questions(exam.questionCount)}
                  </span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <button
          type="button"
          onClick={() => setCreating(true)}
          className="flex w-full items-center gap-3 rounded-[10px] border border-dashed border-border px-4 py-5 text-left hover:bg-muted/50"
        >
          <ClipboardList className="size-5 text-muted-foreground" aria-hidden />
          <span>
            <span className="block text-[13.5px] font-medium">{t.noExams}</span>
            <span className="block text-[12.5px] text-muted-foreground">
              {t.noExamsHint}
            </span>
          </span>
        </button>
      )}
      <Dialog open={creating} onOpenChange={setCreating}>
        <DialogContent>
          <DialogTitle>{t.newExam}</DialogTitle>
          <DialogDescription>{t.examPrepHint}</DialogDescription>
          <label className="grid gap-1.5 text-[12.5px] font-medium">
            {t.examTitle}
            <input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") void create();
              }}
              placeholder={t.examTitlePlaceholder}
              className="h-9 rounded-[6px] border border-border bg-background px-3 text-[14px] font-normal outline-none focus-visible:border-foreground/40"
            />
          </label>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setCreating(false)}>
              {t.cancel}
            </Button>
            <Button
              disabled={!title.trim() || busy}
              onClick={() => void create()}
            >
              {t.create}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </section>
  );
}
