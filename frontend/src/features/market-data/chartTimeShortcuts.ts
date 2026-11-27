import type { ChartTimeSeekResult } from "./chartTimeNavigation.js";

/**
 * Relative jumps and quick targets for Go to date (PL-8). Relative jumps move
 * the view's centre by a fixed amount through the ordinary seek, so linked
 * charts follow and the result is reported the same way as a typed date.
 */
export type ChartTimeAmount = "hour" | "day" | "week";
export const CHART_TIME_AMOUNT_SECONDS: Readonly<Record<ChartTimeAmount, number>> = Object.freeze({
  hour: 3_600,
  day: 86_400,
  week: 604_800,
});
export const CHART_TIME_RELATIVE_JUMPS: readonly { readonly amount: ChartTimeAmount; readonly direction: -1 | 1 }[] = Object.freeze([
  { amount: "week", direction: -1 },
  { amount: "day", direction: -1 },
  { amount: "hour", direction: -1 },
  { amount: "hour", direction: 1 },
  { amount: "day", direction: 1 },
  { amount: "week", direction: 1 },
]);

export type ChartTimeOutcomes = Array<{ cellId: string; result: ChartTimeSeekResult }>;

/** What a chart lends the dialog for its shortcuts. */
export interface ChartTimeShortcuts {
  /** Centre of the view, epoch ms, or null before the chart has a range. */
  centerTimeMs(): number | null;
  jumpBy(seconds: number): Promise<ChartTimeOutcomes> | null;
  /** Returns to the live (or, in replay, the revealed) edge; the time that edge stands for, or null when it couldn't. */
  latest(): Promise<number | null>;
  /** Epoch ms of the bar it moved to, or null when nothing is loaded. */
  firstLoaded(): number | null;
  /** Where the view was before the last jump, epoch ms. */
  lastViewedMs: number | null;
  jumpLastViewed(): Promise<ChartTimeOutcomes> | null;
}

/** The view's centre in epoch ms from a lightweight-charts time range in seconds. */
export function visibleCenterTimeMs(range: { readonly from?: unknown; readonly to?: unknown } | null | undefined): number | null {
  const from = Number(range?.from);
  const to = Number(range?.to);
  if (!Number.isFinite(from) || !Number.isFinite(to)) return null;
  return Math.round(((from + to) / 2)) * 1000;
}

/** Target of a relative jump, never past `ceilingMs` (now, or replay's revealed boundary); null without a centre. */
export function relativeJumpTarget(centerMs: number | null, seconds: number, ceilingMs: number): number | null {
  if (centerMs === null || !Number.isFinite(centerMs) || !Number.isFinite(seconds)) return null;
  const target = Math.round(centerMs + seconds * 1000);
  return target < 0 ? null : Math.min(target, ceilingMs);
}

/**
 * Rapid relative jumps add up. While one is still loading, the view hasn't
 * moved yet, so the next one counts from the pending target instead of the
 * view's centre: two quick "−1 day" clicks land two days back. The last jump
 * still wins in the seek itself; this only keeps its target right.
 */
export class RelativeJumpTracker {
  private pending: { readonly targetMs: number } | null = null;

  /** Where the next relative jump counts from. */
  base(centerMs: number | null): number | null {
    return this.pending?.targetMs ?? centerMs;
  }

  /** Marks a jump in flight; call the returned function when it settles. */
  begin(targetMs: number): () => void {
    const token = { targetMs };
    this.pending = token;
    return () => { if (this.pending === token) this.pending = null; };
  }

  /** A typed time or a quick target replaces any relative chain. */
  reset(): void {
    this.pending = null;
  }
}

export const CHART_TIME_LAST_VIEWED_KEY = "candlescope.chartTime.lastViewed.v1";
const LAST_VIEWED_LIMIT = 64;

interface LastViewedEntry { readonly slot: string; readonly key: string; readonly timeMs: number }

function readLastViewedEntries(storage: Pick<Storage, "getItem"> | null): LastViewedEntry[] {
  try {
    const parsed: unknown = JSON.parse(storage?.getItem(CHART_TIME_LAST_VIEWED_KEY) ?? "[]");
    if (!Array.isArray(parsed)) return [];
    return (parsed as unknown[]).filter((value): value is LastViewedEntry => {
      if (!value || typeof value !== "object") return false;
      const entry = value as Partial<Record<keyof LastViewedEntry, unknown>>;
      return typeof entry.slot === "string" && typeof entry.key === "string"
        && typeof entry.timeMs === "number" && Number.isSafeInteger(entry.timeMs) && entry.timeMs >= 0;
    });
  } catch {
    return [];
  }
}

function browserStorage(): Storage | null {
  try { return typeof localStorage === "undefined" ? null : localStorage; } catch { return null; }
}

/**
 * "Last viewed" survives a reload (PL-8). It is kept per chart slot
 * (workspace and cell) and only counts for the series it was taken on:
 * another symbol, interval or replay track in the same slot finds nothing.
 */
export function readLastViewed(slot: string, key: string, storage: Pick<Storage, "getItem"> | null = browserStorage()): number | null {
  return readLastViewedEntries(storage).find((entry) => entry.slot === slot && entry.key === key)?.timeMs ?? null;
}

/** Most recent first, at most 64 slots; storage failures are ignored. */
export function writeLastViewed(slot: string, key: string, timeMs: number,
  storage: Pick<Storage, "getItem" | "setItem"> | null = browserStorage()): void {
  if (!storage || !Number.isSafeInteger(timeMs) || timeMs < 0) return;
  const entries = [{ slot, key, timeMs }, ...readLastViewedEntries(storage).filter((entry) => entry.slot !== slot)]
    .slice(0, LAST_VIEWED_LIMIT);
  try { storage.setItem(CHART_TIME_LAST_VIEWED_KEY, JSON.stringify(entries)); } catch { /* private mode or full */ }
}
