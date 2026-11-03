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

let uploadCount = 0;
/** Text standing in for an image while it uploads; unique, so two pastes of `image.png` never collide. */
export const uploadPlaceholder = (name: string) =>
  `![上傳中：${name.replace(/[[\]()\r\n]+/g, " ")} #${++uploadCount}]()`;
/** Any upload placeholder left in a note; such a note must not be saved (the image never arrived). */
export const UPLOAD_PLACEHOLDER = /!\[上傳中：[^\]\n]*\]\(\)/;

export const siteUrl = (path: string) =>
  `${import.meta.env?.BASE_URL ?? "/"}${path.replace(/^\//, "")}`;

/** `/files/<course>/<…parts>`, each segment encoded; the one place course file URLs are built. */
export const fileUrl = (courseId: string, ...parts: string[]) =>
  siteUrl(`/files/${[courseId, ...parts].map(encodeURIComponent).join("/")}`);

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

/** Where a markdown body's images resolve: a deck's notes, or an exam handout (docs/architecture.md, Exam prep). */
export type ImageSource =
  | { courseId: string; deckId: string }
  | {
      courseId: string;
      examId: string;
      /** Decks whose slide images exist here; others render as caption text. */
      decks?: string[];
    };

const SLIDE = /^slide:([\p{L}\p{N}_][\p{L}\p{N}_-]*)\/(\d{1,4})$/u;

/** URL of a note or handout image, or null for anything that is not one of the allowed forms. */
export function imageUrl(source: ImageSource, src: string): string | null {
  if (!("examId" in source))
    return assetUrl(source.courseId, source.deckId, src);
  const slide = SLIDE.exec(src);
  if (slide) {
    const index = Number(slide[2]);
    if (index < 1 || (source.decks && !source.decks.includes(slide[1])))
      return null;
    return fileUrl(
      source.courseId,
      "generated",
      "decks",
      slide[1],
      "slides",
      `${String(index).padStart(3, "0")}.webp`,
    );
  }
  const asset = assetUrl(source.courseId, "_", src);
  if (!asset) return null;
  const name = asset.split("/").at(-1) ?? "";
  return fileUrl(
    source.courseId,
    "exams",
    source.examId,
    "handout",
    "assets",
    decodeURIComponent(name),
  );
}
