import { BookOpen, Check, PenLine, Plus } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useBlocker } from "react-router-dom";
import { toast } from "sonner";
import { Markdown } from "@/components/Markdown";
import { NoteEditor, type SlidePick } from "@/components/notes/NoteEditor";
import { Button } from "@/components/ui/button";
import { EmptyState, LoadingState } from "@/components/ui/states";
import { type ImageSource, UPLOAD_PLACEHOLDER } from "@/lib/assets";
import { data } from "@/lib/data";
import type { ExamDetail, Section } from "@/lib/exam-types";
import { useT } from "@/lib/i18n";
import type { CourseDetail } from "@/lib/types";
import { cn, errorMessage } from "@/lib/utils";

type Draft = { section: number; markdown: string; saved: string };

/** The cram handout: a table of contents beside every section in reading order, each editable like a note. */
export function Handout({
  courseId,
  course,
  detail,
  source,
}: {
  courseId: string;
  course: CourseDetail;
  detail: ExamDetail;
  source: ImageSource;
}) {
  const { t } = useT();
  const examId = detail.exam.id;
  const [sections, setSections] = useState<Section[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  const [active, setActive] = useState<number | null>(null);
  const [slides, setSlides] = useState<SlidePick[]>([]);
  const main = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setSections(null);
    data
      .handout(courseId, examId)
      .then(setSections, (reason) => setError(errorMessage(reason)));
  }, [courseId, examId]);

  // Slide thumbnails for the editor's「插入投影片截圖」, loaded the first time someone edits.
  const editing = draft !== null;
  // biome-ignore lint/correctness/useExhaustiveDependencies: load once per exam when editing starts
  useEffect(() => {
    if (!editing || slides.length) return;
    const ids = detail.exam.scope.decks.length
      ? detail.exam.scope.decks
      : course.decks.map((deck) => deck.id);
    Promise.all(ids.map((id) => data.deck(courseId, id).catch(() => null)))
      .then((decks) =>
        setSlides(
          decks.flatMap((value) =>
            value
              ? value.slides.map((slide) => ({
                  deck: value.deck.id,
                  deckTitle: value.deck.title,
                  index: slide.index,
                  title: slide.title,
                  thumb: slide.thumb,
                }))
              : [],
          ),
        ),
      )
      .catch(() => {});
  }, [editing]);

  // Highlight the section being read in the table of contents.
  useEffect(() => {
    if (!sections?.length) return;
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0])
          setActive(Number((visible[0].target as HTMLElement).dataset.section));
      },
      { rootMargin: "-100px 0px -60% 0px" },
    );
    for (const node of main.current?.querySelectorAll("[data-section]") ?? [])
      observer.observe(node);
    return () => observer.disconnect();
  }, [sections]);

  const dirty = draft !== null && draft.markdown !== draft.saved;
  // Switching tabs or leaving the exam is an in-app navigation, which beforeunload does not see.
  const blocker = useBlocker(dirty || saving);
  useEffect(() => {
    if (blocker.state !== "blocked") return;
    if (window.confirm(t.unsavedLeave)) blocker.proceed();
    else blocker.reset();
  }, [blocker, t]);
  useEffect(() => {
    if (!dirty) return;
    const unload = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", unload);
    return () => window.removeEventListener("beforeunload", unload);
  }, [dirty]);

  const save = async (close: boolean) => {
    if (!draft || saving) return;
    if (UPLOAD_PLACEHOLDER.test(draft.markdown)) {
      toast.error(t.saveFailed);
      return;
    }
    setSaving(true);
    try {
      const meta = await data.saveSection(
        courseId,
        examId,
        draft.section,
        draft.markdown,
      );
      setSections((old) => {
        const next = (old ?? []).filter((s) => s.section !== draft.section);
        next.push({
          ...meta,
          section: draft.section,
          title:
            old?.find((s) => s.section === draft.section)?.title ?? meta.title,
          markdown: draft.markdown,
        });
        return next.sort((a, b) => a.section - b.section);
      });
      setDraft(close ? null : { ...draft, saved: draft.markdown });
    } catch (reason) {
      toast.error(t.saveFailed, { description: errorMessage(reason) });
    } finally {
      setSaving(false);
    }
  };
  const open = (section: number, markdown: string) => {
    if (dirty && !window.confirm(t.unsavedLeave)) return;
    setDraft({ section, markdown, saved: markdown });
  };

  const editor = (onCancel: () => void) =>
    draft && (
      <SectionEditor
        draft={draft}
        saving={saving}
        source={source}
        slides={slides}
        onChange={(markdown) => setDraft({ ...draft, markdown })}
        onSave={() => void save(false)}
        onDone={() => void save(true)}
        onCancel={onCancel}
        upload={(file, signal) =>
          data.uploadExamAsset(courseId, examId, file, signal)
        }
      />
    );

  if (error)
    return <EmptyState tone="error" title={t.saveFailed} description={error} />;
  if (!sections) return <LoadingState label={t.loading} />;
  if (!sections.length && !data.editable)
    return <EmptyState icon={BookOpen} title={t.noHandout} className="py-16" />;

  return (
    <div className="mx-auto flex w-full max-w-6xl gap-8 px-4 py-6 sm:px-6 sm:py-8">
      <nav
        aria-label={t.contents}
        className="sticky top-28 hidden max-h-[calc(100dvh-8rem)] w-56 shrink-0 self-start overflow-y-auto lg:block"
      >
        <p className="mb-2 text-[12px] font-medium text-muted-foreground">
          {t.contents}
        </p>
        <ol className="grid gap-0.5 text-[13px]">
          {sections.map((section) => (
            <li key={section.section}>
              <a
                href={`#section-${section.section}`}
                className={cn(
                  "block rounded-[5px] px-2 py-1.5 leading-snug hover:bg-muted",
                  active === section.section
                    ? "bg-muted font-medium text-foreground"
                    : "text-muted-foreground",
                )}
              >
                <span className="nums mr-1.5 text-muted-foreground/70">
                  {section.section}.
                </span>
                {section.title}
              </a>
            </li>
          ))}
        </ol>
      </nav>
      <div ref={main} className="min-w-0 flex-1">
        <details className="mb-5 rounded-[8px] border border-border bg-card lg:hidden">
          <summary className="cursor-pointer px-3 py-2 text-[13px] font-medium">
            {t.contents}
          </summary>
          <ol className="grid gap-0.5 border-t border-hairline p-2 text-[13px]">
            {sections.map((section) => (
              <li key={section.section}>
                <a
                  href={`#section-${section.section}`}
                  className="block rounded-[5px] px-2 py-1.5 hover:bg-muted"
                >
                  {section.section}. {section.title}
                </a>
              </li>
            ))}
          </ol>
        </details>
        {!sections.length && (
          <EmptyState
            icon={BookOpen}
            title={t.noHandout}
            description={t.noHandoutHint}
            className="rounded-[10px] border border-dashed border-border py-12"
          />
        )}
        {sections.map((section) => (
          <section
            key={section.section}
            id={`section-${section.section}`}
            data-section={section.section}
            className="scroll-mt-28 border-b border-hairline pb-8 pt-2 last:border-b-0"
          >
            <header className="mb-3 flex items-start gap-3">
              <h2 className="min-w-0 flex-1 text-[21px] font-semibold leading-snug tracking-tight">
                <span className="nums mr-2 text-muted-foreground/70">
                  {section.section}.
                </span>
                {section.title}
              </h2>
              {data.editable && draft?.section !== section.section && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => open(section.section, section.markdown)}
                >
                  <PenLine /> {t.edit}
                </Button>
              )}
            </header>
            {draft?.section === section.section ? (
              editor(() => {
                if (!dirty || window.confirm(t.unsavedLeave)) setDraft(null);
              })
            ) : (
              <Markdown markdown={section.markdown} source={source} />
            )}
          </section>
        ))}
        {data.editable &&
          (draft && !sections.some((s) => s.section === draft.section) ? (
            <section className="pt-4">{editor(() => setDraft(null))}</section>
          ) : (
            <div className="pt-4">
              <Button
                variant="outline"
                size="sm"
                onClick={() =>
                  open(
                    (sections.at(-1)?.section ?? 0) + 1,
                    `## ${t.addSection}\n\n`,
                  )
                }
              >
                <Plus /> {t.addSection}
              </Button>
            </div>
          ))}
      </div>
    </div>
  );
}

