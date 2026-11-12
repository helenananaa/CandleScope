import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { ChartErrorBoundary } from "../../app/AppProviders.js";
import { createPriceLineSource } from "../../chart-adapter/externalPriceLineSource.js";
import { useChartSurfaceRuntime } from "../../chart-adapter/useChartSurfaceRuntime.js";
import SingleChartPanes from "../../components/SingleChartPanes.js";
import { chartIndicatorSelection } from "../indicators/chartIndicatorInput.js";
import { capturedSyntheticSource } from "../market-data/synthetic/capturedSyntheticSource.js";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { normalizeMainChartType } from "../../shared/mainChartTypes.js";
import { parseIntervalSeconds } from "../../utils/intervals.js";
import { normalizeChartAccountOverlay, type ChartAccountOverlaySettings } from "../chart-workspace/chartAccountOverlaySettings.js";
import type { IndicatorDefinition } from "../indicators/indicatorTypes.js";
import { useProvidedBarsIndicatorRuntime } from "../indicators/useProvidedBarsIndicatorRuntime.js";
import type { ChartDataCommitMeta } from "../market-data/useChartDataRuntime.js";
import { useMarketDataWorkspaceResources } from "../market-data/marketDataWorkspaceContext.js";
import { SeriesWindowStore } from "../market-data/window/seriesWindowStore.js";
import { createManagedReplayHistoryReader, loadReplayBars, ReplayHistoryPendingError } from "./quickReplayData.js";
import {
  STANDARD_STEPS,
  initialCursor,
  nextEventCursor,
  journalAtCursor,
  positionAt,
  previousEventCursor,
  protectionOrdersAt,
  replayEvents,
  replayWindow,
  visibleBars,
  type ReplayBar,
} from "./quickReplayModel.js";
import { filterJournalNoteMarkers } from "./journalNoteMarkers.js";
import { createReplayMarkerSource } from "./replayMarkerSource.js";
import { tradingApi } from "./tradingApi.js";
import { formatAmount, formatDateTime, formatPrice, formatQty, formatSigned, pnlTone, tokenColor } from "./tradingFormat.js";
import type { QuickReplayRequest, TradeDetail } from "./tradingTypes.js";
import { tradingErrorMessage } from "./useTradingAccountsRuntime.js";
import "./tradingAccounts.css";

export interface QuickReplayChartStyle {
  upColor: string;
  downColor: string;
  chartType?: string;
  theme: string;
  inheritApplicationTheme?: boolean;
  customBg: string;
}

const PLAY_DELAY_MS = [700, 250] as const;
const SETUP_BARS = 20;

function stepSeconds(step: string, fallback: number): number {
  return parseIntervalSeconds(step) ?? fallback;
}

