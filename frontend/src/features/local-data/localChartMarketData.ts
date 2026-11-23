import type { ChartSession } from "../chart-session/chartSessionTypes.js";
import type { MarketDataRuntimeContract } from "../market-data/marketDataRuntimeContract.js";
import type { KlineBar } from "../market-data/marketDataTypes.js";
import type { ChartDataCommitMeta } from "../market-data/useChartDataRuntime.js";
import type { LocalChartRuntime } from "./useLocalChartRuntime.js";

const SOURCE = "local_dataset";

/**
 * An imported dataset's paged reader as source-neutral market data (ADR-BACKTEST-015 P5d3), so the
 * research workspace draws it through the shared chart surface. The reader is offline: there is no
 * feed to follow, and the chart only pages older bars.
 */
export function localChartMarketData(runtime: Pick<LocalChartRuntime,
  "seriesStore" | "loading" | "loadingMore" | "error" | "hasMoreLeft" | "loadMoreLeft" | "retry">, input: {
  session: ChartSession;
  bars: KlineBar[];
  dataMeta: ChartDataCommitMeta;
}): MarketDataRuntimeContract {
  const { bars, session } = input;
  const last = bars.at(-1) ?? null;
  return {
    view: {
      bars,
      seriesStore: runtime.seriesStore,
      meta: input.dataMeta,
      loading: runtime.loading || runtime.loadingMore,
      error: runtime.error,
      crosshairData: null,
      lastPrice: last,
      connectionStatus: "idle",
      dataSource: SOURCE,
      wsStatus: "idle",
      display: {
        displayData: last ? {
          time: last.time,
          open: Number(last.open ?? 0),
          high: Number(last.high ?? 0),
          low: Number(last.low ?? 0),
          close: Number(last.close ?? 0),
          volume: Number(last.volume ?? 0),
        } : null,
        priceChange: 0,
        isUp: true,
        amplitude: "0.00%",
        wsStatusLabel: SOURCE,
        exchangeLabel: session.exchange,
        marketLabel: session.marketType,
      },
    },
    actions: {
      retry: runtime.retry,
      loadMoreLeft: runtime.loadMoreLeft,
      onCrosshairMove() {},
      onVisibleRangeChange() {},
      consumeIndicatorRangeRequest() {},
    },
    status: {
      hasMoreLeft: runtime.hasMoreLeft,
      loadingMoreLeft: runtime.loadingMore,
      initialHistoryPending: runtime.loading,
      activeChartReady: !runtime.loading,
      canLoadMoreLeft: runtime.hasMoreLeft,
      canLoadMoreRight: false,
      canRestoreLatestWindow: false,
      barCount: bars.length,
      cacheDiagnostics: () => ({ source: SOURCE, bars: bars.length }),
      trimCacheEntries: () => ({ source: SOURCE, removed: 0 }),
      indicatorRangeRequests: [],
      requestDemand: null,
    },
  };
}
