import { t } from "../../i18n/index.js";
import { formatIntervalLabel } from "../../utils/intervals.js";
import type { BacktestResultReplayFrame, BacktestResultReplayMA } from "../backtest/backtestTypes.js";
import { replayChartMarkers, type ReplayChartDisplay, type ReplayChartSlot } from "./strategyResultReplayDisplay.js";

function ReplayCandles({ bars, ma, display, markers }: {
  bars: BacktestResultReplayFrame["bars"];
  ma: BacktestResultReplayMA | undefined;
  display: ReplayChartDisplay;
  markers: ReturnType<typeof replayChartMarkers>;
}) {
  if (bars.length === 0) return null;
  const values = ma?.points.map(point => point.value) ?? [];
  const high = Math.max(...bars.map(bar => Number(bar.high)), ...values);
  const low = Math.min(...bars.map(bar => Number(bar.low)), ...values);
  const y = (price: string | number) => high === low ? 170 : 316 - (Number(price) - low) / (high - low) * 292;
  const spacing = Math.min(48, 968 / bars.length);
  const points = new Map(ma?.points.map(point => [point.open_time_ms, point.value]));
  const line = bars.flatMap((bar, index) => {
    const value = points.get(bar.open_time_ms);
    if (value === undefined) return [];
    const previous = bars[index - 1];
    const adjacent = previous?.close_time_ms === bar.open_time_ms - 1 && points.has(previous.open_time_ms);
    const at = `${24 + index * spacing} ${y(value)}`;
    return adjacent ? `L ${at}` : `M ${at} h 0`;
  }).join(" ");
  return <svg viewBox="0 0 1000 340" role="img" aria-label={t("strategy.chartSlot")} className="strategy-result-replay-candles">
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
    {line && <path d={line} stroke="#f59e0b" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" fill="none" />}
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

export function StrategyResultReplayChart({ slot, chart, frame, display, disabled, onChange }: {
  slot: ReplayChartSlot;
  chart: ReplayChart;
  frame: BacktestResultReplayFrame;
  display: ReplayChartDisplay;
  disabled: boolean;
  onChange<K extends keyof ReplayChartDisplay>(slot: ReplayChartSlot, field: K, value: ReplayChartDisplay[K]): void;
}) {
  const ownsMarkers = chart.dataset_id === undefined;
  const symbol = chart.symbol ?? frame.symbol;
  const interval = formatIntervalLabel(chart.interval);
  const markers = replayChartMarkers(frame, chart.bars, ownsMarkers, display);
  const last = chart.bars.at(-1);
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
      </fieldset>
      {!ownsMarkers && <p>{t("researchBatch.replayReferenceMarkers")}</p>}
    </details>
    <ReplayCandles bars={chart.bars} ma={chart.ma} display={display} markers={markers} />
    <ReplayMaLegend ma={chart.ma} />
    {last && <p data-testid={slot === "primary" ? "strategy-replay-last-ohlc" : "strategy-replay-comparison-ohlc"}>
      {last.open} / {last.high} / {last.low} / {last.close}
    </p>}
  </section>;
}
