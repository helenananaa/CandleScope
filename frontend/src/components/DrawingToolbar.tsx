/**
 * Drawing toolbar sits on the left side of the chart area.
 *
 * Buttons: Mouse cursor, Pen/Highlighter, Eraser, Line, Shape, Text, Fibonacci, Calculated, Position (Long/Short).
 * Left-click toggles the tool on/off.
 * Right-click or double-click on Cursor / Pen / Line / Shape opens a flyout to switch variants.
 *
 * All drawing is native (Plugin API), no pixel overlays.
 */
import { memo, useCallback, useEffect } from "react";
import type { MouseEvent } from "react";
import {
  CHART_DRAWING_ANCHOR_MODES,
  getChartTypeDescriptor,
} from "../features/chart-representation/chartTypeRegistry.js";
import {
  drawingToolForAnchorMode,
  hasSupportedDrawingVariant,
  supportsDrawingAnchorMode,
  supportsDrawingTool,
} from "../features/drawings/drawingCapabilities.js";
import { t } from "../i18n/index.js";
import { resolveDrawingHostInteractionSurfaceMode } from "../features/drawings/interactionSurfaceMode.js";
import { isCalculatedToolId } from "../features/drawings/drawingModel.js";
import { useLocale } from "../i18n/useLocale.js";
import { markPerfOnce } from "../runtime/performance/perfMarks";
import DrawingActionButtons from "./drawing/DrawingActionButtons.js";
import DrawingStyleControls from "./drawing/DrawingStyleControls.js";
import DrawingToolButton from "./drawing/DrawingToolButton.js";
import DrawingVariantToolButton from "./drawing/DrawingVariantToolButton.js";
import { drawingVariantLabel } from "./drawing/drawingToolbarI18n.js";
import {
  CALCULATED_VARIANTS,
  CHART_TYPE_VARIANTS,
  ContinuousDrawingIcon,
  AutoSelectIcon,
  CURSOR_VARIANTS,
  EraserIcon,
  FibonacciIcon,
  FREEHAND_VARIANTS,
  LINE_VARIANTS,
  MagnetIcon,
  POSITION_VARIANTS,
  SHAPE_VARIANTS,
  TEXT_VARIANTS,
} from "./drawing/drawingToolbarDefinitions.js";
import FibLevelsPanel from "./drawing/FibLevelsPanel.js";
import PositionSettingsPanel from "./drawing/PositionSettingsPanel.js";
import { useDrawingToolbarController } from "./drawing/useDrawingToolbarController.js";
import type { ToolbarVariant } from "./drawing/drawingToolbarDefinitions.js";
import type { DrawingStylePatch } from "../features/drawings/drawingInteractionController.js";
import type { SelectedDrawingMeta } from "../features/drawings/drawingSelectionController.js";
import type { DrawingToolId, FibonacciLevel } from "../features/drawings/drawingTypes.js";
import type { MainChartType } from "../shared/mainChartTypes.js";

export interface DrawingToolbarProps {
  activeTool: DrawingToolId | null;
  onToolChange?: (tool: DrawingToolId | null) => void;
  drawingInteractionReady?: boolean;
  penColor: string;
  onPenColorChange?: (color: string) => void;
  penSize: number;
  onPenSizeChange?: (size: number) => void;
  onClearAll(): void;
  drawingsHidden?: boolean;
  onToggleDrawingsHidden(): void;
  drawingSnapEnabled?: boolean;
  onDrawingSnapEnabledChange?: (enabled: boolean) => void;
  drawingContinuousEnabled?: boolean;
  drawingAutoSelectEnabled?: boolean;
  onDrawingContinuousEnabledChange?: (enabled: boolean) => void;
  onDrawingAutoSelectEnabledChange?: (enabled: boolean) => void;
  textFontSize?: number;
  onTextFontSizeChange?: (size: number) => void;
  textBold?: boolean;
  onTextBoldChange?: (bold: boolean) => void;
  textItalic?: boolean;
  onTextItalicChange?: (italic: boolean) => void;
  fibLevels?: FibonacciLevel[] | null;
  onFibLevelsChange?: (levels: FibonacciLevel[] | null) => void;
  fibInverted?: boolean;
  onFibInvertedChange?: (inverted: boolean) => void;
  positionSize?: number;
  onPositionSizeChange(size: number): void;
  selectedDrawing?: SelectedDrawingMeta | null;
  onSelectedDrawingStyleChange?: (patch: DrawingStylePatch) => void;
  exportPanelOpen?: boolean;
  exportInProgress?: boolean;
  onToggleExportPanel?: () => void;
  chartType?: MainChartType;
  onChartTypeChange?: (chartType: MainChartType) => void;
}

