import { useCallback, useEffect, useMemo, useRef } from "react";
import type { ComponentType, MutableRefObject } from "react";
import { createLightweightChartAdapter } from "../chart-adapter/chartInstanceBridge.js";
import type { DrawingFrameSnapshot } from "../chart-adapter/drawingFrameSnapshot.js";
import type { createMainSeries } from "../chart-adapter/seriesLifecycle.js";
import type { MainSeriesHandle } from "../chart-adapter/chartAdapterTypes.js";
import type { DisplayRow } from "../features/chart-representation/chartRepresentationTypes.js";
import type { DrawingEngineApi, DrawingEngineHostProps } from "../features/drawings/DrawingEngineHost.js";
import type { SelectedDrawingMeta } from "../features/drawings/drawingSelectionController.js";
import type { IntervalString } from "../utils/intervals.js";

type AdapterChart = Parameters<typeof createMainSeries>[0];
type DrawingEngineHostComponent = ComponentType<DrawingEngineHostProps>;

type PaneDrawingHostProps = Omit<
  DrawingEngineHostProps,
  "chartAdapter" | "chartContainerRef" | "onApiChange" | "onSelectedDrawingChange"
>;

interface NativePaneDrawingHostProps {
  readonly component: DrawingEngineHostComponent;
  readonly chartAdapter?: ReturnType<typeof createLightweightChartAdapter>;
  readonly paneId: string;
  readonly paneIndex: number;
  readonly series: MainSeriesHandle;
  readonly chartRef: MutableRefObject<AdapterChart | null>;
  readonly chartContainerRef: MutableRefObject<HTMLDivElement | null>;
  readonly seriesDataRef: MutableRefObject<DisplayRow[]>;
  readonly sourceTimeHorizonRef: MutableRefObject<number | null>;
  readonly sourceIntervalRef: MutableRefObject<IntervalString>;
  readonly sourceIntervalSecondsRef: MutableRefObject<number | null>;
  readonly projectionConfigRef: MutableRefObject<string | null>;
  readonly frameInvalidationRevision: number;
  readonly captureDrawingFrame: (
    paneId: string,
    series: MainSeriesHandle,
    paneIndex: number,
  ) => DrawingFrameSnapshot | null;
  readonly hostProps: PaneDrawingHostProps;
  readonly interactionKey: string;
  readonly onPaneApiChange: (
    paneId: string,
    drawingKey: string,
    interactionKey: string,
    api: DrawingEngineApi | null,
    previousApi: DrawingEngineApi | null,
  ) => void;
  readonly onPaneAdapterChange: (
    paneId: string,
    adapter: ReturnType<typeof createLightweightChartAdapter> | null,
  ) => void;
  readonly onPaneSelectedDrawingChange: (
    paneId: string,
    drawing: SelectedDrawingMeta | null,
  ) => void;
}

/** One independent document/interaction surface attached to one native LWC pane. */
export default function NativePaneDrawingHost({
  component: DrawingEngineHostComponent,
  chartAdapter: providedChartAdapter,
  paneId,
  paneIndex,
  series,
  chartRef,
  chartContainerRef,
  seriesDataRef,
  sourceTimeHorizonRef,
  sourceIntervalRef,
  sourceIntervalSecondsRef,
  projectionConfigRef,
  frameInvalidationRevision,
  captureDrawingFrame,
  hostProps,
  interactionKey,
  onPaneApiChange,
  onPaneAdapterChange,
  onPaneSelectedDrawingChange,
}: NativePaneDrawingHostProps) {
  const paneChartAdapter = useMemo(() => createLightweightChartAdapter({
    chartRef,
    seriesRef: series,
    containerRef: chartContainerRef,
    drawingPaneIndexRef: paneIndex,
    seriesDataRef,
    sourceTimeHorizonRef,
    sourceIntervalRef,
    sourceIntervalSecondsRef,
    projectionConfigRef,
    drawingCoordinateSnapshotProvider: () => captureDrawingFrame(paneId, series, paneIndex),
  }), [
    captureDrawingFrame,
    chartContainerRef,
    chartRef,
    paneId,
    paneIndex,
    projectionConfigRef,
    series,
    seriesDataRef,
    sourceIntervalRef,
    sourceIntervalSecondsRef,
    sourceTimeHorizonRef,
  ]);
  // The main chart already owns a stable ref-backed adapter. Reuse it so
  // main-series replacements do not tear down and recreate the drawing worker;
  // subpanes still need their series-specific adapters.
  const chartAdapter = providedChartAdapter ?? paneChartAdapter;
  const publishedApiRef = useRef<DrawingEngineApi | null>(null);
  const handleApiChange = useCallback((api: DrawingEngineApi | null) => {
    const previousApi = publishedApiRef.current;
    publishedApiRef.current = api;
    onPaneApiChange(paneId, hostProps.drawingKey, interactionKey, api, previousApi);
  }, [hostProps.drawingKey, interactionKey, onPaneApiChange, paneId]);
  const handleSelectedDrawingChange = useCallback((drawing: SelectedDrawingMeta | null) => {
    onPaneSelectedDrawingChange(paneId, drawing);
  }, [onPaneSelectedDrawingChange, paneId]);

  useEffect(() => {
    onPaneAdapterChange(paneId, chartAdapter);
    return () => onPaneAdapterChange(paneId, null);
  }, [chartAdapter, onPaneAdapterChange, paneId]);

  useEffect(() => {
    if (frameInvalidationRevision <= 0) return;
    chartAdapter.notifyDrawingFrameInvalidation();
  }, [chartAdapter, frameInvalidationRevision]);

  return (
    <DrawingEngineHostComponent
      {...hostProps}
      chartAdapter={chartAdapter}
      chartContainerRef={chartContainerRef}
      onApiChange={handleApiChange}
      onSelectedDrawingChange={handleSelectedDrawingChange}
    />
  );
}
