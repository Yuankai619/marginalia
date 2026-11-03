import { useEffect, useState, useSyncExternalStore } from "react";

/** useState persisted in localStorage; storage failures (private mode) fall back to memory. */
export function useStored<T>(
  key: string,
  fallback: T,
  valid: (value: unknown) => boolean,
) {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key);
      const parsed: unknown = raw === null ? undefined : JSON.parse(raw);
      return valid(parsed) ? (parsed as T) : fallback;
    } catch {
      return fallback;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {}
  }, [key, value]);
  return [value, setValue] as const;
}

// One subscribe function per query, so useSyncExternalStore does not resubscribe on every render.
const mediaSubscribers = new Map<string, (notify: () => void) => () => void>();
function subscribeMedia(query: string) {
  let subscribe = mediaSubscribers.get(query);
  if (!subscribe) {
    subscribe = (notify) => {
      const list = window.matchMedia(query);
      list.addEventListener("change", notify);
      return () => list.removeEventListener("change", notify);
    };
    mediaSubscribers.set(query, subscribe);
  }
  return subscribe;
}

export function useMediaQuery(query: string) {
  return useSyncExternalStore(
    subscribeMedia(query),
    () => window.matchMedia(query).matches,
    () => false,
  );
}

const subscribeResize = (notify: () => void) => {
  window.addEventListener("resize", notify);
  return () => window.removeEventListener("resize", notify);
};

export function useViewportWidth() {
  return useSyncExternalStore(
    subscribeResize,
    () => window.innerWidth,
    () => 1440,
  );
}

/** `value`, settling `delay` ms after it stops changing; the first value is returned at once. */
export function useDebounced<T>(value: T, delay: number) {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return settled;
}
