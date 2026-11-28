/**
 * The bar grid a forward run advances on (ADR-BACKTEST-015 B-333): the chart's signal
 * interval, when it has a fixed length of whole minutes (1m, 5m, 1h, 1d, 1w). Calendar
 * months, zoned calendars and second intervals have none; the backend refuses them.
 */
import { INTERVAL_UNIT_SECONDS, parseIntervalParts } from "../../../utils/intervals.js";
import { floorIntervalTime } from "../../../utils/intervalTimeline.js";

export const MINUTE_MS = 60_000;

/** The interval's bar length in ms, or null when a forward run cannot follow it. */
export function forwardIntervalMs(interval: string): number | null {
  const parts = parseIntervalParts(interval);
  if (!parts || parts.unit === "M" || parts.unit === "s" || `${parts.amount}${parts.unit}` !== interval) return null;
  const ms = parts.amount * INTERVAL_UNIT_SECONDS[parts.unit] * 1000;
  return Number.isSafeInteger(ms) && ms >= MINUTE_MS && ms % MINUTE_MS === 0 ? ms : null;
}

/** The open of the bar containing `timeMs`, or null for intervals forward runs do not follow. */
export function forwardBarOpenMs(interval: string, timeMs: number): number | null {
  if (forwardIntervalMs(interval) === null || !Number.isSafeInteger(timeMs)) return null;
  const open = floorIntervalTime(interval, timeMs / 1000);
  return open === null ? null : open * 1000;
}
