/**
 * Chart overlay for any `candlescope.run-result/1` (ADR-BACKTEST-015 §4, step P1c).
 *
 * One model for every run family: fill markers, round-trip connectors, the open
 * position, working orders and the strategy's own plots. It draws through the
 * chart's existing external-marker and chart-layer renderers; nothing here
 * recomputes money, it only places what the run result already says.
 */
import type { ExternalMarkerSource, ExternalMarkerSnapshot, ExternalSeriesMarker } from "../../../chart-adapter/externalMarkerSource.js";
import { seriesPricePrecision } from "../../../chart-adapter/mainSeriesPriceFormat.js";
import type { ChartSurfaceVisibleRange } from "../../../chart-adapter/useChartSurfaceRuntime.js";
import type { ChartLayerSource, PluginChartLayerSnapshot, PluginChartRenderEntry } from "../../plugins/pluginChartLayerSource.js";
import { parseIntervalSeconds } from "../../../utils/intervals.js";
import {
  boundVisibleBacktestMarkers, CHART_STRATEGY_MARKER_OVERSCAN_BARS, CHART_STRATEGY_VISIBLE_MARKER_LIMIT, normalizedTimeRange,
} from "../chart-tester/chartStrategyResultMarkerSource.js";
import type { SeriesWindowView } from "../../market-data/window/seriesWindowView.js";
import type { StrategyTradeFocus } from "../chart-tester/strategyTradeReview.js";
import { floorIntervalTime } from "../../../utils/intervalTimeline.js";
import { formatPrice, formatQty } from "../../trading-accounts/tradingFormat.js";
import type { RunResult, RunResultFill } from "./runResult.js";

export type FillAction =
  | "OPEN_LONG" | "ADD_LONG" | "REDUCE_LONG" | "CLOSE_LONG" | "REVERSE_TO_SHORT"
  | "OPEN_SHORT" | "ADD_SHORT" | "REDUCE_SHORT" | "CLOSE_SHORT" | "REVERSE_TO_LONG";

export interface StrategyOverlayLabels {
  actions: Readonly<Record<FillAction, string>>;
  long: string;
  short: string;
  workingOrder: string;
  rejection: string;
}

/** What a clicked marker stands for, when the run recorded decision-time evidence for it. */
export interface StrategyMarkerEvidence {
  markerId: string;
  kind: "FILL" | "REJECTION";
  explanation: Record<string, unknown>;
}

export interface StrategyOverlay {
  markers: ExternalSeriesMarker[];
  /** Plots, the open position and working orders: few, always drawn. */
  entries: PluginChartRenderEntry[];
  /** Entry-to-exit lines, one per round trip: bounded to the visible range like markers. */
  connectors: PluginChartRenderEntry[];
  /** Evidence by marker id, for click-through. */
  evidence: ReadonlyMap<string, StrategyMarkerEvidence>;
}

