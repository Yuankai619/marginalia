import {
  ChevronRight,
  CircleCheck,
  ClipboardCheck,
  Info,
  Quote,
  Wrench,
} from "lucide-react";
import { useState } from "react";
import { Markdown, type NoteSource } from "@/components/Markdown";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/states";
import {
  checkSummary,
  type Finding,
  REVIEWERS,
  type ReviewView,
  SEVERITY,
} from "@/lib/review";
import type { VideoTime } from "@/lib/types";
import { cn } from "@/lib/utils";

const CHECKS_INTRO =
  "三位 AI 檢查員會對照投影片和老師的講解看這頁筆記：內容對不對、沒有基礎的人讀不讀得懂、有沒有漏掉老師講的重點。發現問題會自動改好筆記，改不好的才留給你。";

type Props = {
  view: ReviewView | null;
  source: NoteSource;
  onTime: (target: VideoTime) => void;
  canPlay: (video: string) => boolean;
};

function FindingCard({
  finding,
  muted,
  ...props
}: { finding: Finding; muted?: boolean } & Omit<Props, "view">) {
  const reviewer = REVIEWERS[finding.reviewer] ?? {
    name: finding.reviewer,
    role: "",
  };
  const severity = SEVERITY[finding.severity];
  return (
    <article
      className={cn(
        "rounded-[8px] border bg-card p-3.5 shadow-edge",
        !muted && finding.severity === "high"
          ? "border-destructive/35"
          : "border-border",
      )}
    >
      <header className="flex flex-wrap items-center gap-1.5">
        <span className="text-[12.5px] font-medium" title={reviewer.role}>
          {reviewer.name}
        </span>
        {!muted && <Badge tone={severity.tone}>{severity.label}</Badge>}
      </header>
      {finding.quote && (
        <blockquote className="mt-2.5 flex gap-2 rounded-[6px] bg-muted/70 px-2.5 py-2 text-muted-foreground">
          <Quote className="mt-1 size-3 shrink-0 opacity-60" aria-hidden />
          <Markdown
            markdown={finding.quote}
            variant="inline"
            className="text-[12.5px] text-muted-foreground"
            {...props}
          />
        </blockquote>
      )}
      <div className="mt-2.5 grid gap-2">
        <Markdown
          markdown={finding.problem}
          variant="inline"
          className="text-[13px]"
          {...props}
        />
        {finding.fix && (
          <div className="flex gap-2 border-t border-hairline pt-2">
            <Wrench
              className="mt-1 size-3.5 shrink-0 text-muted-foreground"
              aria-label="建議"
            />
            <Markdown
              markdown={finding.fix}
              variant="inline"
              className="text-[13px] text-muted-foreground"
              {...props}
            />
          </div>
        )}
      </div>
    </article>
  );
}

function Group({
  title,
  hint,
  items,
  defaultOpen,
  muted,
  ...props
}: {
  title: string;
  hint: string;
  items: Finding[];
  defaultOpen: boolean;
  muted?: boolean;
} & Omit<Props, "view">) {
  const [open, setOpen] = useState(defaultOpen);
  if (!items.length) return null;
  return (
    <section>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-1.5 rounded-[6px] px-1 py-1.5 text-left outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring/30"
      >
        <ChevronRight
          className={cn(
            "size-3.5 text-muted-foreground transition-transform",
            open && "rotate-90",
          )}
          aria-hidden
        />
        <span className="text-[13px] font-medium">{title}</span>
        <span className="text-[12px] text-muted-foreground">{hint}</span>
      </button>
      {open && (
        <div className="mt-2 grid gap-2">
          {items.map((finding, index) => (
            <FindingCard
              key={`${finding.reviewer}-${index}`}
              finding={finding}
              muted={muted}
              {...props}
            />
          ))}
        </div>
      )}
    </section>
  );
}

export function NoteChecks({ view, ...props }: Props) {
  const intro = (
    <p className="flex gap-2 rounded-[8px] bg-muted/60 px-3 py-2.5 text-[12.5px] leading-relaxed text-muted-foreground">
      <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
      {CHECKS_INTRO}
    </p>
  );
  if (!view)
    return (
      <div className="grid gap-4">
        {intro}
        <EmptyState
          icon={ClipboardCheck}
          title="這頁還沒做過筆記檢查"
          description="產生筆記時會自動檢查；也可以在 AI 助教選「檢查筆記」請它看一遍。"
          className="py-10"
        />
      </div>
    );
  if (view.stale)
    return (
      <div className="grid gap-4">
        {intro}
        <EmptyState
          icon={ClipboardCheck}
          title="筆記在檢查之後改過了"
          description="之前的檢查意見對應的是舊版內容，所以先不顯示。下次產生或重新檢查筆記時會再檢查一次。"
          className="py-10"
        />
      </div>
    );
  const summary = checkSummary(view);
  const warning = summary.tone === "warning";
  return (
    <div className="grid gap-4">
      {intro}
      <div
        className={cn(
          "flex items-start gap-2.5 rounded-[8px] border px-3.5 py-3",
          warning
            ? "border-warning/40 bg-warning/8"
            : "border-success/30 bg-success/8",
        )}
      >
        {warning ? (
          <Info className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
        ) : (
          <CircleCheck
            className="mt-0.5 size-4 shrink-0 text-success"
            aria-hidden
          />
        )}
        <div className="min-w-0 text-[13px] leading-relaxed">
          <p className="font-medium">{summary.title}</p>
          <p className="text-[12px] text-muted-foreground">
            {view.reviewedAt &&
              `檢查於 ${new Date(view.reviewedAt).toLocaleString("zh-TW", { dateStyle: "medium", timeStyle: "short" })}`}
            {view.failed.length > 0 &&
              "・下次產生或重新檢查筆記時會再跑一次，下面的意見可能不完整"}
          </p>
        </div>
      </div>
      {view.open.length > 0 && (
        <div className="grid gap-2">
          {view.open.map((finding, index) => (
            <FindingCard
              key={`${finding.reviewer}-${index}`}
              finding={finding}
              {...props}
            />
          ))}
        </div>
      )}
      <Group
        title={`已自動修正 ${view.fixed.length} 項`}
        hint="檢查員指出、修訂筆記時已處理的地方"
        items={view.fixed}
        defaultOpen={false}
        muted
        {...props}
      />
      <Group
        title={`小建議 ${view.suggestions.length} 項`}
        hint="不影響理解，沒有自動修改"
        items={view.suggestions}
        defaultOpen={false}
        {...props}
      />
    </div>
  );
}
