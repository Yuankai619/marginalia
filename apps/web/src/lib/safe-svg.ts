// Mermaid's strict mode sanitizes labels with DOMPurify defaults, which still allow remote <img>, image shapes and
// `url(https://…)` in styles. Diagrams come from notes and chat replies (untrusted model output), so a reply could
// make the browser fetch an attacker URL carrying note text. The CSP (vite.config.ts) blocks the fetch, including
// the ones mermaid makes while laying out; this keeps the inserted SVG itself free of outside references.

const URL_ATTRS = [
  "src",
  "href",
  "xlink:href",
  "srcset",
  "poster",
  "background",
  "action",
  "formaction",
];
const REMOTE_TAGS = new Set([
  "img",
  "image",
  "picture",
  "source",
  "video",
  "audio",
  "iframe",
  "object",
  "embed",
  "link",
  "script",
]);

const local = (value: string) => value.trim().startsWith("#");

("data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7");

/** `url(#marker)` stays; any other `url(...)` and every `@import` is neutralised. */
export function safeCss(css: string) {
  return css
    .replace(/@import[^;]*;?/gi, "")
    .replace(
      /url\(\s*(['"]?)\s*([^)'"]*)\1\s*\)/gi,
      (match, _quote, target: string) => (local(target) ? match : "none"),
    );
}

export function stripExternal(svg: string): string {
  const template = document.createElement("template"); // inert: nothing in it loads or runs
  template.innerHTML = svg;
  for (const element of template.content.querySelectorAll("*")) {
    if (REMOTE_TAGS.has(element.localName)) {
      element.remove();
      continue;
    }
    for (const attribute of [...element.attributes]) {
      const name = attribute.name.toLowerCase();
      if (
        name.startsWith("on") ||
        (URL_ATTRS.includes(name) && !local(attribute.value))
      )
        element.removeAttribute(attribute.name);
      else if (name === "style")
        element.setAttribute("style", safeCss(attribute.value));
    }
    if (element.localName === "style")
      element.textContent = safeCss(element.textContent ?? "");
  }
  return template.innerHTML;
}
