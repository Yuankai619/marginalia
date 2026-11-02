import { useEffect, useState, useSyncExternalStore } from "react";

const KEY = "marginalia:theme";
type Theme = "light" | "dark";

const subscribe = (notify: () => void) => {
  const observer = new MutationObserver(notify);
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["class"],
  });
  return () => observer.disconnect();
};
const isDark = () => document.documentElement.classList.contains("dark");

/** Tracks the `dark` class on <html>, so non-React renderers (mermaid) can follow the theme. */
export const useDark = () =>
  useSyncExternalStore(subscribe, isDark, () => false);

/** The saved theme, else the system preference. main.tsx applies it before the first paint. */
export function initialTheme(): Theme {
  try {
    const value = localStorage.getItem(KEY);
    if (value === "light" || value === "dark") return value;
  } catch {}
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(initialTheme);
  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    try {
      localStorage.setItem(KEY, theme);
    } catch {}
  }, [theme]);
  return [theme, () => setTheme(theme === "dark" ? "light" : "dark")] as const;
}
