import type { MarketSeries } from "../marketDataTypes.js";
import type { BackendSyntheticSource } from "./syntheticSeries.js";
import { BACKEND_SYNTHETIC_SERIES_ENABLED } from "./backendSyntheticFeature.js";

/** Browser-owned history registers only its displayed prefix, never hidden rows. */
export function capturedSyntheticSource(market: MarketSeries, seriesKey: string | null, scope: string, cutoff_ms: number): BackendSyntheticSource | null {
  return BACKEND_SYNTHETIC_SERIES_ENABLED ? { ...market, syntheticSeriesKey: seriesKey ?? "captured-prefix-unavailable",
    syntheticCapture: { scope, cutoff_ms } } : null;
}
