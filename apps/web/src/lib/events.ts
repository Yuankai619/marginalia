import type { ChatEvent, Job } from "./types";

export async function readEventStream(
  response: Response,
  onEvent: (event: ChatEvent) => void,
) {
  if (!response.body) throw new Error("助教沒有傳回內容");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let completed = false;
  const dispatch = (frame: string) => {
    const payload = frame
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n");
    if (!payload) return;
    const event = JSON.parse(payload) as ChatEvent;
    if (event.type === "done" || event.type === "error") completed = true;
    onEvent(event);
  };
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      buffer = buffer.replace(/\r\n/g, "\n");
      let end = buffer.indexOf("\n\n");
      while (end >= 0) {
        dispatch(buffer.slice(0, end));
        buffer = buffer.slice(end + 2);
        end = buffer.indexOf("\n\n");
      }
      if (done) break;
    }
    if (buffer.trim()) dispatch(buffer);
    if (!completed) throw new Error("和助教的連線中斷了，回覆可能不完整");
  } finally {
    await reader.cancel();
    reader.releaseLock();
  }
}

export const jobFinished = (job: Job) =>
  ["done", "failed", "cancelled"].includes(job.state);

export function subscribeJob(
  id: string,
  getJob: (id: string) => Promise<Job>,
  onJob: (job: Job) => void,
  live = true,
) {
  let active = true;
  let revision = 0;
  const events =
    live && window.EventSource ? new EventSource("/api/events") : null;
  let poll: ReturnType<typeof setInterval> | undefined;
  const stop = () => {
    active = false;
    events?.close();
    clearInterval(poll);
  };
  const update = (job: Job) => {
    if (!active || job.id !== id) return;
    revision++;
    onJob(job);
    if (jobFinished(job)) stop();
  };
  const sync = async () => {
    const before = revision;
    try {
      const job = await getJob(id);
      if (before === revision) update(job);
    } catch {
      /* Retry on open or the next poll. */
    }
  };
  events?.addEventListener("job", (event) => {
    try {
      update(JSON.parse((event as MessageEvent).data));
    } catch {
      void sync();
    }
  });
  events?.addEventListener("open", () => void sync());
  poll = setInterval(() => void sync(), 5000);
  void sync();
  return stop;
}
