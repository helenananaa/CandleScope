import { useSyncExternalStore } from "react";
import {
  canonicalizeIntervalValue,
  intervalSemanticSignature,
  parseIntervalSeconds,
} from "../../utils/intervals.js";
import type { IntervalString } from "../../utils/intervals.js";

/**
 * Native intervals pinned to the compact top-bar interval control.
 * Shared by every chart cell and window; custom intervals keep their
 * own `pinned` flag in customIntervalStore.
 */
const INTERVAL_FAVORITES_KEY = "candlescope-interval-favorites-v1";

export const DEFAULT_FAVORITE_INTERVALS: readonly IntervalString[] = Object.freeze([
  "1m",
  "5m",
  "15m",
  "1h",
  "4h",
  "1d",
]);

export function sanitizeFavoriteIntervals(raw: unknown): IntervalString[] | null {
  if (!Array.isArray(raw)) return null;
  const seen = new Set<string>();
  const values: IntervalString[] = [];
  for (const item of raw) {
    const value = canonicalizeIntervalValue(item);
    if (!value || !parseIntervalSeconds(value)) continue;
    const signature = intervalSemanticSignature(value);
    if (seen.has(signature)) continue;
    seen.add(signature);
    values.push(value);
  }
  return values.sort((a, b) => (parseIntervalSeconds(a) || 0) - (parseIntervalSeconds(b) || 0));
}

function readFavorites(): readonly IntervalString[] {
  try {
    const raw = localStorage.getItem(INTERVAL_FAVORITES_KEY);
    return (raw ? sanitizeFavoriteIntervals(JSON.parse(raw)) : null) ?? DEFAULT_FAVORITE_INTERVALS;
  } catch {
    return DEFAULT_FAVORITE_INTERVALS;
  }
}

let snapshot: readonly IntervalString[] | null = null;
const listeners = new Set<() => void>();

function getSnapshot(): readonly IntervalString[] {
  snapshot ??= Object.freeze(readFavorites());
  return snapshot;
}

function emit(): void {
  for (const listener of listeners) listener();
}

function handleStorage(event: StorageEvent): void {
  if (event.key !== null && event.key !== INTERVAL_FAVORITES_KEY) return;
  snapshot = null;
  emit();
}

function subscribe(listener: () => void): () => void {
  if (listeners.size === 0 && typeof window !== "undefined") {
    window.addEventListener("storage", handleStorage);
  }
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0 && typeof window !== "undefined") {
      window.removeEventListener("storage", handleStorage);
    }
  };
}

export function toggleFavoriteInterval(interval: unknown): void {
  const value = canonicalizeIntervalValue(interval);
  if (!value) return;
  const signature = intervalSemanticSignature(value);
  const current = getSnapshot();
  const next = current.some((item) => intervalSemanticSignature(item) === signature)
    ? current.filter((item) => intervalSemanticSignature(item) !== signature)
    : [...current, value];
  snapshot = Object.freeze(sanitizeFavoriteIntervals(next) ?? []);
  try {
    localStorage.setItem(INTERVAL_FAVORITES_KEY, JSON.stringify(snapshot));
  } catch {
    // Ignore storage failures; the favorite still applies for this session.
  }
  emit();
}

export function useFavoriteIntervals(): readonly IntervalString[] {
  return useSyncExternalStore(subscribe, getSnapshot, () => DEFAULT_FAVORITE_INTERVALS);
}
