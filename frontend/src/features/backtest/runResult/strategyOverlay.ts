/**
 * Chart overlay for any `candlescope.run-result/1` (ADR-BACKTEST-015 §4, step P1c).
 *
 * One model for every run family: fill markers, round-trip connectors, the open
 * position, working orders and the strategy's own plots. It draws through the
 * chart's existing external-marker and chart-layer renderers; nothing here
 * recomputes money, it only places what the run result already says.
 */
import type { ExternalMarkerSource, ExternalMarkerSnapshot, ExternalSeriesMarker } from "../../../chart-adapter/externalMarkerSource.js";
import type { ChartSurfaceVisibleRange } from "../../../chart-adapter/useChartSurfaceRuntime.js";
import type { ChartLayerSource, PluginChartLayerSnapshot, PluginChartRenderEntry } from "../../plugins/pluginChartLayerSource.js";
import { parseIntervalSeconds } from "../../../utils/intervals.js";
import { boundVisibleBacktestMarkers, normalizedTimeRange } from "../chart-tester/chartStrategyResultMarkerSource.js";
import type { SeriesWindowView } from "../../market-data/window/seriesWindowView.js";
import type { RunResult, RunResultFill } from "./runResult.js";

export type FillAction =
  | "OPEN_LONG" | "ADD_LONG" | "REDUCE_LONG" | "CLOSE_LONG" | "REVERSE_TO_SHORT"
  | "OPEN_SHORT" | "ADD_SHORT" | "REDUCE_SHORT" | "CLOSE_SHORT" | "REVERSE_TO_LONG";

export interface StrategyOverlayLabels {
  actions: Readonly<Record<FillAction, string>>;
  long: string;
  short: string;
  workingOrder: string;
}

export interface StrategyOverlay {
  markers: ExternalSeriesMarker[];
  entries: PluginChartRenderEntry[];
}

export const STRATEGY_OVERLAY_COLORS = {
  buy: "#22c55e",
  sell: "#ef4444",
  win: "#22c55e",
  loss: "#ef4444",
  neutral: "#94a3b8",
  position: "#3b82f6",
  order: "#f59e0b",
  plots: ["#3b82f6", "#f97316", "#a855f7", "#14b8a6", "#eab308", "#ec4899"],
} as const;

/** What each fill did to the position, from the running signed size. */
export function fillActions(fills: readonly RunResultFill[]): FillAction[] {
  let position = 0;
  return fills.map((fill) => {
    const qty = Number(fill.qty);
    const before = position;
    position += fill.side === "BUY" ? qty : -qty;
    const after = position;
    if (fill.side === "BUY") {
      if (before >= 0) return before === 0 ? "OPEN_LONG" : "ADD_LONG";
      if (after < 0) return "REDUCE_SHORT";
      return after === 0 ? "CLOSE_SHORT" : "REVERSE_TO_LONG";
    }
    if (before <= 0) return before === 0 ? "OPEN_SHORT" : "ADD_SHORT";
    if (after > 0) return "REDUCE_LONG";
    return after === 0 ? "CLOSE_LONG" : "REVERSE_TO_SHORT";
  });
}

function seconds(ms: number): number {
  return Math.floor(ms / 1_000);
}

