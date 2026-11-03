import { CircleAlert, Languages } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";
import { AppShell } from "@/components/AppShell";
import { ExamSetup } from "@/components/exam/ExamSetup";
import { Handout } from "@/components/exam/Handout";
import { QuizView } from "@/components/exam/Quiz";
import { Button } from "@/components/ui/button";
import { EmptyState, LoadingState } from "@/components/ui/states";
import { data } from "@/lib/data";
import type { ExamDetail } from "@/lib/exam-types";
import { useT } from "@/lib/i18n";
import type { CourseDetail } from "@/lib/types";
import { cn, errorMessage } from "@/lib/utils";

const TABS = ["setup", "handout", "quiz"] as const;
type Tab = (typeof TABS)[number];

/** One exam: setup (local only), the cram handout and the mock exam (docs/architecture.md, Exam prep). */
export function Exam() {
  const { courseId = "", examId = "", tab } = useParams();
  const { t, toggle } = useT();
  const navigate = useNavigate();
  const [course, setCourse] = useState<CourseDetail | null>(null);
  const [exam, setExam] = useState<ExamDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refresh = useCallback(
    () => data.exam(courseId, examId).then(setExam),
    [courseId, examId],
  );
  useEffect(() => {
    setExam(null);
    setError(null);
    Promise.all([data.course(courseId).then(setCourse), refresh()]).catch(
      (reason) => setError(errorMessage(reason)),
    );
  }, [courseId, refresh]);

  const base = `/c/${encodeURIComponent(courseId)}/exam/${encodeURIComponent(examId)}`;
  const tabs = TABS.filter((name) => data.editable || name !== "setup");
  if (exam && !tab)
    return (
      <Navigate
        replace
        to={`${base}/${exam.handout.length || !data.editable ? "handout" : "setup"}`}
      />
    );
  const current: Tab = tabs.includes(tab as Tab) ? (tab as Tab) : "handout";
  const label = { setup: t.tabSetup, handout: t.tabHandout, quiz: t.tabQuiz };

  return (
    <AppShell
      readOnly={!data.editable}
      crumbs={[
        {
          label: course?.info.title ?? "…",
          to: `/c/${encodeURIComponent(courseId)}`,
        },
        { label: exam?.exam.title ?? t.examPrep },
      ]}
      actions={
        <Button
          variant="ghost"
          size="sm"
          onClick={toggle}
          aria-label="Language"
        >
          <Languages /> {t.language}
        </Button>
      }
    >
      {error ? (
        <EmptyState
          tone="error"
          icon={CircleAlert}
          title={t.notFound}
          description={error}
          action={
            <Button
              variant="outline"
              render={<Link to={`/c/${encodeURIComponent(courseId)}`} />}
            >
              {t.backToCourse}
            </Button>
          }
        />
      ) : !exam || !course ? (
        <LoadingState label={t.loading} />
      ) : (
        <>
          <nav
            aria-label={exam.exam.title}
            className="sticky top-12 z-20 flex gap-1 border-b border-hairline bg-background/90 px-3 backdrop-blur-md sm:px-6"
          >
            {tabs.map((name) => (
              <button
                key={name}
                type="button"
                aria-current={current === name ? "page" : undefined}
                onClick={() => navigate(`${base}/${name}`)}
                className={cn(
                  "-mb-px border-b-2 px-3 py-2.5 text-[13.5px] outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring/40",
                  current === name
                    ? "border-brand font-medium text-foreground"
                    : "border-transparent text-muted-foreground hover:text-foreground",
                )}
              >
                {label[name]}
              </button>
            ))}
          </nav>
          {current === "setup" ? (
            <ExamSetup
              courseId={courseId}
              course={course}
              detail={exam}
              onChange={setExam}
              onRefresh={refresh}
            />
          ) : current === "handout" ? (
            <Handout courseId={courseId} course={course} detail={exam} />
          ) : (
            <QuizView courseId={courseId} course={course} detail={exam} />
          )}
        </>
      )}
    </AppShell>
  );
}
