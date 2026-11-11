import type { ChartAccountOverlaySettings } from "../chart-workspace/chartAccountOverlaySettings.js";
import type { ReplayStoreSnapshot } from "./replayStore.js";
import type { ReplayTrainingMarketTrack, ReplayTrainingPortfolio } from "./replayV2Types.js";

type TradeSnapshot = Pick<ReplayStoreSnapshot, "sessionId" | "hasAuthoritativeSnapshot" | "virtualTimeMs"
  | "sourceSequence" | "revision" | "fills" | "orders">;
type TrackBinding = Pick<ReplayTrainingMarketTrack, "adapter_session_id" | "cursor">;

export function replayChartTradeInputs(
  store: TradeSnapshot,
  projectionBoundaryMs: number | null,
  track: TrackBinding | undefined,
  portfolio: ReplayTrainingPortfolio | undefined,
  settings: ChartAccountOverlaySettings | undefined,
) {
  const visible = store.hasAuthoritativeSnapshot && store.sessionId !== null
    && store.virtualTimeMs !== null && projectionBoundaryMs !== null
    && store.sessionId === track?.adapter_session_id;
  const cutoff = visible ? Math.min(projectionBoundaryMs, store.virtualTimeMs) : null;
  const current = cutoff !== null && projectionBoundaryMs === store.virtualTimeMs;
  // The portfolio and this track cursor arrive in one server projection, on a
  // separate stream from chart data. Only use its open positions at the same
  // adapter revision; timestamps alone cannot distinguish same-time commands.
  const cursor = track?.cursor;
  const portfolioCurrent = current && cursor?.virtual_time_ms === cutoff
    && cursor.source_sequence === store.sourceSequence && cursor.revision === store.revision;

  return {
    fills: settings?.trades !== false && cutoff !== null
      ? store.fills.filter(fill => fill.event_time_ms <= cutoff) : [],
    orders: settings?.positions !== false && current
      ? store.orders.filter(order => order.created_time_ms <= cutoff) : [],
    portfolio: settings?.positions !== false && portfolioCurrent ? portfolio : undefined,
  };
}
