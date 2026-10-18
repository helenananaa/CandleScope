import { SeriesWindowStore } from "../market-data/window/seriesWindowStore.js";
import { applyReplayHistoryPage } from "./replayHistoryProvider.js";
import type { ReplayHistoryProvider } from "./replayHistoryProvider.js";
import type { ReplayDigest } from "./replayTypes.js";
import { asSeriesKey } from "../market-data/marketDataTypes.js";
import type { ChartDataCommitMeta } from "../market-data/useChartDataRuntime.js";
import { parseIntervalSeconds } from "../../utils/intervals.js";
import { rebuildReplayViewerSeries } from "./replayViewerProjection.js";

export const REVIEW_PREFIX_MAX_BARS = 20_000;
export const REVIEW_INITIAL_BARS = 500;
const PAGE_SIZE = 1_000;

/** The chart, metadata and indicator renderer must own the same review event. */
export function commitReplayReviewPrefix(target: SeriesWindowStore, source: SeriesWindowStore,
  displayInterval: string, datasetKey: string): void {
  const intervalSeconds = parseIntervalSeconds(displayInterval);
  if (intervalSeconds === null) throw new TypeError("invalid review display interval");
  target.intervalSeconds = intervalSeconds;
  target.seriesKey = asSeriesKey(datasetKey);
  target.replace(source.snapshot(), { source: "replay-review-display-prefix", serverAuthoritative: true });
}

/** Compatibility until historical tape tails have a source-sequence projection. */
export function commitReplayReviewBasePrefix(target: SeriesWindowStore, source: SeriesWindowStore,
  baseInterval: string, displayInterval: string, datasetKey: string): void {
  rebuildReplayViewerSeries(target, source, baseInterval, displayInterval);
  target.seriesKey = asSeriesKey(datasetKey);
}

export function replayReviewDataMeta(store: SeriesWindowStore, loading: boolean): ChartDataCommitMeta {
  return { version: Number(store.version), status: loading ? "loading" : "ready",
    source: "replay-review-closed-prefix", seriesKey: store.seriesKey, optimistic: false,
    bars: store.barCount, firstTime: store.first()?.time ?? null, lastTime: store.last()?.time ?? null,
    committedAt: null };
}

/** Keep the selected-event tail while collecting the bounded older prefix. */
export async function loadReplayReviewPrefix(
  provider: Pick<ReplayHistoryProvider, "loadBefore">,
  dataEpoch: ReplayDigest,
  revealedBoundaryMs: number,
  signal: AbortSignal,
  maxBars = REVIEW_INITIAL_BARS,
): Promise<{ source: SeriesWindowStore; bounded: boolean; nextBeforeMs: number; hasMore: boolean }> {
  if (!Number.isSafeInteger(maxBars) || maxBars < 1 || maxBars > REVIEW_PREFIX_MAX_BARS) {
    throw new RangeError("invalid review history budget");
  }
  const source = new SeriesWindowStore({ maxBars: REVIEW_PREFIX_MAX_BARS });
  let beforeMs = Math.min(Number.MAX_SAFE_INTEGER, revealedBoundaryMs + 1);
  let bounded = false;
  let hasMore = true;
  for (let pageIndex = 0; pageIndex < Math.ceil(maxBars / PAGE_SIZE); pageIndex += 1) {
    signal.throwIfAborted();
    const page = await provider.loadBefore({ beforeMs, revealedBoundaryMs, dataEpoch, limit: Math.min(PAGE_SIZE, maxBars - source.barCount) });
    signal.throwIfAborted();
    applyReplayHistoryPage(source, page);
    hasMore = page.has_more;
    if (hasMore && page.next_before_ms >= beforeMs) throw new TypeError("review history cursor did not progress");
    beforeMs = page.next_before_ms;
    bounded = hasMore && source.barCount >= REVIEW_PREFIX_MAX_BARS;
    if (!hasMore || page.bars.length === 0) break;
  }
  return { source, bounded, nextBeforeMs: beforeMs, hasMore };
}
