import { createIntervalTimeline } from "../../utils/intervalTimeline.js";
import { locateChartTime, planChartTimeSeek, type ChartTimeSeekResult } from "../market-data/chartTimeNavigation.js";
import type { SeriesWindowStore } from "../market-data/window/seriesWindowStore.js";
import type { ReplayHistoryPage, ReplayHistorySource } from "./replayHistoryProvider.js";
import { replayDisplayBarToKline } from "./replaySeriesProjection.js";
import type { ReplayDigest } from "./replayTypes.js";

/** One bounded display read. This port cannot issue a clock/account command. */
export async function seekReplayViewportTime(input: {
  requestedTimeMs: number; runId: string; dataEpoch: ReplayDigest;
  revealedBoundaryMs: number; store: SeriesWindowStore; provider: ReplayHistorySource;
  current(): boolean;
  onApplied?(page: ReplayHistoryPage): void;
}): Promise<ChartTimeSeekResult> {
  const { requestedTimeMs, revealedBoundaryMs, store, provider } = input;
  const limit = Math.min(500, store.maxBars);
  const plan = planChartTimeSeek(provider.identity.display_interval, requestedTimeMs, revealedBoundaryMs, limit);
  if (!plan) return { status: "invalid", requestedTimeMs };
  if (!input.current()) return { status: "superseded", requestedTimeMs };
  if (store.hasTime(plan.bucketTime)) return {
    status: "located", requestedTimeMs, actualTimeMs: plan.bucketTime * 1000, exact: true,
  };
  // Closed-history pages end at an aligned boundary. A forming right-edge
  // candle must already come from the authoritative display projection.
  const timeline = createIntervalTimeline(provider.identity.display_interval)!;
  const end = timeline.next(plan.end);
  const revealedEnd = timeline.floor((revealedBoundaryMs + 1) / 1000);
  if (end === null || revealedEnd === null) return { status: "unavailable", requestedTimeMs };
  const beforeMs = Math.min(end, revealedEnd) * 1000;
  const version = store.version;
  const page: ReplayHistoryPage = await provider.loadBefore({
    beforeMs, revealedBoundaryMs, dataEpoch: input.dataEpoch, limit,
  });
  if (!input.current() || store.version !== version) return { status: "superseded", requestedTimeMs };
  if (page.run_id !== input.runId || page.session_id !== provider.sessionId
    || page.track_id !== provider.trackId || page.data_epoch !== input.dataEpoch
    || page.revealed_boundary_ms !== revealedBoundaryMs || page.bars.length > limit)
    throw new Error("Replay viewport input changed");
  // A gap may return much older rows. Report only a neighbour within the
  // requested bounded window, and disclose its actual time in the dialog.
  const rows = page.bars.map(bar => ({ ...replayDisplayBarToKline(bar), replayContextHistory: true }))
    .filter(row => row.time >= plan.start && row.time <= plan.end);
  const location = locateChartTime(rows, plan);
  if (!location) return { status: "empty", requestedTimeMs };
  // Date navigation owns a bounded display window. Merging into a full store
  // could retain the newest overlap and immediately evict the requested date.
  // The normal right-edge restore remains available; execution data is intact.
  store.replace(rows, { source: "replay-view-date-page", sessionId: page.session_id,
    trackId: page.track_id, dataEpoch: page.data_epoch, historyEpoch: page.history_epoch,
    revealedBoundaryMs: page.revealed_boundary_ms }, { rightEdgeCurrent: false });
  input.onApplied?.(page);
  return location;
}
