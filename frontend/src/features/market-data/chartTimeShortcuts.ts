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
  latest(): boolean;
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

/** Target of a relative jump, never past now; null without a centre. */
export function relativeJumpTarget(centerMs: number | null, seconds: number, nowMs: number): number | null {
  if (centerMs === null || !Number.isFinite(centerMs) || !Number.isFinite(seconds)) return null;
  const target = Math.round(centerMs + seconds * 1000);
  return target < 0 ? null : Math.min(target, nowMs);
}
