import { useEffect, useState } from "react";
import { t } from "../../i18n/index.js";
import { describeError } from "../../i18n/serverErrors.js";
import type { BacktestResultReplayCursor, BacktestResultReplayFrame } from "../backtest/backtestTypes.js";
import type { StrategyDataManager } from "../market-data/manager/strategyDataManager.js";
import { formatIntervalLabel } from "../../utils/intervals.js";

function ReplayCandles({ bars }: { bars: BacktestResultReplayFrame["bars"] }) {
  if (bars.length === 0) return null;
  const high = Math.max(...bars.map(bar => Number(bar.high)));
  const low = Math.min(...bars.map(bar => Number(bar.low)));
  const y = (price: string) => high === low ? 170 : 316 - (Number(price) - low) / (high - low) * 292;
  const spacing = Math.min(48, 968 / bars.length);
  return <svg viewBox="0 0 1000 340" role="img" aria-label={t("strategy.chartSlot")} className="strategy-result-replay-candles">
    {bars.map((bar, index) => {
      const x = 24 + index * spacing;
      const open = y(bar.open);
      const close = y(bar.close);
      const color = Number(bar.close) >= Number(bar.open) ? "#159b84" : "#df595e";
      return <g key={bar.open_time_ms} opacity={bar.closed ? 1 : 0.65}>
        <line x1={x} x2={x} y1={y(bar.high)} y2={y(bar.low)} stroke={color} strokeWidth="2" />
        <rect x={x - spacing * 0.28} y={Math.min(open, close)} width={spacing * 0.56}
          height={Math.max(2, Math.abs(open - close))} fill={color} />
        <title>{new Date(bar.open_time_ms).toISOString()} · {bar.open} / {bar.high} / {bar.low} / {bar.close}</title>
      </g>;
    })}
  </svg>;
}