export default function QuickReplayOverlay({
  request,
  style,
  indicatorDefinitions,
  accountOverlay,
  active = true,
  savedCursorSec,
  savedStep,
  onProgress,
  onCursorChange,
  onExit,
}: {
  request: QuickReplayRequest;
  style: QuickReplayChartStyle;
  indicatorDefinitions: readonly IndicatorDefinition[];
  accountOverlay?: ChartAccountOverlaySettings | undefined;
  active?: boolean;
  savedCursorSec?: number | undefined;
  savedStep?: string | undefined;
  onProgress?: (cursorSec: number, step: string) => void;
  onCursorChange?: (cursorSec: number) => void;
  onExit(): void;
}) {
  const locale = useLocale();
  const overlay = useMemo(() => normalizeChartAccountOverlay(accountOverlay), [accountOverlay]);
  const dataManager = useMarketDataWorkspaceResources()?.dataManager ?? null;
  const historyReader = useMemo(() => createManagedReplayHistoryReader(dataManager), [dataManager]);
  const { trade } = request;
  const api = request.api ?? tradingApi;
  const intervalSec = parseIntervalSeconds(request.interval) ?? 900;
  const window_ = useMemo(() => replayWindow(trade, intervalSec, Date.now()), [intervalSec, trade]);
  const [chartBars, setChartBars] = useState<ReplayBar[]>([]);
  const [detail, setDetail] = useState<TradeDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [loadFailed, setLoadFailed] = useState(false);
  const [truncated, setTruncated] = useState(false);
  const [step, setStep] = useState(() => savedStep && stepSeconds(savedStep, intervalSec) <= intervalSec ? savedStep : request.interval);
  const [localCursor, setLocalCursor] = useState(() => savedCursorSec ?? initialCursor(trade, intervalSec));
  const desiredCursor = onCursorChange ? savedCursorSec ?? localCursor : localCursor;
  useEffect(() => { onProgress?.(desiredCursor, step); }, [desiredCursor, onProgress, step]);
  const [playing, setPlaying] = useState<0 | 1 | 2>(0);
  const authoredCursor = useRef<number | null>(null);
  const previousCursor = useRef(desiredCursor);
  useEffect(() => {
    if (previousCursor.current === desiredCursor) return;
    previousCursor.current = desiredCursor;
    if (onCursorChange && authoredCursor.current !== desiredCursor) setPlaying(0);
    authoredCursor.current = null;
  }, [desiredCursor, onCursorChange]);
  const [showOutcome, setShowOutcome] = useState(false);
  const stepSec = Math.min(stepSeconds(step, intervalSec), intervalSec);
  const chartSurface = useChartSurfaceRuntime();
  const instrument = useMemo(() => ({
    exchange: trade.exchange,
    marketType: trade.marketType,
    symbol: trade.symbol,
  }), [trade.exchange, trade.marketType, trade.symbol]);

  const fineRequest = useMemo(() => ({
    reader: historyReader,
    input: { ...instrument, interval: step },
    startSec: Math.floor(trade.openedAtMs / 1000) - intervalSec * 4,
    endSec: window_.endSec,
    reload,
  }), [historyReader, instrument, intervalSec, reload, step, trade.openedAtMs, window_.endSec]);
  const [fineLoaded, setFineLoaded] = useState<{ request: typeof fineRequest; bars: ReplayBar[] } | null>(null);
  // Hide an old period in the same render that changes the request. Clearing
  // it only in an effect would still expose its final OHLC at the new step's
  // earlier close time, before the replacement history has arrived.
  const fineBars = stepSec < intervalSec && fineLoaded?.request === fineRequest ? fineLoaded.bars : null;

  // ── data ──────────────────────────────────────────────────────
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setPlaying(0);
    setChartBars([]);
    setLoadFailed(false);
    setError(null);
    loadReplayBars({ ...instrument, interval: request.interval }, window_.startSec, window_.endSec, controller.signal, historyReader)
      .then((result) => {
        if (controller.signal.aborted) return;
        setChartBars(result.bars);
        setTruncated(result.truncated);
      })
      .catch((cause) => {
        if (!controller.signal.aborted) {
          setLoadFailed(true);
          setError(cause instanceof ReplayHistoryPendingError ? t("trading.replay.pending") : tradingErrorMessage(cause));
        }
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    setDetail(null);
    api.trade(request.accountId, trade.id, controller.signal)
      .then(result => { if (!controller.signal.aborted) setDetail(result); })
      .catch(() => { if (!controller.signal.aborted) setDetail(null); });
    return () => controller.abort();
  }, [api, historyReader, instrument, reload, request.accountId, request.interval, trade.id, window_.endSec, window_.startSec]);

  useEffect(() => {
    if (stepSec >= intervalSec) {
      return undefined;
    }
    const controller = new AbortController();
    // Finer candles only for the holding period, where partial candles matter.
    loadReplayBars(fineRequest.input, fineRequest.startSec, fineRequest.endSec, controller.signal, fineRequest.reader)
      .then((result) => { if (!controller.signal.aborted) setFineLoaded({ request: fineRequest, bars: result.bars }); })
      .catch(() => { if (!controller.signal.aborted) setFineLoaded(null); });
    return () => controller.abort();
  }, [fineRequest, intervalSec, stepSec]);

  const minCursor = (chartBars[0]?.time ?? window_.startSec) + intervalSec * 30;
  // The range API returns closed candles only, so a trade inside the forming
  // chart candle is reachable through the finer candles alone.
  const lastChartEnd = chartBars.length > 0 ? chartBars.at(-1)!.time + intervalSec : window_.startSec;
  const lastFineEnd = fineBars && fineBars.length > 0 ? fineBars.at(-1)!.time + stepSec : 0;
  const maxCursor = Math.max(lastChartEnd, lastFineEnd);
  // An incoming absolute time can exceed this chart's own loaded input.
  // Do not reveal notes past its frontier or advance a cut before its first bar.
  const cursor = chartBars.length > 0 && onCursorChange ? Math.min(desiredCursor, maxCursor) : desiredCursor;
  const timeOutsideHistory = chartBars.length > 0 && (desiredCursor > maxCursor || desiredCursor < chartBars[0]!.time);
  const entryCandleOpen = !loading && chartBars.length > 0
    && initialCursor(trade, intervalSec) + intervalSec > lastChartEnd;
  const autoStepRef = useRef(savedStep !== undefined);
  useEffect(() => {
    if (autoStepRef.current || !entryCandleOpen || intervalSec <= 60) return;
    autoStepRef.current = true;
    setStep("1m");
  }, [entryCandleOpen, intervalSec]);
  const clamp = useCallback(
    (value: number) => Math.max(minCursor, Math.min(maxCursor, value)),
    [maxCursor, minCursor],
  );

  // ── the cut: only bars before the cursor reach the chart ─────
  const store = useMemo(() => new SeriesWindowStore({
    maxBars: 40_000,
    intervalSeconds: intervalSec,
    seriesKey: `quick-replay:${trade.id}:${request.interval}`,
  }), [intervalSec, request.interval, trade.id]);
  const shown = useMemo(
    () => visibleBars(chartBars, fineBars, cursor, intervalSec, stepSec),
    [chartBars, cursor, fineBars, intervalSec, stepSec],
  );
  useEffect(() => {
    store.replace(shown.map((bar) => ({ ...bar, is_closed: true })), { source: "quick-replay" });
  }, [shown, store]);
  const subscribe = useCallback((listener: () => void) => store.subscribe(listener), [store]);
  const getVersion = useCallback(() => Number(store.version), [store]);
  const version = useSyncExternalStore(subscribe, getVersion, getVersion);
  const snapshot = useMemo(() => { void version; return store.snapshot(); }, [store, version]);
  const lastVisible = shown.at(-1)?.time ?? null;
  const dataMeta = useMemo<ChartDataCommitMeta>(() => {
    const description = store.describe();
    return {
      version,
      status: loading ? "loading" : "ready",
      source: "quick-replay",
      seriesKey: store.seriesKey,
      bars: description.bars,
      firstTime: description.firstTime,
      lastTime: description.lastTime,
      coverage: {
        from: description.coverage.firstTime,
        to: description.coverage.lastTime,
        bars: description.coverage.bars,
      },
      committedAt: null,
      optimistic: false,
      historyComplete: true,
      dataRevision: store.seriesKey,
    };
  }, [loading, store, version]);

  // Indicators run on exactly the bars shown; rewinding resets their state.
  const persistence = useMemo(() => ({
    controlled: true,
    load: () => indicatorDefinitions.map((item) => ({ ...item })),
    save: () => undefined,
  }), [indicatorDefinitions]);
  const indicators = useProvidedBarsIndicatorRuntime({
    chart: chartIndicatorSelection(capturedSyntheticSource({ ...instrument, interval: request.interval }, store.seriesKey, `quick:${request.accountId}:${trade.id}`, cursor * 1000), store, { chartType: normalizeMainChartType(style.chartType) }),
    bars: snapshot,
    candleUpColor: style.upColor,
    candleDownColor: style.downColor,
    chartDataMeta: dataMeta,
    datasetKey: `quick-replay:${trade.exchange}:${trade.marketType}:${trade.symbol}:${request.interval}`,
    exchange: trade.exchange,
    interval: request.interval,
    marketType: trade.marketType,
    persistence,
    seriesReady: version,
    sourceOrdinal: cursor,
    sourceScopeKey: `${trade.id}:${request.interval}:${step}`,
    symbol: trade.symbol,
    visibleThroughSeconds: lastVisible,
  });

  // ── markers and position at the cursor ───────────────────────
  const markerSource = useMemo(() => createReplayMarkerSource({
    up: style.upColor,
    down: style.downColor,
    note: tokenColor("--accent-purple", "violet"),
  }), [style.downColor, style.upColor]);
  const priceLineSource = useMemo(() => createPriceLineSource(), []);
  const entries = useMemo(() => detail?.entries.filter(entry => entry.accountId === request.accountId) ?? [], [detail, request.accountId]);
  const { notes, reviewNotes } = useMemo(() => journalAtCursor(entries, cursor), [cursor, entries]);
  useLayoutEffect(() => {
    markerSource.update({
      legs: overlay.trades ? trade.legs : [],
      notes: overlay.notes ? filterJournalNoteMarkers([...notes, ...reviewNotes], overlay, cursor * 1000) : [],
      cursorSec: cursor,
      intervalSec,
      lastVisibleSec: lastVisible,
      labels: { buy: t("trading.replay.buy"), sell: t("trading.replay.sell"), note: t("trading.replay.noteMarker"), reviewNote: t("trading.journal.reviewNote") },
    });
  }, [cursor, notes, reviewNotes, intervalSec, lastVisible, locale, markerSource, overlay, trade.legs]);

  const position = useMemo(() => {
    const atCursor = positionAt(trade, shown, cursor, intervalSec);
    if (!fineBars || stepSec >= intervalSec) return atCursor;
    // Finer candles keep the pre-entry part of the entry candle out of MFE/MAE.
    const fineClosed = fineBars.filter((item) => item.time + stepSec <= cursor);
    const fine = positionAt(trade, fineClosed, cursor, stepSec);
    return { ...atCursor, mfe: fine.mfe, mae: fine.mae };
  }, [cursor, fineBars, intervalSec, shown, stepSec, trade]);
  const entryLineColor = tokenColor("--accent-blue", "royalblue");
  const stopLineColor = tokenColor("--color-danger", "crimson");
  const targetLineColor = tokenColor("--color-success", "seagreen");
  const protectionOrders = detail?.id === trade.id && detail.accountId === request.accountId
    ? detail.protectionOrders
    : undefined;
  useLayoutEffect(() => {
    const price = position.avgEntry;
    if (!overlay.positions || lastVisible === null || price === null || !Number.isFinite(price) || price <= 0) {
      priceLineSource.setLines([]);
      return;
    }
    // Only committed fills before the cursor establish an open position.
    priceLineSource.setLines([{
      id: `quick-replay:entry:${trade.id}`,
      price,
      color: entryLineColor,
      title: t(trade.direction === "long" ? "trading.chart.long" : "trading.chart.short", { qty: formatQty(position.qty) }),
      style: "solid",
      width: 2,
    }, ...protectionOrdersAt(protectionOrders ?? [], cursor).flatMap(order => {
      const level = Number(order.price);
      if (!Number.isFinite(level) || level <= 0) return [];
      return [{
        id: `quick-replay:order:${order.id}`,
        price: level,
        color: order.kind === "stopLoss" ? stopLineColor : targetLineColor,
        title: t(order.kind === "stopLoss" ? "trading.chart.stopLoss" : "trading.chart.takeProfit", { qty: formatQty(order.qty) }),
        style: "dashed" as const,
        width: 1 as const,
      }];
    })]);
  }, [
    cursor, entryLineColor, lastVisible, locale, overlay.positions, position.avgEntry, position.qty,
    priceLineSource, protectionOrders, stopLineColor, targetLineColor, trade.direction, trade.id,
  ]);
  const plan = detail?.plan && detail.plan.lockedAtMs < cursor * 1000 ? detail.plan : null;
  const risk = plan?.riskUsdt ? Number(plan.riskUsdt) : null;
  const toR = (value: number | null) => (value === null || !risk ? null : (value / risk).toFixed(2));
  const events = useMemo(() => replayEvents(trade, entries), [entries, trade]);
  const exitReached = trade.closedAtMs !== null && cursor * 1000 > trade.closedAtMs;

  const planLines = useMemo(() => {
    if (!plan) return [];
    const lines = [
      { id: "quick-replay-entry", price: plan.entryPrice, title: t("trading.tpl.entryPrice"), color: tokenColor("--text-secondary", "gray") },
      { id: "quick-replay-stop", price: plan.stopPrice, title: t("trading.tpl.stopPrice"), color: style.downColor },
      { id: "quick-replay-target", price: plan.targetPrice, title: t("trading.tpl.targetPrice"), color: style.upColor },
    ];
    return lines
      .filter((line) => line.price !== null && Number.isFinite(Number(line.price)))
      .map((line) => ({ ...line, price: Number(line.price), linestyle: 2, linewidth: 1 }));
  }, [plan, style.downColor, style.upColor]);
  const hlines = useMemo(() => [...indicators.view.hlines, ...planLines], [indicators.view.hlines, planLines]);

  // ── controls ─────────────────────────────────────────────────
  const canNavigate = !loading && !loadFailed && chartBars.length > 0;
  const seek = useCallback((next: number) => {
    if (next === desiredCursor) return;
    if (onCursorChange) {
      authoredCursor.current = next;
      onCursorChange(next);
    } else setLocalCursor(next);
  }, [desiredCursor, onCursorChange]);
  const move = useCallback((delta: number) => {
    if (canNavigate && (delta >= 0 || cursor > minCursor)) seek(clamp(cursor + delta));
  }, [canNavigate, clamp, cursor, minCursor, seek]);
  const jumpNext = useCallback(() => {
    if (!canNavigate) return;
    const next = nextEventCursor(events, cursor, stepSec);
    if (next !== null) seek(clamp(next));
  }, [canNavigate, clamp, cursor, events, seek, stepSec]);
  const jumpPrevious = useCallback(() => {
    if (!canNavigate) return;
    const previous = previousEventCursor(events, cursor, stepSec);
    seek(clamp(previous ?? initialCursor(trade, intervalSec)));
  }, [canNavigate, clamp, cursor, events, intervalSec, seek, stepSec, trade]);
  useEffect(() => {
    if (playing === 0 || !canNavigate) return undefined;
    const timer = window.setTimeout(() => {
      const next = clamp(cursor + stepSec);
      if (next === cursor) setPlaying(0);
      else seek(next);
    }, PLAY_DELAY_MS[playing - 1]);
    return () => window.clearTimeout(timer);
  }, [canNavigate, clamp, cursor, playing, seek, stepSec]);

  useEffect(() => {
    if (!active) return;
    const onKey = (event: KeyboardEvent) => {
      const target = event.target instanceof HTMLElement ? event.target : null;
      if (event.defaultPrevented || target?.closest('input, textarea, select, dialog, [role="dialog"]') || target?.isContentEditable) return;
      if (event.key === "Escape") { event.preventDefault(); onExit(); }
      else if (event.key === "ArrowRight" && event.shiftKey) { event.preventDefault(); jumpNext(); }
      else if (event.key === "ArrowLeft" && event.shiftKey) { event.preventDefault(); jumpPrevious(); }
      else if (event.key === "ArrowRight") { event.preventDefault(); move(stepSec); }
      else if (event.key === "ArrowLeft") { event.preventDefault(); move(-stepSec); }
      else if (canNavigate && event.key === " ") { event.preventDefault(); setPlaying((value) => (value === 0 ? 1 : 0)); }
      else return;
      // The chart canvas handles arrow keys itself; replay owns them while open.
      event.stopPropagation();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [active, canNavigate, jumpNext, jumpPrevious, move, onExit, stepSec]);

  const stepOptions = useMemo(() => {
    const span = window_.endSec - Math.floor(trade.openedAtMs / 1000);
    const finer = STANDARD_STEPS.filter((item) => {
      const seconds = parseIntervalSeconds(item);
      return seconds !== null && seconds < intervalSec && span / seconds <= 25_000;
    });
    return [request.interval, ...finer.filter((item) => item !== request.interval)];
  }, [intervalSec, request.interval, trade.openedAtMs, window_.endSec]);

  const [captureComment, setCaptureComment] = useState("");
  const captureAnchor = useRef<number | null>(null);
  const saveReviewNote = async () => {
    const text = captureComment.trim();
    if (!text) return;
    try {
      await api.createEntry(request.accountId, {
        ...instrument,
        kind: "quick",
        body: text,
        tradeId: trade.id,
        // Just inside the cut so the note is visible where it was written.
        marketTimeMs: (captureAnchor.current ?? cursor) * 1000 - 1,
      });
      setCaptureComment("");
      captureAnchor.current = null;
      setDetail(await api.trade(request.accountId, trade.id));
    } catch (cause) {
      setError(tradingErrorMessage(cause));
    }
  };

  return (
    <div className="quick-replay" data-replay-cursor-sec={cursor} data-replay-account={request.accountId} role="region" aria-label={t("trading.replay.title")}>
      <header className="quick-replay-banner">
        <span className="trading-badge" data-tone="warning">{t("trading.replay.badge")}</span>
        <strong>{trade.symbol}</strong>
        <span>{request.interval}</span>
        <span className="quick-replay-cursor">{t("trading.replay.cursor", { time: formatDateTime(cursor * 1000) })}</span>
        {timeOutsideHistory && <span className="trading-help" role="status">{t("trading.replay.timeOutsideHistory")}</span>}
        <span className="quick-replay-spacer" />
        <span className="trading-help">{t("trading.replay.reconstructed")}</span>
        <button type="button" className="trading-button" onClick={onExit}>{t("trading.replay.exit")}</button>
      </header>
      <div className="quick-replay-body">
        <div className="quick-replay-chart">
          {error && <p className="trading-error" role="alert">{error}</p>}
          {loadFailed && <button type="button" className="trading-button" onClick={() => setReload((value) => value + 1)}>{t("trading.replay.retry")}</button>}
          {!loading && chartBars.length === 0 && !error && <p className="trading-empty">{t("trading.replay.noData")}</p>}
          <ChartErrorBoundary>
            <SingleChartPanes
              ref={chartSurface.ref}
              drawingsEnabled={false}
              seriesStore={store}
              backendSyntheticSource={capturedSyntheticSource({ ...instrument, interval: request.interval },
                store.seriesKey, `quick:${request.accountId}:${trade.id}`, cursor * 1000)}
              symbol={trade.symbol}
              interval={request.interval}
              loading={loading}
              dataMeta={dataMeta}
              datasetKey={`quick-replay:${trade.id}:${request.interval}`}
              upColor={style.upColor}
              downColor={style.downColor}
              {...(style.chartType === undefined ? {} : { chartType: normalizeMainChartType(style.chartType) })}
              theme={style.theme} inheritApplicationTheme={style.inheritApplicationTheme ?? true}
              customBg={style.customBg}
              followLatest
              canLoadMoreLeft={false}
              canRestoreLatestWindow={false}
              externalMarkerSource={markerSource}
              externalPriceLineSource={priceLineSource}
              mainOverlayLines={indicators.view.mainOverlayLines}
              subPanes={indicators.view.subPanes}
              indicatorMarkers={indicators.view.markers}
              indicatorFills={indicators.view.fills}
              indicatorHlines={hlines}
              indicatorBgcolors={indicators.view.bgcolors}
              indicatorBarcolors={indicators.view.barcolors}
            />
          </ChartErrorBoundary>
        </div>
        <aside className="quick-replay-side" aria-label={t("trading.replay.position")}>
          <h3>{t("trading.replay.position")}</h3>
          {trade.readonlySource && <p className="trading-help">{t("account.review.source", { instrument: trade.readonlySource.instrument, currency: trade.readonlySource.currency })}</p>}
          <dl className="trading-kv">
            <dt>{t("trading.replay.size")}</dt>
            <dd>{position.qty > 0
              ? `${t(trade.direction === "long" ? "trading.long" : "trading.short")} ${formatQty(position.qty)}`
              : t("trading.replay.flat")}</dd>
            <dt>{t("trading.replay.avgEntry")}</dt>
            <dd>{formatPrice(position.avgEntry)}</dd>
            <dt>{t("trading.replay.unrealized")}</dt>
            <dd data-tone={pnlTone(position.unrealized)}>
              {formatSigned(position.unrealized)}{toR(position.unrealized) ? ` · ${toR(position.unrealized)}R` : ""}
            </dd>
            {trade.readonlySource && <><dt>{t("account.review.funding")}</dt><dd>{formatSigned(position.funding)} USDT</dd></>}
            <dt>{t("trading.replay.realized")}</dt>
            <dd data-tone={pnlTone(position.realized - position.fees + position.funding)}>{formatSigned(position.realized - position.fees + position.funding)}</dd>
            <dt>{t("trading.replay.mfeMae")}</dt>
            <dd>{formatPrice(position.mfe)} / {formatPrice(position.mae)}</dd>
          </dl>
          {plan && (
            <p className="trading-help">
              {t("trading.journal.locked", {
                entry: formatPrice(plan.entryPrice), stop: formatPrice(plan.stopPrice),
                target: formatPrice(plan.targetPrice), risk: formatAmount(plan.riskUsdt),
              })}
            </p>
          )}
          {(showOutcome || exitReached) && trade.status === "closed" && (
            <p className="quick-replay-outcome" data-tone={pnlTone(trade.netPnl)}>
              {t("trading.replay.outcome", { pnl: formatSigned(trade.netPnl) })}
            </p>
          )}
          {!exitReached && trade.status === "closed" && (
            <label className="trading-check">
              <input type="checkbox" checked={showOutcome} onChange={(event) => setShowOutcome(event.target.checked)} />
              <span>{t("trading.replay.showOutcome")}</span>
            </label>
          )}
          <h3>{t("trading.replay.notesSoFar")}</h3>
          <ul className="trading-quick-notes">
            {notes.length === 0 && <li className="trading-empty-line">{t("trading.replay.noNotes")}</li>}
            {notes.map((entry) => (
              <li key={entry.id}>
                <time>{formatDateTime(entry.marketTimeMs ?? entry.createdAtMs)}</time>
                <p>{entry.historyUnavailable ? t("trading.replay.noteHistoryUnavailable")
                  : entry.kind === "quick" ? entry.body : (entry.fields.entryBasis ?? t("trading.journal.plan"))}</p>
              </li>
            ))}
          </ul>
          {reviewNotes.length > 0 && <>
            <h3>{t("trading.journal.reviewNote")}</h3>
            <ul className="trading-quick-notes">
              {reviewNotes.map((entry) => <li key={entry.id}>
                <time>{t("trading.replay.reviewWrittenAt", { time: formatDateTime(entry.updatedAtMs) })}</time>
                <p>{entry.kind === "quick" ? entry.body : entry.fields.entryBasis}</p>
              </li>)}
            </ul>
          </>}
          <input
            className="trading-quick-input"
            value={captureComment}
            placeholder={t("trading.replay.notePlaceholder")}
            onChange={(event) => {
              const text = event.target.value;
              captureAnchor.current = text.trim() ? captureAnchor.current ?? cursor : null;
              setCaptureComment(text);
            }}
            onKeyDown={(event) => { if (event.key === "Enter") void saveReviewNote(); }}
          />
          <p className="trading-help">{t("trading.replay.drawingsHidden")}</p>
          {truncated && <p className="trading-help">{t("trading.replay.truncated")}</p>}
        </aside>
      </div>
      <footer className="quick-replay-controls" role="toolbar" aria-label={t("trading.replay.controls")}>
        <button disabled={!canNavigate} type="button" className="trading-button" onClick={() => move(-SETUP_BARS * intervalSec)} title={t("trading.replay.setupHint")}>
          {t("trading.replay.setup")}
        </button>
        <button disabled={!canNavigate} type="button" className="trading-button" onClick={jumpPrevious} title={t("trading.replay.prevEventHint")}>
          {t("trading.replay.prevEvent")}
        </button>
        <button disabled={!canNavigate} type="button" className="trading-button" onClick={() => move(-stepSec)} aria-label={t("trading.replay.back")}>◀</button>
        <button
          disabled={!canNavigate}
          type="button"
          className="trading-button"
          data-variant="primary"
          onClick={() => setPlaying((value) => (value === 0 ? 1 : 0))}
          aria-label={playing ? t("trading.replay.pause") : t("trading.replay.play")}
        >
          {playing ? "❚❚" : "▶"}
        </button>
        <button
          disabled={!canNavigate}
          type="button"
          className="trading-button"
          data-active={playing === 2}
          onClick={() => setPlaying((value) => (value === 2 ? 1 : 2))}
          aria-label={t("trading.replay.fast")}
        >
          4×
        </button>
        <button disabled={!canNavigate} type="button" className="trading-button" onClick={() => move(stepSec)} aria-label={t("trading.replay.forward")}>▶|</button>
        <button disabled={!canNavigate} type="button" className="trading-button" onClick={jumpNext} title={t("trading.replay.nextEventHint")}>
          {t("trading.replay.nextEvent")}
        </button>
        <label className="quick-replay-step">
          <span>{t("trading.replay.stepBy")}</span>
          <select value={step} onChange={(event) => setStep(event.target.value)}>
            {stepOptions.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        <span className="trading-help">{t("trading.replay.keys")}</span>
      </footer>
    </div>
  );
}
