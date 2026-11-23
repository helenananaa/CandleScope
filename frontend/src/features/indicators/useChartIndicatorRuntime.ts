import { useMemo } from "react";
import { useIndicatorRuntime, type UseIndicatorRuntimeOptions } from "./useIndicatorRuntime.js";
import { useProvidedBarsIndicatorRuntime } from "./useProvidedBarsIndicatorRuntime.js";
import type { ActiveIndicatorPersistence } from "./activeIndicatorStore.js";
import type { ChartIndicatorSelection } from "./chartIndicatorInput.js";
import { isSyntheticTransform } from "../market-data/synthetic/syntheticSeries.js";

const emptyPersistence: ActiveIndicatorPersistence = { controlled: true, load: () => [], save: () => {} };
const emptyBars: [] = [];

/** Only one calculation owner receives definitions. Switching axes tears down
 * hosted raw-candle subscriptions and invalidates all derived output. */
export function useChartIndicatorRuntime(options: UseIndicatorRuntimeOptions & { chart: ChartIndicatorSelection }) {
  const enabled = Boolean(options.chart.source && isSyntheticTransform(options.chart.chartType));
  const raw = useIndicatorRuntime(enabled ? { ...options, autoAddVolume: false,
    indicatorPersistence: emptyPersistence, chartData: emptyBars, seriesReady: 0, realtimeEnabled: false } : options);
  const derived = useProvidedBarsIndicatorRuntime({
    chart: options.chart, bars: emptyBars,
    persistence: enabled ? options.indicatorPersistence ?? emptyPersistence : emptyPersistence,
    datasetKey: "chart-indicators", sourceOrdinal: 0, sourceScopeKey: "chart-indicators",
    exchange: options.session?.view.exchange ?? options.exchange ?? "binance",
    marketType: options.session?.view.marketType ?? options.marketType ?? "spot",
    symbol: options.session?.view.symbol ?? options.symbol ?? "UNKNOWN",
    interval: options.session?.view.interval ?? options.interval ?? "1m",
    ...(options.candleUpColor ? { candleUpColor: options.candleUpColor } : {}),
    ...(options.candleDownColor ? { candleDownColor: options.candleDownColor } : {}),
    ...(options.onIndicatorRemoved ? { onIndicatorRemoved: options.onIndicatorRemoved } : {}),
  });
  return useMemo(() => enabled ? derived : raw, [enabled, derived, raw]);
}
