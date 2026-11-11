import { useCallback, useEffect, useRef, type SetStateAction } from "react";
import { clearDrawingScopeAuthoritatively } from "./drawingScopePersistence.js";
import { useDrawingToolState } from "./drawingToolState.js";
import { awaitControlledSeriesRebuildExportCapture } from "./export/controlledExportRollbackCheckpoint.js";
import {
  beginDrawingExportLifecycle,
  recordDrawingExportCaptureSourceFixed,
  recordDrawingExportImageEncoded,
  recordDrawingExportLeaseRestored,
  recordDrawingExportPostCaptureRevalidate,
  recordDrawingExportPreviewPublished,
} from "./export/drawingExportLifecycle.js";
import type { ChartSurfaceActions } from "../../chart-adapter/useChartSurfaceRuntime.js";
import type { ChartSessionRuntime } from "../chart-session/chartSessionTypes.js";
import type {
  DrawingToolSelectionRuntime,
  DrawingToolStateRuntime,
} from "./drawingToolState.js";
import type {
  DrawingExportLease,
  DrawingExportPrepareOptions,
  DrawingStylePatch,
} from "./drawingInteractionController.js";
import type {
  DrawingExportEncodedResult,
  DrawingExportLifecycleTransaction,
} from "./export/drawingExportLifecycle.js";

export type DrawingRuntimeExportLease = DrawingExportLease;
export type DrawingRuntimeExportPrepareOptions = DrawingExportPrepareOptions;

export interface DrawingExportRuntimeInstrumentation {
  begin(
    lease: DrawingExportLease,
    hideDrawings: boolean,
  ): DrawingExportLifecycleTransaction;
  awaitControlledCapture(
    transaction: DrawingExportLifecycleTransaction,
    signal: AbortSignal,
  ): Promise<unknown>;
  recordCaptureSourceFixed(transaction: DrawingExportLifecycleTransaction | null): void;
  recordPostCaptureRevalidate(
    transaction: DrawingExportLifecycleTransaction | null,
    valid: boolean,
  ): void;
  recordLeaseRestored(transaction: DrawingExportLifecycleTransaction | null): void;
  recordImageEncoded(
    transaction: DrawingExportLifecycleTransaction | null,
    result: DrawingExportEncodedResult,
  ): void;
  recordPreviewPublished(transaction: DrawingExportLifecycleTransaction | null): void;
}

const DRAWING_EXPORT_INSTRUMENTATION: DrawingExportRuntimeInstrumentation = Object.freeze({
  begin: beginDrawingExportLifecycle,
  awaitControlledCapture: awaitControlledSeriesRebuildExportCapture,
  recordCaptureSourceFixed: recordDrawingExportCaptureSourceFixed,
  recordPostCaptureRevalidate: recordDrawingExportPostCaptureRevalidate,
  recordLeaseRestored: recordDrawingExportLeaseRestored,
  recordImageEncoded: recordDrawingExportImageEncoded,
  recordPreviewPublished: recordDrawingExportPreviewPublished,
});

export type DrawingRuntimeActions = DrawingToolStateRuntime["actions"] & {
  handleClearDrawing(): void;
  handleToggleDrawingsHidden(): void;
  handleSelectedDrawingStyleChange(patch: DrawingStylePatch): void;
  prepareExport(options?: DrawingExportPrepareOptions): Promise<DrawingExportLease | null>;
  exportInstrumentation: DrawingExportRuntimeInstrumentation;
  handleIndicatorRemoved(indicatorId: string | null | undefined): void;
};

export interface DrawingRuntime {
  view: DrawingToolStateRuntime["view"];
  actions: DrawingRuntimeActions;
  status: Record<string, never>;
}

export function shouldSynchronizeDrawingVisibility(
  previous: boolean | null,
  next: boolean,
): boolean {
  return previous === null ? next : previous !== next;
}

