import {
  BookOpen,
  Film,
  Library,
  Plus,
  Presentation,
  Search,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { AppShell } from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { EmptyState, LoadingState } from "@/components/ui/states";
import { data } from "@/lib/data";
import type { Course } from "@/lib/types";
import { errorMessage } from "@/lib/utils";

function CreateCourse({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!title.trim() || busy) return;
    setBusy(true);
    try {
      const course = (await data.createCourse(title.trim())) as { id?: string };
      onOpenChange(false);
      setTitle("");
      if (course?.id) navigate(`/c/${encodeURIComponent(course.id)}`);
    } catch (error) {
      toast.error("建立課程失敗", { description: errorMessage(error) });
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={submit} className="grid gap-4">
          <div className="grid gap-1.5">
            <DialogTitle>新增課程</DialogTitle>
            <DialogDescription>
              建立後把投影片和上課錄影拖進課程頁，就能開始產生筆記。
            </DialogDescription>
          </div>
          <label className="grid gap-1.5 text-[12.5px] font-medium">
            課程名稱
            <input
              autoFocus
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="例如：作業系統"
              className="h-9 rounded-[6px] border border-border bg-background px-3 text-[14px] font-normal outline-none focus-visible:border-foreground/40 focus-visible:ring-2 focus-visible:ring-ring/30"
            />
          </label>
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenChange(false)}
            >
              取消
            </Button>
            <Button type="submit" disabled={!title.trim() || busy}>
              {busy ? "建立中…" : "建立課程"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function Courses() {
  const [query, setQuery] = useState("");
  const [courses, setCourses] = useState<Course[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  useEffect(() => {
    data.courses().then(setCourses, (reason) => setError(errorMessage(reason)));
  }, []);
  const shown = courses?.filter((course) =>
    `${course.title} ${course.subtitle ?? ""}`
      .toLowerCase()
      .includes(query.trim().toLowerCase()),
  );
  return (
    <AppShell readOnly={!data.editable}>
      <main className="mx-auto w-full max-w-5xl px-4 py-10 sm:px-6 sm:py-14">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-[26px] font-semibold tracking-tight sm:text-[30px]">
              我的課程
            </h1>
            <p className="mt-1.5 text-[14px] text-muted-foreground">
              投影片、上課錄影和逐頁筆記放在一起讀；每句筆記都能跳回老師講到的那一秒。
            </p>
          </div>
          {data.editable && (
            <Button onClick={() => setCreating(true)}>
              <Plus /> 新增課程
            </Button>
          )}
        </div>
        {courses && courses.length > 3 && (
          <label className="mt-8 flex h-9 max-w-sm items-center gap-2 rounded-[6px] border border-border bg-card px-3 focus-within:border-foreground/40 focus-within:ring-2 focus-within:ring-ring/30">
            <Search className="size-4 text-muted-foreground" aria-hidden />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜尋課程"
              aria-label="搜尋課程"
              className="min-w-0 flex-1 bg-transparent text-[13.5px] outline-none"
            />
          </label>
        )}
        <div className="mt-8">
          {error ? (
            <EmptyState
              tone="error"
              icon={Library}
              title="無法讀取課程"
              description={error}
            />
          ) : !shown ? (
            <LoadingState label="讀取課程" />
          ) : !courses?.length ? (
            <EmptyState
              icon={Library}
              title="還沒有課程"
              description={
                data.editable
                  ? "新增一門課，再把投影片和錄影放進去。"
                  : "這個網站還沒有公開的課程。"
              }
              action={
                data.editable && (
                  <Button onClick={() => setCreating(true)}>
                    <Plus /> 新增課程
                  </Button>
                )
              }
            />
          ) : !shown.length ? (
            <EmptyState
              icon={Search}
              title="找不到符合的課程"
              description="換個關鍵字試試。"
            />
          ) : (
            <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {shown.map((course, index) => (
                <li
                  key={course.id}
                  className="rise-in"
                  style={{ animationDelay: `${Math.min(index, 6) * 40}ms` }}
                >
                  <Link
                    to={`/c/${encodeURIComponent(course.id)}`}
                    className="group flex h-full flex-col rounded-[10px] border border-border bg-card p-5 shadow-edge outline-none transition-[border-color,box-shadow] hover:border-foreground/20 hover:shadow-floating focus-visible:ring-2 focus-visible:ring-ring/40"
                  >
                    <span className="grid size-9 place-items-center rounded-[8px] bg-brand-soft text-brand">
                      <BookOpen className="size-4.5" aria-hidden />
                    </span>
                    <h2 className="mt-4 text-[16px] font-semibold leading-snug">
                      {course.title}
                    </h2>
                    {course.subtitle && (
                      <p className="mt-1 text-[13px] text-muted-foreground">
                        {course.subtitle}
                      </p>
                    )}
                    <div className="mt-auto flex flex-wrap gap-x-4 gap-y-1 pt-6 text-[12.5px] text-muted-foreground">
                      <span className="inline-flex items-center gap-1.5">
                        <Presentation className="size-3.5" aria-hidden />{" "}
                        {course.deckCount} 份投影片
                      </span>
                      <span className="inline-flex items-center gap-1.5">
                        <Film className="size-3.5" aria-hidden />{" "}
                        {course.videoCount} 部錄影
                      </span>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      </main>
      <CreateCourse open={creating} onOpenChange={setCreating} />
    </AppShell>
  );
}
