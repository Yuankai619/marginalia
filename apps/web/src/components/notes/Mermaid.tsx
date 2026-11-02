import { Maximize2, TriangleAlert } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { stripExternal } from "@/lib/safe-svg";
import { useDark } from "@/lib/theme";
import { useDebounced } from "@/lib/use-stored";
import { Lightbox } from "./Lightbox";

type MermaidApi = typeof import("mermaid").default;
let loading: Promise<MermaidApi> | null = null;
let queue: Promise<unknown> = Promise.resolve();
// Rendered SVGs by theme and source, so revisiting a slide or toggling the theme back does not lay out again.
const rendered = new Map<string, Promise<string>>();

// mermaid keeps one global config, so renders run one at a time with the theme set right before each.
function render(id: string, code: string, dark: boolean) {
  const key = `${dark ? "dark" : "light"}\n${code}`;
  const cached = rendered.get(key);
  if (cached) return cached;
  loading ??= import("mermaid").then((module) => module.default);
  const job = queue.then(async () => {
    const mermaid = await loading!;
    // Labels are measured at render time; measuring with a fallback font clips them once Geist loads.
    await document.fonts?.ready;
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: "strict",
      theme: dark ? "dark" : "neutral",
      fontFamily: getComputedStyle(document.body).fontFamily,
      flowchart: { htmlLabels: true, curve: "basis" },
    });
    try {
      // Remote loads during layout (image shapes, label <img>) are blocked by the CSP (vite.config.ts).
      return stripExternal((await mermaid.render(id, code)).svg);
    } finally {
      // A failed render leaves its scratch node (with the error bomb icon) in <body>.
      document.getElementById(`d${id}`)?.remove();
    }
  });
  queue = job.catch(() => undefined);
  rendered.set(key, job);
  job.catch(() => rendered.delete(key));
  return job;
}

export function Mermaid({ code: source }: { code: string }) {
  const dark = useDark();
  // Typing inside a diagram in the editor preview would otherwise queue one full layout per keystroke.
  const code = useDebounced(source, 250);
  const id = `mermaid-${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
  const [state, setState] = useState<
    { svg: string } | { error: string } | null
  >(null);
  const [zoom, setZoom] = useState(false);
  useEffect(() => {
    let active = true;
    render(id, code, dark).then(
      (svg) => active && setState({ svg }),
      (error: unknown) =>
        active &&
        setState({
          error: error instanceof Error ? error.message : String(error),
        }),
    );
    return () => {
      active = false;
    };
  }, [id, code, dark]);

  if (state && "error" in state)
    return (
      <div className="mermaid-block overflow-hidden rounded-[8px] border border-warning/40">
        <p className="flex items-center gap-1.5 bg-warning/10 px-3 py-1.5 text-[12px] font-medium text-warning">
          <TriangleAlert className="size-3.5" aria-hidden />
          圖表語法有誤，先顯示原始碼
        </p>
        <pre className="!m-0 !rounded-none !border-0">
          <code>{code}</code>
        </pre>
        <p className="border-t border-hairline px-3 py-1.5 font-mono text-[11px] text-muted-foreground">
          {state.error.split("\n")[0].slice(0, 200)}
        </p>
      </div>
    );
  return (
    <figure className="mermaid-block group relative !mx-0 rounded-[8px] border border-hairline bg-card px-3 py-4">
      {state ? (
        <>
          <button
            type="button"
            onClick={() => setZoom(true)}
            aria-label="放大圖表"
            className="flex w-full cursor-zoom-in justify-center [&_svg]:h-auto [&_svg]:max-w-full"
            // strict mode sanitizes labels with DOMPurify; stripExternal then drops every reference outside the SVG.
            // biome-ignore lint/security/noDangerouslySetInnerHtml: sanitized mermaid output (see safe-svg.ts)
            dangerouslySetInnerHTML={{ __html: state.svg }}
          />
          <span
            aria-hidden
            className="pointer-events-none absolute top-2 right-2 grid size-6 place-items-center rounded-[5px] bg-background/80 text-muted-foreground opacity-0 shadow-edge transition-opacity group-hover:opacity-100"
          >
            <Maximize2 className="size-3" />
          </span>
          <Lightbox open={zoom} onOpenChange={setZoom} label="圖表">
            <div
              className="flex justify-center [&_svg]:h-auto [&_svg]:max-h-[80vh] [&_svg]:w-full [&_svg]:max-w-none"
              // biome-ignore lint/security/noDangerouslySetInnerHtml: sanitized mermaid output (see safe-svg.ts)
              dangerouslySetInnerHTML={{ __html: state.svg }}
            />
          </Lightbox>
        </>
      ) : (
        <div
          role="status"
          className="h-24 animate-pulse rounded-[6px] bg-muted/60"
          aria-label="繪製圖表中"
        />
      )}
    </figure>
  );
}
