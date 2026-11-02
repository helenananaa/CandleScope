import { useEffect, useMemo, useState } from "react";
import { ChartErrorBoundary } from "../../app/AppProviders.js";
import SingleChartPanes from "../../components/SingleChartPanes.js";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { normalizeMainChartType } from "../../shared/mainChartTypes.js";
import { formatUtcDateTimeInput, parseUtcDateTimeInput } from "../../utils/utcDateTimeInput.js";
import type { IndicatorDefinition } from "../indicators/indicatorTypes.js";
import { providedBarsIndicatorSupport, useProvidedBarsIndicatorRuntime } from "../indicators/useProvidedBarsIndicatorRuntime.js";
import type { ChartDataCommitMeta } from "../market-data/useChartDataRuntime.js";
import type { MarketDataManager } from "../market-data/manager/marketDataManager.js";
import type { QuickReplayChartStyle } from "../trading-accounts/QuickReplayOverlay.js";
import { formatDateTime } from "../trading-accounts/tradingFormat.js";
import type { HistoryStudyPlayback } from "./historyStudyPlayback.js";
import type { StudyNote } from "./historyStudyTypes.js";
import StudyNoteEditor from "./StudyNoteEditor.js";
import "../trading-accounts/tradingAccounts.css";
import "./historyStudy.css";

