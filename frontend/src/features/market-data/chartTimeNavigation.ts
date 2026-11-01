import { createIntervalTimeline } from "../../utils/intervalTimeline.js";
import type { KlineBar } from "./marketDataTypes.js";

export const CHART_TIME_SEEK_BARS = 501;
export const MAX_CHART_TIME_SEEK_BARS = 2001;

/** API bounds are epoch seconds; user input and the resulting location use ms. */
export interface ChartTimeSeekPlan {
  requestedTimeMs: number;
  bucketTime: number;
  start: number;
  end: number;
  bars: number;
}

export type ChartTimeSeekResult =
  | { status: "located"; requestedTimeMs: number; actualTimeMs: number; exact: boolean }
  | { status: "empty" | "unavailable" | "superseded" | "invalid"; requestedTimeMs: number };

/** Build one bounded window around the target, including calendar/DST intervals.
 * Empty results establish only that this window is empty, not a listing bound. */
export function planChartTimeSeek(
  interval: string,
  requestedTimeMs: number,
  nowMs: number,
  bars = CHART_TIME_SEEK_BARS,
): ChartTimeSeekPlan | null {
  if (!Number.isSafeInteger(requestedTimeMs) || requestedTimeMs < 0
    || !Number.isSafeInteger(nowMs) || requestedTimeMs > nowMs
    || !Number.isSafeInteger(bars) || bars < 3 || bars > MAX_CHART_TIME_SEEK_BARS) return null;
  const timeline = createIntervalTimeline(interval);
  const bucketTime = timeline?.floor(requestedTimeMs / 1000);
  const latest = timeline?.floor(nowMs / 1000);
  if (!timeline || bucketTime == null || latest == null) return null;
  const left = Math.floor((bars - 1) / 2);
  let start = bucketTime, end = bucketTime;
  for (let index = 0; index < left; index += 1) {
    const previous = timeline.previous(start);
    if (previous == null || previous >= start) return null;
    start = previous;
  }
  for (let index = 0; index < bars - left - 1; index += 1) {
    const next = timeline.next(end);
    if (next == null || next <= end) return null;
    end = next;
  }
  return { requestedTimeMs, bucketTime, start: Math.max(0, start), end: Math.min(latest, end), bars };
}

export function locateChartTime(
  rows: readonly KlineBar[],
  plan: ChartTimeSeekPlan,
): Extract<ChartTimeSeekResult, { status: "located" }> | null {
  if (!rows.length || rows.length > plan.bars) return null;
  let nearest: number | null = null, previous = Number.NEGATIVE_INFINITY;
  for (const row of rows) {
    const time = Number(row.time);
    if (!Number.isFinite(time) || time < plan.start || time > plan.end || time <= previous) return null;
    previous = time;
    // The containing bucket is the target. Equal-distance gaps prefer the
    // earlier available bar, and the UI must disclose its actual timestamp.
    if (nearest === null || Math.abs(time - plan.bucketTime) < Math.abs(nearest - plan.bucketTime)) nearest = time;
  }
  return nearest === null ? null : { status: "located", requestedTimeMs: plan.requestedTimeMs,
    actualTimeMs: nearest * 1000, exact: nearest === plan.bucketTime };
}
