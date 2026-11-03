import { createIntervalTimeline } from "../../utils/intervalTimeline.js";
import { locateChartTime, planChartTimeSeek, type ChartTimeSeekResult } from "../market-data/chartTimeNavigation.js";
import type { SeriesWindowStore } from "../market-data/window/seriesWindowStore.js";
import { applyReplayHistoryPage, type ReplayHistoryPage, type ReplayHistorySource } from "./replayHistoryProvider.js";
import type { ReplayDigest } from "./replayTypes.js";

/** One bounded display read. This port cannot issue a clock/account command. */
export async function seekReplayViewportTime(input: {
  requestedTimeMs: number; runId: string; dataEpoch: ReplayDigest;
  revealedBoundaryMs: number; store: SeriesWindowStore; provider: ReplayHistorySource;
  current(): boolean;
  onApplied?(page: ReplayHistoryPage): void;
}): Promise<ChartTimeSeekResult> {
  const { requestedTimeMs, revealedBoundaryMs, store, provider } = input;
  const plan = planChartTimeSeek(provider.identity.display_interval, requestedTimeMs, revealedBoundaryMs, 500);
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
    beforeMs, revealedBoundaryMs, dataEpoch: input.dataEpoch, limit: 500,
  });
  if (!input.current() || store.version !== version) return { status: "superseded", requestedTimeMs };
  if (page.run_id !== input.runId || page.session_id !== provider.sessionId
    || page.track_id !== provider.trackId || page.data_epoch !== input.dataEpoch
    || page.revealed_boundary_ms !== revealedBoundaryMs) throw new Error("Replay viewport input changed");
  applyReplayHistoryPage(store, page, { contextHistory: true });
  input.onApplied?.(page);
  // A gap may return much older rows. Report only a neighbour within the
  // requested bounded window, and disclose its actual time in the dialog.
  const rows = store.snapshot().filter(row => row.time >= plan.start && row.time <= plan.end);
  return locateChartTime(rows, plan) ?? { status: "empty", requestedTimeMs };
}
