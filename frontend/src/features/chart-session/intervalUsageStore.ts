import { useSyncExternalStore } from "react";
import { canonicalizeIntervalValue } from "../../utils/intervals.js";

export interface IntervalUsage { interval: string; count: number; lastUsed: number }
const KEY = "candlescope-interval-usage-v1";
const EMPTY: readonly IntervalUsage[] = Object.freeze([]);
const listeners = new Set<() => void>();
let snapshot: readonly IntervalUsage[] | null = null;

export function sanitizeIntervalUsage(raw: unknown): IntervalUsage[] {
  if (!Array.isArray(raw)) return [];
  const records = new Map<string, IntervalUsage>();
  for (const candidate of raw) {
    if (!candidate || typeof candidate !== "object") continue;
    const item = candidate as Record<string, unknown>;
    const interval = canonicalizeIntervalValue(item.interval);
    const count = Number(item.count), lastUsed = Number(item.lastUsed);
    if (!interval || !Number.isFinite(count) || count <= 0 || !Number.isFinite(lastUsed) || lastUsed < 0) continue;
    const old = records.get(interval);
    records.set(interval, { interval, count: Math.min(1_000_000, Math.max(old?.count ?? 0, Math.floor(count))),
      lastUsed: Math.max(old?.lastUsed ?? 0, lastUsed) });
  }
  return [...records.values()].sort((a, b) => b.lastUsed - a.lastUsed).slice(0, 64);
}

function getSnapshot(): readonly IntervalUsage[] {
  if (snapshot) return snapshot;
  try { snapshot = Object.freeze(sanitizeIntervalUsage(JSON.parse(localStorage.getItem(KEY) || "[]")).map(item => Object.freeze(item))); }
  catch { snapshot = EMPTY; }
  return snapshot;
}

function emit(): void { for (const listener of listeners) listener(); }
function onStorage(event: StorageEvent): void {
  if (event.key !== null && event.key !== KEY) return;
  snapshot = null; emit();
}
function subscribe(listener: () => void): () => void {
  if (!listeners.size && typeof window !== "undefined") window.addEventListener("storage", onStorage);
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
    if (!listeners.size && typeof window !== "undefined") window.removeEventListener("storage", onStorage);
  };
}

export function recordIntervalUse(value: unknown): void {
  const interval = canonicalizeIntervalValue(value);
  if (!interval) return;
  const current = getSnapshot(), old = current.find(item => item.interval === interval);
  const next = sanitizeIntervalUsage([{ interval, count: (old?.count ?? 0) + 1, lastUsed: Date.now() },
    ...current.filter(item => item.interval !== interval)]);
  snapshot = Object.freeze(next.map(item => Object.freeze(item)));
  try { localStorage.setItem(KEY, JSON.stringify(snapshot)); } catch { /* session-only preference remains usable */ }
  emit();
}

export function useIntervalUsage(): readonly IntervalUsage[] {
  return useSyncExternalStore(subscribe, getSnapshot, () => EMPTY);
}

/** Bounded local habit ranking: explicit favorites plus recent/frequent use.
 * It never changes selection, pins, or persistent watchlist subscription tiers. */
export function rankWarmIntervals({ available, active, pinned, usage, now = Date.now(), limit = 3 }: {
  available: readonly string[]; active: string; pinned: readonly string[]; usage: readonly IntervalUsage[]; now?: number; limit?: number;
}): string[] {
  const favorites = new Set(pinned.map(canonicalizeIntervalValue));
  const history = new Map(usage.map(item => [canonicalizeIntervalValue(item.interval), item]));
  const activeKey = canonicalizeIntervalValue(active);
  return [...new Set(available.map(canonicalizeIntervalValue))]
    .filter((value): value is string => Boolean(value) && value !== activeKey && (favorites.has(value) || history.has(value)))
    .map((value, index) => {
      const record = history.get(value);
      const age = record ? Math.max(0, now - record.lastUsed) / 86_400_000 : Infinity;
      const score = (favorites.has(value) ? 3 : 0) + (record ? Math.log2(1 + record.count) + 4 / (1 + age) : 0);
      return { value, score, index };
    })
    .sort((a, b) => b.score - a.score || a.index - b.index)
    .slice(0, Math.max(0, Math.min(3, limit))).map(item => item.value);
}
