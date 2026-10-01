import type { StrategyTradeFocus } from "./strategyTradeReview.js";
import { floorIntervalTime } from "../../../utils/intervalTimeline.js";
import type {
  ExternalMarkerSnapshot,
  ExternalMarkerSource,
  ExternalSeriesMarker,
} from "../../../chart-adapter/externalMarkerSource.js";
import type { ChartSurfaceVisibleRange } from "../../../chart-adapter/useChartSurfaceRuntime.js";
import { parseIntervalSeconds } from "../../../utils/intervals.js";
import type { SeriesWindowStore } from "../../market-data/window/seriesWindowStore.js";
import type { BacktestChartData } from "../backtestTypes.js";
import type { TradeExplanationV1 } from "../backtestTypes.js";
import {
  projectBacktestResultMarkers,
  type BacktestMarkerLabels,
} from "./chartStrategyResultProjection.js";
import type { ChartStrategyTesterMarkerSource } from "./ChartStrategyTesterRuntime.js";

const EMPTY_SNAPSHOT: ExternalMarkerSnapshot = Object.freeze({
  markers: Object.freeze([]),
  revision: 0,
});

export const CHART_STRATEGY_MARKER_OVERSCAN_BARS = 20;
export const CHART_STRATEGY_VISIBLE_MARKER_LIMIT = 5_000;

function lowerBound(markers: readonly ExternalSeriesMarker[], value: number): number {
  let left = 0;
  let right = markers.length;
  while (left < right) {
    const middle = (left + right) >> 1;
    if (Number(markers[middle]?.time) < value) left = middle + 1;
    else right = middle;
  }
  return left;
}

function upperBound(markers: readonly ExternalSeriesMarker[], value: number): number {
  let left = 0;
  let right = markers.length;
  while (left < right) {
    const middle = (left + right) >> 1;
    if (Number(markers[middle]?.time) <= value) left = middle + 1;
    else right = middle;
  }
  return left;
}

export function boundVisibleBacktestMarkers(
  markers: readonly ExternalSeriesMarker[],
  range: { from: number; to: number } | null,
  intervalSeconds: number,
  limit = CHART_STRATEGY_VISIBLE_MARKER_LIMIT,
): readonly ExternalSeriesMarker[] {
  if (markers.length === 0 || limit <= 0) return [];
  let visible = markers;
  if (range) {
    const span = Math.max(intervalSeconds, range.to - range.from);
    const overscan = Math.max(
      intervalSeconds * CHART_STRATEGY_MARKER_OVERSCAN_BARS,
      span * 0.25,
    );
    const start = lowerBound(markers, range.from - overscan);
    const end = upperBound(markers, range.to + overscan);
    visible = markers.slice(start, end);
  }
  if (visible.length <= limit) return visible;
  if (limit === 1) return [visible[visible.length - 1]!];
  const sampled: ExternalSeriesMarker[] = [];
  const last = visible.length - 1;
  for (let index = 0; index < limit; index += 1) {
    sampled.push(visible[Math.round((index / (limit - 1)) * last)]!);
  }
  return sampled;
}

function normalizedTimeRange(
  value: ChartSurfaceVisibleRange | null,
): { from: number; to: number } | null {
  const from = Number(value?.time?.from);
  const to = Number(value?.time?.to);
  if (!Number.isFinite(from) || !Number.isFinite(to)) return null;
  return from <= to ? { from, to } : { from: to, to: from };
}

function sameRange(
  left: { from: number; to: number } | null,
  right: { from: number; to: number } | null,
): boolean {
  return left?.from === right?.from && left?.to === right?.to;
}

export interface ChartStrategyResultMarkerSource
  extends ExternalMarkerSource, ChartStrategyTesterMarkerSource {
  setTradeFocus(trade: StrategyTradeFocus | null, interval: string, entryLabel: string, exitLabel: string): void;
  setResult(chart: BacktestChartData | null): void;
  setVisibleRange(range: ChartSurfaceVisibleRange | null): void;
  clear(): void;
  dispose(): void;
  diagnostics(): {
    runId: string | null;
    projectedMarkers: number;
    visibleMarkers: number;
    hasVisibleRange: boolean;
  };
}

export interface ChartStrategyMarkerEvidence {
  markerId: string;
  kind: "FILL" | "REJECTION";
  explanation: TradeExplanationV1;
}

