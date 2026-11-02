// Remark plugins for the note format extensions in docs/architecture.md: GitHub alerts and ==highlight==.
// They only attach hast hints (data.hName / hProperties); the sanitizer in Markdown.tsx allows exactly these.

type Node = {
  type: string;
  value?: string;
  children?: Node[];
  data?: { hName?: string; hProperties?: Record<string, unknown> };
};

export const ALERTS = {
  note: "補充說明",
  tip: "小技巧",
  important: "重點",
  warning: "注意",
  caution: "易混淆",
} as const;
export type AlertKind = keyof typeof ALERTS;

const ALERT_MARKER =
  /^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\][ \t]*(?:\n|$)/i;

function visit(node: Node, fn: (node: Node) => void) {
  fn(node);
  for (const child of node.children ?? []) visit(child, fn);
}

/** `> [!NOTE]` blockquotes become `<div class="alert alert-note">` with a zh-TW title paragraph. */
export function remarkAlerts() {
  return (tree: Node) => {
    visit(tree, (node) => {
      if (node.type !== "blockquote") return;
      const first = node.children?.[0];
      const text =
        first?.type === "paragraph" ? first.children?.[0] : undefined;
      if (text?.type !== "text" || !text.value) return;
      const match = ALERT_MARKER.exec(text.value);
      if (!match) return;
      const kind = match[1].toLowerCase() as AlertKind;
      text.value = text.value.slice(match[0].length);
      if (!text.value && first?.children) first.children.shift();
      // A marker alone on its line leaves an empty paragraph, possibly starting with a soft break.
      if (first?.children?.[0]?.type === "break") first.children.shift();
      if (first && !first.children?.length) node.children?.shift();
      node.data = {
        hName: "div",
        hProperties: { className: ["alert", `alert-${kind}`], role: "note" },
      };
      node.children?.unshift({
        type: "paragraph",
        data: { hName: "p", hProperties: { className: ["alert-title"] } },
        children: [{ type: "text", value: ALERTS[kind] }],
      });
    });
  };
}

const PHRASING_PARENTS = new Set([
  "paragraph",
  "heading",
  "tableCell",
  "emphasis",
  "strong",
  "delete",
  "link",
]);

/** `==text==` becomes `<mark>`; a highlight may span emphasis, links or code inside one paragraph. */
export function remarkHighlight() {
  return (tree: Node) => {
    visit(tree, (node) => {
      if (PHRASING_PARENTS.has(node.type) && node.children)
        node.children = highlight(node.children);
    });
  };
}

const mark = (children: Node[]): Node => ({
  type: "highlight",
  data: { hName: "mark" },
  children,
});

const space = (char: string | undefined) =>
  char === undefined || /\s/.test(char);

/**
 * Like markdown-it-mark: `==` opens only when the next character is not whitespace and closes only when the
 * previous one is not, so `pid == 0 … pid == -1` stays literal. Escaped `\=\=` is indistinguishable here (remark
 * has merged it into plain text); write `=&#61;` to keep a literal pair next to text.
 */
export function highlight(children: Node[]): Node[] {
  const out: Node[] = [];
  let open: Node[] | null = null; // children collected since an unmatched `==`
  let openAt = 0; // index in `out` where the literal `==` goes back if it never closes
  const push = (node: Node) => (open ?? out).push(node);
  children.forEach((child, index) => {
    if (child.type !== "text" || !child.value?.includes("==")) {
      push(child);
      return;
    }
    const parts = child.value.split("==");
    parts.forEach((part, i) => {
      if (i > 0) {
        const before =
          parts[i - 1].at(-1) ?? (i - 1 === 0 && index > 0 ? "x" : undefined);
        const after =
          part[0] ??
          (i === parts.length - 1 && index < children.length - 1
            ? "x"
            : undefined);
        if (open && !space(before) && open.length + parts[i - 1].length > 0) {
          out.push(mark(open));
          open = null;
        } else if (!open && !space(after)) {
          open = [];
          openAt = out.length;
        } else push({ type: "text", value: "==" });
      }
      if (part) push({ type: "text", value: part });
    });
  });
  if (open)
    out.splice(openAt, 0, { type: "text", value: "==" }, ...(open as Node[]));
  return merge(out).map((node) =>
    node.type === "highlight"
      ? { ...node, children: merge(node.children ?? []) }
      : node,
  );
}

function merge(nodes: Node[]): Node[] {
  const out: Node[] = [];
  for (const node of nodes) {
    const last = out.at(-1);
    if (node.type === "text" && last?.type === "text")
      last.value = (last.value ?? "") + (node.value ?? "");
    else out.push(node);
  }
  return out;
}