export default function StrategyResultReplay({ initial, manager, onCommit, onClose }: {
  initial: BacktestResultReplayCursor;
  manager: StrategyDataManager;
  onCommit(cursor: BacktestResultReplayCursor): void;
  onClose(): void;
}) {
  const [request, setRequest] = useState(initial);
  const [received, setReceived] = useState<{ request: BacktestResultReplayCursor; frame: BacktestResultReplayFrame } | null>(null);
  const [playing, setPlaying] = useState(false);
  const [target, setTarget] = useState(String(initial.cursor));
  const [error, setError] = useState<string | null>(null);
  const frame = received?.request === request ? received.frame : null;
  const total = received?.frame.total;
  const candidate = target.trim() === "" ? NaN : Number(target);
  const selectableIntervals = received?.frame.display_intervals ?? [initial.interval];
  const barClock = received?.frame.schema === "candlescope.local-bar-result-replay/1";

  useEffect(() => {
    const controller = new AbortController();
    void manager.loadResultReplay(request, controller.signal).then(value => {
      if (controller.signal.aborted) return;
      setReceived({ request, frame: value });
      onCommit(request);
    }).catch((reason: unknown) => {
      if (controller.signal.aborted) return;
      setPlaying(false);
      setError(reason instanceof Error ? describeError(reason, reason.message) : String(reason));
    });
    return () => controller.abort();
  }, [manager, onCommit, request]);

  useEffect(() => {
    if (!playing || !frame) return;
    if (frame.cursor >= frame.total) return;
    const timer = setTimeout(() => {
      setTarget(String(frame.cursor + 1));
      setRequest({ ...request, cursor: frame.cursor + 1 });
    }, 350);
    return () => clearTimeout(timer);
  }, [frame, playing, request]);

  const navigate = (cursor: number, interval = request.interval, comparison = request.comparisonInterval ?? null) => {
    setPlaying(false);
    setError(null);
    setTarget(String(cursor));
    const { comparisonInterval: _comparison, ...identity } = request;
    setRequest({ ...identity, cursor, interval, ...(comparison ? { comparisonInterval: comparison } : {}) });
  };
  const canAdvance = frame !== null && frame.cursor < frame.total;
  const lastBar = frame?.bars.at(-1);
  return (
    <main className="strategy-result-replay" data-testid="strategy-result-replay"
      data-cursor={frame?.cursor} data-interval={frame?.interval}>
      <header>
        <h1>{t("report.replay")}{frame ? ` · ${frame.symbol}` : ""}</h1>
        <button type="button" onClick={onClose}>{t("report.analysis")}</button>
      </header>
      <div className="strategy-result-replay-controls">
        <button type="button" disabled={request.cursor === 0} onClick={() => navigate(0)}>⏮ {t("native.replay.seek")}</button>
        <button type="button" disabled={request.cursor === 0} onClick={() => navigate(request.cursor - 1)}>← {t("native.replay.seek")}</button>
        <button type="button" disabled={!canAdvance} onClick={() => navigate(request.cursor + 1)}>{t("native.replay.step")}</button>
        <button type="button" disabled={!playing && !canAdvance} onClick={() => setPlaying(!playing)}>
          {t(playing ? "native.replay.pause" : "native.replay.play")}
        </button>
        <form onSubmit={event => {
          event.preventDefault();
          if (Number.isSafeInteger(candidate) && candidate >= 0 && total !== undefined && candidate <= total) navigate(candidate);
        }}>
          <label>{t(barClock ? "native.replay.cursor" : "settings.exchange.channel.trade")}
            <input type="number" min={0} max={total} step={1} value={target} onChange={event => setTarget(event.target.value)} />
          </label>
          <button disabled={!Number.isSafeInteger(candidate) || candidate < 0 || total === undefined || candidate > total}>
            {t("native.replay.seek")}
          </button>
        </form>
        <label>{t("local.interval")}
          <select data-testid="strategy-replay-primary-period" value={request.interval} onChange={event => navigate(request.cursor, event.target.value)}>
            {selectableIntervals.filter(interval => interval !== request.comparisonInterval).map(interval => <option key={interval} value={interval}>{formatIntervalLabel(interval)}</option>)}
          </select>
        </label>
        <label>{t("local.interval")} · {t("replay.workspace.openNew")}
          <select data-testid="strategy-replay-comparison-period" value={request.comparisonInterval ?? ""}
            onChange={event => navigate(request.cursor, request.interval, event.target.value || null)}>
            <option value="">{t("backtest.none")}</option>
            {selectableIntervals.filter(interval => interval !== request.interval).map(interval =>
              <option key={interval} value={interval}>{formatIntervalLabel(interval)}</option>)}
          </select>
        </label>
      </div>
      {error ? <p role="alert">{error} <button type="button" onClick={() => navigate(request.cursor)}>{t("shell.retry")}</button></p>
        : !frame ? <p role="status">{t("research.loading")}</p> : <>
          <div className="strategy-result-replay-status" role="status">
            <span>{frame.cursor} / {frame.total}</span>
            {frame.time_ms !== null && <time>{new Date(frame.time_ms).toISOString()}</time>}
            {frame.source_sequence !== null && <span>#{frame.source_sequence}</span>}
          </div>
          <div className="strategy-result-replay-charts">
            <section aria-label={formatIntervalLabel(frame.interval)} data-testid="strategy-replay-primary-chart">
              <strong>{formatIntervalLabel(frame.interval)}</strong>
              <ReplayCandles bars={frame.bars} />
              {lastBar && <p data-testid="strategy-replay-last-ohlc">{lastBar.open} / {lastBar.high} / {lastBar.low} / {lastBar.close}</p>}
            </section>
            {frame.comparison && <section aria-label={formatIntervalLabel(frame.comparison.interval)} data-testid="strategy-replay-comparison-chart">
              <strong>{formatIntervalLabel(frame.comparison.interval)}</strong>
              <ReplayCandles bars={frame.comparison.bars} />
              {frame.comparison.bars.slice(-1).map(bar => <p key={bar.open_time_ms} data-testid="strategy-replay-comparison-ohlc">
                {bar.open} / {bar.high} / {bar.low} / {bar.close}
              </p>)}
            </section>}
          </div>
          <dl className="strategy-result-replay-status">
            <div><dt>{t("replay.wb.balance")}</dt><dd>{frame.cash} {frame.quote_asset}</dd></div>
            <div><dt>{t("replay.wb.positions")}</dt><dd>{frame.position}</dd></div>
            <div><dt>{t("replay.wb.equity")}</dt><dd data-testid="strategy-replay-equity">{frame.equity} {frame.quote_asset}</dd></div>
          </dl>
          <details open><summary>{t("chartTester.tab.trades")} · {frame.fill_count}</summary>
            <ol data-testid="strategy-replay-fills">
              {frame.fills.map((fill, i) => <li key={`${fill.cursor}:${fill.order_id}:${i}`}>#{fill.cursor} · {fill.side} · {fill.qty} @ {fill.price}</li>)}
            </ol>
          </details>
          {frame.signal_trace_available && <details><summary>{t("local.kind.signal")}</summary>
            <ol data-testid="strategy-replay-signals">{frame.closed_bar_signals.map(signal => <li key={signal.signal_sequence}>
              #{signal.reveal_sequence} · {signal.kind} · {signal.value}
            </li>)}</ol>
          </details>}
          {frame.order_trace_available && <details><summary>{t("native.orders")}</summary>
            <ol data-testid="strategy-replay-orders">{frame.order_events.map(order => <li key={order.ordinal}>
              #{order.reveal_sequence} · {order.order_id} · {order.state}
            </li>)}</ol>
          </details>}
        </>}
    </main>
  );
}