export default function HistoryStudyOverlay({ playback, manager, style, indicators: definitions, active, busy, error, onMove, onRetry }: {
  playback: HistoryStudyPlayback; manager: MarketDataManager; style: QuickReplayChartStyle;
  indicators: readonly IndicatorDefinition[]; active: boolean; busy: boolean; error: unknown;
  onMove(cursorMs: number, active?: boolean): Promise<boolean>; onRetry(): void;
}) {
  useLocale();
  const { input, store, cursorMs } = playback;
  const series = input.series;
  const [playing, setPlaying] = useState(false);
  const [value, setValue] = useState(() => formatUtcDateTimeInput(cursorMs));
  const [invalid, setInvalid] = useState(false);
  const [refreshNotes, setRefreshNotes] = useState(0);
  const [loaded, setLoaded] = useState<{ cursor: number; notes: StudyNote[] } | null>(null);
  const [notesError, setNotesError] = useState(false);
  const [editor, setEditor] = useState<{ marketMs: number; note: StudyNote | null } | null>(null);
  const [changed, setChanged] = useState(false);
  useEffect(() => { setValue(formatUtcDateTimeInput(cursorMs)); }, [cursorMs]);
  useEffect(() => {
    const controller = new AbortController(); setNotesError(false);
    manager.historyStudy.notes(input.id, cursorMs, controller.signal).then(result => {
      if (!controller.signal.aborted) setLoaded({ cursor: cursorMs, notes: result.notes });
    }).catch(() => { if (!controller.signal.aborted) setNotesError(true); });
    return () => controller.abort();
  }, [cursorMs, input.id, manager, refreshNotes]);
  // An old response is absent immediately when rewinding, before effects run.
  const notes = loaded?.cursor === cursorMs ? loaded.notes : [];
  useEffect(() => {
    const saved = new Map(input.rows.map(row => [row.time, row]));
    const changedRows = (rows: readonly import("../market-data/marketDataTypes.js").KlineBar[]) => rows.some(row => {
      if (row.time < input.rows[0]!.time || row.time > input.rows.at(-1)!.time || row.is_closed === false) return false;
      const original = saved.get(row.time);
      return !original || ["open", "high", "low", "close", "volume", "quote_volume", "trades", "taker_buy_base", "taker_buy_quote"]
        .some(key => (original[key] ?? null) !== (row[key] ?? null))
        || JSON.stringify(original.order_flow ?? null) !== JSON.stringify(row.order_flow ?? null);
    });
    // Compare any currently known rows as well as later admitted corrections.
    if (changedRows(manager.read(series).rows)) setChanged(true);
    return manager.cache.subscribe(series, change => { if (changedRows(change.rows)) setChanged(true); });
  }, [input.rows, manager, series]);
  useEffect(() => {
    if (!playing || editor) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      if (cursorMs >= playback.maximumMs) { setPlaying(false); return; }
      void onMove(playback.stepTarget(1)).then(ok => { if (!cancelled && !ok) setPlaying(false); });
    }, 700);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [cursorMs, editor, onMove, playback, playing]);
  useEffect(() => {
    if (!active || editor) return;
    const handler = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.isComposing || event.repeat || event.altKey || event.ctrlKey || event.metaKey
        || (event.target instanceof Element && event.target.closest("input,textarea,select,[contenteditable=true],[role=dialog],dialog"))) return;
      if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
        event.preventDefault(); event.stopPropagation(); setPlaying(false);
        void onMove(playback.stepTarget(event.key === "ArrowRight" ? 1 : -1));
      } else if (event.key === " ") { event.preventDefault(); event.stopPropagation(); setPlaying(value => !value); }
    };
    window.addEventListener("keydown", handler, true);
    return () => window.removeEventListener("keydown", handler, true);
  }, [active, editor, onMove, playback]);
  const version = Number(store.version);
  const rows = store.snapshot();
  const dataMeta = useMemo<ChartDataCommitMeta>(() => ({ version, status: "ready", source: "history-study",
    seriesKey: store.seriesKey, bars: rows.length, firstTime: rows[0]?.time ?? null, lastTime: rows.at(-1)?.time ?? null,
    coverage: { from: rows[0]?.time ?? null, to: rows.at(-1)?.time ?? null, bars: rows.length },
    committedAt: null, optimistic: false, historyComplete: true, dataRevision: input.id }), [input.id, rows, store.seriesKey, version]);
  const persistence = useMemo(() => ({ controlled: true, load: () => definitions.map(item => ({ ...item })), save: () => undefined }), [definitions]);
  const unsupported = definitions.map(indicator => ({ indicator, support: providedBarsIndicatorSupport(indicator) })).filter(item => !item.support.supported);
  const indicators = useProvidedBarsIndicatorRuntime({ bars: rows, chartDataMeta: dataMeta, datasetKey: input.id,
    exchange: series.exchange, marketType: series.marketType, symbol: series.symbol, interval: series.interval,
    persistence, seriesReady: version, sourceOrdinal: cursorMs, sourceScopeKey: input.id,
    visibleThroughSeconds: rows.at(-1)?.time ?? null, candleUpColor: style.upColor, candleDownColor: style.downColor });
  async function jump() {
    const target = parseUtcDateTimeInput(value);
    if (target === null || target < playback.minimumMs || target > playback.maximumMs) { setInvalid(true); return; }
    setInvalid(false); setPlaying(false); await onMove(target);
  }
  return <div className="quick-replay history-study" role="region" aria-label={t("study.title")}
    data-study-id={input.id} data-study-cursor-ms={cursorMs}>
    <header className="quick-replay-banner"><span className="trading-badge" data-tone="warning">{t("study.title")}</span>
      <strong>{series.symbol}</strong><span>{series.interval}</span><time>{formatDateTime(cursorMs)}</time>
      <span className="quick-replay-spacer" /><span role="status">{t(busy ? "study.saving" : "study.saved")}</span>
      <button type="button" className="trading-button" disabled={busy || editor !== null}
        onClick={() => { setPlaying(false); void onMove(cursorMs, false); }}>{t("study.exit")}</button></header>
    <div className="quick-replay-body"><div className="quick-replay-chart">
      {(error || notesError) ? <p className="trading-error" role="alert">{t("study.error")}</p> : null}
      {error ? <button className="trading-button" type="button" onClick={onRetry}>{t("study.retry")}</button> : null}
      <ChartErrorBoundary><SingleChartPanes seriesStore={store} symbol={series.symbol} interval={series.interval}
        loading={false} dataMeta={dataMeta} datasetKey={input.id} upColor={style.upColor} downColor={style.downColor}
        {...(style.chartType === undefined ? {} : { chartType: normalizeMainChartType(style.chartType) })}
        theme={style.theme} customBg={style.customBg} inheritApplicationTheme={style.inheritApplicationTheme ?? true}
        followLatest canLoadMoreLeft={false} canRestoreLatestWindow={false}
        mainOverlayLines={indicators.view.mainOverlayLines} subPanes={indicators.view.subPanes}
        indicatorMarkers={indicators.view.markers} indicatorFills={indicators.view.fills}
        indicatorHlines={indicators.view.hlines} indicatorBgcolors={indicators.view.bgcolors} indicatorBarcolors={indicators.view.barcolors} /></ChartErrorBoundary>
    </div><aside className="quick-replay-side" aria-label={t("study.notes")}>
      <h3>{t("study.fixed")}</h3><p className="trading-help">{t("study.savedAt", { time: formatDateTime(input.capturedAtMs) })}</p>
      <p className="trading-help">{t("study.closedOnly")}</p>{changed && <p role="status">{t("study.changed")}</p>}
      {(unsupported.length > 0 || indicators.view.activeIndicators.some(item => item.error)) && <section aria-label={t("study.indicatorUnavailable")}>
        <h3>{t("study.indicatorUnavailable")}</h3><ul>
          {unsupported.map(({ indicator, support }) => <li key={indicator.id}>{indicator.name ?? indicator.id}: {support.reason}</li>)}
          {indicators.view.activeIndicators.filter(item => item.error).map(indicator => <li key={indicator.id}>{indicator.name ?? indicator.id}: {indicator.error}</li>)}
        </ul>
      </section>}
      <h3>{t("study.notes")}</h3>{!notes.length && <p>{t("study.noNotes")}</p>}
      <ul className="trading-quick-notes">{notes.map(note => <li key={note.id}>
        <time>{t("study.noteMarketTime", { time: formatDateTime(note.marketTimeMs) })}</time>
        <time>{t("study.noteWriteTime", { time: formatDateTime(note.updatedAtMs) })}</time>
        <p>{note.fields.entryBasis}</p><small>{t("study.noteVersions", { count: note.revisionCount })}</small>
        <button className="trading-button" type="button" disabled={busy || editor !== null}
          onClick={() => { setPlaying(false); setEditor({ marketMs: note.marketTimeMs, note }); }}>{t("study.noteEdit")}</button>
      </li>)}</ul>
      <button className="trading-button" type="button" disabled={busy || editor !== null}
        onClick={() => { setPlaying(false); setEditor({ marketMs: cursorMs, note: null }); }}>{t("study.noteNew")}</button>
      {editor && <StudyNoteEditor key={`${input.id}:${editor.note?.id ?? editor.marketMs}`} manager={manager.historyStudy}
        studyId={input.id} marketMs={editor.marketMs} note={editor.note}
        onChanged={() => setRefreshNotes(n => n + 1)} onClose={() => setEditor(null)} />}
    </aside></div>
    <footer className="history-study-controls"><button type="button" className="trading-button" disabled={busy || !!editor || cursorMs <= playback.minimumMs}
      onClick={() => { setPlaying(false); void onMove(playback.stepTarget(-1)); }}>{t("study.previous")}</button>
      <button type="button" className="trading-button" disabled={!!editor || cursorMs >= playback.maximumMs}
        onClick={() => setPlaying(v => !v)}>{t(playing ? "study.pause" : "study.play")}</button>
      <button type="button" className="trading-button" disabled={busy || !!editor || cursorMs >= playback.maximumMs}
        onClick={() => { setPlaying(false); void onMove(playback.stepTarget(1)); }}>{t("study.next")}</button>
      <label>{t("study.cursor")}<input type="datetime-local" step="1" value={value} disabled={!!editor}
        onChange={e => setValue(e.target.value)} /></label>
      <button type="button" className="trading-button" disabled={!!editor} onClick={() => { void jump(); }}>{t("study.seek")}</button>
      {invalid && <span role="alert">{t("study.invalidRange")}</span>}
    </footer>
  </div>;
}
