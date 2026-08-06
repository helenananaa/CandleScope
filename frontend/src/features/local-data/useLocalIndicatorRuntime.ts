import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from "react";

import {
  createActiveIndicatorPersistence,
  useActiveIndicatorStore,
} from "../indicators/activeIndicatorStore.js";
import {
  buildIndicatorMutationSignature,
  collectIndicatorComputeResults,
} from "../indicators/indicatorComputeRuntime.js";
import {
  createIndicatorOutputState,
  filterIndicatorOutputStateByVisibility,
  indicatorOutputReducer,
} from "../indicators/indicatorOutputReducer.js";
import { buildIndicatorPaneData } from "../indicators/indicatorPaneProjection.js";
import type { IndicatorRuntime } from "../indicators/indicatorRuntimeContract.js";
import type {
  IndicatorDefinition,
  IndicatorPayloadEnvelope,
} from "../indicators/indicatorTypes.js";
import { computeLocalIndicatorBatch } from "./localDataApi.js";
import type { LocalIndicatorComputeJob } from "./localDataApi.js";
import type { LocalDatasetManifest, LocalIndicatorName } from "./localDataTypes.js";
import { normalizeLocalIndicatorDefinition } from "./localIndicatorCatalog.js";


const EMPTY_RANGE_REQUEST = () => false;
const LOCAL_INDICATOR_COMPUTE_DEBOUNCE_MS = 160;

function hashText(value: string): string {
  let hash = 0x811c9dc5;
  for (let index = 0; index < value.length; index += 1) {
    hash = Math.imul(hash ^ value.charCodeAt(index), 0x01000193);
  }
  return (hash >>> 0).toString(36);
}

function jobForIndicator(
  manifest: LocalDatasetManifest,
  indicator: IndicatorDefinition,
): LocalIndicatorComputeJob | null {
  const normalized = normalizeLocalIndicatorDefinition(indicator);
  if (normalized === null || !normalized.engineName) return null;
  const params = normalized.params ?? {};
  return {
    clientId: normalized.id,
    jobKey: `${manifest.data_epoch.slice(7, 19)}:${normalized.id}:${hashText(JSON.stringify(params))}`,
    name: normalized.engineName as LocalIndicatorName,
    params,
  };
}

