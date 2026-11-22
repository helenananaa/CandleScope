/**
 * A result replay drawn on the shared chart surface (ADR-BACKTEST-015 P5d3b): the revealed bars become
 * chart rows, and the run's revealed fills and notes, the moving average and the replay's own lines
 * become one strategy overlay, the same model the chart and workspace use for a run.
 */
import type { ExternalSeriesMarker } from "../../chart-adapter/externalMarkerSource.js";
import type { BacktestResultReplayBar, BacktestResultReplayFrame, BacktestResultReplayMA } from "../backtest/backtestTypes.js";
import { STRATEGY_OVERLAY_COLORS, type StrategyOverlay } from "../backtest/runResult/strategyOverlay.js";
import type { KlineBarInput } from "../market-data/marketDataTypes.js";
import type { PluginChartRenderEntry } from "../plugins/pluginChartLayerSource.js";
import { replayChartMarkers, type ReplayChartDisplay } from "./strategyResultReplayDisplay.js";
import { replayDrawingBarIndex, type ReplayDrawing, type ReplayDrawingPoint } from "./strategyResultReplayDrawings.js";

export const REPLAY_OVERLAY_COLORS = { ma: "#f59e0b", note: "#f59e0b", drawing: "#3b82f6" } as const;

const NOTE_TEXT_LIMIT = 24;

function seconds(ms: number): number {
  return Math.floor(ms / 1_000);
}

/** The revealed bars as chart rows, keyed by bar-open seconds. */
export function replayChartRows(bars: readonly BacktestResultReplayBar[]): KlineBarInput[] {
  return bars.map(bar => ({
    time: seconds(bar.open_time_ms),
    open: Number(bar.open),
    high: Number(bar.high),
    low: Number(bar.low),
    close: Number(bar.close),
    volume: bar.volume === null ? 0 : Number(bar.volume),
    is_closed: bar.closed,
  }));
}

/** The bar a clicked chart time falls in, as the point a replay line starts or ends at. */
export function replayPointAt(bars: readonly BacktestResultReplayBar[], timeSeconds: number, price: number): ReplayDrawingPoint | null {
  const index = replayDrawingBarIndex(bars, timeSeconds * 1_000);
  return index < 0 || !Number.isFinite(price) ? null : { timeMs: bars[index]!.open_time_ms, price };
}

function maEntries(bars: readonly BacktestResultReplayBar[], ma: BacktestResultReplayMA, idPrefix: string): PluginChartRenderEntry[] {
  const values = new Map(ma.points.map(point => [point.open_time_ms, point.value]));
  const entries: PluginChartRenderEntry[] = [];
  let segment: Array<{ time: number; price: number }> = [];
  const flush = () => {
    if (segment.length >= 2) {
      const id = `${idPrefix}:ma:${entries.length}`;
      entries.push({ id, zOrder: "above-series",
        item: { id, type: "polyline", points: segment, color: REPLAY_OVERLAY_COLORS.ma, width: 2, style: "solid" } });
    }
    segment = [];
  };
  bars.forEach((bar, index) => {
    const value = values.get(bar.open_time_ms);
    const previous = bars[index - 1];
    // A gap in the bars (or in the average) starts a new line, as the bars themselves do.
    if (value === undefined || !previous || previous.close_time_ms !== bar.open_time_ms - 1) flush();
    if (value !== undefined) segment.push({ time: bar.open_time_ms, price: value });
  });
  flush();
  return entries;
}

function drawingEntries(bars: readonly BacktestResultReplayBar[], drawings: readonly ReplayDrawing[], idPrefix: string): PluginChartRenderEntry[] {
  return drawings.flatMap(({ id: drawingId, points: [first, second] }): PluginChartRenderEntry[] => {
    const id = `${idPrefix}:drawing:${drawingId}`;
    if (!second) return [{ id, zOrder: "above-series", item: { id, type: "price-line", price: first.price,
      color: REPLAY_OVERLAY_COLORS.drawing, width: 2, style: "solid" } }];
    if (replayDrawingBarIndex(bars, first.timeMs) < 0 || replayDrawingBarIndex(bars, second.timeMs) < 0) return [];
    return [{ id, zOrder: "above-series", item: { id, type: "polyline", color: REPLAY_OVERLAY_COLORS.drawing, width: 2,
      style: "solid", points: [{ time: first.timeMs, price: first.price }, { time: second.timeMs, price: second.price }] } }];
  });
}

/**
 * One replay chart's overlay at the current cursor. Fills and notes appear only on the run's own bars
 * (`ownsMarkers`), only once revealed, and only when the chart shows them; lines are the revealed ones.
 */
export function buildReplayOverlay(input: {
  frame: BacktestResultReplayFrame;
  bars: readonly BacktestResultReplayBar[];
  ownsMarkers: boolean;
  display: Pick<ReplayChartDisplay, "fills" | "notes">;
  ma: BacktestResultReplayMA | undefined;
  drawings: readonly ReplayDrawing[];
  firstPoint?: ReplayDrawingPoint | undefined;
  idPrefix: string;
}): StrategyOverlay {
  const { bars, idPrefix } = input;
  const markers: ExternalSeriesMarker[] = [];
  for (const [index, { fills, notes }] of replayChartMarkers(input.frame, bars, input.ownsMarkers, input.display)) {
    const time = seconds(bars[index]!.open_time_ms);
    fills.forEach((fill, order) => {
      const buy = fill.side === "BUY";
      markers.push({ id: `${idPrefix}:fill:${fill.cursor}:${fill.order_id}:${order}`, time,
        position: buy ? "belowBar" : "aboveBar", color: buy ? STRATEGY_OVERLAY_COLORS.buy : STRATEGY_OVERLAY_COLORS.sell,
        shape: buy ? "arrowUp" : "arrowDown", text: `${fill.qty} @ ${fill.price}`, size: 1.2 });
    });
    notes.forEach(note => {
      const body = note.body.length > NOTE_TEXT_LIMIT ? `${note.body.slice(0, NOTE_TEXT_LIMIT - 1)}…` : note.body;
      markers.push({ id: `${idPrefix}:note:${note.id}`, time, position: "aboveBar", color: REPLAY_OVERLAY_COLORS.note,
        shape: "square", text: `#${note.cursor} ${body}` });
    });
  }
  const pending = input.firstPoint && replayDrawingBarIndex(bars, input.firstPoint.timeMs);
  if (input.firstPoint && pending !== undefined && pending >= 0) {
    markers.push({ id: `${idPrefix}:drawing:pending`, time: seconds(bars[pending]!.open_time_ms), position: "atPriceMiddle",
      price: input.firstPoint.price, color: REPLAY_OVERLAY_COLORS.drawing, shape: "circle" });
  }
  markers.sort((left, right) => Number(left.time) - Number(right.time));
  return {
    markers,
    entries: [...(input.ma ? maEntries(bars, input.ma, idPrefix) : []), ...drawingEntries(bars, input.drawings, idPrefix)],
    connectors: [],
    evidence: new Map(),
  };
}
