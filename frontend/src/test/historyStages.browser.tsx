import { useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import { SeriesDataFeed } from "../features/market-data/feed/seriesDataFeed.js";
import { ForegroundPreloadGate } from "../features/market-data/foregroundPreloadGate.js";
import { useActiveChartHistoryHydration } from "../features/market-data/useActiveChartHistoryHydration.js";
import { useHistoryHydrationHolds, useIndicatorHistoryPreparation } from "../features/market-data/useIndicatorHistoryPreparation.js";
import { planInitialHistoryAdmission } from "../features/market-data/useChartInitialLoad.js";
import { computeFrontendScript } from "../features/indicators/frontendScriptRuntime.js";
import { FRONTEND_SCRIPT_STARTER } from "../features/indicators/frontendScriptContract.js";
import type { CommitChartData, KlineApi, KlineFetchResult } from "../features/market-data/klineContracts.js";
import type { MarketSeries } from "../features/market-data/marketDataTypes.js";
import StatusBar from "../app/StatusBar.js";
import { epochSeconds, partialMock } from "./testHelpers.js";

function assert(value: unknown, message: string): asserts value {
  if (!value) throw new Error(message);
}

async function until(predicate: () => boolean): Promise<void> {
  const deadline = performance.now() + 10_000;
  while (!predicate()) {
    if (performance.now() > deadline) throw new Error("History fixture did not settle");
    await new Promise(resolve => setTimeout(resolve, 20));
  }
}
const natives = ["1m", "15m", "30m", "1d", "3d"];
const intervals = ["45m", "90m", "2d", "3d", "4d", "5d"] as const;
type Interval = typeof intervals[number];
const widths: Record<Interval, number> = { "45m": 2700, "90m": 5400, "2d": 172800, "3d": 259200, "4d": 345600, "5d": 432000 };

function rows(count: number, interval: Interval) {
  return Array.from({ length: count }, (_, index) => ({
    time: epochSeconds((index + 1) * widths[interval]), open: index + 1, high: index + 2,
    low: index, close: index + 1, volume: 1, is_closed: true,
  }));
}
function ready(count: number, interval: Interval): KlineFetchResult {
  return { data: rows(count, interval), source: "storage", complete: true, retryable: false,
    history_state: "ready", all_rows_final: true, verified_contiguous: true,
    has_tail_gap: false, truncated: false, missing_ranges: [], has_more: true };
}

export async function checkHistoryStages() {
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const requests = Object.fromEntries(intervals.map(interval => [interval, [] as number[]]));
  const publications = Object.fromEntries(intervals.map(interval => [interval, [] as number[]]));
  const indicators = Object.fromEntries(intervals.map(interval => [interval, [] as number[]]));
  const gate = new ForegroundPreloadGate(0);
  const foreground = gate.enterForeground("manual-range-request");
  let release45mIndicator: (() => void) | undefined;
  let indicatorError: unknown;
  const series: Record<string, MarketSeries> = Object.fromEntries(intervals.map(interval => [interval, {
    exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval,
  }]));
  const feeds = Object.fromEntries(Object.entries(series).map(([interval, active]) => [interval, new SeriesDataFeed({
    getActiveSeries: () => active,
    api: partialMock<KlineApi>({ fetchKlinesHistory: async (_symbol, _interval, _days, _market, _exchange, options) => {
      const count = options.countBack ?? 0;
      requests[interval]!.push(count);
      return ready(count, interval as Interval);
    } }),
  })]));

  function Cell({ interval }: { interval: Interval }) {
    const [count, setCount] = useState(planInitialHistoryAdmission(interval, natives).viewportCountBack);
    const [computed, setComputed] = useState(0);
    const [held, holdHydration] = useHistoryHydrationHolds();
    useIndicatorHistoryPreparation(count < 1500, computed !== count, holdHydration);
    const commit = useCallback<CommitChartData>((_symbol, _interval, bars, meta) => {
      const validated = meta?.historyValidatedCountBack;
      assert(meta?.historyComplete && meta.deferIndicatorWindow === false && validated === bars.length,
        "partial stage leaked into the indicator window");
      publications[interval]!.push(validated);
      setCount(validated);
    }, [interval]);
    useActiveChartHistoryHydration({ enabled: !held, series: series[interval]!, sessionKey: interval,
      viewportCountBack: 128, targetCountBack: 1500, historyComplete: true, historyRepairPending: false,
      validatedCountBack: count, seriesDataFeed: feeds[interval]!, priorityGate: gate,
      commitMergedChartData: commit });
    useEffect(() => {
      const controller = new AbortController();
      void computeFrontendScript({ language: "frontend-js", script: FRONTEND_SCRIPT_STARTER,
        ohlcv: rows(count, interval), params: { length: 3 } }, controller.signal).then(async result => {
        if (interval === "45m" && count === 500) {
          await new Promise<void>(resolve => { release45mIndicator = resolve; });
        }
        if (controller.signal.aborted) return;
        assert(result.ok && result.lines[0]?.data.at(-1)?.value === count - 1, "indicator output differs from SMA arithmetic");
        indicators[interval]!.push(count);
        setComputed(count);
      }).catch(error => { if (!controller.signal.aborted) indicatorError = error; });
      return () => controller.abort();
    }, [count, interval]);
    return <section data-interval={interval} data-stage={count} data-indicator-stage={computed}>
      <h2>{interval}</h2>
      <StatusBar status={{ connectionStatus: "connected", dataSource: "fixture", exchangeLabel: "Binance",
        marketLabel: "spot", wsStatus: "live", wsStatusLabel: "", barCount: count,
        loadingMoreLeft: false, hasMoreLeft: true, exchangeCatalogStatus: "ready",
        historyPreparing: count < 1500, indicatorComputing: computed !== count }} />
    </section>;
  }
  try {
    flushSync(() => root.render(<>{intervals.map(interval => <Cell key={interval} interval={interval} />)}</>));
    assert(host.querySelectorAll('[data-stage="128"]').length === intervals.length, "first viewport was not independently visible");
    assert(host.querySelectorAll('[data-history-preparing="true"]').length === intervals.length, "preparation state missing");
    await until(() => intervals.every(interval => indicators[interval]!.includes(128)));
    assert(intervals.every(interval => requests[interval]!.length === 0), "hydration ignored the foreground request");
    foreground.release();
    await until(() => intervals.filter(interval => interval !== "45m").every(interval =>
      Boolean(host.querySelector(`[data-interval="${interval}"][data-indicator-stage="1500"]`))));
    assert(!indicatorError, String(indicatorError));
    assert(host.querySelector('[data-interval="45m"][data-stage="500"]'), "indicator did not hold the next stage");
    assert(JSON.stringify(requests["45m"]) === "[500]", "blocked chart requested deep history");
    for (const interval of intervals.filter(value => value !== "45m")) {
      assert(JSON.stringify(requests[interval]) === "[500,1500]", `${interval} requests: ${JSON.stringify(requests)}, publications: ${JSON.stringify(publications)}`);
    }
    await until(() => release45mIndicator != null);
    release45mIndicator?.();
    await until(() => Boolean(host.querySelector('[data-interval="45m"][data-indicator-stage="1500"]')));
    assert(!indicatorError, String(indicatorError));
    assert(host.querySelectorAll('[data-history-preparing="true"]').length === 0, "completed history still appears pending");
    assert(JSON.stringify(publications["45m"]) === "[500,1500]", "stages were duplicated or skipped");
    for (const interval of intervals) {
      assert(JSON.stringify(publications[interval]) === "[500,1500]", `${interval} stages duplicated or skipped`);
      assert(JSON.stringify(indicators[interval]) === "[128,500,1500]", `${interval} indicator stage was superseded before completion`);
    }
    return { scope: "Real React lifecycle, SeriesDataFeed, scheduler, status UI and isolated JS indicator worker; synthetic source rows",
      requests, publications, indicators, checks: ["128 visible before hydration", "500 and 1500 atomic publications",
        "foreground pauses the next stage", "other chart remains independent", "SMA worker output matches arithmetic", "preparation label clears"] };
  } finally {
    foreground.release();
    release45mIndicator?.();
    flushSync(() => root.unmount());
    host.remove();
  }
}
