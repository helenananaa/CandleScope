import type { DrawingObjectApi } from "./drawingObjectApi.js";
import { memo, useCallback, useEffect, useRef, useState } from "react";
import { useDrawing } from "./drawingInteractionController.js";
import TextEditOverlay from "../../components/TextEditOverlay";
import TextFormatBar from "../../components/TextFormatBar";
import SelectedDrawingStyleBar from "./SelectedDrawingStyleBar.js";
import DrawingHistoryBar from "./DrawingHistoryBar.js";
import DrawingInteractionOverlay from "./rendering/DrawingInteractionOverlay.js";
import {
    resolveDrawingHostInteractionSurfaceMode,
} from "./interactionSurfaceMode.js";
import { drawingPerfCounters } from "./performance/drawingPerfCounters.js";
import type { MutableRefObject } from "react";
import type {
    DrawingAnchorMode,
    DrawingChartAdapter,
    DrawingToolId,
    FibonacciLevel,
} from "./drawingTypes.js";
import type {
    DrawingExportLease,
    DrawingExportPrepareOptions,
    DrawingStylePatch,
    DrawingSurfaceDisposeBoundaryDescriptor,
} from "./drawingInteractionController.js";
import type { DrawingCommittedPaintTicket } from "./useDrawingPersistenceLifecycle.js";
import type { SelectedDrawingMeta } from "./drawingSelectionController.js";

export interface DrawingEngineApi {
    objects?: DrawingObjectApi;
    clearAll(): void;
    deselectAll(): void;
    completeSurfaceDispose(): void;
    invalidateSurfaceCredentialsForSeriesReplacement(): void;
    prepareSurfaceDispose(boundary?: DrawingSurfaceDisposeBoundaryDescriptor): boolean;
    setHidden(hidden: boolean): void;
    updateSelectedDrawingStyle(patch: DrawingStylePatch): void;
    prepareExport(options?: DrawingExportPrepareOptions): Promise<DrawingExportLease>;
    subscribePublication(listener: (stamp: DrawingCommittedPaintTicket) => void): () => void;
}

export interface DrawingEngineHostProps {
    chartAdapter: DrawingChartAdapter | null;
    chartContainerRef: MutableRefObject<HTMLElement | null>;
    activeTool: DrawingToolId | null;
    manageChartCursor?: boolean;
    onToolChange?: ((tool: DrawingToolId | null) => void) | null;
    penColor: string;
    penSize: number;
    textFontSize: number;
    textBold: boolean;
    textItalic: boolean;
    fibLevels: FibonacciLevel[] | null;
    fibInverted: boolean;
    positionSize: number;
    drawingSnapEnabled: boolean;
    drawingContinuousEnabled: boolean;
    drawingAutoSelectEnabled: boolean;
    drawingKey: string;
    drawingSeriesGeneration: number;
    drawingChartType: string;
    drawingInterval: string;
    drawingCoordinateKey: string;
    drawingAnchorMode: DrawingAnchorMode;
    initialHidden?: boolean;
    onApiChange?: ((api: DrawingEngineApi | null) => void) | null;
    onSelectedDrawingChange?: ((drawing: SelectedDrawingMeta | null) => void) | null;
}

