import { createIntervalTimeline } from "../../utils/intervalTimeline.js";
import type { ChartTimeSeekResult } from "../market-data/chartTimeNavigation.js";
import type { SeriesWindowView } from "../market-data/window/seriesWindowView.js";

/** Navigation can see only the revealed store, never the retained input.
 * An explicit replay seek remains a different, durable action. */
export function locateStudyViewportTime(source: {
  store: SeriesWindowView; interval: string; minimumMs: number; cursorMs: number;
}, requestedTimeMs: number): ChartTimeSeekResult {
  if (!Number.isSafeInteger(requestedTimeMs) || requestedTimeMs < 0) return { status: "invalid", requestedTimeMs };
  if (requestedTimeMs < source.minimumMs || requestedTimeMs > source.cursorMs) return { status: "unavailable", requestedTimeMs };
  const target = createIntervalTimeline(source.interval)?.floor(requestedTimeMs / 1000);
  if (target == null) return { status: "invalid", requestedTimeMs };
  const rows = source.store.snapshot();
  if (!rows.length) return { status: "empty", requestedTimeMs };
  let low = 0, high = rows.length;
  while (low < high) {
    const mid = (low + high) >>> 1;
    if (rows[mid]!.time < target) low = mid + 1;
    else high = mid;
  }
  const left = rows[low - 1], right = rows[low];
  // Equal-distance gaps choose the earlier revealed candle, as live navigation does.
  const nearest = left && (!right || target - left.time <= right.time - target) ? left : right;
  return nearest ? { status: "located", requestedTimeMs, actualTimeMs: nearest.time * 1000, exact: nearest.time === target }
    : { status: "empty", requestedTimeMs };
}
