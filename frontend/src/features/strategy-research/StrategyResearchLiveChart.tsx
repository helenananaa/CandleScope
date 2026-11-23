import { useCallback, useEffect, useMemo, useRef } from "react";
import { useChartSurfaceRuntime } from "../../chart-adapter/useChartSurfaceRuntime.js";
import { useChartSession } from "../chart-session/useChartSession.js";
import type { ChartSession } from "../chart-session/chartSessionTypes.js";
import { useMarketDataRuntime } from "../market-data/useMarketDataRuntime.js";
import { useLiveReferenceMarketChartSource } from "../market-chart-platform/useLiveReferenceMarketChartSource.js";
import { createRunResultSource } from "../market-chart-platform/marketChartSourceRuntime.js";
import MarketChartSurface from "../market-chart-platform/MarketChartSurface.js";
import { ChartErrorBoundary } from "../../app/AppProviders.js";
import { useChartSettingsRuntime } from "../settings/chartAppearanceSettings.js";
import type { ChartStrategyResultBundle } from "../backtest/chart-tester/chartStrategyResultCache.js";
import type { LocalAnalysisFocusRequest } from "../local-data/localAnalysisTypes.js";
import { EmptyState, InlineAlert } from "../../components/ui/index.js";
import { t } from "../../i18n/index.js";
import type { StrategyOverlaySource } from "../backtest/runResult/strategyOverlay.js";
import { researchChartAppearance } from "./researchChartAppearance.js";

export default function StrategyResearchLiveChart({ session, result, focusRequest, overlaySource = null, anchorTimeMs = null }: {
  session: ChartSession; result: ChartStrategyResultBundle | null; focusRequest: LocalAnalysisFocusRequest | null;
  /** The research run drawn on this chart (ADR-BACKTEST-015 P1c). */
  overlaySource?: StrategyOverlaySource | null;
  /** Exchange history chosen in the workspace (P5a): before a result, open here instead of following the latest bar. */
  anchorTimeMs?: number | null;
}) {
  const surface = useChartSurfaceRuntime();
  const appearance = useChartSettingsRuntime();
  const priceRef = useRef<number | null>(null);
  const chartSession = useChartSession({ chartSurfaceActions: surface.actions, initialSession: session, controlledSession: session,
    exchangeCatalogEnabled: true, visibleRangeScope: "strategy-research-live" });
  const marketData = useMarketDataRuntime({ session: chartSession, realtimePriceRef: priceRef, enabled: result === null,
    backgroundPrefetchEnabled: false, intervalPrefetchEnabled: false, workspaceId: "strategy-research", windowId: "research-window", schedulerCellId: "research-live" });
  const live = useLiveReferenceMarketChartSource({ sourceId: "research-live", session, datasetKey: chartSession.view.datasetKey, marketData, paused: result !== null });
  const frozen = useMemo(() => result ? createRunResultSource({ sourceId: `research-result:${result.run.run_id}`, session,
    runId: result.run.run_id, configHash: result.run.config_hash, reportHash: result.reportHash, chartHash: result.chartHash, bars: result.chart.bars.map((bar) => ({ ...bar })) }) : null, [result, session]);
  useEffect(() => () => frozen?.dispose(), [frozen]);
  useEffect(() => { if (focusRequest) surface.ref.current?.setLinkedVisibleTimeAnchor(focusRequest.time); }, [focusRequest, surface.ref]);
  const source = frozen ?? live;
  const seriesStore = source.marketData.view.seriesStore;
  const chartReady = source.marketData.status.activeChartReady && !!seriesStore;
  const anchored = useRef<number | null>(null);
  const seek = marketData.actions.seekToTime;
  const { centerVisibleTime, subscribeLinkedViewportReady } = surface.actions;
  useEffect(() => {
    if (anchorTimeMs === null || result !== null || !chartReady || !seek || anchored.current === anchorTimeMs) return undefined;
    anchored.current = anchorTimeMs;
    let cancelled = false;
    let unsubscribe = () => {};
    void seek(anchorTimeMs).then((located) => {
      if (cancelled || located.status !== "located") return;
      // The surface centers a time only once it has painted the loaded window.
      const position = () => { if (centerVisibleTime(located.actualTimeMs / 1_000)) unsubscribe(); };
      unsubscribe = subscribeLinkedViewportReady(position);
      position();
    });
    return () => { cancelled = true; unsubscribe(); };
  }, [anchorTimeMs, centerVisibleTime, chartReady, result, seek, subscribeLinkedViewportReady]);
  useEffect(() => {
    overlaySource?.setSeries(seriesStore ?? null);
    return () => overlaySource?.setSeries(null);
  }, [overlaySource, seriesStore]);
  const onVisibleRangeChange = source.marketData.actions.onVisibleRangeChange;
  const handleVisibleRange = useCallback((range: Parameters<typeof onVisibleRangeChange>[0]) => {
    onVisibleRangeChange(range);
    overlaySource?.setVisibleRange(range as Parameters<StrategyOverlaySource["setVisibleRange"]>[0]);
  }, [onVisibleRangeChange, overlaySource]);
  const markerSources = useMemo(() => [overlaySource?.markers], [overlaySource]);
  if (!source.marketData.status.activeChartReady || !source.marketData.view.seriesStore) {
    return <EmptyState className="local-chart-empty" compact role={source.marketData.view.error ? "alert" : "status"}
      tone={source.marketData.view.error ? "danger" : "neutral"}
      title={source.marketData.view.error ? String(source.marketData.view.error) : t("research.loading")} />;
  }
  return <div className="strategy-research-imported-chart" role="region" data-testid="strategy-research-live-chart"
    data-source-mode={source.mode} aria-label={t(frozen ? "research.source.frozen" : "research.source.currentChart")}>
    {source.marketData.view.error ? <InlineAlert tone="danger">{String(source.marketData.view.error)}</InlineAlert> : <MarketChartSurface
      source={source} markerSources={markerSources} chartLayerSource={overlaySource?.layer ?? null} errorBoundary={ChartErrorBoundary}
      chartProps={{ ref: surface.ref, symbol: source.session.symbol, interval: source.session.interval, datasetKey: source.datasetKey,
        ...researchChartAppearance(appearance.settings, appearance.resolvedTheme),
        followLatest: result === null && anchorTimeMs === null, onVisibleRangeChange: handleVisibleRange }} />}
  </div>;
}
