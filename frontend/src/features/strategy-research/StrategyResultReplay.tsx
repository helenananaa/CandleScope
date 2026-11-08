import { useEffect, useState } from "react";
import { t } from "../../i18n/index.js";
import { describeError } from "../../i18n/serverErrors.js";
import type { BacktestResultReplayCursor, BacktestResultReplayFrame, BacktestResultReplayNote, BacktestResultReplayNoteDraft } from "../backtest/backtestTypes.js";
import type { LocalDatasetManifest } from "../local-data/localDataTypes.js";
import type { StrategyDataManager } from "../market-data/manager/strategyDataManager.js";
import { formatIntervalLabel } from "../../utils/intervals.js";

import { StrategyResultReplayChart } from "./StrategyResultReplayChart.js";
import { changeReplayChartDisplay, replayDisplayKey, type ReplayDisplay, type ReplayChartDisplay, type ReplayChartSlot } from "./strategyResultReplayDisplay.js";

const MA_PERIODS = [2, 3, 5, 10, 20, 50, 100, 200, 500];

function ReplayMaControl({ testId, interval, period, onChange }: {
  testId: string; interval: string; period: number | undefined; onChange(period: number | undefined): void;
}) {
  const options = period === undefined || MA_PERIODS.includes(period) ? MA_PERIODS : [...MA_PERIODS, period].sort((a, b) => a - b);
  return <label>{t("replay.indicator.sma.name")} · {formatIntervalLabel(interval)}
    <select data-testid={testId} value={period ?? ""} onChange={event => onChange(Number(event.target.value) || undefined)}>
      <option value="">{t("backtest.none")}</option>
      {options.map(value => <option key={value} value={value}>{value}</option>)}
    </select>
  </label>;
}

