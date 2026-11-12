import { useEffect, useMemo, useSyncExternalStore } from "react";
import type { MainChartType } from "../../../shared/mainChartTypes.js";
import type { MarketSeries } from "../marketDataTypes.js";
import type { SeriesWindowView } from "../window/seriesWindowView.js";
import type { ChartDisplaySubscription } from "../chartDisplaySubscription.js";
import { useMarketDataWorkspaceResources } from "../marketDataWorkspaceContext.js";
import { SyntheticSeriesManager } from "./syntheticSeriesManager.js";
import { SyntheticChartBinding } from "./syntheticChartBinding.js";

const idleSubscribe = () => () => {};
const idleStatus = () => "";

export function useBackendSyntheticSeries(input: {
  source: MarketSeries | null; reader: SeriesWindowView | null; chartType: MainChartType;
  settings: { mode?: string; boxSize?: number; atrLength?: number };
  display: ChartDisplaySubscription | null;
}) {
  const { reader, chartType } = input;
  const resources = useMarketDataWorkspaceResources();
  const owned = useMemo(() => new SyntheticSeriesManager(), []);
  const manager = resources?.dataManager.synthetic ?? owned;
  const sourceKey = JSON.stringify(input.source);
  const settingsKey = JSON.stringify(input.settings);
  const binding = useMemo(() => {
    const source = JSON.parse(sourceKey) as MarketSeries | null;
    if (!source || !reader || (chartType !== "renko" && chartType !== "heikin-ashi")) return null;
    return new SyntheticChartBinding(manager, source, reader, chartType,
      JSON.parse(settingsKey) as { mode?: string; boxSize?: number; atrLength?: number });
  }, [chartType, reader, manager, settingsKey, sourceKey]);
  useEffect(() => {
    binding?.start();
    return () => binding?.close();
  }, [binding]);
  useEffect(() => () => owned.closeAll(), [owned]);
  const status = useSyncExternalStore(binding?.subscribe ?? idleSubscribe, binding?.status ?? idleStatus, idleStatus);
  const display = useMemo(() => {
    if (!binding || !input.reader) return input.display;
    const reader = input.reader, original = input.display ?? reader;
    return {
      getSnapshot: input.display?.getSnapshot ?? (() => reader.version),
      subscribe(listener: Parameters<ChartDisplaySubscription["subscribe"]>[0]) {
        const source = original.subscribe(listener);
        const synthetic = binding.subscribe(() => listener({ type: "replace", changed: true }, reader));
        return () => { source(); synthetic(); };
      },
    };
  }, [binding, input.display, input.reader]);
  return { binding, status, display };
}
