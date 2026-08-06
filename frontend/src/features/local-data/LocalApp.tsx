import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import type { ReactNode } from "react";
import SingleChartPanes from "../../components/SingleChartPanes.js";
import type { MainSeriesCrosshairValue } from "../../chart-adapter/chartAdapterTypes.js";
import { ChartErrorBoundary } from "../../app/AppProviders.js";
import MarketPageFrame from "../../app/MarketPageFrame.js";
import MarketStatusBar from "../../app/MarketStatusBar.js";
import MarketTopBarFrame from "../../app/MarketTopBarFrame.js";
import MarketWorkspaceFrame from "../../app/MarketWorkspaceFrame.js";
import {
  importLocalCsv,
  listLocalDatasets,
  LocalDataApiError,
} from "./localDataApi.js";
import type { LocalDatasetManifest } from "./localDataTypes.js";
import LocalAnalysisPanel from "./LocalAnalysisPanel.js";
import LocalIndicatorPanel from "./LocalIndicatorPanel.js";
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
  indicators,
  analysis,
}: {
  datasets: LocalDatasetManifest[];
  selectedId: string | null;
  importing: boolean;
  onSelect(datasetId: string): void;
  onImport: Parameters<typeof LocalImportForm>[0]["onImport"];
  indicators: ReactNode;
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
      {indicators}
      {analysis}
    </aside>
  );
}

function LocalChart({
  manifest,
  eventStore,
  focusRequest,
  indicators,
  onCrosshairMove,
}: {
  manifest: LocalDatasetManifest;
  eventStore: LocalAnalysisEventStore;
  focusRequest: LocalAnalysisFocusRequest | null;
  indicators: IndicatorRuntime;
  onCrosshairMove(value: MainSeriesCrosshairValue | null): void;
}) {
  const runtime = useLocalChartRuntime(manifest);
  const subscribeSeries = useCallback(
    (listener: () => void) => runtime.seriesStore.subscribe(listener),
    [runtime.seriesStore],
  );
  const getSeriesVersion = useCallback(
    () => Number(runtime.seriesStore.version),
    [runtime.seriesStore],
  );
  const seriesVersion = useSyncExternalStore(
    subscribeSeries,
    getSeriesVersion,
    getSeriesVersion,
  );
  const dataMeta = useMemo(() => buildLocalChartDataMeta(
    runtime.seriesStore,
    runtime.loading || runtime.loadingMore ? "loading" : "ready",
    seriesVersion,
  ), [runtime.loading, runtime.loadingMore, runtime.seriesStore, seriesVersion]);
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
          upColor="#22c55e"
          downColor="#ef4444"
          theme="dark"
          customBg="#0a0e17"
          timezone={manifest.timezone}
          followLatest={false}
          externalMarkerSource={markerSource}
          mainOverlayLines={indicators.view.mainOverlayLines}
          subPanes={indicators.view.subPanes}
          indicatorMarkers={indicators.view.markers}
          indicatorFills={indicators.view.fills}
          indicatorHlines={indicators.view.hlines}
          indicatorBgcolors={indicators.view.bgcolors}
          indicatorBarcolors={indicators.view.barcolors}
          onRemoveSubPane={(pane) => {
            if (pane.owner?.kind === "indicator") {
              indicators.actions.removeIndicator(pane.owner.id);
            }
          }}
        />
      </ChartErrorBoundary>
    </>
  );
}

function LocalDatasetWorkspace({
  manifest,
  eventStore,
  focusRequest,
  datasets,
  importing,
  onSelect,
  onImport,
  analysis,
  onCrosshairMove,
}: {
  manifest: LocalDatasetManifest;
  eventStore: LocalAnalysisEventStore;
  focusRequest: LocalAnalysisFocusRequest | null;
  datasets: LocalDatasetManifest[];
  importing: boolean;
  onSelect(datasetId: string): void;
  onImport: Parameters<typeof LocalImportForm>[0]["onImport"];
  analysis: ReactNode;
  onCrosshairMove(value: MainSeriesCrosshairValue | null): void;
}) {
  const indicators = useLocalIndicatorRuntime(manifest);
  return (
    <MarketWorkspaceFrame
      toolbar={null}
      exportOverlay={null}
      chart={(
        <LocalChart
          manifest={manifest}
          eventStore={eventStore}
          focusRequest={focusRequest}
          indicators={indicators}
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
          indicators={<LocalIndicatorPanel manifest={manifest} runtime={indicators} />}
          analysis={analysis}
        />
      )}
    />
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
  const [datasets, setDatasets] = useState<LocalDatasetManifest[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loadingLibrary, setLoadingLibrary] = useState(true);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
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
    listLocalDatasets(controller.signal).then((loaded) => {
      setDatasets(loaded);
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
          controls={<span className="local-offline-badge">● 本地分析</span>}
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
            eventStore={analysisStore}
            focusRequest={focusRequest}
            datasets={datasets}
            importing={importing}
            onSelect={setSelectedId}
            onImport={handleImport}
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
                indicators={null}
                analysis={null}
              />
            )}
          />
        )
      )}
      featureSurfaces={error === null ? null : (
        <div className="local-global-error" role="alert">
          <span>{error}</span>
          <button type="button" onClick={() => setError(null)}>关闭</button>
        </div>
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