function SectionEditor({
  draft,
  saving,
  source,
  slides,
  onChange,
  onSave,
  onDone,
  onCancel,
  upload,
}: {
  draft: Draft;
  saving: boolean;
  source: ImageSource;
  slides: SlidePick[];
  onChange: (markdown: string) => void;
  onSave: () => void;
  onDone: () => void;
  onCancel: () => void;
  upload: (file: File, signal: AbortSignal) => Promise<string>;
}) {
  const { t } = useT();
  return (
    <div className="overflow-hidden rounded-[10px] border border-border bg-card shadow-edge">
      <div className="flex h-[min(42rem,75dvh)] flex-col">
        <NoteEditor
          value={draft.markdown}
          onChange={onChange}
          onSave={onSave}
          source={source}
          uploadImage={upload}
          slides={slides}
          slideLabels={{ insert: t.insertSlide, filter: t.filterSlides }}
          placeholderText="Markdown"
        />
      </div>
      <div className="flex items-center justify-end gap-2 border-t border-hairline px-3 py-2">
        <span className="mr-auto text-[12px] text-muted-foreground">
          {saving ? t.saving : ""}
        </span>
        <Button variant="ghost" size="sm" onClick={onCancel}>
          {t.cancel}
        </Button>
        <Button size="sm" disabled={saving} onClick={onDone}>
          <Check /> {t.done}
        </Button>
      </div>
    </div>
  );
}
