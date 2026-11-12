import {
  useCallback,
  useLayoutEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from "react";
import type { MutableRefObject } from "react";
import { t } from "../../i18n/index.js";

import {
  stripIndicatorRuntimeFields,
  useActiveIndicatorStore,
} from "./activeIndicatorStore.js";
import type {
  ActiveIndicatorPersistence,
} from "./activeIndicatorStore.js";
import { useIndicatorComputeController } from "./indicatorComputeController.js";
import type { IndicatorComputeBatchExecutor } from "./indicatorComputeController.js";
import { resolveLocalIndicatorExecution } from "./indicatorComputeJobRuntime.js";
import {
  createIndicatorOutputState,
  filterIndicatorOutputStateByVisibility,
  indicatorOutputReducer,
} from "./indicatorOutputReducer.js";
import { buildIndicatorPaneData } from "./indicatorPaneProjection.js";
import type { IndicatorRuntime } from "./indicatorRuntimeContract.js";
import type {
  IndicatorDefinition,
  IndicatorVisibleRange,
} from "./indicatorTypes.js";
import type { ChartDataCommitMeta } from "../market-data/useChartDataRuntime.js";
import type { KlineBar } from "../market-data/marketDataTypes.js";
import { MAX_SERIES_BARS } from "../market-data/phase1WindowPolicy.js";

import { clampProvidedBarsIndicatorOutput } from "./providedBarsIndicatorOutput.js";
import { providedBarsViewport } from "./providedBarsViewport.js";
export { clampProvidedBarsIndicatorOutput } from "./providedBarsIndicatorOutput.js";

import { useChartIndicatorInput } from "./useChartIndicatorInput.js";
import type { ChartIndicatorSelection } from "./chartIndicatorInput.js";

const EMPTY_RANGE_REQUEST = () => false;

export interface ProvidedBarsIndicatorSupport {
  supported: boolean;
  reason: string | null;
}

export interface UseProvidedBarsIndicatorRuntimeOptions {
  chart?: ChartIndicatorSelection;
  executeBatch?: IndicatorComputeBatchExecutor;
  chartDerived?: boolean;
  bars: KlineBar[];
  outputBarTimes?: readonly number[];
  candleDownColor?: string;
  candleUpColor?: string;
  chartDataMeta?: ChartDataCommitMeta | null;
  datasetKey: string;
  computeBatch?: IndicatorComputeBatchExecutor | undefined;
  exchange: string;
  interval: string;
  marketType: string;
  onIndicatorRemoved?: (indicatorId: string) => void;
  persistence?: ActiveIndicatorPersistence | null;
  seriesReady?: number;
  sourceOrdinal: number;
  sourceScopeKey: string;
  symbol: string;
  visibleThroughSeconds?: number | null;
  visibleRangePriority?: boolean;
}

function useLatestRef<T>(value: T): MutableRefObject<T> {
  const ref = useRef(value);
  useLayoutEffect(() => {
    ref.current = value;
  });
  return ref;
}

function normalizedScriptLanguage(indicator: IndicatorDefinition): string {
  return String(indicator.language || "pine").trim().toLowerCase();
}

export function providedBarsIndicatorSupport(
  indicator: IndicatorDefinition,
): ProvidedBarsIndicatorSupport {
  const local = {
    ...stripIndicatorRuntimeFields(indicator),
    executionTarget: "local" as const,
  };
  const resolution = resolveLocalIndicatorExecution(local);
  if (resolution.kind !== "local") {
    return {
      supported: false,
      reason: resolution.kind === "invalid"
        ? resolution.error
        : t("indicator.noLocalBars"),
    };
  }
  if (resolution.execution.mode === "builtin") {
    return { supported: true, reason: null };
  }
  const language = normalizedScriptLanguage(local);
  if (language !== "pine" && language !== "frontend-js") {
    return {
      supported: false,
      reason: t("indicator.replayUnsafe", { language: language || t("indicator.unknownRuntime") }),
    };
  }
  return { supported: true, reason: null };
}

/**
 * Converts a catalog definition into the only execution shape accepted by a
 * provided-bars runtime. The caller supplies every bar; hosted/range lookup is
 * never an implicit fallback.
 */
export function prepareProvidedBarsIndicator(
  indicator: IndicatorDefinition,
): IndicatorDefinition | null {
  const support = providedBarsIndicatorSupport(indicator);
  if (!support.supported) return null;
  const stripped = stripIndicatorRuntimeFields(indicator);
  const local: IndicatorDefinition = {
    ...stripped,
    executionTarget: "local",
  };
  const resolution = resolveLocalIndicatorExecution(local);
  if (resolution.kind !== "local") return null;
  if (resolution.execution.mode === "builtin") return local;

  const language = normalizedScriptLanguage(local);
  const {
    securityMode: _discardedSecurityMode,
    ...withoutSecurityMode
  } = local;
  return {
        ...withoutSecurityMode,
        language,
      };
}

export function clearProvidedBarsIndicatorRuntimeFields(
  indicator: IndicatorDefinition,
): IndicatorDefinition {
  const cleared: IndicatorDefinition = {
    ...indicator,
    lines: [],
  };
  delete cleared.error;
  delete cleared.paramSchema;
  return cleared;
}

/**
 * Shared indicator product runtime for an explicit, caller-owned bar array.
 * It reuses the live page's compute controller, output reducer and pane
 * projection, while deliberately excluding hosted range, WebSocket and shared
 * result-cache lifecycles.
 */
function useProvidedBarsIndicatorCore({
  bars,
  outputBarTimes,
  candleDownColor = "#ef4444",
  candleUpColor = "#22c55e",
  chartDataMeta = null,
  datasetKey,
  computeBatch,
  executeBatch,
  chartDerived = false,
  exchange,
  interval,
  marketType,
  onIndicatorRemoved,
  persistence = null,
  seriesReady = 0,
  sourceOrdinal,
  sourceScopeKey,
  symbol,
  visibleThroughSeconds = null,
  visibleRangePriority = false,
}: UseProvidedBarsIndicatorRuntimeOptions): IndicatorRuntime {
  const pendingForceComputeRef = useRef(false);
  const requireIndicatorCompute = useCallback(() => {
    pendingForceComputeRef.current = true;
  }, []);
  const {
    activeIndicators,
    setActiveIndicators,
    addIndicator,
    removeIndicator: removeActiveIndicator,
    toggleVisibility,
    updateIndicatorParams,
    updateIndicatorScript,
  } = useActiveIndicatorStore({
    autoAddVolume: false,
    normalizeIndicator: chartDerived ? prepareChartIndicator : prepareProvidedBarsIndicator,
    onRequireCompute: requireIndicatorCompute,
    persistence,
  });
  const [outputState, outputDispatch] = useReducer(
    indicatorOutputReducer,
    undefined,
    createIndicatorOutputState,
  );
  const activeIndicatorsRef = useLatestRef(activeIndicators);
  const [requestedViewport, setRequestedViewport] = useState<{
    scope: string; range: IndicatorVisibleRange; key: string;
  } | null>(null);
  const viewportRequestRef = useRef<{ scope: string; key: string } | null>(null);
  const computationBars = useMemo(() => visibleRangePriority
    ? providedBarsViewport(bars, requestedViewport?.scope === sourceScopeKey ? requestedViewport.range : null).bars
    : bars, [bars, requestedViewport, sourceScopeKey, visibleRangePriority]);
  const barsRef = useLatestRef(bars);
  const ensureVisibleIndicatorRange = useCallback((value: unknown) => {
    if (!visibleRangePriority || !value || typeof value !== "object" || Array.isArray(value)) return false;
    const range = value as IndicatorVisibleRange;
    const plan = providedBarsViewport(bars, range);
    const previous = viewportRequestRef.current;
    if (previous?.scope === sourceScopeKey && previous.key === plan.key) return false;
    viewportRequestRef.current = { scope: sourceScopeKey, key: plan.key };
    setRequestedViewport({ scope: sourceScopeKey, range, key: plan.key });
    return true;
  }, [bars, sourceScopeKey, visibleRangePriority]);
  const chartDataMetaRef = useLatestRef(chartDataMeta);
  const candleUpColorRef = useLatestRef(candleUpColor);
  const candleDownColorRef = useLatestRef(candleDownColor);
  const previousSourceRef = useRef<{
    ordinal: number;
    scopeKey: string;
  } | null>(null);

  useLayoutEffect(() => {
    const previous = previousSourceRef.current;
    previousSourceRef.current = {
      ordinal: sourceOrdinal,
      scopeKey: sourceScopeKey,
    };
    if (previous === null || (
      previous.scopeKey === sourceScopeKey
      && sourceOrdinal >= previous.ordinal
    )) return;

    pendingForceComputeRef.current = true;
    outputDispatch({
      type: "reset-context",
      preserveParamSchemas: false,
    });
    setActiveIndicators((current) => (
      current.map(clearProvidedBarsIndicatorRuntimeFields)
    ));
  }, [
    pendingForceComputeRef,
    setActiveIndicators,
    sourceOrdinal,
    sourceScopeKey,
  ]);

  const {
    computeAll,
    computing,
    recompute,
  } = useIndicatorComputeController({
    activeIndicators,
    activeIndicatorsRef,
    candleDownColor,
    candleDownColorRef,
    candleUpColor,
    candleUpColorRef,
    chartData: bars,
    ...(visibleRangePriority ? { builtinChartData: computationBars } : {}),
    chartDataMeta,
    chartDataMetaRef,
    chartDataRef: barsRef,
    datasetKey,
    ...(computeBatch === undefined ? {} : { computeBatch }),
    ...(executeBatch === undefined ? {} : { executeBatch }),
    exchange,
    forceHostedSubscriptions: () => undefined,
    historyLimit: MAX_SERIES_BARS,
    interval,
    marketType,
    outputDispatch,
    pendingForceComputeRef,
    resultCacheMode: "disabled",
    seriesReady,
    setActiveIndicators,
    symbol,
  });

  const removeIndicator = useCallback((indicatorId: string) => {
    removeActiveIndicator(indicatorId);
    outputDispatch({ type: "remove-indicator", indicatorId });
    onIndicatorRemoved?.(indicatorId);
  }, [onIndicatorRemoved, removeActiveIndicator]);

  const clamped = useMemo(() => clampProvidedBarsIndicatorOutput({
    activeIndicators,
    outputState,
    visibleThroughSeconds,
    ...(outputBarTimes === undefined ? {} : { outputBarTimes }),
  }), [activeIndicators, outputState, visibleThroughSeconds, outputBarTimes]);
  const visibleOutputState = useMemo(
    () => filterIndicatorOutputStateByVisibility(
      clamped.outputState,
      clamped.activeIndicators,
    ),
    [clamped.activeIndicators, clamped.outputState],
  );
  const paneData = useMemo(() => buildIndicatorPaneData(
    clamped.activeIndicators,
    {
      markers: visibleOutputState.markers,
      fills: visibleOutputState.fills,
      hlines: visibleOutputState.hlines,
      bgcolors: visibleOutputState.bgcolors,
      drawings: visibleOutputState.drawings,
    },
  ), [clamped.activeIndicators, visibleOutputState]);
  const view = useMemo(() => ({
    activeIndicators: clamped.activeIndicators,
    mainOverlayLines: paneData.mainOverlayLines,
    subPanes: paneData.subPanes,
    markers: visibleOutputState.markers,
    fills: visibleOutputState.fills,
    hlines: visibleOutputState.hlines,
    bgcolors: visibleOutputState.bgcolors,
      drawings: visibleOutputState.drawings,
    barcolors: visibleOutputState.barcolors,
    signals: visibleOutputState.signals,
    paramSchemas: visibleOutputState.paramSchemas,
  }), [
    clamped,
    paneData,
    visibleOutputState,
  ]);
  const actions = useMemo(() => ({
    addIndicator,
    computeAll,
    ensureVisibleIndicatorRange,
    recompute,
    removeIndicator,
    requestIndicatorRange: EMPTY_RANGE_REQUEST,
    toggleVisibility,
    updateIndicatorParams,
    updateIndicatorScript,
  }), [
    addIndicator,
    computeAll,
    ensureVisibleIndicatorRange,
    recompute,
    removeIndicator,
    toggleVisibility,
    updateIndicatorParams,
    updateIndicatorScript,
  ]);

  return {
    view,
    actions,
    status: {
      computing,
      realtimeMode: "historical-only",
    },
  };
}

/** Keep definitions, including unavailable plugin languages, visible and editable. */
function prepareChartIndicator(indicator: IndicatorDefinition): IndicatorDefinition {
  return { ...stripIndicatorRuntimeFields(indicator), executionTarget: "local" };
}

const markAxis = <T extends object>(item: T): T => ({ ...item, inputAxis: "display-ordinal" });

export function useProvidedBarsIndicatorRuntime(options: UseProvidedBarsIndicatorRuntimeOptions): IndicatorRuntime {
  const chart = useChartIndicatorInput(options.chart);
  const persistence = useMemo<ActiveIndicatorPersistence | null>(() => {
    const original = options.persistence;
    if (!chart.enabled || !original) return original ?? null;
    return { ...original, load: () => original.load(), save: list => {
      const targets = new Map(original.load().map(item => [item.id, item.executionTarget]));
      original.save(list.map(item => {
        const saved = { ...item };
        const target = targets.get(item.id);
        if (target === undefined) delete saved.executionTarget;
        else saved.executionTarget = target;
        return saved;
      }));
    }};
  }, [chart.enabled, options.persistence]);
  const runtime = useProvidedBarsIndicatorCore(chart.enabled ? {
    ...options, persistence, bars: chart.bars, chartDerived: true,
    exchange: options.chart!.source!.exchange, marketType: options.chart!.source!.marketType,
    symbol: options.chart!.source!.symbol, interval: options.chart!.source!.interval,
    executeBatch: chart.executeBatch, computeBatch: undefined,
    chartDataMeta: null, outputBarTimes: chart.bars.map(row => Number(row.time)),
    datasetKey: `${chart.key}:${chart.revision}`, sourceScopeKey: chart.key,
    sourceOrdinal: chart.revision, seriesReady: chart.ready ? chart.revision + 1 : 0,
    visibleThroughSeconds: chart.bars.length ? Number(chart.bars.at(-1)!.time) : null, visibleRangePriority: false,
  } : options);
  const view = useMemo(() => {
    if (!chart.enabled || !chart.ready) {
      if (!chart.enabled) return runtime.view;
      return { ...runtime.view, mainOverlayLines: [], subPanes: [], markers: [], fills: [], hlines: [],
        bgcolors: [], drawings: [], barcolors: [], signals: [],
        activeIndicators: runtime.view.activeIndicators.map(item => ({ ...item, lines: [], error: chart.error })) };
    }
    if (!chart.ordinal) return runtime.view;
    const map = <T extends object>(items: T[]) => items.map(markAxis);
    return { ...runtime.view, mainOverlayLines: map(runtime.view.mainOverlayLines),
      subPanes: runtime.view.subPanes.map(pane => ({ ...pane, lines: map(pane.lines) })),
      markers: map(runtime.view.markers), fills: map(runtime.view.fills), hlines: map(runtime.view.hlines),
      bgcolors: map(runtime.view.bgcolors), drawings: map(runtime.view.drawings ?? []),
      barcolors: map(runtime.view.barcolors), signals: map(runtime.view.signals) };
  }, [chart.enabled, chart.ordinal, chart.ready, chart.error, runtime.view]);
  return { ...runtime, view, status: { ...runtime.status,
    computing: runtime.status.computing || (chart.enabled && !chart.ready && !chart.error) } };
}