export const STRATEGY_OVERLAY_COLORS = {
  buy: "#22c55e",
  sell: "#ef4444",
  win: "#22c55e",
  loss: "#ef4444",
  neutral: "#94a3b8",
  position: "#3b82f6",
  order: "#f59e0b",
  rejection: "#f59e0b",
  focusEntry: "#38bdf8",
  focusExit: "#f59e0b",
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
  /** The chart's price precision; fill and average prices carry slippage and float digits past the tick. */
  pricePrecision?: number | undefined;
}): StrategyOverlay {
  const { labels, idPrefix, pricePrecision } = options;
  const actions = fillActions(result.fills);
  const markers: ExternalSeriesMarker[] = [];
  const evidence = new Map<string, StrategyMarkerEvidence>();
  result.fills.forEach((fill, index) => {
    if (fill.bar_time_ms === null) return;
    const time = seconds(fill.bar_time_ms);
    const buy = fill.side === "BUY";
    const id = `${idPrefix}:fill:${index}`;
    markers.push({
      id,
      time,
      position: buy ? "belowBar" : "aboveBar",
      color: buy ? STRATEGY_OVERLAY_COLORS.buy : STRATEGY_OVERLAY_COLORS.sell,
      shape: buy ? "arrowUp" : "arrowDown",
      text: `${labels.actions[actions[index]!]} ${formatPrice(fill.price, pricePrecision)}`,
      size: 1.2,
    });
    if (fill.explanation) evidence.set(id, { markerId: id, kind: "FILL", explanation: fill.explanation });
  });
  result.rejections.forEach((rejection, index) => {
    if (rejection.bar_time_ms === null) return;
    const id = `${idPrefix}:rejection:${index}`;
    markers.push({ id, time: seconds(rejection.bar_time_ms), position: "aboveBar", color: STRATEGY_OVERLAY_COLORS.rejection,
      shape: "square", text: labels.rejection });
    if (rejection.explanation) evidence.set(id, { markerId: id, kind: "REJECTION", explanation: rejection.explanation });
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
  const connectors: PluginChartRenderEntry[] = [];
  result.trades.forEach((trade) => {
    const entry = priceOf(trade.entry_price), exit = priceOf(trade.exit_price);
    if (trade.entry_bar_time_ms === null || trade.exit_bar_time_ms === null || entry === null || exit === null) return;
    const pnl = priceOf(trade.net_pnl);
    const color = pnl === null ? STRATEGY_OVERLAY_COLORS.neutral : pnl > 0 ? STRATEGY_OVERLAY_COLORS.win : STRATEGY_OVERLAY_COLORS.loss;
    connectors.push({ id: `${idPrefix}:trade:${trade.id}`, zOrder: "above-series", item: {
      id: `${idPrefix}:trade:${trade.id}`, type: "polyline", color, width: 1, style: "dashed",
      points: [{ time: trade.entry_bar_time_ms, price: entry }, { time: trade.exit_bar_time_ms, price: exit }],
    } });
  });
  const position = result.open_position;
  const average = position ? priceOf(position.avg_price) : null;
  if (position && average !== null) {
    entries.push({ id: `${idPrefix}:position`, zOrder: "above-series", item: {
      id: `${idPrefix}:position`, type: "price-line", price: average, color: STRATEGY_OVERLAY_COLORS.position, width: 1, style: "dashed",
      text: `${position.side === "LONG" ? labels.long : labels.short} ${formatQty(position.qty)} @ ${formatPrice(position.avg_price, pricePrecision)}`,
    } });
  }
  result.pending_orders.forEach((order, index) => {
    const price = priceOf(order.limit_price ?? order.stop_price);
    if (price === null) return;
    entries.push({ id: `${idPrefix}:order:${order.order_id}:${index}`, zOrder: "above-series", item: {
      id: `${idPrefix}:order:${order.order_id}:${index}`, type: "price-line", price, color: STRATEGY_OVERLAY_COLORS.order,
      width: 1, style: "dotted", text: `${labels.workingOrder} ${order.side} ${order.type}${order.qty ? ` ${formatQty(order.qty)}` : ""}`,
    } });
  });
  return { markers, entries, connectors, evidence };
}

/** Connectors overlapping the visible range (with the markers' overscan), evenly sampled past `limit`. */
export function boundVisibleConnectors(
  connectors: readonly PluginChartRenderEntry[],
  range: { from: number; to: number } | null,
  intervalSeconds: number,
  limit = CHART_STRATEGY_VISIBLE_MARKER_LIMIT,
): readonly PluginChartRenderEntry[] {
  let visible = connectors;
  if (range) {
    const overscan = Math.max(intervalSeconds * CHART_STRATEGY_MARKER_OVERSCAN_BARS, Math.max(intervalSeconds, range.to - range.from) * 0.25);
    const from = (range.from - overscan) * 1000, to = (range.to + overscan) * 1000;
    visible = connectors.filter((entry) => {
      if (entry.item.type !== "polyline") return true;
      const times = entry.item.points.map((point) => point.time);
      return Math.max(...times) >= from && Math.min(...times) <= to;
    });
  }
  if (visible.length <= limit) return visible;
  const last = visible.length - 1;
  return Array.from({ length: limit }, (_, index) => visible[Math.round((index / (limit - 1)) * last)]!);
}

/** Entry and exit highlights for the trade under review; drawn on top, outside the visible-range bound. */
export function tradeFocusMarkers(focus: {
  trade: StrategyTradeFocus; interval: string; entryLabel: string; exitLabel: string;
}): ExternalSeriesMarker[] {
  const { trade, interval, entryLabel, exitLabel } = focus;
  const markers: ExternalSeriesMarker[] = [];
  for (const [kind, timeMs, label, price] of [["entry", trade.entryTimeMs, entryLabel, trade.entryPrice],
    ["exit", trade.exitTimeMs, exitLabel, trade.exitPrice]] as const) {
    if (timeMs === null) continue;
    const time = floorIntervalTime(interval, timeMs / 1000);
    if (time === null) continue;
    markers.push({ id: `review:${trade.id}:${kind}`, time, position: kind === "entry" ? "belowBar" : "aboveBar",
      color: kind === "entry" ? STRATEGY_OVERLAY_COLORS.focusEntry : STRATEGY_OVERLAY_COLORS.focusExit,
      shape: kind === "entry" ? "arrowUp" : "arrowDown", text: `${label}${price === null ? "" : ` ${price}`}`, size: 2 });
  }
  return markers;
}

const NO_OVERLAY: StrategyOverlay = { markers: [], entries: [], connectors: [], evidence: new Map() };

const EMPTY_MARKERS: ExternalMarkerSnapshot = Object.freeze({ markers: Object.freeze([]), revision: 0 });
const EMPTY_LAYER: PluginChartLayerSnapshot = Object.freeze({ entries: Object.freeze([]), revision: 0 });

type OverlaySeries = Pick<SeriesWindowView, "hasTime" | "axisRevision" | "subscribe"> & Partial<Pick<SeriesWindowView, "snapshot">>;

/** An overlay, or one built for the chart's price precision (rebuilt when its bars change it). */
export type StrategyOverlayInput = StrategyOverlay | ((pricePrecision: number | undefined) => StrategyOverlay);

/**
 * Serves one run's overlay to a chart cell. Markers are limited to bars the chart
 * has loaded (re-checked when its axis changes) and bounded to the visible range,
 * like the host tester's markers; layer entries are few and always drawn.
 */
export class StrategyOverlaySource {
  private overlay: StrategyOverlay = NO_OVERLAY;
  private build: ((pricePrecision: number | undefined) => StrategyOverlay) | null = null;
  private pricePrecision: number | undefined = undefined;
  private owner: string | null = null;
  private focus: ExternalSeriesMarker[] = [];
  private series: OverlaySeries | null = null;
  private seriesAxis = -1;
  private stopSeries: (() => void) | null = null;
  private intervalSeconds = 1;
  private visibleRange: { from: number; to: number } | null = null;
  private markerSnapshot: ExternalMarkerSnapshot = EMPTY_MARKERS;
  private layerSnapshot: PluginChartLayerSnapshot = EMPTY_LAYER;
  private revision = 0;
  private readonly listeners = new Set<() => void>();

  constructor(private readonly onActivate?: (evidence: StrategyMarkerEvidence) => void) {}

  readonly markers: ExternalMarkerSource = {
    getSnapshot: () => this.markerSnapshot,
    subscribe: (listener) => this.subscribe(listener),
    activate: (markerId) => {
      const evidence = this.overlay.evidence.get(markerId);
      if (!evidence || !this.onActivate) return false;
      this.onActivate(evidence);
      return true;
    },
  };

  readonly layer: ChartLayerSource = {
    getSnapshot: () => this.layerSnapshot,
    subscribe: (listener) => this.subscribe(listener),
  };

  /** Show one run's overlay; `owner` names it (for example `run:host:<id>`) so a stale owner can be cleared. */
  setOverlay(overlay: StrategyOverlayInput | null, interval: string | null, owner: string | null = null): void {
    this.build = typeof overlay === "function" ? overlay : null;
    this.overlay = (this.build ? this.build(this.pricePrecision) : overlay as StrategyOverlay | null) ?? NO_OVERLAY;
    this.owner = overlay ? owner : null;
    this.intervalSeconds = Math.max(1, (interval ? parseIntervalSeconds(interval) : null) ?? 1);
    this.publish(true);
  }

  /** Clear synchronously when the current overlay's owner starts with `prefix` (same-frame STALE hiding). */
  clearOwner(prefix: string): void {
    if (this.owner === null || !this.owner.startsWith(prefix)) return;
    this.setOverlay(null, null);
  }

  setTradeFocus(trade: StrategyTradeFocus | null, interval: string, entryLabel: string, exitLabel: string): void {
    this.focus = trade ? tradeFocusMarkers({ trade, interval, entryLabel, exitLabel }) : [];
    this.publish(false);
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
        this.publish(this.refreshPricePrecision());
      });
    }
    this.publish(this.refreshPricePrecision());
  }

  dispose(): void {
    this.overlay = NO_OVERLAY;
    this.build = null;
    this.focus = [];
    this.stopSeries?.();
    this.stopSeries = null;
    this.series = null;
    this.listeners.clear();
  }

  setVisibleRange(range: ChartSurfaceVisibleRange | null): void {
    const next = normalizedTimeRange(range);
    if (next?.from === this.visibleRange?.from && next?.to === this.visibleRange?.to) return;
    this.visibleRange = next;
    this.publish(this.overlay.connectors.length > 0);
  }

  diagnostics() {
    return { markers: this.overlay.markers.length, visibleMarkers: this.markerSnapshot.markers.length,
      entries: this.overlay.entries.length, connectors: this.overlay.connectors.length,
      drawnLayerEntries: this.layerSnapshot.entries.length, revision: this.revision };
  }

  /** Rebuild a deferred overlay when the chart's price precision changes; true if the layer did. */
  private refreshPricePrecision(): boolean {
    const rows = this.series?.snapshot?.();
    const next = rows?.length ? seriesPricePrecision(rows) : undefined;
    if (next === this.pricePrecision) return false;
    this.pricePrecision = next;
    if (!this.build) return false;
    this.overlay = this.build(next);
    return true;
  }

  private subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }

  private publish(layerChanged: boolean): void {
    this.revision += 1;
    const series = this.series;
    const loaded = series ? this.overlay.markers.filter((marker) => series.hasTime(marker.time)) : this.overlay.markers;
    const focus = series ? this.focus.filter((marker) => series.hasTime(marker.time)) : this.focus;
    this.markerSnapshot = {
      markers: [...boundVisibleBacktestMarkers(loaded, this.visibleRange, this.intervalSeconds), ...focus],
      revision: this.revision,
    };
    if (layerChanged) {
      this.layerSnapshot = { entries: [...this.overlay.entries,
        ...boundVisibleConnectors(this.overlay.connectors, this.visibleRange, this.intervalSeconds)], revision: this.revision };
    }
    for (const listener of [...this.listeners]) listener();
  }
}
