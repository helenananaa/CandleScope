import { klineSeriesIdentityKey } from "../market-data/klineSeriesIdentity.js";
import type { StableSeriesSnapshot } from "../market-data/window/stableSeriesSnapshot.js";
import type { KlineSeriesIdentityInput } from "../market-data/klineSeriesIdentity.js";
import type { IndicatorCacheInputSource } from "./indicatorInputBinding.js";
import {
  startTransition,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { flushSync } from "react-dom";
import type { Dispatch, MutableRefObject, SetStateAction } from "react";
import { computeIndicatorBatch } from "../../services/indicatorApi.js";
import { isFrontendScript } from "./frontendScriptContract.js";
import { routeIndicatorComputeBatch } from "./frontendScriptBatch.js";
import { cachedIndicatorComputeResult } from "./indicatorCachedCompute.js";
import { markPerf, recordPerfEvent } from "../../runtime/performance/perfMarks.js";
import {
  buildIndicatorComputeParams,
  buildIndicatorOhlcv,
  buildIndicatorOhlcvSignature,
  limitIndicatorHistory,
  chunkIndicatorComputeJobs,
  collectIndicatorComputeResults,
  resolveIndicatorComputeDelay,
  resolveSeriesReadyComputeDelay,
  shouldDeferIndicatorCompute,
} from "./indicatorComputeRuntime.js";
import {
  buildIndicatorComputeJobKey,
  buildIndicatorComputeLifecycleKey,
  createIndicatorComputeJobCoordinator,
  resolveLocalIndicatorExecution,
} from "./indicatorComputeJobRuntime.js";
import {
  buildIndicatorCacheContext,
  cacheIndicatorSnapshot,
  removeCachedIndicatorResult,
} from "./indicatorResultCacheStore.js";
import type { ChartDataCommitMeta } from "../market-data/useChartDataRuntime.js";
import type { KlineBar } from "../market-data/marketDataTypes.js";
import type {
  IndicatorComputeRequest,
  IndicatorComputeBatchItem,
  IndicatorComputeBatchJob,
  IndicatorComputeBatchResponse,
  IndicatorDefinition,
  IndicatorOutputAction,
} from "./indicatorTypes.js";

export type IndicatorComputeBatchExecutor = (options: {
  jobs: IndicatorComputeBatchJob[];
  signal?: AbortSignal;
  /** Independent results may publish before slower jobs in the same batch. */
  onResults?: (results: IndicatorComputeBatchItem[]) => void;
}) => Promise<IndicatorComputeBatchResponse>;

export interface UseIndicatorComputeControllerOptions {
  activeIndicators: IndicatorDefinition[];
  activeIndicatorsRef: MutableRefObject<IndicatorDefinition[]>;
  candleDownColor: string;
  candleDownColorRef: MutableRefObject<string>;
  candleUpColor: string;
  candleUpColorRef: MutableRefObject<string>;
  chartData: KlineBar[];
  /** Display-only builtins may request a viewport; scripts retain caller input. */
  builtinChartData?: KlineBar[];
  chartDataMeta: ChartDataCommitMeta | null;
  chartDataMetaRef: MutableRefObject<ChartDataCommitMeta | null>;
  chartDataRef: MutableRefObject<KlineBar[]>;
  datasetKey: string;
  exchange: string;
  seriesIdentity?: KlineSeriesIdentityInput;
  inputSource?: IndicatorCacheInputSource | undefined;
  computeBatch?: IndicatorComputeBatchExecutor;
  /** Whole live demand route, including browser scripts; replay retains its executor. */
  executeBatch?: IndicatorComputeBatchExecutor | undefined;
  inputSnapshot?: StableSeriesSnapshot;
  onComputePendingChange?(delta: 1 | -1): void;
  forceHostedSubscriptions(): void;
  historyLimit?: number;
  interval: string;
  marketType: string;
  outputDispatch: Dispatch<IndicatorOutputAction>;
  pendingForceComputeRef: MutableRefObject<boolean>;
  resultCacheMode?: "shared" | "disabled";
  seriesReady: number;
  setActiveIndicators: Dispatch<SetStateAction<IndicatorDefinition[]>>;
  symbol: string;
}

export interface IndicatorComputeController {
  computeAll(force?: boolean): Promise<void>;
  computing: boolean;
  recompute(force?: boolean): void;
}

export function buildLocalIndicatorPlanSignature(
  indicators: IndicatorDefinition[],
  candleUpColor: string,
  candleDownColor: string,
): string {
  const keys = indicators
    .filter((indicator) => indicator.executionTarget === "local" || isFrontendScript(indicator))
    .map((indicator) => {
      const params = buildIndicatorComputeParams(indicator, {
        candleUpColor,
        candleDownColor,
      });
      return buildIndicatorComputeJobKey({
        indicator,
        lifecycleKey: "indicator-local-plan",
        params,
      });
    })
    .sort();
  return JSON.stringify(keys);
}

export function resolveSubmittedLocalJobKeysById({
  candleDownColor,
  candleUpColor,
  indicators,
  lifecycleKey,
  submittedJobKeys,
}: {
  candleDownColor: string;
  candleUpColor: string;
  indicators: readonly IndicatorDefinition[];
  lifecycleKey: string;
  submittedJobKeys: ReadonlySet<string>;
}): Map<string, string> {
  const result = new Map<string, string>();
  for (const indicator of indicators) {
    if (resolveLocalIndicatorExecution(indicator).kind !== "local") continue;
    const params = buildIndicatorComputeParams(indicator, {
      candleUpColor,
      candleDownColor,
    });
    const jobKey = buildIndicatorComputeJobKey({ indicator, lifecycleKey, params });
    if (submittedJobKeys.has(jobKey)) result.set(indicator.id, jobKey);
  }
  return result;
}

export function useIndicatorComputeController({
  activeIndicators,
  activeIndicatorsRef,
  candleDownColor,
  candleDownColorRef,
  candleUpColor,
  candleUpColorRef,
  chartData,
  builtinChartData,
  chartDataMeta,
  chartDataMetaRef,
  chartDataRef,
  datasetKey,
  exchange,
  seriesIdentity,
  inputSource,
  computeBatch = computeIndicatorBatch,
  executeBatch,
  onComputePendingChange,
  inputSnapshot,
  forceHostedSubscriptions,
  historyLimit,
  interval,
  marketType,
  outputDispatch,
  pendingForceComputeRef,
  resultCacheMode = "shared",
  seriesReady,
  setActiveIndicators,
  symbol,
}: UseIndicatorComputeControllerOptions): IndicatorComputeController {
  const [computing, setComputing] = useState(false);
  const [jobCoordinator] = useState(() => createIndicatorComputeJobCoordinator());
  const userTriggeredRef = useRef(false);
  const hasExplicitLocalIndicator = activeIndicators.some(
    (indicator) => indicator.executionTarget === "local" || isFrontendScript(indicator),
  );
  const desiredDataSignature = useMemo(
    () => hasExplicitLocalIndicator
      ? JSON.stringify([buildIndicatorOhlcvSignature(
          chartData || [],
          historyLimit === undefined ? {} : { limit: historyLimit },
        ), builtinChartData === undefined ? null : buildIndicatorOhlcvSignature(builtinChartData, { limit: builtinChartData.length })])
      : "hosted-only",
    [chartData, builtinChartData, hasExplicitLocalIndicator, historyLimit],
  );
  const desiredPlanSignature = useMemo(() => buildLocalIndicatorPlanSignature(
    activeIndicators,
    candleUpColor,
    candleDownColor,
  ), [activeIndicators, candleDownColor, candleUpColor]);
  const desiredLifecycleKey = buildIndicatorComputeLifecycleKey({
    dataSignature: JSON.stringify([desiredDataSignature, desiredPlanSignature, klineSeriesIdentityKey(exchange, seriesIdentity), inputSource?.scope]),
    datasetKey,
    exchange,
    interval,
    marketType,
    symbol,
  });
  const committedRuntimeRef = useRef({
    context: { datasetKey, exchange, interval, marketType, symbol, seriesIdentity, inputSource },
    lifecycleKey: desiredLifecycleKey,
    builtinChartData,
    inputSnapshot,
  });

  const computeAll = useCallback(async (force = false) => {
    const showUI = userTriggeredRef.current;
    userTriggeredRef.current = false;
    const currentChartData = chartDataRef.current;
    const currentIndicators = activeIndicatorsRef.current;
    const committedRuntime = committedRuntimeRef.current;
    const context = committedRuntime.context;
    const lifecycleKey = committedRuntime.lifecycleKey;
    // React may not have committed the new lifecycle when a source changes.
    // Fence directly against the captured owner/input before any publication.
    const providedRows = limitIndicatorHistory(currentChartData, historyLimit);
    const inputSeries = { ...context.seriesIdentity, ...context };
    const inputVersion = context.inputSource?.captureProvided(inputSeries, providedRows);
    const last = providedRows.at(-1);
    const closedInput = last ? context.inputSource?.capture(inputSeries,
      Number(last.time) - (last.is_closed === true ? 0 : 1), Number(providedRows[0]!.time)) : null;
    const inputIsCurrent = () => (committedRuntime.inputSnapshot?.isCurrent("forming-preview") ?? true)
      && (closedInput?.isCurrent() ?? true);
    if (!inputIsCurrent()) return;

    if (!currentChartData || currentChartData.length === 0) {
      recordPerfEvent("indicator.compute.skip", { reason: "no-chart-data" });
      return;
    }

    jobCoordinator.activate(lifecycleKey);

    const invalid = new Map<string, string>();
    const localIndicators = currentIndicators.flatMap((indicator) => {
      if (isFrontendScript(indicator) && indicator.visible === false) return [];
      // A broken browser program remains visible and idle until an explicit
      // retry or program/parameter edit. Live ticks must not spin it forever.
      if (isFrontendScript(indicator) && indicator.error && !force) return [];
      const resolution = resolveLocalIndicatorExecution(indicator);
      if (resolution.kind === "invalid") {
        invalid.set(indicator.id, resolution.error);
        return [];
      }
      return resolution.kind === "local" ? [{ indicator, execution: resolution.execution }] : [];
    });
    if (invalid.size > 0) {
      setActiveIndicators((previous) => {
        let changed = false;
        const next = previous.map((indicator) => {
          const error = invalid.get(indicator.id);
          if (!error || indicator.error === error) return indicator;
          changed = true;
          return { ...indicator, error };
        });
        return changed ? next : previous;
      });
    }
    if (localIndicators.length === 0) {
      recordPerfEvent("indicator.compute.skip", { reason: "no-local-indicators" });
      return;
    }

    if (showUI) setComputing(true);
    const ohlcv = buildIndicatorOhlcv(
      currentChartData,
      historyLimit === undefined ? {} : { limit: historyLimit },
    );
    const builtinOhlcv = committedRuntime.builtinChartData === undefined ? ohlcv
      : buildIndicatorOhlcv(committedRuntime.builtinChartData, { limit: committedRuntime.builtinChartData.length });
    const targetByJobKey = new Map<string, {
      indicator: IndicatorDefinition;
      job: IndicatorComputeBatchJob;
    }>();
    for (const { indicator, execution } of localIndicators) {
      const params = buildIndicatorComputeParams(indicator, {
        candleUpColor: candleUpColorRef.current,
        candleDownColor: candleDownColorRef.current,
      });
      const jobKey = buildIndicatorComputeJobKey({ indicator, lifecycleKey, params });
      const request: IndicatorComputeRequest = {
        mode: execution.mode,
        ohlcv: execution.mode === "builtin" ? builtinOhlcv : ohlcv,
        params,
        exchange: context.exchange,
        seriesIdentity: context.seriesIdentity,
        symbol: context.symbol,
        interval: context.interval,
        marketType: context.marketType,
      };
      if (execution.name !== undefined) request.name = execution.name;
      if (execution.script !== undefined) request.script = execution.script;
      if (execution.mode === "script" && indicator.language !== undefined) {
        request.language = indicator.language;
      }
      if (execution.securityMode !== undefined) request.securityMode = execution.securityMode;
      targetByJobKey.set(jobKey, {
        indicator,
        job: { clientId: indicator.id, jobKey, request },
      });
    }
    const jobs = Array.from(targetByJobKey.values()).map((target) => target.job);
    const cacheContext = resultCacheMode === "shared"
      ? buildIndicatorCacheContext({
          inputSource: context.inputSource,
          localInputKey: buildIndicatorOhlcvSignature(providedRows, { limit: providedRows.length }),
          seriesIdentity: context.seriesIdentity,
          candleDownColor: candleDownColorRef.current,
          candleUpColor: candleUpColorRef.current,
          exchange: context.exchange,
          interval: context.interval,
          marketType: context.marketType,
          symbol: context.symbol,
        })
      : null;
    const submittedJobKeys = new Set<string>();
    const publishedJobKeys = new Set<string>();
    const publishResults = (results: IndicatorComputeBatchItem[]) => {
      if (!inputIsCurrent() || committedRuntimeRef.current.lifecycleKey !== lifecycleKey) return;
      const acceptedJobKeyById = new Map<string, string>();
      const accepted = results.flatMap((result) => {
        if (publishedJobKeys.has(result.jobKey)) return [];
        const target = targetByJobKey.get(result.jobKey);
        if (!target || result.clientId !== target.indicator.id) return [];
        const currentIndicator = activeIndicatorsRef.current.find(
          (indicator) => indicator.id === target.indicator.id,
        );
        if (!currentIndicator) return [];
        const currentResolution = resolveLocalIndicatorExecution(currentIndicator);
        if (currentResolution.kind !== "local") return [];
        const currentParams = buildIndicatorComputeParams(currentIndicator, {
          candleUpColor: candleUpColorRef.current,
          candleDownColor: candleDownColorRef.current,
        });
        if (buildIndicatorComputeJobKey({
          indicator: currentIndicator,
          lifecycleKey,
          params: currentParams,
        }) !== result.jobKey) return [];
        acceptedJobKeyById.set(currentIndicator.id, result.jobKey);
        return [{
          status: "fulfilled" as const,
          value: {
            id: currentIndicator.id,
            result: result.payload,
            visible: Boolean(currentIndicator.visible),
          },
        }];
      });
      if (accepted.length === 0) return;
      for (const key of acceptedJobKeyById.values()) {
        publishedJobKeys.add(key);
        submittedJobKeys.delete(key);
      }

      const {
        processedResults,
        allMarkers,
        allFills,
        allHlines,
        allBgcolors,
        allBarcolors,
        allSignals,
        allDrawings,
        newParamSchemas,
      } = collectIndicatorComputeResults(accepted, { parsed: true });
      const indicatorById = new Map(
        activeIndicatorsRef.current.map((indicator) => [indicator.id, indicator]),
      );
      const cachedJobKeys: string[] = [];
      for (const { id, normalized, error } of processedResults) {
        if (error || !normalized) continue;
        const jobKey = acceptedJobKeyById.get(id);
        // A separately provided builtin viewport cannot certify the larger
        // script-input cache identity. Its completed job can still publish.
        const cacheable = jobKey !== undefined && targetByJobKey.get(jobKey)?.job.request.ohlcv === ohlcv;
        const cached = cacheContext === null || !cacheable || cacheIndicatorSnapshot(
          indicatorById.get(id),
          cacheContext,
          normalized,
          newParamSchemas[id],
          { ...(inputVersion ? { inputVersion } : {}),
            range: { start: Number(providedRows[0]!.time), end: Number(providedRows.at(-1)!.time) } },
        );
        if (cached && jobKey) cachedJobKeys.push(jobKey);
      }
      jobCoordinator.complete(cachedJobKeys);

      const publishAcceptedResults = () => {
        if (!inputIsCurrent() || committedRuntimeRef.current.lifecycleKey !== lifecycleKey) return;
        outputDispatch({
          type: "compute-results",
          processedIds: processedResults.map((item) => item.id),
          markers: allMarkers,
          fills: allFills,
          hlines: allHlines,
          bgcolors: allBgcolors,
          barcolors: allBarcolors,
          signals: allSignals,
          drawings: allDrawings,
          paramSchemas: newParamSchemas,
        });

        setActiveIndicators((prev) => {
          if (!inputIsCurrent() || committedRuntimeRef.current.lifecycleKey !== lifecycleKey) {
            return prev;
          }
          const updated = [...prev];
          for (const { id, mappedLines, error } of processedResults) {
            const index = updated.findIndex((indicator) => indicator.id === id);
            if (index === -1) continue;
            const current = updated[index];
            if (current === undefined) continue;
            const paramSchema = newParamSchemas[id];
            updated[index] = {
              ...current,
              lines: mappedLines,
              error,
              ...(paramSchema ? { paramSchema } : {}),
            };
          }
          return updated;
        });
      };
      if (resultCacheMode === "disabled") {
        // Replay must publish in the urgent lane. A deferred transition from a
        // longer revealed prefix could otherwise commit after a cursor rewind
        // and repaint historical points with future-bar knowledge.
        flushSync(publishAcceptedResults);
      } else {
        startTransition(publishAcceptedResults);
      }
    };
    try {
      const scheduled = await jobCoordinator.schedule<
        IndicatorComputeBatchJob,
        IndicatorComputeBatchItem
      >({
        force,
        isResultComplete: (result) => result.payload.ok === false,
        jobs,
        lifecycleKey,
        onResults: publishResults,
        execute: async (physicalJobs, signal, publish) => {
          const startedAt = performance.now();
          const cached = physicalJobs.flatMap(job => {
            const result = cachedIndicatorComputeResult(job, targetByJobKey.get(job.jobKey)?.indicator, cacheContext, force);
            return result ? [result] : [];
          });
          const cachedKeys = new Set(cached.map(result => result.jobKey));
          publish(cached);
          const misses = physicalJobs.filter(job => !cachedKeys.has(job.jobKey));
          if (!misses.length) return cached;
          const chunks = chunkIndicatorComputeJobs(misses);
          for (const job of misses) {
            submittedJobKeys.add(job.jobKey);
            if (cacheContext !== null) {
              removeCachedIndicatorResult(
                targetByJobKey.get(job.jobKey)?.indicator,
                cacheContext,
              );
            }
          }
          markPerf("indicator.compute.start", {
            force,
            indicatorCount: physicalJobs.length,
            bars: ohlcv.length,
            symbol: context.symbol,
            interval: context.interval,
            marketType: context.marketType,
            exchange: context.exchange,
            lifecycleKey,
            physicalRequestCount: chunks.length,
          });
          try {
            onComputePendingChange?.(1);
            const responses = await Promise.all(
              chunks.map(async (chunk) => {
                const request = { jobs: chunk, signal, onResults: publish };
                const response = await (executeBatch ? executeBatch(request) : routeIndicatorComputeBatch(request, computeBatch));
                publish(response.results);
                return response;
              }),
            );
            return [...cached, ...responses.flatMap((response) => response.results)];
          } finally {
            onComputePendingChange?.(-1);
            markPerf("indicator.compute.end", {
              force,
              indicatorCount: physicalJobs.length,
              bars: ohlcv.length,
              symbol: context.symbol,
              interval: context.interval,
              marketType: context.marketType,
              exchange: context.exchange,
              lifecycleKey,
              durationMs: performance.now() - startedAt,
              physicalRequestCount: chunks.length,
            });
          }
        },
      });
      recordPerfEvent("indicator.compute.plan", {
        force,
        lifecycleKey,
        joined: scheduled.joined,
        queued: scheduled.queued,
        skipped: scheduled.skipped,
        stale: scheduled.stale,
      });
      if (scheduled.stale || scheduled.results.length === 0) return;
      if (!inputIsCurrent() || committedRuntimeRef.current.lifecycleKey !== lifecycleKey) return;

      publishResults(scheduled.results);
    } catch (error) {
      if (inputIsCurrent() && committedRuntimeRef.current.lifecycleKey === lifecycleKey) {
        const message = error instanceof Error ? error.message : String(error);
        const failedJobKeysById = resolveSubmittedLocalJobKeysById({
          candleDownColor: candleDownColorRef.current,
          candleUpColor: candleUpColorRef.current,
          indicators: activeIndicatorsRef.current,
          lifecycleKey,
          submittedJobKeys,
        });
        if (failedJobKeysById.size === 0) return;

        // A transport failure invalidates only the still-pending results.
        // Clear both chart lines and auxiliary trading signals immediately so
        // stale output cannot masquerade as a current computation.
        outputDispatch({
          type: "compute-results",
          processedIds: Array.from(failedJobKeysById.keys()),
          markers: [],
          fills: [],
          hlines: [],
          bgcolors: [],
          barcolors: [],
          signals: [],
          paramSchemas: {},
        });
        setActiveIndicators((previous) => {
          if (!inputIsCurrent() || committedRuntimeRef.current.lifecycleKey !== lifecycleKey) return previous;
          let changed = false;
          const next = previous.map((indicator) => {
            const failedJobKey = failedJobKeysById.get(indicator.id);
            if (!failedJobKey) return indicator;
            if (resolveLocalIndicatorExecution(indicator).kind !== "local") return indicator;
            const params = buildIndicatorComputeParams(indicator, {
              candleUpColor: candleUpColorRef.current,
              candleDownColor: candleDownColorRef.current,
            });
            const currentJobKey = buildIndicatorComputeJobKey({
              indicator,
              lifecycleKey,
              params,
            });
            if (currentJobKey !== failedJobKey) {
              return indicator;
            }
            if ((indicator.lines?.length ?? 0) === 0 && indicator.error === message) {
              return indicator;
            }
            changed = true;
            return { ...indicator, lines: [], error: message };
          });
          return changed ? next : previous;
        });
      }
    } finally {
      if (showUI) {
        setComputing(false);
      }
    }
  }, [
    activeIndicatorsRef,
    candleDownColorRef,
    candleUpColorRef,
    chartDataRef,
    computeBatch,
    executeBatch,
    historyLimit,
    jobCoordinator,
    onComputePendingChange,
    outputDispatch,
    resultCacheMode,
    setActiveIndicators,
  ]);

  const recompute = useCallback((force = true) => {
    userTriggeredRef.current = true;
    forceHostedSubscriptions();
    void computeAll(force);
  }, [computeAll, forceHostedSubscriptions]);

  useLayoutEffect(() => {
    committedRuntimeRef.current = {
      context: { datasetKey, exchange, interval, marketType, symbol, seriesIdentity, inputSource },
      lifecycleKey: desiredLifecycleKey,
      builtinChartData,
      inputSnapshot,
    };
    jobCoordinator.activate(desiredLifecycleKey);
  }, [
    datasetKey,
    builtinChartData,
    inputSnapshot,
    desiredLifecycleKey,
    exchange,
    seriesIdentity,
    inputSource,
    interval,
    jobCoordinator,
    marketType,
    symbol,
  ]);

  useEffect(() => {
    if (!chartData || chartData.length === 0) return;
    if (activeIndicators.length === 0) return;
    const urgent = pendingForceComputeRef.current;
    pendingForceComputeRef.current = false;

    let fired = false;
    const delayMs = resolveIndicatorComputeDelay({ chartDataMeta, force: urgent });
    if (shouldDeferIndicatorCompute(chartDataMeta)) {
      recordPerfEvent("indicator.compute.deferred", {
        reason: "provisional-chart-data",
        force: false,
        bars: chartData.length,
      });
    }
    const timer = setTimeout(() => {
      fired = true;
      void computeAll(urgent);
    }, delayMs);
    return () => {
      clearTimeout(timer);
      if (urgent && !fired) {
        pendingForceComputeRef.current = true;
      }
    };
  }, [
    activeIndicators,
    candleDownColor,
    candleUpColor,
    chartData,
    builtinChartData,
    chartDataMeta,
    computeAll,
    pendingForceComputeRef,
  ]);

  useEffect(() => {
    if (seriesReady === 0) return undefined;
    const currentIndicators = activeIndicatorsRef.current;
    const currentChartData = chartDataRef.current;
    const currentMeta = chartDataMetaRef.current;

    if (currentIndicators.length > 0 && currentChartData?.length > 0) {
      const delayMs = resolveSeriesReadyComputeDelay(currentMeta);
      const timer = setTimeout(() => {
        void computeAll(false);
      }, delayMs);
      return () => clearTimeout(timer);
    }
    return undefined;
  }, [activeIndicatorsRef, chartDataMetaRef, chartDataRef, computeAll, seriesReady]);

  useEffect(() => () => jobCoordinator.dispose(), [jobCoordinator]);

  return {
    computeAll,
    computing,
    recompute,
  };
}
