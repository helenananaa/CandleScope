import type { KlineApi, KlineFetchResult, KlineStreamFactory } from "./klineContracts.js";
import type { MarketSeries } from "./marketDataTypes.js";
import type { MarketCacheSnapshot, MarketRange } from "./manager/sharedMarketCache.js";

/** Consumer port passed by the composition root. Feature consumers declare IO
 * demands and read admitted data; they never own a second candle collection. */
export interface MarketDataService extends KlineApi {
  subscribe: KlineStreamFactory;
  read(series: MarketSeries, range?: MarketRange): MarketCacheSnapshot;
  recover(series: MarketSeries, options: { from?: number; to?: number; limit?: number; signal?: AbortSignal }): Promise<KlineFetchResult>;
}
