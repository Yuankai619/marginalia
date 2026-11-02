import type { CourseDetail, VideoTime } from "./types";

export function parseVideoLink(href: string): VideoTime | null {
  const match = /^video:([a-zA-Z0-9_-]+)\?t=(\d+(?:\.\d+)?)$/.exec(href);
  if (!match) return null;
  const time = Number(match[2]);
  return Number.isFinite(time) && time >= 0 ? { video: match[1], time } : null;
}

export function safeNoteUrl(href: string): string {
  if (parseVideoLink(href)) return href;
  if (!/^https?:\/\//i.test(href)) return "";
  try {
    const url = new URL(href);
    return ["http:", "https:"].includes(url.protocol) ? href : "";
  } catch {
    return "";
  }
}

export function videoSource(
  course: CourseDetail | null,
  courseId: string,
  videoId: string,
  editable: boolean,
): string | null {
  if (!course) return null;
  if (!editable) {
    const url = course.info.videoUrls?.[videoId];
    return url && /^https?:/i.test(safeNoteUrl(url)) ? url : null;
  }
  const source = course.videos.find((video) => video.id === videoId)?.source;
  if (
    !source ||
    source.startsWith("/") ||
    source.split("/").some((part) => part === "..")
  )
    return null;
  return `/files/${encodeURIComponent(courseId)}/${source.split("/").map(encodeURIComponent).join("/")}`;
}

export const formatTime = (seconds: number) =>
  `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
