import { useId, useState, type MouseEvent } from "react";
import { t } from "../../i18n/index.js";
import { formatIntervalLabel } from "../../utils/intervals.js";
import type { BacktestResultReplayFrame, BacktestResultReplayMA } from "../backtest/backtestTypes.js";
import { replayChartMarkers, type ReplayChartDisplay, type ReplayChartSlot } from "./strategyResultReplayDisplay.js";
import { replayDrawingBarIndex, revealedReplayDrawings, type ReplayDrawing, type ReplayDrawingEdit, type ReplayDrawingPoint } from "./strategyResultReplayDrawings.js";

function ReplayCandles({ bars, ma, display, markers, drawings, firstPoint, onDrawingPoint }: {
  bars: BacktestResultReplayFrame["bars"];
  ma: BacktestResultReplayMA | undefined;
  display: ReplayChartDisplay;
  markers: ReturnType<typeof replayChartMarkers>;
  drawings: readonly ReplayDrawing[];
  firstPoint: ReplayDrawingPoint | undefined;
  onDrawingPoint: ((point: ReplayDrawingPoint) => void) | undefined;
}) {
  const clipId = useId();
  if (bars.length === 0) return null;
  const values = ma?.points.map(point => point.value) ?? [];
  const high = Math.max(...bars.map(bar => Number(bar.high)), ...values);
  const low = Math.min(...bars.map(bar => Number(bar.low)), ...values);
  const y = (price: string | number) => high === low ? 170 : 316 - (Number(price) - low) / (high - low) * 292;
  const spacing = Math.min(48, 968 / bars.length);
  const x = (index: number) => 24 + index * spacing;
  const left = Math.max(0, x(0) - spacing / 2);
  const right = x(bars.length - 1) + spacing / 2;
  const placePoint = (event: MouseEvent<SVGSVGElement>) => {
    if (!onDrawingPoint) return;
    const matrix = event.currentTarget.getScreenCTM();
    if (!matrix) return;
    const local = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse());
    if (local.x < left || local.x > right || local.y < 24 || local.y > 316) return;
    const index = Math.min(bars.length - 1, Math.max(0, Math.round((local.x - x(0)) / spacing)));
    onDrawingPoint({ timeMs: bars[index]!.open_time_ms, price: low + (316 - local.y) / 292 * (high - low) });
  };
  const points = new Map(ma?.points.map(point => [point.open_time_ms, point.value]));
  const line = bars.flatMap((bar, index) => {
    const value = points.get(bar.open_time_ms);
    if (value === undefined) return [];
    const previous = bars[index - 1];
    const adjacent = previous?.close_time_ms === bar.open_time_ms - 1 && points.has(previous.open_time_ms);
    const at = `${24 + index * spacing} ${y(value)}`;
    return adjacent ? `L ${at}` : `M ${at} h 0`;
  }).join(" ");
  return <svg viewBox="0 0 1000 340" role="img" aria-label={t("strategy.chartSlot")} className="strategy-result-replay-candles"
    data-drawing-active={onDrawingPoint ? true : undefined} onClick={onDrawingPoint ? placePoint : undefined}>
    <defs><clipPath id={clipId}><rect x={left} y={24} width={right - left} height={292} /></clipPath></defs>
    {bars.map((bar, index) => {
      const x = 24 + index * spacing;
      const open = y(bar.open);
      const close = y(bar.close);
      const rising = Number(bar.close) >= Number(bar.open);
      const color = rising ? display.upColor : display.downColor;
      const fill = rising && display.candleStyle === "hollow" ? "none" : color;
      return <g key={bar.open_time_ms} opacity={bar.closed ? 1 : 0.65}>
        <line x1={x} x2={x} y1={y(bar.high)} y2={y(bar.low)} stroke={color} strokeWidth="2" />
        <rect x={x - spacing * 0.28} y={Math.min(open, close)} width={spacing * 0.56}
          height={Math.max(2, Math.abs(open - close))} fill={fill} stroke={color} />
        <title>{new Date(bar.open_time_ms).toISOString()} · {bar.open} / {bar.high} / {bar.low} / {bar.close}</title>
      </g>;
    })}
    {line && <path d={line} data-testid="strategy-replay-ma-line" stroke="#f59e0b" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" fill="none" />}
    <g clipPath={`url(#${clipId})`} className="strategy-result-replay-drawings">
      {drawings.map(({ id, points: [first, second] }) => {
        const from = second ? replayDrawingBarIndex(bars, first.timeMs) : 0;
        const to = second ? replayDrawingBarIndex(bars, second.timeMs) : 0;
        if (from < 0 || to < 0) return null;
        return <line key={id} data-testid="strategy-replay-drawing" data-drawing-id={id}
          x1={second ? x(from) : left} y1={y(first.price)} x2={second ? x(to) : right} y2={y(second?.price ?? first.price)} />;
      })}
      {firstPoint && <circle cx={x(replayDrawingBarIndex(bars, firstPoint.timeMs))} cy={y(firstPoint.price)} r={3} />}
    </g>
    {[...markers].map(([index, { fills, notes }]) => {
      const x = 24 + index * spacing;
      const radius = Math.min(7, spacing * 0.42);
      return <g key={index}>
        {fills.length > 0 && <circle cx={x} cy={14} r={radius} fill="var(--strategy-replay-fill, #508bd5)"
          data-testid="strategy-replay-fill-marker" data-cursors={fills.map(fill => fill.cursor).join(",")}>
          <title>{fills.map(fill => `#${fill.cursor} · ${fill.side} ${fill.qty} @ ${fill.price}`).join("\n")}</title>
        </circle>}
        {notes.length > 0 && <circle cx={x} cy={326} r={radius} fill="#f59e0b"
          data-testid="strategy-replay-note-marker" data-cursors={notes.map(note => note.cursor).join(",")}>
          <title>{notes.map(note => `#${note.cursor} · ${note.body}`).join("\n")}</title>
        </circle>}
      </g>;
    })}
  </svg>;
}

