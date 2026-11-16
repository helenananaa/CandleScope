import { useEffect, useState } from "react";
import { Button, Checkbox, Disclosure, Field, InlineAlert, Input, Select, Stat, Textarea } from "../../components/ui/index.js";
import { t } from "../../i18n/index.js";
import { describeError } from "../../i18n/serverErrors.js";
import { BACKTEST_REPLAY_EXTRA_SLOTS, type BacktestReplayChartOptions, type BacktestReplayExtraSlot, type BacktestReplayExtraCharts, type BacktestResultReplayChart, type BacktestResultReplayCursor, type BacktestResultReplayFrame, type BacktestResultReplayNote, type BacktestResultReplayNoteDraft } from "../backtest/backtestTypes.js";
import type { LocalDatasetManifest } from "../local-data/localDataTypes.js";
import type { StrategyDataManager } from "../market-data/manager/strategyDataManager.js";
import { formatIntervalLabel } from "../../utils/intervals.js";

import { StrategyResultReplayChart } from "./StrategyResultReplayChart.js";
import { changeReplayChartDisplay, replayChartDisplay, replayDisplayKey, replayLayout, restoreReplayLayout, type ReplayDisplay, type ReplayChartDisplay, type ReplayChartSlot } from "./strategyResultReplayDisplay.js";
import { editReplayDrawings, replayDrawingOwner, replayDrawingScope, type ReplayDrawingEdit } from "./strategyResultReplayDrawings.js";

const MA_PERIODS = [2, 3, 5, 10, 20, 50, 100, 200, 500];

