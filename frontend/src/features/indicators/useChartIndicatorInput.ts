import { useCallback, useMemo, useSyncExternalStore } from "react";
import { useBackendSyntheticSeries } from "../market-data/synthetic/useBackendSyntheticSeries.js";
import { EMPTY_SYNTHETIC, isSyntheticTransform } from "../market-data/synthetic/syntheticSeries.js";
import { chartIndicatorBars, chartIndicatorSourceError, type ChartIndicatorSelection } from "./chartIndicatorInput.js";
import type { IndicatorComputeBatchExecutor } from "./indicatorComputeController.js";
import { routeIndicatorComputeBatch } from "./frontendScriptBatch.js";
import { computeIndicatorBatch } from "../../services/indicatorApi.js";

const idle = () => () => {};
const empty = () => EMPTY_SYNTHETIC;
const disabled: ChartIndicatorSelection = { source: null, reader: null, chartType: "candlestick", settings: {} };

export function useChartIndicatorInput(selection: ChartIndicatorSelection | undefined) {
  const selected = selection ?? disabled;
  const backend = useBackendSyntheticSeries({ ...selected, display: null });
  const enabled = Boolean(selected.source && isSyntheticTransform(selected.chartType));
  const getSnapshot = useCallback(() => backend.binding?.snapshot() ?? EMPTY_SYNTHETIC, [backend.binding]);
  const snapshot = useSyncExternalStore(backend.binding?.subscribe ?? idle, getSnapshot, empty);
  const ordinal = selected.chartType !== "heikin-ashi";
  const bars = useMemo(() => chartIndicatorBars(snapshot, ordinal), [snapshot, ordinal]);
  const reference = useMemo(() => {
    const request = backend.binding?.request();
    return request && snapshot.status === "ready" ? { request, seriesId: snapshot.seriesId,
      generation: snapshot.generation, revision: snapshot.revision } : null;
  }, [backend.binding, snapshot]);
  const executeBatch = useMemo<IndicatorComputeBatchExecutor>(() => async options => {
    if (!reference) throw new Error("Chart indicator input is not ready");
    const sources = new Map(bars.map(row => [Number(row.time), Number(row.sourceTime)]));
    const enriched = new Map<unknown, typeof options.jobs[number]["request"]["ohlcv"]>();
    const jobs = options.jobs.map(job => {
      let rows = enriched.get(job.request.ohlcv);
      if (!rows) {
        rows = job.request.ohlcv.map(row => {
          const sourceTime = sources.get(row.time);
          if (sourceTime === undefined || !Number.isFinite(sourceTime)) throw new Error("Unknown chart input row");
          return { ...row, sourceTime };
        });
        enriched.set(job.request.ohlcv, rows);
      }
      return { ...job, request: { ...job.request, ohlcv: rows, chartInput: reference } };
    });
    return routeIndicatorComputeBatch({ ...options, jobs }, computeIndicatorBatch);
  }, [bars, reference]);
  return { enabled, ordinal: enabled && ordinal, bars, executeBatch, snapshot,
    ready: snapshot.status === "ready", key: `chart:${snapshot.seriesId}:${snapshot.generation}`,
    revision: snapshot.revision, status: backend.status, error: chartIndicatorSourceError(snapshot, backend.status) };
}