const DEFAULT_LINE_VARIANT = (() => {
  const variant = LINE_VARIANTS.find((item) => item.id === "line-segment");
  if (!variant) throw new Error("Missing required line-segment toolbar variant");
  return variant;
})();

const DrawingToolbar = memo(function DrawingToolbar({
  activeTool,
  onToolChange,
  drawingInteractionReady = true,
  penColor,
  onPenColorChange,
  penSize,
  onPenSizeChange,
  onClearAll,
  drawingsHidden = false,
  onToggleDrawingsHidden,
  drawingSnapEnabled = true,
  onDrawingSnapEnabledChange,
  drawingContinuousEnabled = false,
  drawingAutoSelectEnabled = false,
  onDrawingContinuousEnabledChange,
  onDrawingAutoSelectEnabledChange,
  // Text settings
  textFontSize = 14,
  onTextFontSizeChange,
  textBold = false,
  onTextBoldChange,
  textItalic = false,
  onTextItalicChange,
  // Fibonacci settings
  fibLevels,
  onFibLevelsChange,
  fibInverted = false,
  onFibInvertedChange,
  // Position settings
  positionSize = 1000,
  onPositionSizeChange,
  exportPanelOpen = false,
  exportInProgress = false,
  onToggleExportPanel,
  chartType = "candlestick",
  onChartTypeChange,
}: DrawingToolbarProps) {
  useLocale();
  useEffect(() => {
    markPerfOnce("lazy.drawingToolbar.ready");
  }, []);

  const chartTypeDescriptor = getChartTypeDescriptor(chartType);
  const drawingAnchorMode = chartTypeDescriptor.drawingAnchorMode;
  const usesSourceLineageAnchors = drawingAnchorMode
    === CHART_DRAWING_ANCHOR_MODES.SOURCE_LINEAGE;
  const drawingFeaturesEnabled = supportsDrawingAnchorMode(drawingAnchorMode);
  const effectiveActiveTool = drawingToolForAnchorMode(drawingAnchorMode, activeTool);
  const handleCapabilityToolChange = useCallback((nextTool: DrawingToolId | null) => {
    if (nextTool == null || supportsDrawingTool(drawingAnchorMode, nextTool)) {
      onToolChange?.(nextTool);
    }
  }, [drawingAnchorMode, onToolChange]);
  const isVariantDisabled = useCallback(
    (variant: ToolbarVariant<DrawingToolId>) => !supportsDrawingTool(drawingAnchorMode, variant.id)
      || ((variant.id.startsWith("measure-") || isCalculatedToolId(variant.id)
        || variant.id === "callout" || variant.id === "price-label")
        && resolveDrawingHostInteractionSurfaceMode() !== "overlay"),
    [drawingAnchorMode],
  );

  const {
    chartTypeBtnRef,
    calculatedGroup,
    closeFlyout,
    currentChartType,
    currentCursorIcon,
    currentCursorId,
    currentCursorLabel,
    currentFreehandIcon,
    currentFreehandId,
    currentFreehandLabel,
    currentLineIcon,
    currentLineLabel,
    currentPosIcon,
    currentPosLabel,
    currentShapeIcon,
    currentShapeLabel,
    cursorBtnRef,
    fibBtnRef,
    flyoutOpen,
    freehandBtnRef,
    freehandOptionLabel,
    handleChartTypeClick,
    handleCursorClick,
    handleCursorContextMenu,
    handleCursorDblClick,
    handleEraserClick,
    handleExportClick,
    handleFibonacciClick,
    handleFibonacciSettingsContextMenu,
    handleFreehandClick,
    handleFreehandContextMenu,
    handleFreehandDblClick,
    handleLineClick,
    handleLineContextMenu,
    handleLineDblClick,
    handlePositionClick,
    handlePositionContextMenu,
    handlePositionDblClick,
    handleSelectChartType,
    handleSelectCursorVariant,
    handleSelectFreehandVariant,
    handleSelectLineVariant,
    handleSelectPositionVariant,
    handleSelectShapeVariant,
    handleShapeClick,
    handleShapeContextMenu,
    handleShapeDblClick,
    handleTextClick,
    handleTextContextMenu,
    handleTextDblClick,
    handleSelectTextVariant,
    currentTextIcon,
    currentTextId,
    currentTextLabel,
    textBtnRef,
    handleToggleFibonacciSettings,
    handleTogglePositionSettings,
    isCursorActive,
    isEraserActive,
    isFibonacciActive,
    isFreehandActive,
    isLineActive,
    isPositionActive,
    isShapeActive,
    isTextActive,
    lineBtnRef,
    lineVariant,
    posBtnRef,
    posVariant,
    shapeBtnRef,
    shapeVariant,
    showFibonacciOptions,
    showLineOptions,
    showPenOptions,
    showPositionOptions,
    showShapeOptions,
    showTextOptions,
  } = useDrawingToolbarController({
    activeTool: effectiveActiveTool,
    chartType,
    onToolChange: handleCapabilityToolChange,
    ...(onChartTypeChange === undefined ? {} : { onChartTypeChange }),
    ...(onToggleExportPanel === undefined ? {} : { onToggleExportPanel }),
  });

  const handleStrokeColorChange = useCallback((color: string) => {
    onPenColorChange?.(color);
  }, [onPenColorChange]);

  const handleStrokeSizeChange = useCallback((lineWidth: number) => {
    onPenSizeChange?.(lineWidth);
  }, [onPenSizeChange]);
  const drawingCapabilitiesDisabled = !drawingFeaturesEnabled;
  const drawingGestureToolsDisabled = drawingCapabilitiesDisabled || !drawingInteractionReady;
  const cursorToolsDisabled = !hasSupportedDrawingVariant(drawingAnchorMode, CURSOR_VARIANTS);
  const freehandToolsDisabled = drawingGestureToolsDisabled
    || !hasSupportedDrawingVariant(drawingAnchorMode, FREEHAND_VARIANTS);
  const eraserDisabled = drawingGestureToolsDisabled
    || !supportsDrawingTool(drawingAnchorMode, "eraser");
  const lineToolsDisabled = drawingGestureToolsDisabled
    || !hasSupportedDrawingVariant(drawingAnchorMode, LINE_VARIANTS);
  const shapeToolsDisabled = drawingGestureToolsDisabled
    || !hasSupportedDrawingVariant(drawingAnchorMode, SHAPE_VARIANTS);
  const textDisabled = drawingGestureToolsDisabled
    || !hasSupportedDrawingVariant(drawingAnchorMode, TEXT_VARIANTS);
  const fibonacciDisabled = drawingGestureToolsDisabled
    || !supportsDrawingTool(drawingAnchorMode, "fibonacci");
  const positionToolsDisabled = drawingGestureToolsDisabled
    || !hasSupportedDrawingVariant(drawingAnchorMode, POSITION_VARIANTS);
  // Calculated drawings are painted only by the scene overlay.
  const calculatedToolsDisabled = drawingGestureToolsDisabled
    || !hasSupportedDrawingVariant(drawingAnchorMode, CALCULATED_VARIANTS)
    || resolveDrawingHostInteractionSurfaceMode() !== "overlay";
  const lineVariantSupported = supportsDrawingTool(drawingAnchorMode, lineVariant);
  const displayedLineVariant = lineVariantSupported
    ? (LINE_VARIANTS.find((variant) => variant.id === lineVariant) || DEFAULT_LINE_VARIANT)
    : DEFAULT_LINE_VARIANT;
  const handleCapabilityLineClick = useCallback((event: MouseEvent<HTMLButtonElement>) => {
    if (lineVariantSupported) {
      handleLineClick(event);
      return;
    }
    if (event?.detail > 1) return;
    if (isLineActive) handleCapabilityToolChange(null);
    else handleSelectLineVariant(DEFAULT_LINE_VARIANT.id);
    closeFlyout();
  }, [
    closeFlyout,
    handleCapabilityToolChange,
    handleLineClick,
    handleSelectLineVariant,
    isLineActive,
    lineVariantSupported,
  ]);
  const drawingToolTitle = !drawingFeaturesEnabled
    ? t("drawing.unsupported", { chartType: drawingVariantLabel(currentChartType) })
    : t("drawing.initializing");
  const snapTitle = usesSourceLineageAnchors
    ? (drawingSnapEnabled
        ? t("drawing.snap.sourceEnabled")
        : t("drawing.snap.sourcePriceDisabled"))
    : (drawingSnapEnabled
        ? t("drawing.snap.enabled")
        : t("drawing.snap.disabled"));
  const continuousDrawingTitle = drawingContinuousEnabled
    ? t("drawing.continuous.enabled")
    : t("drawing.continuous.disabled");

  return (
    <div
      className="drawing-toolbar"
      data-drawing-toolbar-state={drawingInteractionReady ? "ready" : "waiting-for-engine"}
      aria-busy={!drawingInteractionReady}
    >
      <DrawingVariantToolButton
        active={flyoutOpen === "chart-type"}
        anchorRef={chartTypeBtnRef}
        buttonClassName="chart-type-tool-btn"
        currentId={chartType}
        dataChartType={chartType}
        flyoutClassName="chart-type-flyout"
        flyoutKey="chart-type"
        flyoutOpen={flyoutOpen}
        icon={currentChartType.icon}
        onClick={handleChartTypeClick}
        onCloseFlyout={closeFlyout}
        onSelect={handleSelectChartType}
        title={t("drawing.chartType", { type: drawingVariantLabel(currentChartType) })}
        variants={CHART_TYPE_VARIANTS}
        wrapperClassName="chart-type-tool-wrapper"
      />

      <div className="drawing-toolbar-divider" />

      <DrawingVariantToolButton
        active={isCursorActive}
        anchorRef={cursorBtnRef}
        currentId={currentCursorId}
        dataDrawingTool="cursor"
        disabled={cursorToolsDisabled}
        flyoutKey="cursor"
        flyoutOpen={flyoutOpen}
        icon={currentCursorIcon}
        onClick={handleCursorClick}
        onCloseFlyout={closeFlyout}
        onContextMenu={handleCursorContextMenu}
        onDoubleClick={handleCursorDblClick}
        onSelect={handleSelectCursorVariant}
        title={cursorToolsDisabled ? drawingToolTitle : t("drawing.switch.cursor", { tool: currentCursorLabel })}
        variants={CURSOR_VARIANTS}
        isVariantDisabled={isVariantDisabled}
      />

      <DrawingVariantToolButton
        active={isFreehandActive}
        anchorRef={freehandBtnRef}
        currentId={currentFreehandId}
        dataDrawingTool={currentFreehandId}
        disabled={freehandToolsDisabled}
        flyoutKey="freehand"
        flyoutOpen={flyoutOpen}
        icon={currentFreehandIcon}
        onClick={handleFreehandClick}
        onCloseFlyout={closeFlyout}
        onContextMenu={handleFreehandContextMenu}
        onDoubleClick={handleFreehandDblClick}
        onSelect={handleSelectFreehandVariant}
        title={freehandToolsDisabled ? drawingToolTitle : t("drawing.switch.pen", { tool: currentFreehandLabel })}
        variants={FREEHAND_VARIANTS}
        isVariantDisabled={isVariantDisabled}
      />

      <DrawingToolButton
        active={isEraserActive}
        dataDrawingTool="eraser"
        disabled={eraserDisabled}
        icon={EraserIcon}
        onClick={handleEraserClick}
        title={eraserDisabled ? drawingToolTitle : t("drawing.eraser")}
      />

      <DrawingVariantToolButton
        active={isLineActive}
        anchorRef={lineBtnRef}
        currentId={displayedLineVariant.id}
        dataDrawingTool={displayedLineVariant.id}
        disabled={lineToolsDisabled}
        flyoutKey="line"
        flyoutOpen={flyoutOpen}
        icon={lineVariantSupported ? currentLineIcon : displayedLineVariant.icon}
        onClick={handleCapabilityLineClick}
        onCloseFlyout={closeFlyout}
        onContextMenu={handleLineContextMenu}
        onDoubleClick={handleLineDblClick}
        onSelect={handleSelectLineVariant}
        title={lineToolsDisabled ? drawingToolTitle : t("drawing.switch.line", { tool: lineVariantSupported ? currentLineLabel : drawingVariantLabel(displayedLineVariant) })}
        variants={LINE_VARIANTS}
        isVariantDisabled={isVariantDisabled}
      />

      <DrawingVariantToolButton
        active={isShapeActive}
        anchorRef={shapeBtnRef}
        currentId={shapeVariant}
        dataDrawingTool={shapeVariant}
        disabled={shapeToolsDisabled}
        flyoutKey="shape"
        flyoutOpen={flyoutOpen}
        icon={currentShapeIcon}
        onClick={handleShapeClick}
        onCloseFlyout={closeFlyout}
        onContextMenu={handleShapeContextMenu}
        onDoubleClick={handleShapeDblClick}
        onSelect={handleSelectShapeVariant}
        title={shapeToolsDisabled ? drawingToolTitle : t("drawing.switch.shape", { tool: currentShapeLabel })}
        variants={SHAPE_VARIANTS}
        isVariantDisabled={isVariantDisabled}
      />

      <DrawingVariantToolButton
        active={isTextActive}
        anchorRef={textBtnRef}
        currentId={currentTextId}
        dataDrawingTool={currentTextId}
        disabled={textDisabled}
        flyoutKey="text"
        flyoutOpen={flyoutOpen}
        icon={currentTextIcon}
        onClick={handleTextClick}
        onCloseFlyout={closeFlyout}
        onContextMenu={handleTextContextMenu}
        onDoubleClick={handleTextDblClick}
        onSelect={handleSelectTextVariant}
        title={textDisabled ? drawingToolTitle : currentTextId === "text" ? t("drawing.textNote") : currentTextLabel}
        variants={TEXT_VARIANTS}
        isVariantDisabled={isVariantDisabled}
      />

      <DrawingToolButton
        active={isFibonacciActive}
        anchorRef={fibBtnRef}
        dataDrawingTool="fibonacci"
        disabled={fibonacciDisabled}
        icon={FibonacciIcon}
        onClick={handleFibonacciClick}
        onContextMenu={handleFibonacciSettingsContextMenu}
        onDoubleClick={handleToggleFibonacciSettings}
        showVariantIndicator
        title={fibonacciDisabled ? drawingToolTitle : t("drawing.fibonacciHint")}
      >
        {flyoutOpen === "fib-levels" && (
          <FibLevelsPanel
            {...(fibLevels === undefined ? {} : { levels: fibLevels })}
            onLevelsChange={(levels) => {
              onFibLevelsChange?.(levels);
            }}
            inverted={fibInverted}
            onInvertedChange={(v) => {
              onFibInvertedChange?.(v);
            }}
            onClose={closeFlyout}
            anchorRef={fibBtnRef}
          />
        )}
      </DrawingToolButton>

      <DrawingVariantToolButton
        active={calculatedGroup.active}
        anchorRef={calculatedGroup.anchorRef}
        currentId={calculatedGroup.currentId}
        dataDrawingTool={calculatedGroup.currentId}
        disabled={calculatedToolsDisabled}
        flyoutKey="calculated"
        flyoutOpen={flyoutOpen}
        icon={calculatedGroup.icon}
        onClick={calculatedGroup.onClick}
        onCloseFlyout={closeFlyout}
        onContextMenu={calculatedGroup.onContextMenu}
        onDoubleClick={calculatedGroup.onDoubleClick}
        onSelect={calculatedGroup.onSelect}
        title={calculatedToolsDisabled ? drawingToolTitle : t("drawing.switch.calculated", { tool: calculatedGroup.label })}
        variants={CALCULATED_VARIANTS}
        isVariantDisabled={isVariantDisabled}
      />

      <DrawingVariantToolButton
        active={isPositionActive}
        anchorRef={posBtnRef}
        currentId={posVariant}
        dataDrawingTool={posVariant}
        disabled={positionToolsDisabled}
        flyoutKey="position"
        flyoutOpen={flyoutOpen}
        icon={currentPosIcon}
        onClick={handlePositionClick}
        onCloseFlyout={closeFlyout}
        onContextMenu={handlePositionContextMenu}
        onDoubleClick={handlePositionDblClick}
        onSelect={handleSelectPositionVariant}
        title={positionToolsDisabled ? drawingToolTitle : t("drawing.switch.position", { tool: currentPosLabel })}
        variants={POSITION_VARIANTS}
        isVariantDisabled={isVariantDisabled}
      >
        {flyoutOpen === "position-settings" && (
          <PositionSettingsPanel
            positionSize={positionSize}
            onPositionSizeChange={onPositionSizeChange}
            onClose={closeFlyout}
            anchorRef={posBtnRef}
          />
        )}
      </DrawingVariantToolButton>

      <DrawingToolButton
        active={drawingSnapEnabled}
        disabled={drawingCapabilitiesDisabled}
        icon={MagnetIcon}
        onClick={() => onDrawingSnapEnabledChange?.(!drawingSnapEnabled)}
        title={drawingCapabilitiesDisabled
          ? drawingToolTitle
          : snapTitle}
      />

      <DrawingToolButton
        active={drawingContinuousEnabled}
        dataDrawingTool="continuous"
        disabled={drawingCapabilitiesDisabled}
        icon={ContinuousDrawingIcon}
        onClick={() => onDrawingContinuousEnabledChange?.(!drawingContinuousEnabled)}
        title={drawingCapabilitiesDisabled
          ? drawingToolTitle
          : continuousDrawingTitle}
      />

      <DrawingToolButton
        active={drawingAutoSelectEnabled}
        dataDrawingTool="auto-select"
        disabled={drawingCapabilitiesDisabled}
        icon={AutoSelectIcon}
        onClick={() => onDrawingAutoSelectEnabledChange?.(!drawingAutoSelectEnabled)}
        title={drawingCapabilitiesDisabled ? drawingToolTitle : t(drawingAutoSelectEnabled ? "drawing.autoSelect.on" : "drawing.autoSelect.off")}
      />

      {/* Divider */}
      <div className="drawing-toolbar-divider" />

      {!drawingCapabilitiesDisabled && <DrawingStyleControls
        freehandOptionLabel={freehandOptionLabel}
        onOpenPositionSettings={handleTogglePositionSettings}
        onPenColorChange={handleStrokeColorChange}
        onPenSizeChange={handleStrokeSizeChange}
        {...(onTextBoldChange === undefined ? {} : { onTextBoldChange })}
        {...(onTextFontSizeChange === undefined ? {} : { onTextFontSizeChange })}
        {...(onTextItalicChange === undefined ? {} : { onTextItalicChange })}
        penColor={penColor}
        penSize={penSize}
        positionSize={positionSize}
        showFibonacciOptions={showFibonacciOptions}
        showLineOptions={showLineOptions}
        showPenOptions={showPenOptions}
        showPositionOptions={showPositionOptions}
        showShapeOptions={showShapeOptions}
        showTextOptions={showTextOptions}
        textBold={textBold}
        textFontSize={textFontSize}
        textItalic={textItalic}
      />}

      <DrawingActionButtons
        drawingsHidden={drawingsHidden}
        exportInProgress={exportInProgress}
        exportPanelOpen={exportPanelOpen}
        onClearAll={onClearAll}
        onToggleDrawingsHidden={onToggleDrawingsHidden}
        onToggleExportPanel={handleExportClick}
      />
    </div>
  );
});

export default DrawingToolbar;
