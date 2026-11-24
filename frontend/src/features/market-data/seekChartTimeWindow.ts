import type { SeriesDataFeed } from "./feed/seriesDataFeed.js";
import type { KlineFetchResult } from "./klineContracts.js";
import type { MarketSeries } from "./marketDataTypes.js";
import { hasVerifiedCoverage, isKlineResultRepairPending } from "./quality/klineQualityPolicy.js";
import { locateChartTime, type ChartTimeSeekPlan, type ChartTimeSeekResult } from "./chartTimeNavigation.js";

/** A cold window settles in the backend's backfill, not in one request: a far
 * 1m window took about 3 s and a window that starts before the listing about
 * 30 s (its pre-listing rows must be proven absent). The dialog stays busy and
 * keeps the current view meanwhile; a newer jump or "back to live" supersedes. */
export const CHART_TIME_SEEK_BUDGET_MS = 60_000;
/** The range endpoint's maximum `wait_ms`; it answers as soon as rows settle. */
export const CHART_TIME_SEEK_REPAIR_WAIT_MS = 5_000;
/** An endpoint that starts no repair answers at once; never spin on it. */
export const CHART_TIME_SEEK_RETRY_FLOOR_MS = 500;

function abortableDelay(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) { resolve(); return; }
    const done = () => { clearTimeout(timer); signal.removeEventListener("abort", done); resolve(); };
    const timer = setTimeout(done, ms);
    signal.addEventListener("abort", done, { once: true });
  });
}

/** Read the window again: the backend is still repairing or proving it, or a
 * stream gap fenced this read in flight (stale) while the seek still owns it. */
function readAgain(result: KlineFetchResult): boolean {
  if (result.active === false) return false;
  return result.stale === true
    || (result.retryable !== false && isKlineResultRepairPending(result));
}

/** Fetch through the existing manager, one bounded window per request. Re-read
 * only while the backend reports a retryable repair or a stream gap fenced the
 * read, up to the budget. No result may replace a view after its owner changes. */
export async function seekChartTimeWindow({
  plan, series, feed, signal, hasCachedRange, ownsRequest, commit,
  budgetMs = CHART_TIME_SEEK_BUDGET_MS, now = Date.now, delay = abortableDelay,
}: {
  plan: ChartTimeSeekPlan;
  series: MarketSeries;
  feed: Pick<SeriesDataFeed, "getRange">;
  signal: AbortSignal;
  hasCachedRange: boolean;
  ownsRequest(): boolean;
  commit(result: KlineFetchResult): void;
  budgetMs?: number;
  now?: () => number;
  delay?: (ms: number, signal: AbortSignal) => Promise<void>;
}): Promise<ChartTimeSeekResult> {
  const failure = (status: "superseded" | "empty" | "unavailable"): ChartTimeSeekResult => (
    { status, requestedTimeMs: plan.requestedTimeMs }
  );
  const current = () => !signal.aborted && ownsRequest();
  if (!current()) return failure("superseded");
  const options = { start: plan.start, end: plan.end, source: "date-seek",
    signal, commit: "none" as const, maxPages: 1 };
  try {
    let result: KlineFetchResult | null = null;
    if (hasCachedRange) {
      result = await feed.getRange(series, {
        ...options, repair: "none", waitMs: 0, strict: false, cacheMode: "prefer-cache",
      });
      if (!current()) return failure("superseded");
      // A cache proof is rechecked against storage once; it never waits alone.
      if (isKlineResultRepairPending(result) || !hasVerifiedCoverage(result, "range")) result = null;
    }
    const deadline = now() + Math.max(0, budgetMs);
    while (result === null || readAgain(result)) {
      const started = now();
      result = await feed.getRange(series, {
        ...options, repair: "wait", strict: true, cacheMode: "network-only",
        waitMs: Math.max(0, Math.min(CHART_TIME_SEEK_REPAIR_WAIT_MS, Math.floor(deadline - started))),
      });
      if (!current()) return failure("superseded");
      if (!readAgain(result) || now() >= deadline) break;
      const pause = Math.min(CHART_TIME_SEEK_RETRY_FLOOR_MS - (now() - started), deadline - now());
      if (pause > 0) await delay(pause, signal);
      if (!current()) return failure("superseded");
    }
    if (result.stale || result.active === false || isKlineResultRepairPending(result)
      || !hasVerifiedCoverage(result, "range")) return failure("unavailable");
    const rows = result.data ?? [];
    if (!rows.length) return failure("empty");
    const location = locateChartTime(rows, plan);
    if (!location) return failure("unavailable");
    commit(result);
    return location;
  } catch {
    return failure(current() ? "unavailable" : "superseded");
  }
}
