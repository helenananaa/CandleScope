import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { t } from "../../../i18n/index.js";
import { useLocale } from "../../../i18n/useLocale.js";
import { useMarketDataWorkspaceResources } from "../../market-data/marketDataWorkspaceContext.js";
import type { SeriesWindowView } from "../../market-data/window/seriesWindowView.js";
import type { RunResultFamily } from "./runResult.js";
import {
  buildStrategyOverlay, StrategyOverlaySource, type StrategyMarkerEvidence, type StrategyOverlayLabels,
} from "./strategyOverlay.js";

/** The completed run a chart cell should overlay, by family and id. */
export interface StrategyOverlayRun {
  family: RunResultFamily;
  runId: string;
}

/** The overlay run for the native strategy panel's run: completed runs only, by execution mode. */
export function overlayRunForNative(run: {
  run_id: string; state: string; execution_mode?: string | null; result?: unknown;
} | null): StrategyOverlayRun | null {
  if (!run || run.state !== "COMPLETED" || !run.result) return null;
  return { family: run.execution_mode === "CANDLESCOPE" ? "external" : "native", runId: run.run_id };
}

/** The dock shows one run at a time: the native panel's in native mode, otherwise the fixed-history result. */
export function shownOverlayRun(mode: "NATIVE" | "CANDLESCOPE", native: StrategyOverlayRun | null,
  host: StrategyOverlayRun | null): StrategyOverlayRun | null {
  return mode === "NATIVE" ? native : host;
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
export function useStrategyRunOverlay({ run, interval, series, onActivate }: {
  run: StrategyOverlayRun | null;
  interval: string;
  series: SeriesWindowView | null;
  /** A marker with recorded evidence was clicked. */
  onActivate?: (evidence: StrategyMarkerEvidence) => void;
}): { source: StrategyOverlaySource; error: string | null } {
  const locale = useLocale();
  const manager = useMarketDataWorkspaceResources()?.dataManager.strategy;
  const activate = useRef(onActivate);
  useLayoutEffect(() => { activate.current = onActivate; }, [onActivate]);
  const source = useMemo(() => new StrategyOverlaySource((evidence) => activate.current?.(evidence)), []);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => () => source.dispose(), [source]);
  useEffect(() => { source.setSeries(series); }, [series, source]);
  const family = run?.family ?? null;
  const runId = run?.runId ?? null;
  useEffect(() => {
    source.setOverlay(null, null);
    setError(null);
    if (!manager || family === null || runId === null) return;
    const controller = new AbortController();
    manager.loadRunResult(family, runId, controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      if (result.interval !== interval) return;  // a run for another interval never draws on this chart
      void locale;
      const owner = `run:${family}:${runId}`;
      source.setOverlay(buildStrategyOverlay(result, { labels: strategyOverlayLabels(), idPrefix: owner }), result.interval, owner);
    }).catch((failure: unknown) => {
      if (controller.signal.aborted) return;
      setError(failure instanceof Error ? failure.message : String(failure));
    });
    return () => controller.abort();
  }, [family, interval, locale, manager, runId, source]);
  return { source, error };
}
