import type { MarketSeries } from "../market-data/marketDataTypes.js";
import type { BackendSyntheticSource } from "../market-data/synthetic/syntheticSeries.js";
import { BACKEND_SYNTHETIC_SERIES_ENABLED } from "../market-data/synthetic/backendSyntheticFeature.js";

/** A captured public cursor owns this request, including when OHLC is unchanged. */
export function replaySyntheticSource(input: {
  market: MarketSeries; seriesKey: string | null;
  sessionId: string | null; trackId: string | null; dataEpoch: string | null;
  revealedBoundaryMs: number | null; sourceSequence: number | null;
  historyEpoch?: string;
}): BackendSyntheticSource | null {
  if (!BACKEND_SYNTHETIC_SERIES_ENABLED) return null;
  const ready = input.sessionId && input.trackId && input.dataEpoch && input.seriesKey
    && input.revealedBoundaryMs !== null && input.sourceSequence !== null;
  return { ...input.market,
    syntheticSeriesKey: ready ? input.seriesKey! : "synthetic-replay-prefix-unavailable",
    syntheticOrigin: { kind: "REPLAY", session_id: input.sessionId ?? "pending",
      track_id: input.trackId ?? "pending", data_epoch: input.dataEpoch ?? "pending",
      revealed_boundary_ms: input.revealedBoundaryMs ?? 0, source_sequence: input.sourceSequence ?? 0,
      ...(input.historyEpoch ? { history_epoch: input.historyEpoch } : {}) } };
}