export function createChartStrategyResultMarkerSource({
  seriesStore,
  labels,
  onActivate,
}: {
  seriesStore: SeriesWindowStore;
  labels: BacktestMarkerLabels;
  onActivate?: (evidence: ChartStrategyMarkerEvidence) => void;
}): ChartStrategyResultMarkerSource {
  let focus: { trade: StrategyTradeFocus; interval: string; entryLabel: string; exitLabel: string } | null = null;
  let chart: BacktestChartData | null = null;
  let visibleRange: { from: number; to: number } | null = null;
  let projected: readonly ExternalSeriesMarker[] = [];
  let projectedAxisRevision = -1;
  let projectedRunHash = "";
  let snapshot = EMPTY_SNAPSHOT;
  let snapshotRevision = -1;
  let revision = 0;
  let disposed = false;
  const listeners = new Set<() => void>();

  const publish = () => listeners.forEach((listener) => listener());
  const invalidate = () => {
    revision += 1;
    snapshot = { markers: [], revision };
    snapshotRevision = -1;
    publish();
  };
  const project = () => {
    if (!chart) {
      projected = [];
      projectedAxisRevision = Number(seriesStore.axisRevision);
      projectedRunHash = "";
      return;
    }
    const axisRevision = Number(seriesStore.axisRevision);
    if (projectedAxisRevision === axisRevision && projectedRunHash === chart.chart_hash) return;
    projectedAxisRevision = axisRevision;
    projectedRunHash = chart.chart_hash;
    projected = projectBacktestResultMarkers(chart, {
      hasTime: (time) => seriesStore.hasTime(time),
      labels,
    }).sort((left, right) => Number(left.time) - Number(right.time));
  };
  const getSnapshot = (): ExternalMarkerSnapshot => {
    if (disposed) return EMPTY_SNAPSHOT;
    if (snapshotRevision === revision && projectedAxisRevision === Number(seriesStore.axisRevision)) return snapshot;
    if (projectedAxisRevision !== Number(seriesStore.axisRevision)) revision += 1;
    project();
    const intervalSeconds = chart ? Math.max(1, parseIntervalSeconds(chart.interval) ?? 1) : 1;
    const markers = boundVisibleBacktestMarkers(projected, visibleRange, intervalSeconds);
    const focused: ExternalSeriesMarker[] = [];
    if (focus) {
      const { trade, interval, entryLabel, exitLabel } = focus;
      for (const [kind, timeMs, label, price] of [["entry", trade.entryTimeMs, entryLabel, trade.entryPrice], ["exit", trade.exitTimeMs, exitLabel, trade.exitPrice]] as const) {
        if (timeMs === null) continue;
        const time = floorIntervalTime(interval, timeMs / 1000);
        if (time === null || !seriesStore.hasTime(time)) continue;
        focused.push({ id: `review:${trade.id}:${kind}`, time, position: kind === "entry" ? "belowBar" : "aboveBar",
          color: kind === "entry" ? "#38bdf8" : "#f59e0b", shape: kind === "entry" ? "arrowUp" : "arrowDown",
          text: `${label}${price === null ? "" : ` ${price}`}`, size: 2 });
      }
    }
    snapshot = { markers: [...markers, ...focused], revision };
    snapshotRevision = revision;
    return snapshot;
  };
  let unsubscribeSeries: (() => void) | null = null;
  const observeSeries = () => seriesStore.subscribe(() => {
    const nextAxisRevision = Number(seriesStore.axisRevision);
    if (nextAxisRevision === projectedAxisRevision) return;
    projectedAxisRevision = -1;
    invalidate();
  });

  return {
    getSnapshot,
    subscribe(listener) {
      if (disposed) return () => undefined;
      if (!unsubscribeSeries) unsubscribeSeries = observeSeries();
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
        if (!listeners.size) { unsubscribeSeries?.(); unsubscribeSeries = null; }
      };
    },
    activate(markerId) {
      if (!chart || !markerId.startsWith("backtest:")) return false;
      const index = Number(markerId.slice(markerId.lastIndexOf(":") + 1));
      if (!Number.isSafeInteger(index) || index < 0) return false;
      const rejection = markerId.startsWith("backtest:rejected:");
      const row = rejection
        ? chart.rejected_orders?.[index]
        : chart.fills[index];
      const explanation = row?.explanation;
      if (!explanation || typeof explanation !== "object") return false;
      onActivate?.({
        markerId,
        kind: rejection ? "REJECTION" : "FILL",
        explanation: explanation as TradeExplanationV1,
      });
      return true;
    },
    setTradeFocus(trade, interval, entryLabel, exitLabel) {
      if (disposed) return;
      focus = trade ? { trade, interval, entryLabel, exitLabel } : null;
      invalidate();
    },
    setResult(next) {
      if (disposed || chart?.chart_hash === next?.chart_hash) return;
      chart = next;
      projectedAxisRevision = -1;
      projectedRunHash = "";
      invalidate();
    },
    setVisibleRange(next) {
      if (disposed) return;
      const normalized = normalizedTimeRange(next);
      if (sameRange(visibleRange, normalized)) return;
      visibleRange = normalized;
      invalidate();
    },
    clear() {
      if (disposed || (chart === null && focus === null)) return;
      focus = null;
      chart = null;
      projected = [];
      projectedRunHash = "";
      invalidate();
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      focus = null;
      chart = null;
      projected = [];
      listeners.clear();
      unsubscribeSeries?.();
      unsubscribeSeries = null;
    },
    diagnostics() {
      const current = getSnapshot();
      return {
        runId: chart?.run_id ?? null,
        projectedMarkers: projected.length,
        visibleMarkers: current.markers.length,
        hasVisibleRange: visibleRange !== null,
      };
    },
  };
}
