import type { SeriesDataFeed } from "./feed/seriesDataFeed.js";
import type { KlineFetchResult } from "./klineContracts.js";
import type { MarketSeries } from "./marketDataTypes.js";
import { hasVerifiedCoverage, isKlineResultRepairPending } from "./quality/klineQualityPolicy.js";
import { locateChartTime, type ChartTimeSeekPlan, type ChartTimeSeekResult } from "./chartTimeNavigation.js";

/** Fetch through the existing manager, with one bounded request and at most one
 * cache-proof fallback. No result may replace a view after its owner changes. */
export async function seekChartTimeWindow({
  plan, series, feed, signal, hasCachedRange, ownsRequest, commit,
}: {
  plan: ChartTimeSeekPlan;
  series: MarketSeries;
  feed: Pick<SeriesDataFeed, "getRange">;
  signal: AbortSignal;
  hasCachedRange: boolean;
  ownsRequest(): boolean;
  commit(result: KlineFetchResult): void;
}): Promise<ChartTimeSeekResult> {
  const failure = (status: "superseded" | "empty" | "unavailable"): ChartTimeSeekResult => (
    { status, requestedTimeMs: plan.requestedTimeMs }
  );
  const current = () => !signal.aborted && ownsRequest();
  if (!current()) return failure("superseded");
  const options = { start: plan.start, end: plan.end, source: "date-seek",
    signal, commit: "none" as const, maxPages: 1 };
  try {
    let result = await feed.getRange(series, {
      ...options, repair: hasCachedRange ? "none" : "wait", waitMs: hasCachedRange ? 0 : 1_500,
      strict: !hasCachedRange, cacheMode: hasCachedRange ? "prefer-cache" : "network-only",
    });
    if (!current()) return failure("superseded");
    if (hasCachedRange && (isKlineResultRepairPending(result) || !hasVerifiedCoverage(result, "range"))) {
      result = await feed.getRange(series, {
        ...options, repair: "wait", waitMs: 1_500, strict: true, cacheMode: "network-only",
      });
    }
    if (!current()) return failure("superseded");
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
