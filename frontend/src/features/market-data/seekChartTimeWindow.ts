import type { SeriesDataFeed } from "./feed/seriesDataFeed.js";
import type { KlineFetchResult } from "./klineContracts.js";
import type { MarketSeries } from "./marketDataTypes.js";
import { hasVerifiedCoverage, isKlineResultRepairPending } from "./quality/klineQualityPolicy.js";
import { locateChartTime, type ChartTimeSeekPlan, type ChartTimeSeekResult } from "./chartTimeNavigation.js";

/** A cold window settles in the backend's backfill, not in one request: a far
 * 1m window took about 3 s and a window that starts before the listing about
 * 30 s (its pre-listing rows must be proven absent). The dialog stays busy and
 * keeps the current view meanwhile; a newer jump or "back to live" supersedes.
 * A seek whose backend stops repairing the window gives up after this long. */
export const CHART_TIME_SEEK_BUDGET_MS = 60_000;
/** While every answer says the backend is still repairing the window, the seek
 * keeps waiting up to this long. RC 32: the proof before a listing (the same
 * empty page on two attempts, 5 s and 15 s retry backoffs) queues behind other
 * history work for the same series, such as a gap audit's monthly archive
 * import that ran 55-61 s and was retried. The backend finished after 77 s and
 * 117 s in two runs, while the jump had given up at 60 s. */
export const CHART_TIME_SEEK_REPAIR_BUDGET_MS = 180_000;
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

/** The backend started or joined a repair for this window and may still finish it. */
function backendStillRepairing(result: KlineFetchResult): boolean {
  return result.backfill_triggered === true && result.retryable === true;
}

/** Fetch through the existing manager, one bounded window per request. Re-read
 * only while the backend reports a retryable repair or a stream gap fenced the
 * read, up to the budget, or up to the repair budget while the backend is still
 * repairing the window. No result may replace a view after its owner changes. */
export async function seekChartTimeWindow({
  plan, series, feed, signal, hasCachedRange, ownsRequest, commit,
  budgetMs = CHART_TIME_SEEK_BUDGET_MS, repairBudgetMs = CHART_TIME_SEEK_REPAIR_BUDGET_MS,
  now = Date.now, delay = abortableDelay,
}: {
  plan: ChartTimeSeekPlan;
  series: MarketSeries;
  feed: Pick<SeriesDataFeed, "getRange" | "beginEpoch">;
  signal: AbortSignal;
  hasCachedRange: boolean;
  ownsRequest(): boolean;
  commit(result: KlineFetchResult): void;
  budgetMs?: number;
  repairBudgetMs?: number;
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
    const begun = now();
    const deadline = begun + Math.max(0, budgetMs);
    const repairDeadline = begun + Math.max(0, budgetMs, repairBudgetMs);
    let limit = deadline;
    while (result === null || readAgain(result)) {
      const started = now();
      result = await feed.getRange(series, {
        ...options, repair: "wait", strict: true, cacheMode: "network-only",
        waitMs: Math.max(0, Math.min(CHART_TIME_SEEK_REPAIR_WAIT_MS, Math.floor(limit - started))),
      });
      if (!current()) return failure("superseded");
      // Past the budget, read again only while this answer says the backend is still on it.
      limit = backendStillRepairing(result) ? repairDeadline : deadline;
      if (!readAgain(result) || now() >= limit) break;
      const pause = Math.min(CHART_TIME_SEEK_RETRY_FLOOR_MS - (now() - started), limit - now());
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
    // Reads planned against the replaced window must not land in this one. A
    // backfill readback queued while the seek was in flight carries the seek's
    // epoch, and older rows are always admitted to the right-truncated window:
    // it brought the previous far window back beside this one.
    feed.beginEpoch(series);
    return location;
  } catch {
    return failure(current() ? "unavailable" : "superseded");
  }
}
