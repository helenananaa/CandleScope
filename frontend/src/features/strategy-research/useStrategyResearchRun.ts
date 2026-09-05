import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { ChartSession } from "../chart-session/chartSessionTypes.js";
import { defaultBacktestApi, type ChartContextResolution } from "../backtest/backtestApi.js";
import {
  chartStrategyResultCache,
  type ChartStrategyResultBundle,
} from "../backtest/chart-tester/chartStrategyResultCache.js";
import {
  ChartStrategyRunError,
  chartStrategyRunDiagnostics,
  qualitySummaryFromImportedManifest,
  runResearchBacktest,
} from "../backtest/chart-tester/chartStrategyRunRequest.js";
import { ChartStrategyTesterRuntime } from "../backtest/chart-tester/ChartStrategyTesterRuntime.js";
import type {
  ChartStrategyTesterStaleReason,
  ChartStrategyTesterStatus,
} from "../backtest/chart-tester/chartStrategyTesterState.js";
import { currentChartStrategyTesterToken } from "../backtest/chart-tester/chartStrategyTesterState.js";
import type { ChartStrategyRunRequest } from "../backtest/chart-tester/chartStrategyTesterUiModel.js";
import type { LocalDatasetManifest } from "../local-data/localDataTypes.js";
import type { ResearchRuntimeMode, ResearchSourceRefV1 } from "../research-data/researchDataTypes.js";
import { StrategyResearchRunEffectGuard } from "./strategyResearchRunLifecycle.js";
import { pollBacktestRunToTerminal } from "../backtest/backtestRunClient.js";
import { DEFAULT_STRATEGY_RUN_SETTINGS, validStrategyRunSettings, type StrategyRunSettings } from "../../shared/strategyRunSettings.js";

export function sessionFromResearchSource(
  source: ResearchSourceRefV1 | null,
  imported: LocalDatasetManifest | null,
  interval: string | null,
): ChartSession | null {
  if (source?.kind === "CURRENT_CHART") return { exchange: source.exchange, marketType: source.marketType, symbol: source.symbol, interval: source.interval };
  if (source?.kind === "IMPORTED_DATASET" && imported !== null) {
    return {
      exchange: "local",
      marketType: "spot",
      symbol: imported.symbol,
      interval: interval ?? imported.interval,
    };
  }
  return null;
}

function isAbortError(reason: unknown): boolean {
  if (reason instanceof DOMException && reason.name === "AbortError") return true;
  return reason instanceof Error && reason.name === "AbortError";
}

