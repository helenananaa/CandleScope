import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { t } from "../../../i18n/index.js";
import { useLocale } from "../../../i18n/useLocale.js";
import { useMarketDataWorkspaceResources } from "../../market-data/marketDataWorkspaceContext.js";
import type { SeriesWindowView } from "../../market-data/window/seriesWindowView.js";
import type { StrategyDataManager } from "../../market-data/manager/strategyDataManager.js";
import type { RunResult, RunResultFamily } from "./runResult.js";
import type { StrategyRunStatus } from "./strategyRun.js";
import { StrategyRunStreamError } from "../backtestRunStream.js";
import {
  buildStrategyOverlay, StrategyOverlaySource, type StrategyMarkerEvidence, type StrategyOverlayLabels,
} from "./strategyOverlay.js";

/** The completed run a chart cell should overlay, by family and id. */
export interface StrategyOverlayRun {
  family: RunResultFamily;
  runId: string;
  /** A FOLLOW run (P4b): the fixed run it keeps current, whose views it takes over. */
  followsRunId?: string;
}

/** A loaded run result together with the run it belongs to, for views that show it. */
export interface ShownRunResult {
  run: StrategyOverlayRun;
  result: RunResult;
}

/** The overlay run for the native strategy panel's run: completed runs only, by execution mode. */
export function overlayRunForNative(run: {
  run_id: string; state: string; execution_mode?: string | null; result?: unknown;
} | null): StrategyOverlayRun | null {
  if (!run || run.state !== "COMPLETED" || !run.result) return null;
  return { family: run.execution_mode === "CANDLESCOPE" ? "external" : "native", runId: run.run_id };
}

/** The dock shows one run at a time: the native panel's in native mode, otherwise the CandleScope-mode run. */
export function shownOverlayRun(mode: "NATIVE" | "CANDLESCOPE", native: StrategyOverlayRun | null,
  candleScope: StrategyOverlayRun | null): StrategyOverlayRun | null {
  return mode === "NATIVE" ? native : candleScope;
}

/**
 * Follow a forward run (ADR-BACKTEST-015 P2d): its result is read for each committed revision the
 * run's stream reports, coalesced so at most one read is in flight, until the run stops. A resumed
 * run (a new generation) reconnects. Resolves when the run stops; the last result is its final one.
 */
export function followForwardRun(manager: Pick<StrategyDataManager, "loadRunResult" | "watchRun">, runId: string,
  signal: AbortSignal, onResult: (result: RunResult) => void, onError: (failure: unknown) => void): Promise<void> {
  return followLiveRun(manager, "continuous", runId, signal, onResult, onError);
}

/**
 * Follow a run whose result keeps changing: a forward run (P2d) or a chart's FOLLOW run (P4b), whose
 * stream reports each newly applied page of bars. A recomputed FOLLOW run (a new generation) reconnects.
 */
export async function followLiveRun(manager: Pick<StrategyDataManager, "loadRunResult" | "watchRun">,
  family: "continuous" | "follow", runId: string, signal: AbortSignal, onResult: (result: RunResult) => void,
  onError: (failure: unknown) => void): Promise<void> {
  let loading: Promise<void> | null = null;
  let again = false;
  const refresh = (): Promise<void> => {
    if (loading) { again = true; return loading; }
    loading = (async () => {
      do {
        again = false;
        const result = await manager.loadRunResult(family, runId, signal);
        if (!signal.aborted) onResult(result);
      } while (again && !signal.aborted);
    })().finally(() => { loading = null; });
    return loading;
  };
  const onStatus = (status: StrategyRunStatus) => {
    if (status.result_available && !status.terminal) refresh().catch(onError);
  };
  for (;;) {
    try {
      const stopped = await manager.watchRun(runId, onStatus, signal);
      if (stopped.result_available) await refresh();
      return;
    } catch (failure) {
      if (!signal.aborted && failure instanceof StrategyRunStreamError && failure.code === "RUN_IDENTITY_CHANGED") continue;
      throw failure;
    }
  }
}

export function strategyOverlayLabels(): StrategyOverlayLabels {
  return {
    actions: {
      OPEN_LONG: t("backtest.openLong"), ADD_LONG: t("backtest.addLong"), REDUCE_LONG: t("backtest.reduceLong"),
      CLOSE_LONG: t("backtest.closeLong"), REVERSE_TO_SHORT: t("backtest.reverseShort"),
      OPEN_SHORT: t("backtest.openShort"), ADD_SHORT: t("backtest.addShort"), REDUCE_SHORT: t("backtest.reduceShort"),
      CLOSE_SHORT: t("backtest.closeShort"), REVERSE_TO_LONG: t("backtest.reverseLong"),
    },
    long: t("report.long"),
    short: t("report.short"),
    workingOrder: t("replay.shell.order"),
    rejection: t("backtest.reject"),
  };
}

/**
 * One overlay source per chart cell. It shows `run` only while its result's interval
 * matches the chart's, and clears on any load failure rather than drawing stale data.
 */
export function useStrategyRunOverlay({ run, interval, series, onActivate, manager: explicitManager }: {
  run: StrategyOverlayRun | null;
  interval: string;
  /** The chart's loaded bars. Leave undefined when the chart registers them itself (setSeries). */
  series?: SeriesWindowView | null;
  /** A page with its own data manager (the research page) passes it; charts use the workspace's. */
  manager?: StrategyDataManager | null;
  /** A marker with recorded evidence was clicked. */
  onActivate?: (evidence: StrategyMarkerEvidence) => void;
}): { source: StrategyOverlaySource; error: string | null; shown: ShownRunResult | null } {
  const locale = useLocale();
  const workspaceManager = useMarketDataWorkspaceResources()?.dataManager.strategy;
  const manager = explicitManager ?? workspaceManager;
  const activate = useRef(onActivate);
  useLayoutEffect(() => { activate.current = onActivate; }, [onActivate]);
  const source = useMemo(() => new StrategyOverlaySource((evidence) => activate.current?.(evidence)), []);
  const [error, setError] = useState<string | null>(null);
  const [shown, setShown] = useState<ShownRunResult | null>(null);
  useEffect(() => () => source.dispose(), [source]);
  useEffect(() => { if (series !== undefined) source.setSeries(series); }, [series, source]);
  const family = run?.family ?? null;
  const runId = run?.runId ?? null;
  const followsRunId = run?.followsRunId;
  useEffect(() => {
    source.setOverlay(null, null);
    setError(null);
    setShown(null);
    if (!manager || family === null || runId === null) return;
    const controller = new AbortController();
    const owner = `run:${family}:${runId}`;
    const draw = (result: RunResult) => {
      if (controller.signal.aborted) return;
      if (result.interval !== interval) return;  // a run for another interval never draws on this chart
      void locale;
      source.setOverlay(buildStrategyOverlay(result, { labels: strategyOverlayLabels(), idPrefix: owner }), result.interval, owner);
      setShown({ run: { family, runId, ...(followsRunId ? { followsRunId } : {}) }, result });
    };
    const fail = (failure: unknown) => {
      if (controller.signal.aborted) return;
      setError(failure instanceof Error ? failure.message : String(failure));
    };
    if (family === "continuous" || family === "follow") {
      void followLiveRun(manager, family, runId, controller.signal, draw, fail).catch(fail);
    } else manager.loadRunResult(family, runId, controller.signal).then(draw).catch(fail);
    return () => controller.abort();
  }, [family, followsRunId, interval, locale, manager, runId, source]);
  return { source, error, shown };
}
