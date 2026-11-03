import { ChevronLeft, ChevronRight, Moon, Sun } from "lucide-react";
import { Fragment, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Hint } from "@/components/ui/tooltip";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";

export type Crumb = { label: string; to?: string };

function Logo() {
  return (
    <svg viewBox="0 0 20 20" className="size-5" aria-hidden>
      <rect
        x="1.5"
        y="2.5"
        width="11"
        height="15"
        rx="2"
        className="fill-brand"
      />
      <rect
        x="14.5"
        y="2.5"
        width="4"
        height="15"
        rx="1.5"
        className="fill-brand/35"
      />
      <path
        d="M4.5 7h5M4.5 10h5M4.5 13h3"
        className="stroke-brand-foreground"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
    </svg>
  );
}

/** Top bar shared by every page: brand, breadcrumbs, theme switch and page-specific actions. */
export function AppShell({
  crumbs = [],
  actions,
  readOnly,
  children,
  fill,
}: {
  crumbs?: Crumb[];
  actions?: ReactNode;
  readOnly?: boolean;
  children: ReactNode;
  /** Reader pages fill the viewport and scroll inside their panes. */
  fill?: boolean;
}) {
  const [theme, toggle] = useTheme();
  return (
    <div
      className={cn(
        "flex flex-col bg-background",
        fill ? "h-dvh overflow-hidden" : "min-h-dvh",
      )}
    >
      <header className="sticky top-0 z-30 flex h-12 shrink-0 items-center gap-2 border-b border-hairline bg-background/90 px-3 backdrop-blur-md sm:px-4">
        <Link
          to="/"
          className="flex shrink-0 items-center gap-2 rounded-[6px] px-1.5 py-1 text-[14px] font-semibold tracking-tight outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring/40"
        >
          <Logo />
          <span className={cn(crumbs.length > 0 && "max-sm:sr-only")}>
            Marginalia
          </span>
        </Link>
        {crumbs.length > 1 && crumbs.at(-2)?.to && (
          <Link
            to={crumbs.at(-2)?.to ?? "/"}
            aria-label={`回到${crumbs.at(-2)?.label}`}
            className="grid size-7 shrink-0 place-items-center rounded-[5px] text-muted-foreground hover:bg-muted hover:text-foreground md:hidden"
          >
            <ChevronLeft className="size-4" aria-hidden />
          </Link>
        )}
        <nav
          aria-label="目前位置"
          className="flex min-w-0 items-center text-[13px]"
        >
          {crumbs.map((crumb, index) => (
            <Fragment key={`${crumb.label}-${index}`}>
              <ChevronRight
                className={cn(
                  "mx-0.5 size-3.5 shrink-0 text-muted-foreground/60",
                  // Phones show a back arrow to the parent instead of the chevron trail.
                  crumbs.length > 1 && "max-md:hidden",
                )}
                aria-hidden
              />
              {crumb.to ? (
                <Link
                  to={crumb.to}
                  className={cn(
                    "truncate rounded-[5px] px-1.5 py-1 text-muted-foreground hover:bg-muted hover:text-foreground",
                    index < crumbs.length - 1 && "max-md:hidden",
                  )}
                >
                  {crumb.label}
                </Link>
              ) : (
                <span
                  className="truncate px-1.5 font-medium"
                  aria-current="page"
                >
                  {crumb.label}
                </span>
              )}
            </Fragment>
          ))}
        </nav>
        <div className="ml-auto flex shrink-0 items-center gap-1">
          {readOnly && (
            <Hint label="這是公開的閱讀版，無法編輯或使用 AI 助教">
              <Badge className="max-sm:hidden">唯讀</Badge>
            </Hint>
          )}
          {actions}
          <Hint label={theme === "dark" ? "切換成淺色" : "切換成深色"}>
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={toggle}
              aria-label={theme === "dark" ? "切換成淺色" : "切換成深色"}
            >
              {theme === "dark" ? <Sun /> : <Moon />}
            </Button>
          </Hint>
        </div>
      </header>
      {children}
    </div>
  );
}