export function useStrategyResearchRun(input: {
  source: ResearchSourceRefV1 | null;
  imported: LocalDatasetManifest | null;
  interval: string | null;
  runtimeMode: ResearchRuntimeMode;
  draftId: string | null;
  draftContentRevision: number;
  configuration?: StrategyRunSettings | undefined;
  restoreRunId?: string | null;
  onRunId(runId: string | null): void;
}) {
  const tester = useMemo(() => new ChartStrategyTesterRuntime("strategy-research", null), []);
  const [, setTesterVersion] = useState(0);
  const [result, setResult] = useState<ChartStrategyResultBundle | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [needsData, setNeedsData] = useState<ChartContextResolution | null>(null);
  const [restoringRun, setRestoringRun] = useState(false);
  const pendingRequestRef = useRef<ChartStrategyRunRequest | null>(null);
  const lifecycle = useMemo(() => new StrategyResearchRunEffectGuard(), []);
  const session = useMemo(() => sessionFromResearchSource(input.source, input.imported, input.interval), [input.source, input.imported, input.interval]);
  const configuration = input.configuration ?? DEFAULT_STRATEGY_RUN_SETTINGS;

  useEffect(() => {
    const runId = input.restoreRunId;
    if (!runId || tester.snapshot().activeRunId === runId) return;
    const controller = new AbortController();
    setRestoringRun(true);
    void defaultBacktestApi.getRun(runId, controller.signal).then(async (record) => {
      const terminal = record.state === "QUEUED" || record.state === "RUNNING"
        ? await pollBacktestRunToTerminal({ api: defaultBacktestApi, runId, signal: controller.signal }) : record;
      if (terminal.state !== "COMPLETED") throw new Error(`Backtest ${terminal.state}: ${terminal.failure_code ?? runId}`);
      return chartStrategyResultCache.load(defaultBacktestApi, runId, controller.signal);
    }).then((bundle) => {
      if (!controller.signal.aborted) setResult(bundle);
    }).catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : String(reason)); })
      .finally(() => { if (!controller.signal.aborted) setRestoringRun(false); });
    return () => controller.abort();
  }, [input.restoreRunId, tester]);

  useEffect(() => tester.subscribe(() => setTesterVersion((value) => value + 1)), [tester]);
  // StrictMode replays this effect immediately; the guard ignores the
  // rehearsal cleanup but disposes after a real unmount.
  useEffect(() => lifecycle.mount(tester), [lifecycle, tester]);

  useEffect(() => {
    const source = input.source;
    const before = tester.snapshot().generation;
    tester.syncInputs(session && source ? {
      session,
      attachment: {
        schemaVersion: 1,
        strategyDraftId: input.draftId ?? "draft-placeholder",
        strategyRevisionId: null,
        displayName: "",
        language: "pyne",
        parameters: {},
        fidelityPreference: "FAST",
        quickPresetId: session.marketType === "spot" ? "CRYPTO_SPOT_STANDARD_V1" : "CRYPTO_PERP_STANDARD_V1",
        autoRun: false,
        ...configuration,
      },
      draftContentRevision: input.draftContentRevision,
      sourceKind: source.kind,
      ...(source.kind === "IMPORTED_DATASET"
        ? { datasetId: source.datasetId, dataEpoch: source.dataEpoch }
        : {}),
    } : null);
    if (tester.snapshot().generation !== before) {
      pendingRequestRef.current = null;
      setNeedsData(null);
    }
  }, [configuration, input.draftContentRevision, input.draftId, input.source, session, tester]);

  const snapshot = tester.snapshot();
  const barOnly = input.source?.kind === "IMPORTED_DATASET";
  const restoredContextChanged = result !== null && session !== null && (
    result.chart.symbol !== session.symbol || result.chart.interval !== session.interval
    || (input.source?.kind === "IMPORTED_DATASET" && (
      result.run.dataset_id !== input.source.datasetId || result.run.data_epoch !== input.source.dataEpoch
    ))
  );
  const inputStale = snapshot.status === "STALE" || restoredContextChanged;
  const updatingResult = result !== null && ["RESOLVING", "QUEUED", "RUNNING"].includes(snapshot.status);

  const execute = useCallback(async (request: ChartStrategyRunRequest, materialize?: ChartContextResolution | null) => {
    pendingRequestRef.current = request;
    setError(null);
    const token = tester.beginRequest("RESOLVING");
    const controller = new AbortController();
    const untrack = tester.trackAbortController(controller);
    const stillCurrent = () => (
      currentChartStrategyTesterToken(tester.snapshot()).generation === token.generation
      && !controller.signal.aborted
    );
    try {
      const source = input.source;
      const imported = input.imported;
      if (!validStrategyRunSettings(configuration)) throw new Error("Invalid backtest conditions");
      if (source === null) throw new Error("source required");
      if (source.kind === "CURRENT_CHART" && input.runtimeMode === "LOCAL_OFFLINE") {
        throw new ChartStrategyRunError(
          "CURRENT_CHART_UNBOUND",
          "live chart backtesting is unavailable in the offline runtime",
          { next_step: "use the market-page strategy tester or imported library data" },
        );
      }
      if (source.kind === "IMPORTED_DATASET" && imported === null) {
        throw new ChartStrategyRunError(
          "IMPORTED_DATASET_NOT_READY",
          "imported data is not ready for a Run",
          { next_step: "select the current library dataset and run again" },
        );
      }
      if (input.runtimeMode === "LOCAL_OFFLINE" && materialize) {
        throw new ChartStrategyRunError(
          "OFFLINE_LIVE_SOURCE_UNAVAILABLE",
          "live market data is unavailable in the offline runtime",
          { next_step: "use imported library data" },
        );
      }
      if (source.kind !== "CURRENT_CHART" && (source.kind !== "IMPORTED_DATASET" || imported === null)) {
        throw new ChartStrategyRunError(
          "SOURCE_UNSUPPORTED",
          "this workspace can only run imported library data",
          { next_step: "select imported library data" },
        );
      }
      const researchSource = source.kind === "CURRENT_CHART" ? {
        kind: "CURRENT_CHART" as const,
        materializeResolution: materialize ?? null,
      } : {
        kind: "IMPORTED_DATASET" as const,
        datasetId: imported!.dataset_id,
        dataEpoch: imported!.data_epoch,
        interval: input.interval ?? source.interval,
        symbol: imported!.symbol,
        startTimeMs: configuration.customRange?.startMs ?? imported!.first_open_ms,
        endTimeMs: configuration.customRange?.endMs ?? imported!.last_open_ms + 1,
        quality: qualitySummaryFromImportedManifest({
          rows: imported!.rows,
          excludedRangeCount: imported!.excluded_range_count,
          volumeAvailable: imported!.volume_available,
        }),
      };
      if (researchSource.kind === "IMPORTED_DATASET" && imported && (researchSource.startTimeMs < imported.first_open_ms || researchSource.endTimeMs > imported.last_open_ms + 1)) {
        throw new ChartStrategyRunError("DATA_COVERAGE_INCOMPLETE", "The selected dates exceed the imported data coverage", { next_step: "choose dates within the data coverage" });
      }
      const outcome = await runResearchBacktest({
        api: defaultBacktestApi,
        request,
        source: researchSource,
        signal: controller.signal,
        onResolution(resolution) {
          if (!stillCurrent()) return;
          tester.dispatch({
            type: "REQUEST_STATUS",
            token,
            status: resolution.status === "NEEDS_DATA" ? "NEEDS_DATA" : "RESOLVING",
          });
        },
        onRunCreated(run, identity) {
          if (!stillCurrent()) return;
          input.onRunId(run.run_id);
          tester.dispatch({
            type: "REQUEST_STATUS",
            token,
            status: run.state === "QUEUED" ? "QUEUED" : "RUNNING",
            activeRunId: run.run_id,
          });
          void identity;
        },
      });
      if (!stillCurrent()) return;
      if (outcome.kind === "NEEDS_DATA") {
        setNeedsData(outcome.resolution);
        tester.dispatch({ type: "REQUEST_STATUS", token, status: "NEEDS_DATA" });
        return;
      }
      setNeedsData(null);
      if (outcome.kind !== "TERMINAL") {
        tester.dispatch({
          type: "REQUEST_FAILED",
          token,
          error: { code: outcome.resolution.status, message: outcome.resolution.status, action: null },
        });
        return;
      }
      tester.dispatch({ type: "REQUEST_COMPLETED", token, identity: outcome.identity });
      const bundle = await chartStrategyResultCache.load(
        defaultBacktestApi,
        outcome.run.run_id,
        controller.signal,
      );
      if (!stillCurrent()) return;
      setResult(bundle);
      input.onRunId(outcome.run.run_id);
    } catch (reason) {
      if (!stillCurrent() || isAbortError(reason)) return;
      const diagnostics = chartStrategyRunDiagnostics(reason);
      setError(diagnostics.message);
      tester.dispatch({
        type: "REQUEST_FAILED",
        token,
        error: { code: diagnostics.code, message: diagnostics.message, action: diagnostics.action },
      });
    } finally {
      untrack();
    }
  }, [configuration, input, tester]);

  const onRun = useCallback((request: ChartStrategyRunRequest) => {
    void execute(request, null);
  }, [execute]);

  const onConfirmNeedsData = useCallback(() => {
    const pending = pendingRequestRef.current;
    if (pending === null || needsData === null) return;
    void execute(pending, needsData);
  }, [execute, needsData]);

  return {
    session,
    barOnly,
    runStatus: (restoringRun ? "RUNNING" : snapshot.status) as ChartStrategyTesterStatus,
    stale: inputStale || updatingResult,
    inputStale,
    staleReasons: snapshot.staleReasons as ChartStrategyTesterStaleReason[],
    result,
    error,
    needsData: needsData !== null,
    dataResolution: needsData,
    onRun,
    onConfirmNeedsData,
    tester,
  };
}
