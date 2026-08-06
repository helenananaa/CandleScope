import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import type { ReactNode, RefObject } from "react";
import SingleChartPanes from "../../components/SingleChartPanes.js";
import type { MainSeriesCrosshairValue } from "../../chart-adapter/chartAdapterTypes.js";
import { useChartSurfaceRuntime } from "../../chart-adapter/useChartSurfaceRuntime.js";
import { ChartErrorBoundary } from "../../app/AppProviders.js";
import { drawingToolWhenInteractionReady } from "../../app/drawingInteractionReadiness.js";
import MarketPageFrame from "../../app/MarketPageFrame.js";
import MarketStatusBar from "../../app/MarketStatusBar.js";
import MarketTopBarFrame from "../../app/MarketTopBarFrame.js";
import MarketWorkspaceFrame from "../../app/MarketWorkspaceFrame.js";
import DrawingToolbar from "../../components/DrawingToolbar.js";
import ExportPanel from "../export/ExportPanel.js";
import { useExportRuntime } from "../export/useExportRuntime.js";
import {
  loadUserPrefs,
  updateUserPref,
} from "../chart-session/chartSessionModel.js";
import {
  getVisibleRangeForInterval,
  saveVisibleRangeForInterval,
} from "../chart-session/visibleRangeStorage.js";
import {
  fetchLocalIndicatorPresets,
  importLocalCsv,
  listLocalDatasets,
  LocalDataApiError,
} from "./localDataApi.js";
import type { LocalDatasetManifest } from "./localDataTypes.js";
import LocalAnalysisPanel from "./LocalAnalysisPanel.js";
import { createLocalAnalysisMarkerSource } from "./localAnalysisMarkerSource.js";
import {
  EMPTY_LOCAL_ANALYSIS_SNAPSHOT,
  LocalAnalysisEventStore,
} from "./localAnalysisStore.js";
import type {
  LocalAnalysisEvent,
  LocalAnalysisFocusRequest,
} from "./localAnalysisTypes.js";
import {
  buildLocalChartDataMeta,
  useLocalChartRuntime,
} from "./useLocalChartRuntime.js";
import { useLocalIndicatorRuntime } from "./useLocalIndicatorRuntime.js";
import type { IndicatorRuntime } from "../indicators/indicatorRuntimeContract.js";
import type { IndicatorPreset } from "../indicators/indicatorTypes.js";
import IndicatorPanel from "../indicators/IndicatorPanel.js";
import { useDrawingRuntime } from "../drawings/useDrawingRuntime.js";
import type { DrawingRuntime } from "../drawings/useDrawingRuntime.js";
import type { DrawingToolId } from "../drawings/drawingTypes.js";
import SettingsModal from "../settings/SettingsModal.js";
import {
  useChartSettingsRuntime,
} from "../settings/chartAppearanceSettings.js";
import type { ChartSettings } from "../settings/chartAppearanceSettings.js";
import { usePriceScalePrefs } from "../settings/priceScalePrefsRuntime.js";
import {
  createLocalIndicatorCatalog,
  resolveLocalIndicatorSupport,
} from "./localIndicatorCatalog.js";


function formatRows(rows: number): string {
  return new Intl.NumberFormat("zh-CN").format(rows);
}

function formatDate(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString("zh-CN");
}

function errorMessage(reason: unknown): string {
  if (reason instanceof LocalDataApiError && reason.code === "local_profile_not_active") {
    return "后端没有以 LOCAL_OFFLINE 模式启动。请按文档重启后端。";
  }
  return reason instanceof Error ? reason.message : "本地数据操作失败";
}