function priceOf(value: string | null): number | null {
  if (value === null) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export function buildStrategyOverlay(result: RunResult, options: {
  labels: StrategyOverlayLabels;
  /** Run identity, so ids stay unique when several runs share one chart. */
  idPrefix: string;
}): StrategyOverlay {
  const { labels, idPrefix } = options;
  const actions = fillActions(result.fills);
  const markers: ExternalSeriesMarker[] = [];
  result.fills.forEach((fill, index) => {
    if (fill.bar_time_ms === null) return;
    const time = seconds(fill.bar_time_ms);
    const buy = fill.side === "BUY";
    markers.push({
      id: `${idPrefix}:fill:${index}`,
      time,
      position: buy ? "belowBar" : "aboveBar",
      color: buy ? STRATEGY_OVERLAY_COLORS.buy : STRATEGY_OVERLAY_COLORS.sell,
      shape: buy ? "arrowUp" : "arrowDown",
      text: `${labels.actions[actions[index]!]} ${fill.price}`,
      size: 1.2,
    });
  });
  markers.sort((left, right) => Number(left.time) - Number(right.time));

  const entries: PluginChartRenderEntry[] = [];
  result.plots.forEach((plot, plotIndex) => {
    const color = STRATEGY_OVERLAY_COLORS.plots[plotIndex % STRATEGY_OVERLAY_COLORS.plots.length]!;
    let segment: Array<{ time: number; price: number }> = [];
    let part = 0;
    const flush = () => {
      if (segment.length >= 2) {
        entries.push({ id: `${idPrefix}:plot:${plot.id}:${part}`, zOrder: "above-series",
          item: { id: `${idPrefix}:plot:${plot.id}:${part}`, type: "polyline", points: segment, color, width: 1.5, style: "solid" } });
        part += 1;
      }
      segment = [];
    };
    for (const [time, value] of plot.points) {
      if (value === null) flush();
      else segment.push({ time, price: value });
    }
    flush();
  });
  result.trades.forEach((trade) => {
    const entry = priceOf(trade.entry_price), exit = priceOf(trade.exit_price);
    if (trade.entry_bar_time_ms === null || trade.exit_bar_time_ms === null || entry === null || exit === null) return;
    const pnl = priceOf(trade.net_pnl);
    const color = pnl === null ? STRATEGY_OVERLAY_COLORS.neutral : pnl > 0 ? STRATEGY_OVERLAY_COLORS.win : STRATEGY_OVERLAY_COLORS.loss;
    entries.push({ id: `${idPrefix}:trade:${trade.id}`, zOrder: "above-series", item: {
      id: `${idPrefix}:trade:${trade.id}`, type: "polyline", color, width: 1, style: "dashed",
      points: [{ time: trade.entry_bar_time_ms, price: entry }, { time: trade.exit_bar_time_ms, price: exit }],
    } });
  });
  const position = result.open_position;
  const average = position ? priceOf(position.avg_price) : null;
  if (position && average !== null) {
    entries.push({ id: `${idPrefix}:position`, zOrder: "above-series", item: {
      id: `${idPrefix}:position`, type: "price-line", price: average, color: STRATEGY_OVERLAY_COLORS.position, width: 1, style: "dashed",
      text: `${position.side === "LONG" ? labels.long : labels.short} ${position.qty} @ ${position.avg_price}`,
    } });
  }
  result.pending_orders.forEach((order, index) => {
    const price = priceOf(order.limit_price ?? order.stop_price);
    if (price === null) return;
    entries.push({ id: `${idPrefix}:order:${order.order_id}:${index}`, zOrder: "above-series", item: {
      id: `${idPrefix}:order:${order.order_id}:${index}`, type: "price-line", price, color: STRATEGY_OVERLAY_COLORS.order,
      width: 1, style: "dotted", text: `${labels.workingOrder} ${order.side} ${order.type}${order.qty ? ` ${order.qty}` : ""}`,
    } });
  });
  return { markers, entries };
}

const EMPTY_MARKERS: ExternalMarkerSnapshot = Object.freeze({ markers: Object.freeze([]), revision: 0 });
const EMPTY_LAYER: PluginChartLayerSnapshot = Object.freeze({ entries: Object.freeze([]), revision: 0 });

type OverlaySeries = Pick<SeriesWindowView, "hasTime" | "axisRevision" | "subscribe">;

/**
 * Serves one run's overlay to a chart cell. Markers are limited to bars the chart
 * has loaded (re-checked when its axis changes) and bounded to the visible range,
 * like the host tester's markers; layer entries are few and always drawn.
 */
export class StrategyOverlaySource {
  private overlay: StrategyOverlay = { markers: [], entries: [] };
  private series: OverlaySeries | null = null;
  private seriesAxis = -1;
  private stopSeries: (() => void) | null = null;
  private intervalSeconds = 1;
  private visibleRange: { from: number; to: number } | null = null;
  private markerSnapshot: ExternalMarkerSnapshot = EMPTY_MARKERS;
  private layerSnapshot: PluginChartLayerSnapshot = EMPTY_LAYER;
  private revision = 0;
  private readonly listeners = new Set<() => void>();

  readonly markers: ExternalMarkerSource = {
    getSnapshot: () => this.markerSnapshot,
    subscribe: (listener) => this.subscribe(listener),
  };

  readonly layer: ChartLayerSource = {
    getSnapshot: () => this.layerSnapshot,
    subscribe: (listener) => this.subscribe(listener),
  };

  setOverlay(overlay: StrategyOverlay | null, interval: string | null): void {
    this.overlay = overlay ?? { markers: [], entries: [] };
    this.intervalSeconds = Math.max(1, (interval ? parseIntervalSeconds(interval) : null) ?? 1);
    this.publish(true);
  }

  /** The chart's loaded bars; markers on bars it does not have are held back until they load. */
  setSeries(series: OverlaySeries | null): void {
    if (series === this.series) return;
    this.stopSeries?.();
    this.stopSeries = null;
    this.series = series;
    this.seriesAxis = series ? Number(series.axisRevision) : -1;
    if (series) {
      this.stopSeries = series.subscribe(() => {
        const axis = Number(series.axisRevision);
        if (axis === this.seriesAxis) return;
        this.seriesAxis = axis;
        this.publish(false);
      });
    }
    this.publish(false);
  }

  dispose(): void {
    this.stopSeries?.();
    this.stopSeries = null;
    this.series = null;
    this.listeners.clear();
  }

  setVisibleRange(range: ChartSurfaceVisibleRange | null): void {
    const next = normalizedTimeRange(range);
    if (next?.from === this.visibleRange?.from && next?.to === this.visibleRange?.to) return;
    this.visibleRange = next;
    this.publish(false);
  }

  diagnostics() {
    return { markers: this.overlay.markers.length, visibleMarkers: this.markerSnapshot.markers.length,
      entries: this.overlay.entries.length, revision: this.revision };
  }

  private subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }

  private publish(layerChanged: boolean): void {
    this.revision += 1;
    const series = this.series;
    const loaded = series ? this.overlay.markers.filter((marker) => series.hasTime(marker.time)) : this.overlay.markers;
    this.markerSnapshot = {
      markers: boundVisibleBacktestMarkers(loaded, this.visibleRange, this.intervalSeconds),
      revision: this.revision,
    };
    if (layerChanged) this.layerSnapshot = { entries: this.overlay.entries, revision: this.revision };
    for (const listener of [...this.listeners]) listener();
  }
}