function ReplayMaControl({ testId, interval, period, onChange }: {
  testId: string; interval: string; period: number | undefined; onChange(period: number | undefined): void;
}) {
  const options = period === undefined || MA_PERIODS.includes(period) ? MA_PERIODS : [...MA_PERIODS, period].sort((a, b) => a - b);
  return <Field label={`${t("replay.indicator.sma.name")} · ${formatIntervalLabel(interval)}`}>
    <Select size="sm" data-testid={testId} value={period ?? ""} onChange={event => onChange(Number(event.target.value) || undefined)}>
      <option value="">{t("backtest.none")}</option>
      {options.map(value => <option key={value} value={value}>{value}</option>)}
    </Select>
  </Field>;
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
  const [request, setRequest] = useState(() => restoreReplayLayout(initial, display));
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
      const saved = { ...request };
      delete saved.additionalCharts; // Reference preferences live with the run's display settings.
      onCommit(saved);
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

  const navigate = (cursor: number, changes: {
    interval?: string;
    comparisonInterval?: string | undefined;
    comparisonDataset?: BacktestResultReplayCursor["comparisonDataset"];
    maPeriod?: number | undefined;
    comparisonMaPeriod?: number | undefined;
    additionalCharts?: BacktestReplayExtraCharts;
  } = {}) => {
    setPlaying(false);
    setError(null);
    setTarget(String(cursor));
    const { comparisonInterval, comparisonDataset, maPeriod, comparisonMaPeriod, ...identity } = { ...request, ...changes };
    const next = { ...identity, cursor,
      ...(maPeriod === undefined ? {} : { maPeriod }),
      ...(comparisonInterval ? { comparisonInterval,
        ...(comparisonDataset ? { comparisonDataset } : {}),
        ...(comparisonMaPeriod === undefined ? {} : { comparisonMaPeriod }) } : {}),
    };
    setRequest(next);
    if (Object.keys(changes).length) onDisplay(displayKey, {
      ...display, layout: replayLayout(next), ...(next.additionalCharts ? { references: next.additionalCharts } : {}),
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
  const extraSlots = BACKTEST_REPLAY_EXTRA_SLOTS.filter(slot => request.additionalCharts?.[slot]);
  const nextSlot = BACKTEST_REPLAY_EXTRA_SLOTS.find(slot => !request.additionalCharts?.[slot]);
  const activeSlots: ReplayChartSlot[] = ["primary", ...(request.comparisonInterval ? ["comparison" as const] : []), ...extraSlots];
  const changeReference = (slot: BacktestReplayExtraSlot, chart: BacktestReplayChartOptions | null) => {
    const additionalCharts = { ...request.additionalCharts };
    if (chart) additionalCharts[slot] = chart;
    else delete additionalCharts[slot];
    navigate(request.cursor, { additionalCharts });
  };
  const updateChart = <K extends keyof ReplayChartDisplay>(slot: ReplayChartSlot, field: K, value: ReplayChartDisplay[K]) => {
    onDisplay(displayKey, changeReplayChartDisplay(display, slot, field, value, activeSlots));
  };
  const charts: Partial<Record<ReplayChartSlot, BacktestResultReplayChart | null>> = frame
    ? { primary: frame, comparison: frame.comparison ?? null, ...frame.additional_charts } : {};
  const drawingControl = (slot: ReplayChartSlot) => {
    const chart = charts[slot];
    const owner = chart && replayDrawingOwner(chart);
    if (!owner) return undefined;
    const sourceScope = replayDrawingScope(slot, owner);
    const documents = display.drawings ?? {};
    return {
      owner,
      drawings: documents[sourceScope] ?? [],
      locked: playing || noteDraft !== null,
      edit: (edit: ReplayDrawingEdit) => {
        const targets = display.links.drawings ? activeSlots.filter(target => {
          const peer = charts[target];
          return peer && replayDrawingOwner(peer) === owner;
        }) : [slot];
        const drawings = editReplayDrawings(documents, targets.map(target => replayDrawingScope(target, owner)), edit);
        if (!drawings) return false;
        const { drawings: _previous, ...next } = display;
        onDisplay(displayKey, Object.keys(drawings).length ? { ...next, drawings } : next);
        return true;
      },
    };
  };
  return (
    <main className="strategy-result-replay" data-testid="strategy-result-replay"
      data-cursor={frame?.cursor} data-interval={frame?.interval}>
      <header className="strategy-result-replay-head">
        <h1>{t("report.replay")}{frame ? ` · ${frame.symbol}` : ""}</h1>
        <Button size="sm" variant="ghost" disabled={noteDraft !== null} onClick={onClose}>{t("report.analysis")}</Button>
      </header>
      <fieldset className="strategy-result-replay-controls" disabled={noteDraft !== null}>
        <div className="strategy-result-replay-transport">
          <Button size="sm" disabled={request.cursor === 0} onClick={() => navigate(0)}>⏮ {t("native.replay.seek")}</Button>
          <Button size="sm" disabled={request.cursor === 0} onClick={() => navigate(request.cursor - 1)}>← {t("native.replay.seek")}</Button>
          <Button size="sm" disabled={!canAdvance} onClick={() => navigate(request.cursor + 1)}>{t("native.replay.step")}</Button>
          <Button size="sm" variant="primary" disabled={!playing && !canAdvance} onClick={() => setPlaying(!playing)}>
            {t(playing ? "native.replay.pause" : "native.replay.play")}
          </Button>
        </div>
        <form className="strategy-result-replay-seek" onSubmit={event => {
          event.preventDefault();
          if (Number.isSafeInteger(candidate) && candidate >= 0 && total !== undefined && candidate <= total) navigate(candidate);
        }}>
          <Field label={t(barClock ? "native.replay.cursor" : "settings.exchange.channel.trade")}>
            <Input size="sm" type="number" min={0} max={total} step={1} value={target} onChange={event => setTarget(event.target.value)} />
          </Field>
          <Button size="sm" type="submit" disabled={!Number.isSafeInteger(candidate) || candidate < 0 || total === undefined || candidate > total}>
            {t("native.replay.seek")}
          </Button>
        </form>
        <Field label={t("local.interval")}>
          <Select size="sm" data-testid="strategy-replay-primary-period" value={request.interval} onChange={event => navigate(request.cursor, { interval: event.target.value })}>
            {selectableIntervals.filter(interval => pinned || interval !== request.comparisonInterval).map(interval => <option key={interval} value={interval}>{formatIntervalLabel(interval)}</option>)}
          </Select>
        </Field>
        {(comparisonDatasets.length > 0 || pinned) && <Field label={t("researchBatch.replayComparisonSource")}>
          <Select size="sm" data-testid="strategy-replay-comparison-source" value={pinnedKey} onChange={event => {
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
          </Select>
        </Field>}
        <Field label={`${t("local.interval")} · ${t("replay.workspace.openNew")}`}>
          <Select size="sm" data-testid="strategy-replay-comparison-period" value={request.comparisonInterval ?? ""}
            onChange={event => navigate(request.cursor, { comparisonInterval: event.target.value || undefined })}>
            <option value="">{t("backtest.none")}</option>
            {comparisonIntervals.map(interval =>
              <option key={interval} value={interval}>{formatIntervalLabel(interval)}</option>)}
          </Select>
        </Field>
        <ReplayMaControl testId="strategy-replay-primary-ma" interval={request.interval} period={request.maPeriod}
          onChange={maPeriod => navigate(request.cursor, { maPeriod })} />
        {request.comparisonInterval && <ReplayMaControl testId="strategy-replay-comparison-ma" interval={request.comparisonInterval}
          period={request.comparisonMaPeriod} onChange={comparisonMaPeriod => navigate(request.cursor, { comparisonMaPeriod })} />}
        {nextSlot && <Button size="sm" variant="ghost" data-testid="strategy-replay-add-chart"
          onClick={() => changeReference(nextSlot, { interval: request.interval })}>{t("replay.workspace.openNew")}</Button>}
      </fieldset>
      {extraSlots.map(slot => {
        const chart = request.additionalCharts![slot]!;
        const datasetKey = chart.dataset ? `${chart.dataset.datasetId}:${chart.dataset.dataEpoch}` : "";
        const previous = received?.frame.additional_charts?.[slot];
        const intervals = chart.dataset
          ? previous?.dataset_id === chart.dataset.datasetId && previous?.data_epoch === chart.dataset.dataEpoch
            ? previous.display_intervals ?? [chart.interval] : [chart.interval]
          : selectableIntervals;
        return <fieldset key={slot} className="strategy-result-replay-view-controls" disabled={noteDraft !== null}
          data-testid={`strategy-replay-${slot}-controls`}>
          <legend>{t("workspace.cellN", { n: activeSlots.indexOf(slot) + 1 })}</legend>
          <Field label={t("researchBatch.replayComparisonSource")}>
            <Select size="sm" data-testid={`strategy-replay-${slot}-source`} value={datasetKey} onChange={event => {
              const dataset = comparisonDatasets.find(item => `${item.dataset_id}:${item.data_epoch}` === event.target.value);
              changeReference(slot, dataset
                ? { ...chart, interval: dataset.interval, dataset: { datasetId: dataset.dataset_id, dataEpoch: dataset.data_epoch } }
                : { interval: request.interval, ...(chart.maPeriod === undefined ? {} : { maPeriod: chart.maPeriod }) });
            }}>
              <option value="">{t("researchBatch.replayRunSource")}</option>
              {chart.dataset && !comparisonDatasets.some(dataset => `${dataset.dataset_id}:${dataset.data_epoch}` === datasetKey) &&
                <option value={datasetKey}>{previous?.symbol ?? chart.dataset.datasetId} · {chart.dataset.dataEpoch.slice(-8)}</option>}
              {comparisonDatasets.map(dataset => <option key={dataset.dataset_id} value={`${dataset.dataset_id}:${dataset.data_epoch}`}>
                {dataset.name} · {dataset.symbol}
              </option>)}
            </Select>
          </Field>
          <Field label={t("local.interval")}>
            <Select size="sm" data-testid={`strategy-replay-${slot}-period`} value={chart.interval}
              onChange={event => changeReference(slot, { ...chart, interval: event.target.value })}>
              {intervals.map(interval => <option key={interval} value={interval}>{formatIntervalLabel(interval)}</option>)}
            </Select>
          </Field>
          <ReplayMaControl testId={`strategy-replay-${slot}-ma`} interval={chart.interval} period={chart.maPeriod} onChange={maPeriod => {
            const next = { ...chart };
            if (maPeriod === undefined) delete next.maPeriod;
            else next.maPeriod = maPeriod;
            changeReference(slot, next);
          }} />
          <Button size="sm" variant="ghost" data-testid={`strategy-replay-${slot}-close`}
            onClick={() => changeReference(slot, null)}>{t("workspace.closeChart")}</Button>
        </fieldset>;
      })}
      {activeSlots.length > 1 && <fieldset className="strategy-result-replay-view-controls"
        data-testid="strategy-replay-display-links" disabled={noteDraft !== null}>
        <legend>{t("workspace.tab.links")}</legend>
        {([
          ["chartStyle", "workspace.link.chartStyle"],
          ["fills", "researchBatch.replayFillMarkers"],
          ["notes", "researchBatch.replayNoteMarkers"],
          ["indicatorVisibility", "replay.indicator.sma.name"],
          ["drawings", "workspace.link.drawings"],
          ["drawingVisibility", "drawing.showAll"],
        ] as const).map(([channel, label]) => <Checkbox key={channel} data-testid={`strategy-replay-link-${channel}`} checked={display.links[channel]}
          onChange={event => onDisplay(displayKey, { ...display, links: { ...display.links, [channel]: event.target.checked } })} label={t(label)} />)}
      </fieldset>}
      {error ? <InlineAlert tone="danger" action={<Button size="sm" variant="ghost" onClick={() => navigate(request.cursor)}>{t("shell.retry")}</Button>}>{error}</InlineAlert>
        : !frame ? <p className="strategy-research-note" role="status">{t("research.loading")}</p> : <>
          <div className="strategy-result-replay-status" role="status">
            <strong>{frame.cursor} / {frame.total}</strong>
            {frame.time_ms !== null && <time>{new Date(frame.time_ms).toISOString()}</time>}
            {frame.source_sequence !== null && <span>#{frame.source_sequence}</span>}
          </div>
          <div className="strategy-result-replay-charts">
            <StrategyResultReplayChart slot="primary" chart={frame} frame={frame} display={display.primary}
              drawingControl={drawingControl("primary")} disabled={noteDraft !== null} onChange={updateChart} />
            {frame.comparison && <StrategyResultReplayChart slot="comparison" chart={frame.comparison} frame={frame}
              display={display.comparison} drawingControl={drawingControl("comparison")}
              disabled={noteDraft !== null} onChange={updateChart} />}
            {extraSlots.map(slot => {
              const chart = frame.additional_charts?.[slot];
              return chart && <StrategyResultReplayChart key={slot} slot={slot} chart={chart} frame={frame}
                display={replayChartDisplay(display, slot)} drawingControl={drawingControl(slot)}
                disabled={noteDraft !== null} onChange={updateChart} />;
            })}
          </div>
          <div className="strategy-result-replay-account">
            <Stat label={t("replay.wb.balance")} value={`${frame.cash} ${frame.quote_asset}`} />
            <Stat label={t("replay.wb.positions")} value={frame.position} />
            <Stat label={t("replay.wb.equity")} value={<span data-testid="strategy-replay-equity">{frame.equity} {frame.quote_asset}</span>} />
          </div>
          {frame.notes && <section className="strategy-result-replay-notes" data-testid="strategy-replay-notes">
            <h2>{t("replay.notes.title")}</h2>
            {frame.notes.length === 0 && <p className="strategy-research-note">{t("replay.notes.empty")}</p>}
            {frame.notes.map(note => <article key={note.id} data-testid="strategy-replay-note"
              data-revision={note.revision} data-cursor={note.cursor}>
              <span className="strategy-result-replay-note-meta">#{note.cursor} {note.time_ms !== null && <time>{new Date(note.time_ms).toISOString()}</time>}</span>
              <p>{note.body}</p>
              <Button size="sm" variant="ghost" disabled={noteDraft !== null || note.revision >= 20}
                onClick={() => editNote(note)}>{t("replay.notes.edit")}</Button>
            </article>)}
            {noteDraft ? <form className="strategy-result-replay-note-form" onSubmit={event => { event.preventDefault(); void saveNote(); }}>
              <Field label={t("replay.notes.body")}>
                <Textarea data-testid="strategy-replay-note-body" rows={4} maxLength={2000} required
                  value={noteDraft.body} disabled={noteSaving}
                  onChange={event => setNoteDraft({ ...noteDraft, body: event.target.value })} />
              </Field>
              {noteError && <InlineAlert tone="danger">{noteError}</InlineAlert>}
              <div className="strategy-history-actions">
                <Button size="sm" variant="primary" type="submit" disabled={noteSaving || !noteDraft.body.trim()}>
                  {t(noteSaving ? "replay.notes.saving" : "replay.notes.save")}
                </Button>
                <Button size="sm" variant="ghost" disabled={noteSaving} onClick={() => setNoteDraft(null)}>{t("replay.notes.close")}</Button>
              </div>
            </form> : <Button size="sm" disabled={frame.notes.length >= 100}
              onClick={() => editNote()}>{t("replay.notes.add")}</Button>}
          </section>}
          <Disclosure defaultOpen className="strategy-result-replay-trace" summary={`${t("chartTester.tab.trades")} · ${frame.fill_count}`}>
            <ol data-testid="strategy-replay-fills">
              {frame.fills.map((fill, i) => <li key={`${fill.cursor}:${fill.order_id}:${i}`}>#{fill.cursor} · {fill.side} · {fill.qty} @ {fill.price}</li>)}
            </ol>
          </Disclosure>
          {frame.signal_trace_available && <Disclosure className="strategy-result-replay-trace" summary={t("local.kind.signal")}>
            <ol data-testid="strategy-replay-signals">{frame.closed_bar_signals.map(signal => <li key={signal.signal_sequence}>
              #{signal.reveal_sequence} · {signal.kind} · {signal.value}
            </li>)}</ol>
          </Disclosure>}
          {frame.order_trace_available && <Disclosure className="strategy-result-replay-trace" summary={t("native.orders")}>
            <ol data-testid="strategy-replay-orders">{frame.order_events.map(order => <li key={order.ordinal}>
              #{order.reveal_sequence} · {order.order_id} · {order.state}
            </li>)}</ol>
          </Disclosure>}
        </>}
    </main>
  );
}