export default function StrategyResultReplay({ initial, manager, datasets, display, onCommit, onClose, onDisplay }: {
  initial: BacktestResultReplayCursor;
  manager: StrategyDataManager;
  datasets: readonly LocalDatasetManifest[];
  display: ReplayDisplay;
  onDisplay(key: string, display: ReplayDisplay): void;
  onCommit(cursor: BacktestResultReplayCursor): void;
  onClose(): void;
}) {
  const [request, setRequest] = useState(initial);
  const [received, setReceived] = useState<{ request: BacktestResultReplayCursor; frame: BacktestResultReplayFrame } | null>(null);
  const [playing, setPlaying] = useState(false);
  const [target, setTarget] = useState(String(initial.cursor));
  const [error, setError] = useState<string | null>(null);
  const [noteDraft, setNoteDraft] = useState<BacktestResultReplayNoteDraft | null>(null);
  const [noteSaving, setNoteSaving] = useState(false);
  const [noteError, setNoteError] = useState<string | null>(null);
  const frame = received?.request === request ? received.frame : null;
  const total = received?.frame.total;
  const candidate = target.trim() === "" ? NaN : Number(target);
  const selectableIntervals = received?.frame.display_intervals ?? [initial.interval];
  const comparisonDatasets = datasets.filter(dataset => dataset.source === "local_dataset" && !dataset.archived);
  const pinned = request.comparisonDataset;
  const pinnedKey = pinned ? `${pinned.datasetId}:${pinned.dataEpoch}` : "";
  const visibleReference = received?.frame.comparison;
  const sameReference = pinned && visibleReference?.dataset_id === pinned.datasetId
    && visibleReference?.data_epoch === pinned.dataEpoch;
  const comparisonIntervals = pinned
    ? sameReference ? visibleReference.display_intervals ?? [] : request.comparisonInterval ? [request.comparisonInterval] : []
    : selectableIntervals.filter(interval => interval !== request.interval);
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

  const navigate = (cursor: number, display: {
    interval?: string;
    comparisonInterval?: string | undefined;
    comparisonDataset?: BacktestResultReplayCursor["comparisonDataset"];
    maPeriod?: number | undefined;
    comparisonMaPeriod?: number | undefined;
  } = {}) => {
    setPlaying(false);
    setError(null);
    setTarget(String(cursor));
    const { comparisonInterval, comparisonDataset, maPeriod, comparisonMaPeriod, ...identity } = { ...request, ...display };
    setRequest({ ...identity, cursor,
      ...(maPeriod === undefined ? {} : { maPeriod }),
      ...(comparisonInterval ? { comparisonInterval,
        ...(comparisonDataset ? { comparisonDataset } : {}),
        ...(comparisonMaPeriod === undefined ? {} : { comparisonMaPeriod }) } : {}),
    });
  };
  const editNote = (note?: BacktestResultReplayNote) => {
    setPlaying(false);
    setNoteError(null);
    setNoteDraft(note
      ? { id: note.id, expectedRevision: note.revision, body: note.body }
      : { id: crypto.randomUUID(), expectedRevision: 0, body: "" });
  };
  const saveNote = async () => {
    if (!frame || !noteDraft?.body.trim() || noteSaving) return;
    setNoteSaving(true);
    setNoteError(null);
    try {
      await manager.saveResultReplayNote(request, noteDraft);
      setNoteDraft(null);
      setRequest(current => current === request ? { ...current } : current);
    } catch (reason) {
      setNoteError(describeError(reason, t("replay.notes.saveFailed")));
    } finally {
      setNoteSaving(false);
    }
  };

  const canAdvance = frame !== null && frame.cursor < frame.total;
  const displayKey = replayDisplayKey(initial);
  const updateChart = <K extends keyof ReplayChartDisplay>(slot: ReplayChartSlot, field: K, value: ReplayChartDisplay[K]) => {
    const next = changeReplayChartDisplay(display, slot, field, value);
    onDisplay(displayKey, request.comparisonInterval ? next : { ...display, primary: next.primary });
  };
  return (
    <main className="strategy-result-replay" data-testid="strategy-result-replay"
      data-cursor={frame?.cursor} data-interval={frame?.interval}>
      <header>
        <h1>{t("report.replay")}{frame ? ` · ${frame.symbol}` : ""}</h1>
        <button type="button" disabled={noteDraft !== null} onClick={onClose}>{t("report.analysis")}</button>
      </header>
      <fieldset className="strategy-result-replay-controls" disabled={noteDraft !== null}>
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
          <select data-testid="strategy-replay-primary-period" value={request.interval} onChange={event => navigate(request.cursor, { interval: event.target.value })}>
            {selectableIntervals.filter(interval => pinned || interval !== request.comparisonInterval).map(interval => <option key={interval} value={interval}>{formatIntervalLabel(interval)}</option>)}
          </select>
        </label>
        {(comparisonDatasets.length > 0 || pinned) && <label>{t("researchBatch.replayComparisonSource")}
          <select data-testid="strategy-replay-comparison-source" value={pinnedKey} onChange={event => {
            const dataset = comparisonDatasets.find(item => `${item.dataset_id}:${item.data_epoch}` === event.target.value);
            navigate(request.cursor, dataset
              ? { comparisonDataset: { datasetId: dataset.dataset_id, dataEpoch: dataset.data_epoch }, comparisonInterval: dataset.interval }
              : { comparisonDataset: undefined, comparisonInterval: selectableIntervals.find(interval => interval !== request.interval) });
          }}>
            <option value="">{t("researchBatch.replayRunSource")}</option>
            {pinned && !comparisonDatasets.some(dataset => `${dataset.dataset_id}:${dataset.data_epoch}` === pinnedKey) &&
              <option value={pinnedKey}>{sameReference ? visibleReference.symbol : pinned.datasetId} · {pinned.dataEpoch.slice(-8)}</option>}
            {comparisonDatasets.map(dataset => <option key={dataset.dataset_id} value={`${dataset.dataset_id}:${dataset.data_epoch}`}>
              {dataset.name} · {dataset.symbol}
            </option>)}
          </select>
        </label>}
        <label>{t("local.interval")} · {t("replay.workspace.openNew")}
          <select data-testid="strategy-replay-comparison-period" value={request.comparisonInterval ?? ""}
            onChange={event => navigate(request.cursor, { comparisonInterval: event.target.value || undefined })}>
            <option value="">{t("backtest.none")}</option>
            {comparisonIntervals.map(interval =>
              <option key={interval} value={interval}>{formatIntervalLabel(interval)}</option>)}
          </select>
        </label>
        <ReplayMaControl testId="strategy-replay-primary-ma" interval={request.interval} period={request.maPeriod}
          onChange={maPeriod => navigate(request.cursor, { maPeriod })} />
        {request.comparisonInterval && <ReplayMaControl testId="strategy-replay-comparison-ma" interval={request.comparisonInterval}
          period={request.comparisonMaPeriod} onChange={comparisonMaPeriod => navigate(request.cursor, { comparisonMaPeriod })} />}
      </fieldset>
      {request.comparisonInterval && <fieldset className="strategy-result-replay-view-controls"
        data-testid="strategy-replay-display-links" disabled={noteDraft !== null}>
        <legend>{t("workspace.tab.links")}</legend>
        {([
          ["chartStyle", "workspace.link.chartStyle"],
          ["fills", "researchBatch.replayFillMarkers"],
          ["notes", "researchBatch.replayNoteMarkers"],
        ] as const).map(([channel, label]) => <label key={channel}>
          <input type="checkbox" data-testid={`strategy-replay-link-${channel}`} checked={display.links[channel]}
            onChange={event => onDisplay(displayKey, { ...display, links: { ...display.links, [channel]: event.target.checked } })} />
          {t(label)}
        </label>)}
      </fieldset>}
      {error ? <p role="alert">{error} <button type="button" onClick={() => navigate(request.cursor)}>{t("shell.retry")}</button></p>
        : !frame ? <p role="status">{t("research.loading")}</p> : <>
          <div className="strategy-result-replay-status" role="status">
            <span>{frame.cursor} / {frame.total}</span>
            {frame.time_ms !== null && <time>{new Date(frame.time_ms).toISOString()}</time>}
            {frame.source_sequence !== null && <span>#{frame.source_sequence}</span>}
          </div>
          <div className="strategy-result-replay-charts">
            <StrategyResultReplayChart slot="primary" chart={frame} frame={frame} display={display.primary}
              disabled={noteDraft !== null} onChange={updateChart} />
            {frame.comparison && <StrategyResultReplayChart slot="comparison" chart={frame.comparison} frame={frame}
              display={display.comparison} disabled={noteDraft !== null} onChange={updateChart} />}
          </div>
          <dl className="strategy-result-replay-status">
            <div><dt>{t("replay.wb.balance")}</dt><dd>{frame.cash} {frame.quote_asset}</dd></div>
            <div><dt>{t("replay.wb.positions")}</dt><dd>{frame.position}</dd></div>
            <div><dt>{t("replay.wb.equity")}</dt><dd data-testid="strategy-replay-equity">{frame.equity} {frame.quote_asset}</dd></div>
          </dl>
          {frame.notes && <section className="strategy-result-replay-notes" data-testid="strategy-replay-notes">
            <h2>{t("replay.notes.title")}</h2>
            {frame.notes.length === 0 && <p>{t("replay.notes.empty")}</p>}
            {frame.notes.map(note => <article key={note.id} data-testid="strategy-replay-note"
              data-revision={note.revision} data-cursor={note.cursor}>
              <span>#{note.cursor} {note.time_ms !== null && <time>{new Date(note.time_ms).toISOString()}</time>}</span>
              <p>{note.body}</p>
              <button type="button" disabled={noteDraft !== null || note.revision >= 20}
                onClick={() => editNote(note)}>{t("replay.notes.edit")}</button>
            </article>)}
            {noteDraft ? <form onSubmit={event => { event.preventDefault(); void saveNote(); }}>
              <label>{t("replay.notes.body")}
                <textarea data-testid="strategy-replay-note-body" rows={4} maxLength={2000} required
                  value={noteDraft.body} disabled={noteSaving}
                  onChange={event => setNoteDraft({ ...noteDraft, body: event.target.value })} />
              </label>
              {noteError && <p role="alert">{noteError}</p>}
              <button type="submit" disabled={noteSaving || !noteDraft.body.trim()}>
                {t(noteSaving ? "replay.notes.saving" : "replay.notes.save")}
              </button>
              <button type="button" disabled={noteSaving} onClick={() => setNoteDraft(null)}>{t("replay.notes.close")}</button>
            </form> : <button type="button" disabled={frame.notes.length >= 100}
              onClick={() => editNote()}>{t("replay.notes.add")}</button>}
          </section>}
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
