import type { KlineApi, KlineFetchResult, KlineStreamFactory } from "./klineContracts.js";
import type { MarketSeries } from "./marketDataTypes.js";
import type { MarketCacheSnapshot, MarketRange } from "./manager/sharedMarketCache.js";
import type { MarketWarmLease, WarmReason } from "./manager/marketWarmQueue.js";

export interface MarketWarmOptions { owner: string; reason: WarmReason; nativeIntervals: readonly string[]; limit?: number }

/** Consumer port passed by the composition root. Feature consumers declare IO
 * demands and read admitted data; they never own a second candle collection. */
export interface MarketDataService extends KlineApi {
  subscribe: KlineStreamFactory;
  read(series: MarketSeries, range?: MarketRange): MarketCacheSnapshot;
  warm(series: MarketSeries, options: MarketWarmOptions): MarketWarmLease;
  prepareForeground(series: MarketSeries): { release(): void };
  recover(series: MarketSeries, options: { from?: number; to?: number; limit?: number; signal?: AbortSignal }): Promise<KlineFetchResult>;
}