export function useLocalIndicatorRuntime(
  manifest: LocalDatasetManifest,
): IndicatorRuntime {
  const persistence = useMemo(() => createActiveIndicatorPersistence(
    `candlescope:local-indicators:v1:${manifest.dataset_id}:${manifest.data_epoch}`,
  ), [manifest.data_epoch, manifest.dataset_id]);
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
    normalizeIndicator: normalizeLocalIndicatorDefinition,
    persistence,
  });
  const [outputState, outputDispatch] = useReducer(
    indicatorOutputReducer,
    undefined,
    createIndicatorOutputState,
  );
  const [computing, setComputing] = useState(false);
  const activeIndicatorsRef = useRef(activeIndicators);
  const requestGenerationRef = useRef(0);
  const requestControllerRef = useRef<AbortController | null>(null);

  useLayoutEffect(() => {
    activeIndicatorsRef.current = activeIndicators;
  }, [activeIndicators]);

  const runCompute = useCallback(async (): Promise<void> => {
    const snapshot = activeIndicatorsRef.current;
    const jobs = snapshot.flatMap((indicator) => {
      const job = jobForIndicator(manifest, indicator);
      return job === null ? [] : [job];
    });
    if (jobs.length === 0) {
      requestControllerRef.current?.abort();
      outputDispatch({ type: "reset-context", preserveParamSchemas: false });
      setComputing(false);
      return;
    }

    requestControllerRef.current?.abort();
    const controller = new AbortController();
    requestControllerRef.current = controller;
    const generation = requestGenerationRef.current + 1;
    requestGenerationRef.current = generation;
    setComputing(true);
    const expectedJobById = new Map(jobs.map((job) => [job.clientId, job.jobKey]));
    try {
      const response = await computeLocalIndicatorBatch(manifest, jobs, controller.signal);
      if (controller.signal.aborted || requestGenerationRef.current !== generation) return;
      const resultById = new Map(response.results.map((item) => [item.clientId, item]));
      const accepted: PromiseSettledResult<{
        id: string;
        result: IndicatorPayloadEnvelope;
        visible: boolean;
      }>[] = snapshot.flatMap((indicator) => {
        const item = resultById.get(indicator.id);
        if (!item || item.jobKey !== expectedJobById.get(indicator.id)) return [];
        return [{
          status: "fulfilled" as const,
          value: {
            id: indicator.id,
            result: item.payload,
            visible: indicator.visible === true,
          },
        }];
      });
      const collected = collectIndicatorComputeResults(accepted, { parsed: true });
      outputDispatch({
        type: "compute-results",
        processedIds: collected.processedResults.map((item) => item.id),
        markers: collected.allMarkers,
        fills: collected.allFills,
        hlines: collected.allHlines,
        bgcolors: collected.allBgcolors,
        barcolors: collected.allBarcolors,
        signals: collected.allSignals,
        paramSchemas: collected.newParamSchemas,
      });
      setActiveIndicators((current) => current.map((indicator) => {
        const expectedJob = expectedJobById.get(indicator.id);
        const currentJob = jobForIndicator(manifest, indicator);
        if (!expectedJob || currentJob?.jobKey !== expectedJob) return indicator;
        const processed = collected.processedResults.find((item) => item.id === indicator.id);
        if (!processed) return indicator;
        const paramSchema = collected.newParamSchemas[indicator.id];
        return {
          ...indicator,
          lines: processed.mappedLines,
          error: processed.error,
          ...(paramSchema ? { paramSchema } : {}),
        };
      }));
    } catch (reason) {
      if (controller.signal.aborted || requestGenerationRef.current !== generation) return;
      const message = reason instanceof Error ? reason.message : "本地指标计算失败";
      outputDispatch({
        type: "compute-results",
        processedIds: Array.from(expectedJobById.keys()),
        markers: [],
        fills: [],
        hlines: [],
        bgcolors: [],
        barcolors: [],
        signals: [],
        paramSchemas: {},
      });
      setActiveIndicators((current) => current.map((indicator) => {
        const expectedJob = expectedJobById.get(indicator.id);
        const currentJob = jobForIndicator(manifest, indicator);
        return expectedJob && currentJob?.jobKey === expectedJob
          ? { ...indicator, lines: [], error: message }
          : indicator;
      }));
    } finally {
      if (requestGenerationRef.current === generation) setComputing(false);
    }
  }, [manifest, setActiveIndicators]);

  const mutationSignature = useMemo(
    () => buildIndicatorMutationSignature(activeIndicators),
    [activeIndicators],
  );
  useEffect(() => {
    const timer = globalThis.setTimeout(() => {
      void runCompute();
    }, LOCAL_INDICATOR_COMPUTE_DEBOUNCE_MS);
    return () => globalThis.clearTimeout(timer);
  }, [mutationSignature, runCompute]);
  useEffect(() => () => requestControllerRef.current?.abort(), []);

  const removeIndicator = useCallback((indicatorId: string) => {
    removeActiveIndicator(indicatorId);
    outputDispatch({ type: "remove-indicator", indicatorId });
  }, [removeActiveIndicator]);
  const visibleOutputState = useMemo(
    () => filterIndicatorOutputStateByVisibility(outputState, activeIndicators),
    [activeIndicators, outputState],
  );
  const paneData = useMemo(() => buildIndicatorPaneData(activeIndicators, {
    markers: visibleOutputState.markers,
    fills: visibleOutputState.fills,
    hlines: visibleOutputState.hlines,
    bgcolors: visibleOutputState.bgcolors,
  }), [activeIndicators, visibleOutputState]);

  return {
    view: {
      activeIndicators,
      mainOverlayLines: paneData.mainOverlayLines,
      subPanes: paneData.subPanes,
      ...visibleOutputState,
    },
    actions: {
      addIndicator,
      computeAll: () => runCompute(),
      ensureVisibleIndicatorRange: EMPTY_RANGE_REQUEST,
      recompute: () => { void runCompute(); },
      removeIndicator,
      requestIndicatorRange: EMPTY_RANGE_REQUEST,
      toggleVisibility,
      updateIndicatorParams,
      updateIndicatorScript,
    },
    status: {
      computing,
      realtimeMode: "historical-only",
    },
  };
}
