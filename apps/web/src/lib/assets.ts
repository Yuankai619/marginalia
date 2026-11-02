// Note images live in notes/<deck>/assets/ and are referenced as `assets/<name>` (docs/architecture.md).

/** Note image formats: extension → MIME type (mirrors note_assets.TYPES on the server). */
export const IMAGE_FORMATS: Record<string, string> = {
  png: "image/png",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  webp: "image/webp",
  svg: "image/svg+xml",
};
const ASSET = /^assets\/([\p{L}\p{N}_][\p{L}\p{N}_.-]*)$/u;

/** `/files/<course>/<…parts>`, each segment encoded; the one place course file URLs are built. */
export const fileUrl = (courseId: string, ...parts: string[]) =>
  `/files/${[courseId, ...parts].map(encodeURIComponent).join("/")}`;

/** URL of a note image, or null for anything that is not a plain file under the deck's assets/ folder. */
export function assetUrl(
  courseId: string,
  deckId: string,
  src: string,
): string | null {
  // remark percent-encodes non-ASCII URLs (`assets/架構圖.svg`); match the name as written in the note.
  let path = src;
  try {
    path = decodeURI(src);
  } catch {}
  const match = ASSET.exec(path);
  if (!match || match[1].includes("..")) return null;
  const extension = match[1].split(".").at(-1)?.toLowerCase();
  if (!extension || !Object.hasOwn(IMAGE_FORMATS, extension)) return null;
  return fileUrl(courseId, "notes", deckId, "assets", match[1]);
}
