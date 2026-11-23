import { MAX_PLUGIN_CHART_BARS, observePluginBar, usePluginChartSource } from "../plugins/unifiedChartContext.js";
import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useState } from "react";
import { ChartErrorBoundary } from "../../app/AppProviders.js";
import { parseIntervalSeconds } from "../../utils/intervals.js";
import type { ChartSession } from "../chart-session/chartSessionTypes.js";
import { StrategyOverlaySource } from "../backtest/runResult/strategyOverlay.js";
import MarketChartSurface from "../market-chart-platform/MarketChartSurface.js";
import { storeMarketData } from "../market-chart-platform/marketChartSourceRuntime.js";
import { useLiveReferenceMarketChartSource } from "../market-chart-platform/useLiveReferenceMarketChartSource.js";
import { SeriesWindowStore } from "../market-data/window/seriesWindowStore.js";
import { useChartSettingsRuntime } from "../settings/chartAppearanceSettings.js";
import { Button, Checkbox, Disclosure, Field, InlineAlert, Select } from "../../components/ui/index.js";
import { t } from "../../i18n/index.js";
import { formatIntervalLabel } from "../../utils/intervals.js";
import type { BacktestResultReplayFrame, BacktestResultReplayMA } from "../backtest/backtestTypes.js";
import type { ReplayChartDisplay, ReplayChartSlot } from "./strategyResultReplayDisplay.js";
import { revealedReplayDrawings, type ReplayDrawing, type ReplayDrawingEdit, type ReplayDrawingPoint } from "./strategyResultReplayDrawings.js";
import { buildReplayOverlay, replayChartRows, replayPointAt } from "./strategyResultReplayOverlay.js";

const NO_DRAWINGS: readonly ReplayDrawing[] = [];

/**
 * One replay chart on the shared chart surface (ADR-BACKTEST-015 P5d3b). The revealed bars fill a store
 * this chart owns, served as a reference source (a replay is never a run input); fills, notes, the
 * moving average and the replay's lines are a strategy overlay. With a line tool on, a click on the
 * chart places a point at the clicked bar and price.
 */
function ReplaySurface({ slot, chart, frame, symbol, display, ownsMarkers, ma, drawings, firstPoint, onDrawingPoint }: {
  slot: ReplayChartSlot;
  chart: ReplayChart;
  frame: BacktestResultReplayFrame;
  symbol: string;
  display: ReplayChartDisplay;
  ownsMarkers: boolean;
  ma: BacktestResultReplayMA | undefined;
  drawings: readonly ReplayDrawing[];
  firstPoint: ReplayDrawingPoint | undefined;
  onDrawingPoint: ((point: ReplayDrawingPoint) => void) | undefined;
}) {
  const appearance = useChartSettingsRuntime();
  const owner = chart.dataset_id === undefined ? `run:${frame.snapshot_hash}` : `${chart.dataset_id}:${chart.data_epoch ?? ""}`;
  const datasetKey = `replay:${frame.run_id}:${owner}:${chart.interval}`;
  const store = useMemo(() => new SeriesWindowStore({ intervalSeconds: parseIntervalSeconds(chart.interval), seriesKey: datasetKey }),
    [chart.interval, datasetKey]);
  const [revision, setRevision] = useState(0);
  useLayoutEffect(() => {
    store.replace(replayChartRows(chart.bars), { source: "result_replay" });
    setRevision(value => value + 1);
  }, [chart.bars, store]);
  const session = useMemo<ChartSession>(() => ({ exchange: "replay", marketType: "result_replay", symbol, interval: chart.interval }),
    [chart.interval, symbol]);
  const marketData = useMemo(() => {
    void revision;
    return storeMarketData("RESULT_REPLAY", session, store);
  }, [revision, session, store]);
  const source = useLiveReferenceMarketChartSource({ sourceId: `research-replay:${slot}`, session, datasetKey, marketData, paused: false });
  const overlaySource = useMemo(() => new StrategyOverlaySource(), []);
  useEffect(() => () => overlaySource.dispose(), [overlaySource]);
  useEffect(() => {
    overlaySource.setSeries(store);
    return () => overlaySource.setSeries(null);
  }, [overlaySource, store]);
  const overlay = useMemo(() => buildReplayOverlay({ frame, bars: chart.bars, ownsMarkers, display, ma, drawings, firstPoint,
    idPrefix: `replay:${slot}` }), [chart.bars, display, drawings, firstPoint, frame, ma, ownsMarkers, slot]);
  useEffect(() => overlaySource.setOverlay(overlay, chart.interval, `replay:${slot}`), [chart.interval, overlay, overlaySource, slot]);
  const markerSources = useMemo(() => [overlaySource.markers], [overlaySource]);
  const bars = chart.bars;
  const placePoint = useCallback(({ time, price }: { time: unknown; price: number }) => {
    const point = typeof time === "number" ? replayPointAt(bars, time, price) : null;
    if (point) onDrawingPoint?.(point);
  }, [bars, onDrawingPoint]);
  return <div className="strategy-result-replay-surface" data-testid={`strategy-replay-${slot}-surface`}
    data-drawing-active={onDrawingPoint ? true : undefined} data-markers={overlay.markers.length} data-entries={overlay.entries.length}>
    <MarketChartSurface source={source} markerSources={markerSources} chartLayerSource={overlaySource.layer} errorBoundary={ChartErrorBoundary}
      chartProps={{ symbol, interval: chart.interval, datasetKey, upColor: display.upColor, downColor: display.downColor,
        chartType: display.candleStyle === "hollow" ? "hollow-candlestick" : "candlestick",
        theme: appearance.resolvedTheme, customBg: appearance.settings.customBg, followLatest: true,
        onVisibleRangeChange: range => overlaySource.setVisibleRange(range as Parameters<StrategyOverlaySource["setVisibleRange"]>[0]),
        onChartPointClick: onDrawingPoint ? placePoint : null }} />
  </div>;
}