function DrawingEngineHost({
    chartAdapter,
    chartContainerRef,
    activeTool,
    manageChartCursor = true,
    onToolChange,
    penColor,
    penSize,
    textFontSize,
    textBold,
    textItalic,
    fibLevels,
    fibInverted,
    positionSize,
    drawingSnapEnabled,
    drawingContinuousEnabled,
    drawingAutoSelectEnabled,
    drawingKey,
    drawingSeriesGeneration,
    drawingChartType,
    drawingInterval,
    drawingCoordinateKey,
    drawingAnchorMode,
    initialHidden = false,
    onApiChange,
    onSelectedDrawingChange,
}: DrawingEngineHostProps) {
    const dynamicCanvasRef = useRef<HTMLCanvasElement | null>(null);
    const liveInkCanvasRef = useRef<HTMLCanvasElement | null>(null);
    const [interactionSurfaceMode, setInteractionSurfaceMode] = useState(
        resolveDrawingHostInteractionSurfaceMode,
    );
    const handleInteractionSurfaceFallback = useCallback(() => {
        // The rollout flag is mount-locked, but a scene-canary initialization
        // failure is allowed to make one fail-closed transition. Keep the
        // interaction owner aligned with the legacy static surface that the
        // persistence lifecycle just restored.
        setInteractionSurfaceMode("legacy");
    }, []);
    const drawing = useDrawing({
        chartAdapter,
        chartContainerRef,
        activeTool,
        manageChartCursor,
        penColor,
        penSize,
        textFontSize,
        textBold,
        textItalic,
        fibLevels,
        fibInverted,
        positionSize,
        drawingSnapEnabled,
        drawingContinuousEnabled,
        drawingAutoSelectEnabled,
        symbol: drawingKey,
        seriesReady: drawingSeriesGeneration,
        drawingChartType,
        drawingInterval,
        drawingCoordinateKey,
        drawingAnchorMode,
        interactionSurfaceMode,
        dynamicCanvasRef,
        liveInkCanvasRef,
        onInteractionSurfaceFallback: handleInteractionSurfaceFallback,
        ...(onToolChange === undefined ? {} : { onToolChange }),
    });
    const {
        getObjectDocument, subscribeObjectDocument, selectObject, updateObject, deleteObject, reorderObject,
        clearAll,
        deselectAll,
        completeSurfaceDispose,
        invalidateSurfaceCredentialsForSeriesReplacement,
        prepareExport,
        prepareSurfaceDispose,
        selectedDrawingMeta,
        setHidden,
        updateSelectedDrawingStyle,
        subscribeVisibleScenePublication,
    } = drawing;
    const legacyPrimitiveEvidence = drawing.getLegacyPrimitiveRuntimeEvidence();
    const appliedInitialHiddenRef = useRef(false);
    const interactionMarkerRef = useRef<HTMLSpanElement | null>(null);

    useEffect(() => {
        drawingPerfCounters.incrementCounter("reactRenderCount");
    });

    useEffect(() => {
        if (appliedInitialHiddenRef.current) return;
        appliedInitialHiddenRef.current = true;
        if (initialHidden) setHidden(true);
    }, [initialHidden, setHidden]);

    const selectedTextId = drawing.selectedTextSnapshot ? drawing.selectedPrimId : null;
    useEffect(() => {
        // Text uses its own formatter but still participates in cross-pane selection.
        onSelectedDrawingChange?.(selectedDrawingMeta
            ?? (selectedTextId ? { id: selectedTextId, type: "text" } : null));
    }, [onSelectedDrawingChange, selectedDrawingMeta, selectedTextId]);

    useEffect(() => () => {
        onSelectedDrawingChange?.(null);
    }, [onSelectedDrawingChange]);

    useEffect(() => {
        // useDrawing's pointer-subscription effect is registered earlier in
        // this component and therefore runs before this API publication. Only
        // expose "ready" after that listener boundary has been crossed.
        if (interactionMarkerRef.current) {
            interactionMarkerRef.current.dataset.drawingEngine = "ready";
        }
        onApiChange?.({
            ...(interactionSurfaceMode === "overlay" ? { objects: { getObjectDocument, subscribeObjectDocument, selectObject, updateObject, deleteObject, reorderObject } } : {}),
            clearAll,
            deselectAll,
            completeSurfaceDispose,
            invalidateSurfaceCredentialsForSeriesReplacement,
            prepareSurfaceDispose,
            setHidden,
            updateSelectedDrawingStyle,
            prepareExport,
            subscribePublication: (listener) => subscribeVisibleScenePublication(
                listener,
                { replayLastPublication: false },
            ),
        });
    }, [
        interactionSurfaceMode, getObjectDocument, subscribeObjectDocument, selectObject, updateObject, deleteObject, reorderObject,
        clearAll,
        deselectAll,
        completeSurfaceDispose,
        invalidateSurfaceCredentialsForSeriesReplacement,
        onApiChange,
        prepareExport,
        prepareSurfaceDispose,
        setHidden,
        subscribeVisibleScenePublication,
        updateSelectedDrawingStyle,
    ]);

    useEffect(() => {
        const interactionMarker = interactionMarkerRef.current;
        return () => {
            if (interactionMarker) {
                interactionMarker.dataset.drawingEngine = "mounted";
            }
            onApiChange?.(null);
        };
    }, [onApiChange]);

    return (
        <>
            <span ref={interactionMarkerRef} data-drawing-engine="mounted" hidden />
            <span
                data-drawing-interaction-mode={interactionSurfaceMode}
                data-drawing-active-tool={activeTool ?? ""}
                data-drawing-scope={drawingKey}
                data-drawing-editing-text-id={drawing.editingTextId ?? ""}
                data-drawing-editing-text-position={drawing.editingTextPos
                    ? `${drawing.editingTextPos.x},${drawing.editingTextPos.y}`
                    : ""}
                hidden
            />
            <span
                data-drawing-registry-kind={legacyPrimitiveEvidence.registryKind}
                data-drawing-legacy-instances={legacyPrimitiveEvidence.legacyPrimitiveInstanceCount}
                data-drawing-legacy-attached={legacyPrimitiveEvidence.legacyPrimitiveAttachedCount}
                data-drawing-zero-legacy={legacyPrimitiveEvidence.zeroLegacyPrimitiveInvariant ? "true" : "false"}
                hidden
            />

            {interactionSurfaceMode === "overlay" && (
                <DrawingInteractionOverlay
                    dynamicCanvasRef={dynamicCanvasRef}
                    liveInkCanvasRef={liveInkCanvasRef}
                />
            )}

            {drawing.editingTextId && drawing.editingTextPos && (
                <TextEditOverlay
                    box={drawing.editingTextPos}
                    value={drawing.editingTextValue}
                    onChange={drawing.setEditingTextValue}
                    onCommit={drawing.commitTextEditing}
                    onCancel={drawing.cancelTextEditing}
                    fontSize={drawing.selectedTextSnapshot?.fontSize ?? textFontSize}
                    {...(drawing.selectedTextSnapshot?.fontFamily === undefined
                        ? {}
                        : { fontFamily: drawing.selectedTextSnapshot.fontFamily })}
                    bold={drawing.selectedTextSnapshot?.bold ?? textBold}
                    italic={drawing.selectedTextSnapshot?.italic ?? textItalic}
                    underline={drawing.selectedTextSnapshot?.underline ?? false}
                    align={drawing.selectedTextSnapshot?.align ?? "left"}
                    color={drawing.selectedTextSnapshot?.color ?? penColor}
                    bgColor={drawing.selectedTextSnapshot?.bgColor ?? null}
                    borderColor={drawing.selectedTextSnapshot?.borderColor ?? null}
                    padding={drawing.selectedTextSnapshot?.padding ?? 6}
                    widthPx={drawing.selectedTextSnapshot?.widthPx ?? null}
                    inputRef={drawing.editInputRef}
                />
            )}

            {!drawing.editingTextId && drawing.selectedTextSnapshot && (
                <TextFormatBar
                    key={drawing.selectedPrimId}
                    snapshot={drawing.selectedTextSnapshot}
                    onPatch={drawing.updateSelectedText}
                    {...(interactionSurfaceMode === "overlay" ? { currentInterval: drawingInterval, onToggleLock: () => drawing.updateSelectedDrawingStyle({ locked: !drawing.selectedTextSnapshot?.locked }) } : {})}
                    onDelete={drawing.deleteSelected}
                />
            )}
            {!drawing.editingTextId && selectedDrawingMeta && (
                <SelectedDrawingStyleBar
                    drawing={selectedDrawingMeta}
                    {...(interactionSurfaceMode === "overlay" ? { onSave: drawing.saveDrawingProperties, currentInterval: drawingInterval } : {})}
                    openRequestRevision={drawing.selectedDrawingSettingsRequest?.id === selectedDrawingMeta.id
                        ? drawing.selectedDrawingSettingsRequest.revision : 0}
                    onPatch={drawing.updateSelectedDrawingStyle}
                    onDelete={drawing.deleteSelected}
                />
            )}
            {interactionSurfaceMode === "overlay" && <DrawingHistoryBar container={chartContainerRef} adapter={chartAdapter} scope={drawingKey}
                canUndo={!drawing.editingTextId && drawing.canUndo} canRedo={!drawing.editingTextId && drawing.canRedo}
                replay={drawing.replayHistory} />}
        </>
    );
}

export default memo(DrawingEngineHost);
