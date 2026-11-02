import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export const clamp = (value: number, min: number, max: number) =>
  Math.min(max, Math.max(min, value));

export const errorMessage = (error: unknown) =>
  error instanceof Error ? error.message : String(error);