function ReplayMaLegend({ ma }: { ma: BacktestResultReplayMA | undefined }) {
  if (!ma) return null;
  const last = ma.points.at(-1);
  return <p className="strategy-result-replay-ohlc" data-testid="strategy-replay-ma" data-period={ma.period} data-value={last?.value}>
    {t("replay.indicator.sma.name")} ({ma.period}) · {last?.value.toLocaleString(undefined, { maximumSignificantDigits: 12 }) ?? "—"}
  </p>;
}

type ReplayChart = NonNullable<BacktestResultReplayFrame["comparison"]>;
type DrawingTool = "horizontal" | "segment";
const drawingToolLabels = { horizontal: "drawing.variant.line-horizontal", segment: "drawing.variant.line-segment" } as const;

export function StrategyResultReplayChart({ slot, chart, frame, display, disabled, drawingControl, onChange }: {
  slot: ReplayChartSlot;
  chart: ReplayChart;
  frame: BacktestResultReplayFrame;
  display: ReplayChartDisplay;
  disabled: boolean;
  drawingControl?: {
    owner: string;
    drawings: readonly ReplayDrawing[];
    locked: boolean;
    edit(edit: ReplayDrawingEdit): boolean;
  } | undefined;
  onChange<K extends keyof ReplayChartDisplay>(slot: ReplayChartSlot, field: K, value: ReplayChartDisplay[K]): void;
}) {
  const ownsMarkers = chart.dataset_id === undefined;
  const symbol = chart.symbol ?? frame.symbol;
  const interval = formatIntervalLabel(chart.interval);
  const ma = display.showMa ? chart.ma : undefined;
  const last = chart.bars.at(-1);
  const chartInstance = useId();
  usePluginChartSource(`strategy:${chartInstance}:${slot}`, !disabled && frame.time_ms !== null && chart.bars.length ? {
    observe: () => ({
      mode: "strategy-replay", runId: frame.run_id, trackId: chart.dataset_id ?? slot,
      seriesId: JSON.stringify([chart.dataset_id, symbol, chart.interval]), symbol, interval: chart.interval,
      dataRevision: JSON.stringify([frame.snapshot_hash, frame.report_hash, chart.data_epoch, frame.cursor, frame.source_sequence]),
      visibleThroughMs: frame.time_ms!,
    }),
    bars: ({ visibleThroughMs }) => chart.bars.slice(-MAX_PLUGIN_CHART_BARS).flatMap((bar, index, rows) => {
      // The saved frame carries the last contributing event's time.
      if (bar.close_time_ms === undefined || bar.close_time_ms > visibleThroughMs
        || !bar.closed && index !== rows.length - 1) return [];
      return observePluginBar(bar.open_time_ms, bar.close_time_ms, bar.closed, bar);
    }),
  } : null);

  const [tool, setTool] = useState<DrawingTool | null>(null);
  const [pending, setPending] = useState<{ owner: string; cursor: number; interval: string; point: ReplayDrawingPoint } | null>(null);
  const [drawingLimit, setDrawingLimit] = useState(false);
  const drawings = revealedReplayDrawings(drawingControl?.drawings ?? [], frame.cursor, frame.time_ms);
  const canDraw = drawingControl && !drawingControl.locked && display.showDrawings && last !== undefined;
  const firstPoint = canDraw && pending?.owner === drawingControl.owner && pending.cursor === frame.cursor
    && pending.interval === chart.interval ? pending.point : undefined;
  const addPoint = (point: ReplayDrawingPoint) => {
    if (!canDraw || tool === null || frame.time_ms === null || point.timeMs > frame.time_ms
      || !Number.isFinite(point.price) || point.price <= 0) return;
    if (tool === "segment" && !firstPoint) {
      setPending({ owner: drawingControl.owner, cursor: frame.cursor, interval: chart.interval, point });
      return;
    }
    if (firstPoint && firstPoint.timeMs === point.timeMs && firstPoint.price === point.price) return;
    const points = firstPoint ? [firstPoint, point] as const : [point] as const;
    const saved = drawingControl.edit({ add: { id: crypto.randomUUID(), cursor: frame.cursor, points } });
    setDrawingLimit(!saved);
    setTool(null);
    setPending(null);
  };
  return <section aria-label={`${symbol} · ${interval}`} data-testid={`strategy-replay-${slot}-chart`}
    data-dataset-epoch={chart.data_epoch} data-candle-style={display.candleStyle}>
    <h3 className="strategy-result-replay-chart-title">{symbol} · {interval}</h3>
    <Disclosure className="strategy-result-replay-style" summary={t("workspace.link.chartStyle")}>
      <fieldset className="strategy-result-replay-view-controls" disabled={disabled}>
        <Field label={t("workspace.link.chartStyle")}>
          <Select size="sm" value={display.candleStyle} data-testid="strategy-replay-candle-style"
            onChange={event => onChange(slot, "candleStyle", event.target.value === "hollow" ? "hollow" : "solid")}>
            <option value="solid">{t("drawing.variant.candlestick")}</option>
            <option value="hollow">{t("drawing.variant.hollow-candlestick")}</option>
          </Select>
        </Field>
        {([["upColor", "settings.appearance.upColor"], ["downColor", "settings.appearance.downColor"]] as const).map(([field, key]) =>
          <label key={field} className="strategy-result-replay-color">
            <span>{t(key)}</span>
            <input type="color" value={display[field]} onChange={event => onChange(slot, field, event.target.value)} />
          </label>)}
        {([["fills", "researchBatch.replayFillMarkers"], ["notes", "researchBatch.replayNoteMarkers"]] as const).map(([field, key]) =>
          <Checkbox key={field} data-testid={`strategy-replay-show-${field}`} disabled={!ownsMarkers} checked={display[field]}
            onChange={event => onChange(slot, field, event.target.checked)} label={t(key)} />)}
        {chart.ma && <Checkbox data-testid="strategy-replay-show-ma" checked={display.showMa}
          onChange={event => onChange(slot, "showMa", event.target.checked)} label={t("replay.indicator.sma.name")} />}
      </fieldset>
      {!ownsMarkers && <p className="strategy-research-note">{t("researchBatch.replayReferenceMarkers")}</p>}
      {drawingControl && <fieldset className="strategy-result-replay-view-controls" disabled={disabled}>
        <legend>{t("workspace.link.drawings")}</legend>
        <Checkbox data-testid="strategy-replay-show-drawings" checked={display.showDrawings}
          onChange={event => onChange(slot, "showDrawings", event.target.checked)} label={t("drawing.showAll")} />
        {(Object.keys(drawingToolLabels) as DrawingTool[]).map(kind => <Button size="sm" key={kind}
          data-testid={`strategy-replay-draw-${kind}`} aria-pressed={tool === kind} disabled={!canDraw}
          onClick={() => { setTool(tool === kind ? null : kind); setPending(null); setDrawingLimit(false); }}>
          {t(drawingToolLabels[kind])}
        </Button>)}
        {drawings.map((drawing, index) => <Button size="sm" variant="ghost" key={drawing.id} disabled={drawingControl.locked}
          data-testid="strategy-replay-remove-drawing" onClick={() => { drawingControl.edit({ remove: drawing.id }); setDrawingLimit(false); }}>
          {t("workspace.delete")} · {t(drawingToolLabels[drawing.points.length === 1 ? "horizontal" : "segment"])} #{index + 1}
        </Button>)}
        {drawingLimit && <InlineAlert tone="danger">{t("drawing.objects.failed")}</InlineAlert>}
      </fieldset>}
    </Disclosure>
    <ReplaySurface slot={slot} chart={chart} frame={frame} symbol={symbol} display={display} ownsMarkers={ownsMarkers} ma={ma}
      drawings={display.showDrawings ? drawings : NO_DRAWINGS} firstPoint={firstPoint}
      onDrawingPoint={canDraw && tool !== null ? addPoint : undefined} />
    <ReplayMaLegend ma={ma} />
    {last && <p className="strategy-result-replay-ohlc" data-testid={slot === "primary" ? "strategy-replay-last-ohlc" : `strategy-replay-${slot}-ohlc`}>
      {last.open} / {last.high} / {last.low} / {last.close}
    </p>}
  </section>;
}
