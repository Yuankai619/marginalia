import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import rehypeRaw from "rehype-raw";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import type { VideoTime } from "../lib/types";
import { parseVideoLink, safeNoteUrl } from "../lib/video";

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
  "em",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "hr",
  "li",
  "ol",
  "p",
  "pre",
  "strong",
  "summary",
  "table",
  "tbody",
  "td",
  "th",
  "thead",
  "tr",
  "ul",
]);
const removeWithChildren = new Set(["iframe", "script", "style", "svg"]);

const sanitizeNoteHtml = () => (tree: HtmlNode) => {
  const clean = (node: HtmlNode): HtmlNode[] => {
    if (node.type === "comment") return [];
    if (node.children) node.children = node.children.flatMap(clean);
    if (node.type !== "element") return [node];
    if (removeWithChildren.has(node.tagName ?? "")) return [];
    if (!safeTags.has(node.tagName ?? "")) return node.children ?? [];
    if (node.tagName === "a" && typeof node.properties?.href === "string") {
      const href = node.properties.href;
      node.properties = { href: safeNoteUrl(href) };
    } else {
      node.properties = {};
    }
    return [node];
  };
  tree.children = tree.children?.flatMap(clean);
};

export function Markdown({
  markdown,
  onTime,
  canPlay,
}: {
  markdown: string;
  onTime: (target: VideoTime) => void;
  canPlay: (video: string) => boolean;
}) {
  return (
    <div className="markdown">
      <ReactMarkdown
        urlTransform={safeNoteUrl}
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeRaw, sanitizeNoteHtml, rehypeKatex]}
        components={{
          a: ({ href, children }) => {
            const found = parseVideoLink(href ?? "");
            if (found)
              return canPlay(found.video) ? (
                <button className="timestamp" onClick={() => onTime(found)}>
                  {children}
                </button>
              ) : (
                <span>{children}</span>
              );
            return href ? (
              <a href={href}>{children}</a>
            ) : (
              <span>{children}</span>
            );
          },
        }}
      >
        {markdown}
      </ReactMarkdown>
    </div>
  );
}
