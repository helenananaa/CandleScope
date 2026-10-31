import type { KlineBar, MarketSeries } from "../marketDataTypes.js";
import type { SharedMarketCache } from "./sharedMarketCache.js";

export interface InitialRowsResolution {
  rows: KlineBar[];
  tier: "market-data-memory" | "shared-market";
  cacheState: string;
  source: string;
  needsRepair: boolean;
}

export function resolveSharedInitialRows(series: MarketSeries, windowRows: KlineBar[] | null | undefined,
  cache: SharedMarketCache | undefined, limit: number): InitialRowsResolution | null {
  // The retained window owns its navigation boundary, even if the shared pool
  // contains a newer or larger range. Only its admission owner may expand it.
  if (windowRows?.length) return { rows: windowRows, tier: "market-data-memory",
    cacheState: "memory", source: "memory-cache-hit", needsRepair: false };
  const shared = cache?.read(series, { limit });
  if (!shared?.rows.length) return null;
  // Cached history proof does not establish current stream freshness. Display
  // a bounded preview while normal initial read/recovery confirms the series.
  return { rows: [...shared.rows], tier: "shared-market", cacheState: "provisional",
    source: "shared-market-cache", needsRepair: true };
}