export function indicatorDrawingScopeKeys(
  drawingScopeBase: string,
  indicatorId: string | null | undefined,
): string[] {
  const base = drawingScopeBase.trim();
  const id = indicatorId?.trim() || "";
  if (!base || !id) return [];
  return [
    `${base}__separate-${id}`,
    `${base}__volume-${id}`,
  ];
}

export function useDrawingRuntime({
  chartSurfaceActions,
  drawingScopeBase,
  drawingToolSelection,
  session,
  visibility,
}: {
  chartSurfaceActions: ChartSurfaceActions | null | undefined;
  drawingScopeBase?: string | null;
  drawingToolSelection?: DrawingToolSelectionRuntime | null;
  session: ChartSessionRuntime | null | undefined;
  visibility?: { hidden: boolean; setHidden(hidden: boolean): void };
}): DrawingRuntime {
  const toolState = useDrawingToolState(drawingToolSelection);
  const setLocalHidden = toolState.actions.setDrawingsHidden;
  const setControlledHidden = visibility?.setHidden;
  const hidden = visibility?.hidden ?? toolState.view.drawingsHidden;
  const setDrawingsHidden = useCallback((value: SetStateAction<boolean>) => {
    if (setControlledHidden) setControlledHidden(typeof value === "function" ? value(hidden) : value);
    else setLocalHidden(value);
  }, [hidden, setControlledHidden, setLocalHidden]);
  const synchronizedDrawingsHiddenRef = useRef<boolean | null>(null);

  const handleClearDrawing = useCallback(() => {
    chartSurfaceActions?.clearAllDrawings?.();
  }, [chartSurfaceActions]);

  const handleToggleDrawingsHidden = useCallback(() => {
    setDrawingsHidden((prev) => !prev);
  }, [setDrawingsHidden]);

  const prepareExport = useCallback((options?: DrawingExportPrepareOptions) => {
    return chartSurfaceActions?.prepareExport?.(options) ?? Promise.resolve(null);
  }, [chartSurfaceActions]);

  useEffect(() => {
    if (setControlledHidden) return;
    const previous = synchronizedDrawingsHiddenRef.current;
    synchronizedDrawingsHiddenRef.current = hidden;
    // A newly mounted chart host already receives `initialHidden`. Avoid
    // converting the normal initial `false` into a mutation while a persisted
    // drawing document is still restoring; only real visibility transitions
    // (or an initially hidden surface) need the imperative API.
    if (!shouldSynchronizeDrawingVisibility(previous, hidden)) return;
    chartSurfaceActions?.setDrawingsHidden?.(hidden);
  }, [chartSurfaceActions, hidden, setControlledHidden]);

  const handleSelectedDrawingStyleChange = useCallback((patch: DrawingStylePatch) => {
    chartSurfaceActions?.updateSelectedDrawingStyle?.(patch);
  }, [chartSurfaceActions]);

  const handleIndicatorRemoved = useCallback((indicatorId: string | null | undefined) => {
    const sessionView = session?.view;
    const storageKeyBase = drawingScopeBase?.trim()
      || (sessionView
        ? `${sessionView.exchange}:${sessionView.marketType}:${sessionView.symbol}`
        : "");
    for (const scopeKey of indicatorDrawingScopeKeys(storageKeyBase, indicatorId)) {
      clearDrawingScopeAuthoritatively(scopeKey);
    }
  }, [drawingScopeBase, session]);

  const actions: DrawingRuntimeActions = {
    ...toolState.actions,
    setDrawingsHidden,
    handleClearDrawing,
    handleToggleDrawingsHidden,
    handleSelectedDrawingStyleChange,
    prepareExport,
    exportInstrumentation: DRAWING_EXPORT_INSTRUMENTATION,
    handleIndicatorRemoved,
  };

  return {
    view: visibility ? { ...toolState.view, drawingsHidden: hidden } : toolState.view,
    actions,
    status: {},
  };
}
