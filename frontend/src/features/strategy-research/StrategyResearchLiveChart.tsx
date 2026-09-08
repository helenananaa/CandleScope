import { useEffect, useMemo, useRef } from "react";
import { useChartSurfaceRuntime } from "../../chart-adapter/useChartSurfaceRuntime.js";
import { useChartSession } from "../chart-session/useChartSession.js";
import type { ChartSession } from "../chart-session/chartSessionTypes.js";
import { useMarketDataRuntime } from "../market-data/useMarketDataRuntime.js";
import { useLiveReferenceMarketChartSource } from "../market-chart-platform/useLiveReferenceMarketChartSource.js";
import { createRunResultSource } from "../market-chart-platform/marketChartSourceRuntime.js";
import SingleChartPanes from "../../components/SingleChartPanes.js";
import { useChartSettingsRuntime } from "../settings/chartAppearanceSettings.js";
import type { ChartStrategyResultBundle } from "../backtest/chart-tester/chartStrategyResultCache.js";
import type { LocalAnalysisFocusRequest } from "../local-data/localAnalysisTypes.js";
import { t } from "../../i18n/index.js";

export default function StrategyResearchLiveChart({ session, result, focusRequest }: {
  session: ChartSession; result: ChartStrategyResultBundle | null; focusRequest: LocalAnalysisFocusRequest | null;
}) {
  const surface = useChartSurfaceRuntime();
  const appearance = useChartSettingsRuntime();
  const priceRef = useRef<number | null>(null);
  const chartSession = useChartSession({ chartSurfaceActions: surface.actions, initialSession: session, controlledSession: session,
    exchangeCatalogEnabled: true, visibleRangeScope: "strategy-research-live" });
  const marketData = useMarketDataRuntime({ session: chartSession, realtimePriceRef: priceRef, enabled: result === null,
    backgroundPrefetchEnabled: false, intervalPrefetchEnabled: false, workspaceId: "strategy-research", windowId: "research-window", schedulerCellId: "research-live" });
  const live = useLiveReferenceMarketChartSource({ sourceId: "research-live", session, datasetKey: chartSession.view.datasetKey, marketData, paused: result !== null });
  const frozen = useMemo(() => result ? createRunResultSource({ sourceId: `research-result:${result.run.run_id}`, session: { ...session, symbol: result.chart.symbol, interval: result.chart.interval },
    runId: result.run.run_id, configHash: result.run.config_hash, reportHash: result.reportHash, chartHash: result.chartHash, bars: result.chart.bars.map((bar) => ({ ...bar })) }) : null, [result, session]);
  useEffect(() => () => frozen?.dispose(), [frozen]);
  useEffect(() => { if (focusRequest) surface.ref.current?.setLinkedVisibleTimeAnchor(focusRequest.time); }, [focusRequest, surface.ref]);
  const source = frozen ?? live;
  if (!source.marketData.status.activeChartReady || !source.marketData.view.seriesStore) {
    return <div className="local-chart-empty" role="status">{source.marketData.view.error ? String(source.marketData.view.error) : t("research.loading")}</div>;
  }
  return <div className="strategy-research-imported-chart">
    {source.marketData.view.error ? <p role="alert">{String(source.marketData.view.error)}</p> : <SingleChartPanes ref={surface.ref}
      symbol={source.session.symbol} interval={source.session.interval} datasetKey={source.datasetKey}
      seriesStore={source.marketData.view.seriesStore} loading={source.marketData.view.loading} dataMeta={source.marketData.view.meta}
      onNeedMoreLeft={source.marketData.actions.loadMoreLeft} onVisibleRangeChange={source.marketData.actions.onVisibleRangeChange}
      onCrosshairMove={source.marketData.actions.onCrosshairMove}
      upColor={appearance.settings.upColor} downColor={appearance.settings.downColor} chartType={appearance.settings.chartType}
      theme={appearance.resolvedTheme} customBg={appearance.settings.customBg} followLatest={result === null}
      canLoadMoreLeft={source.marketData.status.canLoadMoreLeft} />}
  </div>;
}