function ReplayMaLegend({ ma }: { ma: BacktestResultReplayMA | undefined }) {
  if (!ma) return null;
  const last = ma.points.at(-1);
  return <p data-testid="strategy-replay-ma" data-period={ma.period} data-value={last?.value}>
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
  const markers = replayChartMarkers(frame, chart.bars, ownsMarkers, display);
  const ma = display.showMa ? chart.ma : undefined;
  const last = chart.bars.at(-1);
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
    <strong>{symbol} · {interval}</strong>
    <details>
      <summary>{t("workspace.link.chartStyle")}</summary>
      <fieldset className="strategy-result-replay-view-controls" disabled={disabled}>
        <label>{t("workspace.link.chartStyle")}
          <select value={display.candleStyle} data-testid="strategy-replay-candle-style"
            onChange={event => onChange(slot, "candleStyle", event.target.value === "hollow" ? "hollow" : "solid")}>
            <option value="solid">{t("drawing.variant.candlestick")}</option>
            <option value="hollow">{t("drawing.variant.hollow-candlestick")}</option>
          </select>
        </label>
        {([["upColor", "settings.appearance.upColor"], ["downColor", "settings.appearance.downColor"]] as const).map(([field, key]) =>
          <label key={field}>{t(key)}
            <input type="color" value={display[field]} onChange={event => onChange(slot, field, event.target.value)} />
          </label>)}
        {([["fills", "researchBatch.replayFillMarkers"], ["notes", "researchBatch.replayNoteMarkers"]] as const).map(([field, key]) =>
          <label key={field}>
            <input type="checkbox" data-testid={`strategy-replay-show-${field}`} disabled={!ownsMarkers} checked={display[field]}
              onChange={event => onChange(slot, field, event.target.checked)} />
            {t(key)}
          </label>)}
        {chart.ma && <label>
          <input type="checkbox" data-testid="strategy-replay-show-ma" checked={display.showMa}
            onChange={event => onChange(slot, "showMa", event.target.checked)} />
          {t("replay.indicator.sma.name")}
        </label>}
      </fieldset>
      {!ownsMarkers && <p>{t("researchBatch.replayReferenceMarkers")}</p>}
      {drawingControl && <fieldset className="strategy-result-replay-view-controls" disabled={disabled}>
        <legend>{t("workspace.link.drawings")}</legend>
        <label>
          <input type="checkbox" data-testid="strategy-replay-show-drawings" checked={display.showDrawings}
            onChange={event => onChange(slot, "showDrawings", event.target.checked)} />
          {t("drawing.showAll")}
        </label>
        {(Object.keys(drawingToolLabels) as DrawingTool[]).map(kind => <button type="button" key={kind}
          data-testid={`strategy-replay-draw-${kind}`} aria-pressed={tool === kind} disabled={!canDraw}
          onClick={() => { setTool(tool === kind ? null : kind); setPending(null); setDrawingLimit(false); }}>
          {t(drawingToolLabels[kind])}
        </button>)}
        {drawings.map((drawing, index) => <button type="button" key={drawing.id} disabled={drawingControl.locked}
          data-testid="strategy-replay-remove-drawing" onClick={() => { drawingControl.edit({ remove: drawing.id }); setDrawingLimit(false); }}>
          {t("workspace.delete")} · {t(drawingToolLabels[drawing.points.length === 1 ? "horizontal" : "segment"])} #{index + 1}
        </button>)}
        {drawingLimit && <span role="alert">{t("drawing.objects.failed")}</span>}
      </fieldset>}
    </details>
    <ReplayCandles bars={chart.bars} ma={ma} display={display} markers={markers}
      drawings={display.showDrawings ? drawings : []} firstPoint={firstPoint}
      onDrawingPoint={canDraw && tool !== null ? addPoint : undefined} />
    <ReplayMaLegend ma={ma} />
    {last && <p data-testid={slot === "primary" ? "strategy-replay-last-ohlc" : `strategy-replay-${slot}-ohlc`}>
      {last.open} / {last.high} / {last.low} / {last.close}
    </p>}
  </section>;
}
