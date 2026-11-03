import "katex/dist/katex.min.css";
import { Play } from "lucide-react";
import { memo, type ReactElement, useMemo, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeKatex from "rehype-katex";
import rehypeRaw from "rehype-raw";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { type ImageSource, imageUrl } from "@/lib/assets";
import { remarkAlerts, remarkHighlight } from "@/lib/remark-notes";
import type { VideoTime } from "@/lib/types";
import { cn } from "@/lib/utils";
import { parseVideoLink, safeNoteUrl } from "@/lib/video";
import { Lightbox } from "./notes/Lightbox";
import { Mermaid } from "./notes/Mermaid";

type HtmlNode = {
  type: string;
  tagName?: string;
  properties?: Record<string, unknown>;
  children?: HtmlNode[];
};

const safeTags = new Set([
  "a",
  "blockquote",
  "br",
  "code",
  "del",
  "details",
  "div",
  "em",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "hr",
  "img",
  "input",
  "kbd",
  "li",
  "mark",
  "ol",
  "p",
  "pre",
  "span",
  "strong",
  "sub",
  "summary",
  "sup",
  "table",
  "tbody",
  "td",
  "th",
  "thead",
  "tr",
  "ul",
]);
const removeWithChildren = new Set([
  "iframe",
  "script",
  "style",
  "svg",
  "math",
  "object",
]);
// Classes our own remark plugins, remark-gfm and remark-math emit; anything else in raw HTML is dropped.
const safeClass =
  /^(alert|alert-(note|tip|important|warning|caution|title)|language-[\w-]+|math-inline|math-display|contains-task-list|task-list-item)$/;

const sanitizeNoteHtml = () => (tree: HtmlNode) => {
  const clean = (node: HtmlNode): HtmlNode[] => {
    if (node.type === "comment") return [];
    if (node.children) node.children = node.children.flatMap(clean);
    if (node.type !== "element") return [node];
    const tag = node.tagName ?? "";
    if (removeWithChildren.has(tag)) return [];
    if (!safeTags.has(tag)) return node.children ?? [];
    const props = node.properties ?? {};
    const next: Record<string, unknown> = {};
    const classes = (
      Array.isArray(props.className) ? props.className : []
    ).filter(
      (name): name is string =>
        typeof name === "string" && safeClass.test(name),
    );
    if (classes.length) next.className = classes;
    if (tag === "a" && typeof props.href === "string")
      next.href = safeNoteUrl(props.href);
    if (tag === "img") {
      // Resolved against the deck's assets/ folder in the img component; anything else renders as alt text.
      if (typeof props.src === "string") next.src = props.src;
      if (typeof props.alt === "string") next.alt = props.alt;
    }
    if (tag === "input") {
      if (props.type !== "checkbox") return [];
      next.type = "checkbox";
      next.checked = props.checked === true;
      next.disabled = true;
    }
    if (tag === "details" && props.open) next.open = true;
    if (
      (tag === "td" || tag === "th") &&
      ["left", "center", "right"].includes(String(props.align))
    )
      next.align = props.align;
    if (tag === "div" && !classes.length) return node.children ?? [];
    node.properties = next;
    return [node];
  };
  tree.children = tree.children?.flatMap(clean);
};

const keepUrl = (url: string) => url; // hrefs are vetted by the sanitizer, image paths by assetUrl
const remarkPlugins = [remarkGfm, remarkMath, remarkAlerts, remarkHighlight];
const rehypePlugins = [rehypeRaw, sanitizeNoteHtml, rehypeKatex];

export type NoteSource = ImageSource;

function Figure({ src, alt }: { src: string; alt: string }) {
  const [zoom, setZoom] = useState(false);
  const [failed, setFailed] = useState(false);
  if (failed)
    return (
      <span className="inline-block rounded-[6px] border border-dashed border-border px-3 py-2 text-[12px] text-muted-foreground">
        圖片無法載入：{alt || src}
      </span>
    );
  // Spans, not <figure>: an image may sit inside a paragraph.
  return (
    <span className="figure">
      <button
        type="button"
        onClick={() => setZoom(true)}
        aria-label={`放大圖片：${alt}`}
      >
        <img
          src={src}
          alt={alt}
          loading="lazy"
          onError={() => setFailed(true)}
        />
      </button>
      {alt && <span className="figcaption">{alt}</span>}
      <Lightbox open={zoom} onOpenChange={setZoom} label="圖片" caption={alt}>
        <img
          src={src}
          alt={alt}
          className="mx-auto max-h-full max-w-full object-contain"
        />
      </Lightbox>
    </span>
  );
}

function MarkdownView({
  markdown,
  onTime,
  canPlay,
  source,
  variant = "note",
  className,
}: {
  markdown: string;
  onTime?: (target: VideoTime) => void;
  canPlay?: (video: string) => boolean;
  /** Where `assets/…` images resolve; without it images show as alt text. */
  source?: NoteSource;
  variant?: "note" | "chat" | "inline";
  className?: string;
}) {
  // react-markdown uses these as component types: a new map each render would remount every diagram and image.
  const components = useMemo<Components>(
    () => ({
      a: ({ href, children }) => {
        const found = parseVideoLink(href ?? "");
        if (found)
          return onTime && canPlay?.(found.video) ? (
            <button
              type="button"
              className="timestamp"
              onClick={() => onTime(found)}
              title="從這裡播放上課影片"
            >
              <Play className="size-[0.9em] fill-current" aria-hidden />
              {children}
            </button>
          ) : (
            <span className="timestamp" title="影片未提供，僅顯示時間">
              {children}
            </span>
          );
        return href ? (
          <a href={href} target="_blank" rel="noreferrer noopener">
            {children}
          </a>
        ) : (
          <span>{children}</span>
        );
      },
      img: ({ src, alt }) => {
        const url =
          source && typeof src === "string" ? imageUrl(source, src) : null;
        if (!url)
          return (
            <span className="text-muted-foreground">
              {alt ? `［圖：${alt}］` : ""}
            </span>
          );
        return <Figure src={url} alt={alt ?? ""} />;
      },
      p: ({ children, className }) => <p className={className}>{children}</p>,
      pre: ({ children }) => {
        const code = children as ReactElement<{
          className?: string;
          children?: unknown;
        }>;
        if (code?.props?.className?.includes("language-mermaid"))
          return (
            <Mermaid
              code={String(code.props.children ?? "").replace(/\n$/, "")}
            />
          );
        return <pre>{children}</pre>;
      },
      table: ({ children }) => (
        <div className="table-scroll">
          <table>{children}</table>
        </div>
      ),
    }),
    [onTime, canPlay, source],
  );
  return (
    <div
      className={cn(
        "prose-note",
        variant === "chat" && "prose-chat",
        variant === "inline" && "prose-chat [&_p]:!my-0",
        className,
      )}
    >
      <ReactMarkdown
        urlTransform={keepUrl}
        remarkPlugins={remarkPlugins}
        rehypePlugins={rehypePlugins}
        components={components}
      >
        {markdown}
      </ReactMarkdown>
    </div>
  );
}

/** Memoized: the reader re-renders every second while a video plays, and parsing a note with KaTeX is not free. */
export const Markdown = memo(MarkdownView);