function LocalImportForm({
  importing,
  onImport,
}: {
  importing: boolean;
  onImport(input: {
    file: File;
    name: string;
    symbol: string;
    interval: string;
    timezone: string;
    timestampUnit: "auto" | "s" | "ms" | "iso";
    volumeRequired: boolean;
  }): Promise<void>;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [symbol, setSymbol] = useState("BTC-USDT");
  const [interval, setInterval] = useState("1m");
  const [timezone, setTimezone] = useState("UTC");
  const [timestampUnit, setTimestampUnit] = useState<"auto" | "s" | "ms" | "iso">("auto");
  const [volumeRequired, setVolumeRequired] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  return (
    <form
      className="local-import-form"
      onSubmit={(event) => {
        event.preventDefault();
        if (file === null) return;
        void onImport({
          file,
          name: name.trim() || file.name.replace(/\.csv$/i, ""),
          symbol,
          interval,
          timezone,
          timestampUnit,
          volumeRequired,
        }).then(() => {
          setFile(null);
          setName("");
          if (fileInputRef.current !== null) fileInputRef.current.value = "";
        }).catch(() => undefined);
      }}
    >
      <header>
        <div>
          <span>IMPORT</span>
          <strong>导入 CSV</strong>
        </div>
        <small>数据只写入本机</small>
      </header>
      <label className="local-file-picker">
        <span>{file?.name ?? "选择 CSV 文件"}</span>
        <input
          ref={fileInputRef}
          type="file"
          accept=".csv,text/csv"
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        />
      </label>
      <label>
        数据集名称
        <input value={name} onChange={(event) => setName(event.target.value)} placeholder="默认使用文件名" />
      </label>
      <div className="local-import-grid">
        <label>
          商品
          <input required value={symbol} onChange={(event) => setSymbol(event.target.value)} />
        </label>
        <label>
          周期
          <input required value={interval} onChange={(event) => setInterval(event.target.value)} placeholder="1m" />
        </label>
        <label>
          时区
          <input required value={timezone} onChange={(event) => setTimezone(event.target.value)} placeholder="UTC" />
        </label>
        <label>
          时间格式
          <select value={timestampUnit} onChange={(event) => setTimestampUnit(event.target.value as typeof timestampUnit)}>
            <option value="auto">自动识别</option>
            <option value="s">Unix 秒</option>
            <option value="ms">Unix 毫秒</option>
            <option value="iso">ISO 时间</option>
          </select>
        </label>
        <label>
          成交量
          <select
            value={volumeRequired ? "required" : "optional"}
            onChange={(event) => setVolumeRequired(event.target.value === "required")}
          >
            <option value="optional">可选，缺失时标记不可用</option>
            <option value="required">必须存在</option>
          </select>
        </label>
      </div>
      <p>必需列：time, open, high, low, close。volume/Volume 可选；缺失时明确标记为不可用，不会填 0。</p>
      <button type="submit" disabled={file === null || importing}>
        {importing ? "正在校验并导入…" : "导入到本地资料库"}
      </button>
    </form>
  );
}

function LocalDatasetRail({
  datasets,
  selectedId,
  importing,
  onSelect,
  onImport,
  analysis,
}: {
  datasets: LocalDatasetManifest[];
  selectedId: string | null;
  importing: boolean;
  onSelect(datasetId: string): void;
  onImport: Parameters<typeof LocalImportForm>[0]["onImport"];
  analysis: ReactNode;
}) {
  return (
    <aside className="local-data-rail" aria-label="本地数据资料库">
      <LocalImportForm importing={importing} onImport={onImport} />
      <section className="local-dataset-library">
        <header>
          <div>
            <span>LIBRARY</span>
            <strong>本地数据集</strong>
          </div>
          <small>{datasets.length} 个</small>
        </header>
        <div className="local-dataset-list">
          {datasets.length === 0 ? (
            <div className="local-dataset-empty">还没有数据集。先导入一份标准 OHLC 或 OHLCV CSV。</div>
          ) : datasets.map((dataset) => (
            <button
              type="button"
              key={dataset.dataset_id}
              className={dataset.dataset_id === selectedId ? "active" : ""}
              onClick={() => onSelect(dataset.dataset_id)}
            >
              <span><strong>{dataset.name}</strong><em>{dataset.symbol} · {dataset.interval} · {dataset.volume_available ? "OHLCV" : "OHLC-only"}</em></span>
              <span><b>{formatRows(dataset.rows)}</b><small>{dataset.excluded_range_count} 缺口</small></span>
            </button>
          ))}
        </div>
      </section>
      {analysis}
    </aside>
  );
}

function LocalChart({
  manifest,
  runtime,
  dataMeta,
  eventStore,
  focusRequest,
  indicators,
  chartSurfaceRef,
  drawings,
  drawingTool,
  settings,
  resolvedTheme,
  invertScale,
  priceScaleMode,
  savedVisibleRange,
  onVisibleRangeChange,
  onInvertScaleChange,
  onPriceScaleModeChange,
  onDrawingInteractionReadyChange,
  onRemoveIndicator,
  onCrosshairMove,
}: {
  manifest: LocalDatasetManifest;
  runtime: ReturnType<typeof useLocalChartRuntime>;
  dataMeta: ReturnType<typeof buildLocalChartDataMeta>;
  eventStore: LocalAnalysisEventStore;
  focusRequest: LocalAnalysisFocusRequest | null;
  indicators: IndicatorRuntime;
  chartSurfaceRef: ReturnType<typeof useChartSurfaceRuntime>["ref"];
  drawings: DrawingRuntime;
  drawingTool: DrawingToolId | null;
  settings: ChartSettings;
  resolvedTheme: string;
  invertScale: boolean;
  priceScaleMode: number;
  savedVisibleRange: ReturnType<typeof getVisibleRangeForInterval>;
  onVisibleRangeChange(range: unknown): void;
  onInvertScaleChange(value: boolean): void;
  onPriceScaleModeChange(mode: number): void;
  onDrawingInteractionReadyChange(ready: boolean): void;
  onRemoveIndicator(indicatorId: string): void;
  onCrosshairMove(value: MainSeriesCrosshairValue | null): void;
}) {
  const focusTime = runtime.focusTime;
  const markerSource = useMemo(() => createLocalAnalysisMarkerSource({
    eventStore,
    seriesStore: runtime.seriesStore,
  }), [eventStore, runtime.seriesStore]);
  const [navigationTarget, setNavigationTarget] = useState<LocalAnalysisFocusRequest | null>(null);

  useEffect(() => {
    if (focusRequest === null) return undefined;
    let active = true;
    void focusTime(focusRequest.time).then((available) => {
      if (active && available) setNavigationTarget(focusRequest);
    });
    return () => { active = false; };
  }, [focusRequest, focusTime]);

  return (
    <>
      {runtime.error !== null && (
        <div className="local-chart-error" role="alert">
          <span>{runtime.error}</span>
          <button type="button" onClick={runtime.retry}>重试</button>
        </div>
      )}
      <ChartErrorBoundary>
        <SingleChartPanes
          ref={chartSurfaceRef}
          seriesStore={runtime.seriesStore}
          symbol={manifest.symbol}
          drawingKeyBase={`local:${manifest.dataset_id}:${manifest.data_epoch}`}
          interval={manifest.interval}
          loading={runtime.loading || runtime.loadingMore}
          dataMeta={dataMeta}
          onCrosshairMove={onCrosshairMove}
          navigationTarget={navigationTarget}
          onNeedMoreLeft={runtime.loadMoreLeft}
          canLoadMoreLeft={runtime.hasMoreLeft}
          canRestoreLatestWindow={false}
          datasetKey={`local:${manifest.dataset_id}:${manifest.data_epoch}`}
          upColor={settings.upColor}
          downColor={settings.downColor}
          chartType={settings.chartType}
          renkoBoxSizeMode={settings.renkoBoxSizeMode}
          renkoAtrLength={settings.renkoAtrLength}
          renkoBoxSize={settings.renkoBoxSize}
          pointFigureBoxSizeMode={settings.pointFigureBoxSizeMode}
          pointFigureAtrLength={settings.pointFigureAtrLength}
          pointFigureBoxSize={settings.pointFigureBoxSize}
          pointFigureReversalAmount={settings.pointFigureReversalAmount}
          kagiReversalMode={settings.kagiReversalMode}
          kagiAtrLength={settings.kagiAtrLength}
          kagiReversalAmount={settings.kagiReversalAmount}
          lineBreakNumberOfLines={settings.lineBreakNumberOfLines}
          theme={resolvedTheme}
          customBg={settings.customBg}
          timezone={settings.timezone ?? manifest.timezone}
          savedVisibleRange={savedVisibleRange}
          onViewportRangeChange={indicators.actions.ensureVisibleIndicatorRange}
          onVisibleRangeChange={onVisibleRangeChange}
          followLatest={false}
          externalMarkerSource={markerSource}
          drawingTool={drawingTool}
          onDrawingToolChange={drawings.actions.setDrawingTool}
          onDrawingInteractionReadyChange={onDrawingInteractionReadyChange}
          penColor={drawings.view.penColor}
          penSize={drawings.view.penSize}
          textFontSize={drawings.view.textFontSize}
          textBold={drawings.view.textBold}
          textItalic={drawings.view.textItalic}
          fibLevels={drawings.view.fibLevels}
          fibInverted={drawings.view.fibInverted}
          positionSize={drawings.view.positionSize}
          drawingSnapEnabled={drawings.view.drawingSnapEnabled}
          drawingContinuousEnabled={drawings.view.drawingContinuousEnabled}
          onSelectedDrawingChange={drawings.actions.handleSelectedDrawingChange}
          mainOverlayLines={indicators.view.mainOverlayLines}
          subPanes={indicators.view.subPanes}
          indicatorMarkers={indicators.view.markers}
          indicatorFills={indicators.view.fills}
          indicatorHlines={indicators.view.hlines}
          indicatorBgcolors={indicators.view.bgcolors}
          indicatorBarcolors={indicators.view.barcolors}
          invertScale={invertScale}
          onInvertScaleChange={onInvertScaleChange}
          priceScaleMode={priceScaleMode}
          onPriceScaleModeChange={onPriceScaleModeChange}
          onRemoveSubPane={(pane) => {
            if (pane.owner?.kind === "indicator") {
              onRemoveIndicator(pane.owner.id);
            }
          }}
        />
      </ChartErrorBoundary>
    </>
  );
}

function LocalDatasetWorkspace({
  manifest,
  indicatorPresets,
  eventStore,
  focusRequest,
  datasets,
  importing,
  onSelect,
  onImport,
  analysis,
  indicatorPanelOpen,
  onCloseIndicatorPanel,
  onCrosshairMove,
  onActiveIndicatorCountChange,
  pageExportRef,
  settings,
  onSettingsChange,
  resolvedTheme,
}: {
  manifest: LocalDatasetManifest;
  indicatorPresets: readonly IndicatorPreset[];
  eventStore: LocalAnalysisEventStore;
  focusRequest: LocalAnalysisFocusRequest | null;
  datasets: LocalDatasetManifest[];
  importing: boolean;
  onSelect(datasetId: string): void;
  onImport: Parameters<typeof LocalImportForm>[0]["onImport"];
  analysis: ReactNode;
  indicatorPanelOpen: boolean;
  onCloseIndicatorPanel(): void;
  onCrosshairMove(value: MainSeriesCrosshairValue | null): void;
  onActiveIndicatorCountChange(count: number): void;
  pageExportRef: RefObject<HTMLDivElement | null>;
  settings: ChartSettings;
  onSettingsChange(settings: ChartSettings): void;
  resolvedTheme: string;
}) {
  const chartSurface = useChartSurfaceRuntime();
  const chartRuntime = useLocalChartRuntime(manifest);
  const subscribeSeries = useCallback(
    (listener: () => void) => chartRuntime.seriesStore.subscribe(listener),
    [chartRuntime.seriesStore],
  );
  const getSeriesVersion = useCallback(
    () => Number(chartRuntime.seriesStore.version),
    [chartRuntime.seriesStore],
  );
  const seriesVersion = useSyncExternalStore(
    subscribeSeries,
    getSeriesVersion,
    getSeriesVersion,
  );
  const bars = useMemo(() => {
    void seriesVersion;
    return chartRuntime.seriesStore.snapshot();
  }, [chartRuntime.seriesStore, seriesVersion]);
  const dataMeta = useMemo(() => buildLocalChartDataMeta(
    chartRuntime.seriesStore,
    chartRuntime.loading || chartRuntime.loadingMore ? "loading" : "ready",
    seriesVersion,
  ), [
    chartRuntime.loading,
    chartRuntime.loadingMore,
    chartRuntime.seriesStore,
    seriesVersion,
  ]);
  const indicators = useLocalIndicatorRuntime({
    manifest,
    bars,
    chartDataMeta: dataMeta,
    seriesVersion,
    candleUpColor: settings.upColor,
    candleDownColor: settings.downColor,
  });
  const drawings = useDrawingRuntime({
    chartSurfaceActions: chartSurface.actions,
    session: null,
  });
  const priceScale = usePriceScalePrefs({ loadUserPrefs, updateUserPref });
  const exportFlow = useExportRuntime({
    session: null,
    metadata: {
      exchange: "local",
      marketType: manifest.dataset_id,
      symbol: manifest.symbol,
      interval: manifest.interval,
    },
    resolvedTheme,
    chartSurfaceActions: chartSurface.actions,
    pageExportRef,
    drawings,
    loadUserPrefs,
    updateUserPref,
  });
  const indicatorCatalog = useMemo(
    () => createLocalIndicatorCatalog(indicatorPresets),
    [indicatorPresets],
  );
  const savedVisibleRange = useMemo(() => getVisibleRangeForInterval(
    manifest.symbol,
    manifest.interval,
    manifest.dataset_id,
    "local",
  ), [manifest.dataset_id, manifest.interval, manifest.symbol]);
  const handleVisibleRangeChange = useCallback((range: unknown) => {
    saveVisibleRangeForInterval(
      manifest.symbol,
      manifest.interval,
      range,
      manifest.dataset_id,
      "local",
      dataMeta,
    );
  }, [dataMeta, manifest.dataset_id, manifest.interval, manifest.symbol]);
  const [drawingInteractionReady, setDrawingInteractionReady] = useState(false);
  const drawingTool = drawingToolWhenInteractionReady(
    drawings.view.drawingTool,
    drawingInteractionReady,
  );
  const removeIndicator = useCallback((indicatorId: string) => {
    drawings.actions.handleIndicatorRemoved(indicatorId);
    indicators.actions.removeIndicator(indicatorId);
  }, [drawings.actions, indicators.actions]);
  useEffect(() => {
    onActiveIndicatorCountChange(indicators.view.activeIndicators.length);
  }, [indicators.view.activeIndicators.length, onActiveIndicatorCountChange]);
  return (
    <>
      <MarketWorkspaceFrame
        toolbar={(
          <DrawingToolbar
            activeTool={drawingTool}
            onToolChange={drawings.actions.setDrawingTool}
            drawingInteractionReady={drawingInteractionReady}
            penColor={drawings.view.penColor}
            onPenColorChange={drawings.actions.setPenColor}
            penSize={drawings.view.penSize}
            onPenSizeChange={drawings.actions.setPenSize}
            onClearAll={drawings.actions.handleClearDrawing}
            drawingsHidden={drawings.view.drawingsHidden}
            onToggleDrawingsHidden={drawings.actions.handleToggleDrawingsHidden}
            drawingSnapEnabled={drawings.view.drawingSnapEnabled}
            onDrawingSnapEnabledChange={drawings.actions.handleDrawingSnapEnabledChange}
            drawingContinuousEnabled={drawings.view.drawingContinuousEnabled}
            onDrawingContinuousEnabledChange={drawings.actions.handleDrawingContinuousEnabledChange}
            textFontSize={drawings.view.textFontSize}
            onTextFontSizeChange={drawings.actions.setTextFontSize}
            textBold={drawings.view.textBold}
            onTextBoldChange={drawings.actions.setTextBold}
            textItalic={drawings.view.textItalic}
            onTextItalicChange={drawings.actions.setTextItalic}
            fibLevels={drawings.view.fibLevels}
            onFibLevelsChange={drawings.actions.handleFibLevelsChange}
            fibInverted={drawings.view.fibInverted}
            onFibInvertedChange={drawings.actions.handleFibInvertedChange}
            positionSize={drawings.view.positionSize}
            onPositionSizeChange={drawings.actions.handlePositionSizeChange}
            selectedDrawing={drawings.view.selectedDrawing}
            onSelectedDrawingStyleChange={drawings.actions.handleSelectedDrawingStyleChange}
            exportPanelOpen={exportFlow.view.isOpen}
            exportInProgress={exportFlow.status.inProgress}
            onToggleExportPanel={exportFlow.actions.togglePanel}
            chartType={settings.chartType}
            onChartTypeChange={(chartType) => onSettingsChange({ ...settings, chartType })}
          />
        )}
        exportOverlay={exportFlow.view.isOpen ? (
          <ExportPanel
            isOpen={exportFlow.view.isOpen}
            options={exportFlow.view.options}
            onOptionsChange={exportFlow.actions.updateOptions}
            onExport={exportFlow.actions.exportChart}
            onClose={exportFlow.actions.closePanel}
            inProgress={exportFlow.status.inProgress}
            error={exportFlow.view.error}
            notice={exportFlow.view.notice}
            metadata={exportFlow.view.metadata}
            loading={chartRuntime.loading || chartRuntime.loadingMore}
            indicatorComputing={indicators.status.computing}
            preview={exportFlow.view.preview}
          />
        ) : null}
        chart={(
          <LocalChart
            manifest={manifest}
            runtime={chartRuntime}
            dataMeta={dataMeta}
            eventStore={eventStore}
            focusRequest={focusRequest}
            indicators={indicators}
            chartSurfaceRef={chartSurface.ref}
            drawings={drawings}
            drawingTool={drawingTool}
            settings={settings}
            resolvedTheme={resolvedTheme}
            invertScale={priceScale.invertScale}
            priceScaleMode={priceScale.priceScaleMode}
            savedVisibleRange={savedVisibleRange}
            onVisibleRangeChange={handleVisibleRangeChange}
            onInvertScaleChange={priceScale.handleInvertScaleChange}
            onPriceScaleModeChange={priceScale.handlePriceScaleModeChange}
            onDrawingInteractionReadyChange={setDrawingInteractionReady}
            onRemoveIndicator={removeIndicator}
            onCrosshairMove={onCrosshairMove}
          />
        )}
        rightRail={(
          <LocalDatasetRail
            datasets={datasets}
            selectedId={manifest.dataset_id}
            importing={importing}
            onSelect={onSelect}
            onImport={onImport}
            analysis={analysis}
          />
        )}
      />
      <IndicatorPanel
        staticCatalog={indicatorCatalog}
        allowCustomIndicators={false}
        customIndicatorsUnavailableReason="离线 profile 未启动自定义脚本运行时"
        isOpen={indicatorPanelOpen}
        onClose={onCloseIndicatorPanel}
        activeIndicators={indicators.view.activeIndicators}
        paramSchemas={indicators.view.paramSchemas}
        onAddIndicator={indicators.actions.addIndicator}
        onRemoveIndicator={removeIndicator}
        onToggleVisibility={indicators.actions.toggleVisibility}
        onUpdateParams={indicators.actions.updateIndicatorParams}
        onUpdateScript={indicators.actions.updateIndicatorScript}
        computing={indicators.status.computing}
        realtimeMode="historical-only"
        onRecompute={indicators.actions.recompute}
        resolveIndicatorSupport={(indicator) => resolveLocalIndicatorSupport(
          indicator,
          manifest,
        )}
        modeNotice={{
          label: "本地 CSV",
          description: "共享指标 Runtime，只计算当前不可变 dataEpoch；不联网、不回填。",
        }}
      />
    </>
  );
}

function EmptyChart() {
  return (
    <div className="local-chart-empty">
      <div className="local-empty-icon">CSV</div>
      <h1>把表格数据变成可分析的 K 线</h1>
      <p>导入 OHLC CSV 后，可以直接看图、添加事件标记、写备注和保存绘图。</p>
    </div>
  );
}

export default function LocalApp() {
  const pageExportRef = useRef<HTMLDivElement | null>(null);
  const { settings, setSettings, resolvedTheme } = useChartSettingsRuntime();
  const [datasets, setDatasets] = useState<LocalDatasetManifest[]>([]);
  const [indicatorPresets, setIndicatorPresets] = useState<IndicatorPreset[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loadingLibrary, setLoadingLibrary] = useState(true);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [indicatorPanelOpen, setIndicatorPanelOpen] = useState(false);
  const [activeIndicatorCount, setActiveIndicatorCount] = useState(0);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [lastCrosshair, setLastCrosshair] = useState<MainSeriesCrosshairValue | null>(null);
  const [focusRequest, setFocusRequest] = useState<LocalAnalysisFocusRequest | null>(null);

  const refresh = useCallback(async (preferredId?: string) => {
    const loaded = await listLocalDatasets();
    setDatasets(loaded);
    setSelectedId((current) => {
      const candidate = preferredId ?? current;
      if (candidate && loaded.some((dataset) => dataset.dataset_id === candidate)) return candidate;
      return loaded[0]?.dataset_id ?? null;
    });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setLoadingLibrary(true);
    Promise.all([
      listLocalDatasets(controller.signal),
      fetchLocalIndicatorPresets(controller.signal),
    ]).then(([loaded, presets]) => {
      setDatasets(loaded);
      setIndicatorPresets(presets);
      setSelectedId(loaded[0]?.dataset_id ?? null);
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(errorMessage(reason));
    }).finally(() => {
      if (!controller.signal.aborted) setLoadingLibrary(false);
    });
    return () => controller.abort();
  }, []);

  const selected = useMemo(
    () => datasets.find((dataset) => dataset.dataset_id === selectedId) ?? null,
    [datasets, selectedId],
  );
  const analysisStore = useMemo(() => selected === null ? null : new LocalAnalysisEventStore({
    datasetId: selected.dataset_id,
    dataEpoch: selected.data_epoch,
  }), [selected]);
  const subscribeAnalysis = useCallback((listener: () => void) => (
    analysisStore?.subscribe(listener) ?? (() => undefined)
  ), [analysisStore]);
  const getAnalysisSnapshot = useCallback(() => (
    analysisStore?.getSnapshot() ?? EMPTY_LOCAL_ANALYSIS_SNAPSHOT
  ), [analysisStore]);
  const analysisSnapshot = useSyncExternalStore(
    subscribeAnalysis,
    getAnalysisSnapshot,
    () => EMPTY_LOCAL_ANALYSIS_SNAPSHOT,
  );

  useEffect(() => {
    setLastCrosshair(null);
    setFocusRequest(null);
    setIndicatorPanelOpen(false);
    setActiveIndicatorCount(0);
  }, [selected?.data_epoch, selected?.dataset_id]);

  const focusAnalysisEvent = useCallback((event: LocalAnalysisEvent) => {
    setFocusRequest((current) => ({
      requestId: (current?.requestId ?? 0) + 1,
      time: event.time,
    }));
  }, []);

  const handleImport: Parameters<typeof LocalImportForm>[0]["onImport"] = async (input) => {
    setImporting(true);
    setError(null);
    try {
      const manifest = await importLocalCsv(input);
      await refresh(manifest.dataset_id);
    } catch (reason) {
      setError(errorMessage(reason));
      throw reason;
    } finally {
      setImporting(false);
    }
  };

  return (
    <MarketPageFrame
      rootRef={pageExportRef}
      topBar={(
        <MarketTopBarFrame
          source="local"
          brandIcon="◫"
          brandText="CandleScope Analyze"
          identity={selected ? (
            <div className="local-top-identity">
              <strong>{selected.symbol}</strong>
              <span>{selected.name}</span>
            </div>
          ) : null}
          controls={<>
            <button
              type="button"
              className="settings-btn"
              onClick={() => setSettingsOpen(true)}
              title="设置"
              aria-label="设置"
            >
              ⚙️
            </button>
            <button
              type="button"
              className={`indicator-toggle-btn ${indicatorPanelOpen ? "active" : ""}`}
              disabled={selected === null}
              onClick={() => setIndicatorPanelOpen((open) => !open)}
              title="指标 (Indicators)"
            >
              📊
              {activeIndicatorCount > 0 && (
                <span className="indicator-badge">{activeIndicatorCount}</span>
              )}
            </button>
            <span className="local-offline-badge">● 本地分析</span>
          </>}
          trailing={<span className="local-network-truth">CSV 数据 · 事件标记 · 本地绘图</span>}
        />
      )}
      intervalSelector={(
        <div className="local-dataset-truthbar">
          <span>{selected ? `${selected.interval} · ${selected.timezone} · ${formatRows(selected.rows)} bars · ${selected.volume_available ? "OHLCV" : "OHLC-only / 成交量不可用"}` : "等待本地数据"}</span>
          <span>{selected ? `dataEpoch ${selected.data_epoch.slice(7, 19)}` : "source: local_dataset"}</span>
        </div>
      )}
      workspace={(
        selected && analysisStore ? (
          <LocalDatasetWorkspace
            key={selected.data_epoch}
            manifest={selected}
            indicatorPresets={indicatorPresets}
            eventStore={analysisStore}
            focusRequest={focusRequest}
            datasets={datasets}
            importing={importing}
            onSelect={setSelectedId}
            onImport={handleImport}
            indicatorPanelOpen={indicatorPanelOpen}
            onCloseIndicatorPanel={() => setIndicatorPanelOpen(false)}
            analysis={(
              <LocalAnalysisPanel
                key={selected.data_epoch}
                manifest={selected}
                snapshot={analysisSnapshot}
                eventStore={analysisStore}
                crosshair={lastCrosshair}
                onFocus={focusAnalysisEvent}
                onError={setError}
              />
            )}
            onCrosshairMove={(value) => {
              if (value !== null) setLastCrosshair(value);
            }}
            onActiveIndicatorCountChange={setActiveIndicatorCount}
            pageExportRef={pageExportRef}
            settings={settings}
            onSettingsChange={setSettings}
            resolvedTheme={resolvedTheme}
          />
        ) : (
          <MarketWorkspaceFrame
            toolbar={null}
            exportOverlay={null}
            chart={<EmptyChart />}
            rightRail={(
              <LocalDatasetRail
                datasets={datasets}
                selectedId={selectedId}
                importing={importing}
                onSelect={setSelectedId}
                onImport={handleImport}
                analysis={null}
              />
            )}
          />
        )
      )}
      featureSurfaces={(
        <>
          {error !== null && (
            <div className="local-global-error" role="alert">
              <span>{error}</span>
              <button type="button" onClick={() => setError(null)}>关闭</button>
            </div>
          )}
          <SettingsModal
            isOpen={settingsOpen}
            onClose={() => setSettingsOpen(false)}
            settings={settings}
            onUpdate={setSettings}
            currentSymbol={selected?.symbol ?? ""}
            currentMarketType={selected?.dataset_id ?? "local"}
            currentExchange="local"
            allowedCategories={["appearance", "about"]}
            backendFeaturesEnabled={false}
            dataWorkbenchEnabled={false}
          />
        </>
      )}
      statusBar={(
        <MarketStatusBar
          source="local"
          connectionStatus={error === null ? "offline-ready" : "error"}
          left={<><span className="status-dot connected" />LOCAL DATASET · ANALYSIS READY</>}
          right={selected ? <>{analysisSnapshot.events.length} 个标记 · {selected.excluded_range_count} 个数据缺口 · 导入于 {formatDate(selected.imported_at)}</> : loadingLibrary ? "正在读取本地资料库…" : "未选择数据集"}
        />
      )}
    />
  );
}
