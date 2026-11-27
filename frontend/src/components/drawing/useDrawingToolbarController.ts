import { useCallback, useRef, useState } from "react";
import type { MouseEvent } from "react";
import {
  CHART_TYPE_VARIANTS,
  CURSOR_VARIANTS,
  FREEHAND_VARIANTS,
  LINE_VARIANTS,
  LongPositionIcon,
  MouseDefaultIcon,
  PenIcon,
  POSITION_VARIANTS,
  RectangleIcon,
  SegmentIcon,
  SHAPE_VARIANTS,
  TEXT_VARIANTS,
  TextIcon,
} from "./drawingToolbarDefinitions.js";
import { drawingVariantLabel } from "./drawingToolbarI18n.js";
import { t } from "../../i18n/index.js";
import type { LineToolbarToolId, TextToolbarToolId, ToolbarVariant } from "./drawingToolbarDefinitions.js";
import type {
  DrawingToolId,
  FreehandToolId,
  PassiveCursorToolId,
  PositionToolId,
  ShapeToolId,
} from "../../features/drawings/drawingTypes.js";
import type { MainChartType } from "../../shared/mainChartTypes.js";

export type DrawingToolbarFlyoutKey =
  | "chart-type"
  | "cursor"
  | "freehand"
  | "line"
  | "shape"
  | "text"
  | "fib-levels"
  | "position"
  | "position-settings";

export interface DrawingToolbarControllerOptions {
  activeTool: DrawingToolId | null;
  chartType?: MainChartType;
  onChartTypeChange?: (chartType: MainChartType) => void;
  onToolChange(tool: DrawingToolId | null): void;
  onToggleExportPanel?: () => void;
}

function findVariant<TId extends string>(
  variants: readonly ToolbarVariant<TId>[],
  id: TId,
): ToolbarVariant<TId> | undefined {
  return variants.find((variant) => variant.id === id);
}

function requireVariant<TId extends string>(
  variants: readonly ToolbarVariant<TId>[],
  id: TId,
  fallbackId: TId,
): ToolbarVariant<TId> {
  const variant = findVariant(variants, id) ?? findVariant(variants, fallbackId);
  if (!variant) {
    throw new Error(`Missing required toolbar variant: ${fallbackId}`);
  }
  return variant;
}

export function useDrawingToolbarController({
  activeTool,
  chartType = "candlestick",
  onChartTypeChange,
  onToolChange,
  onToggleExportPanel,
}: DrawingToolbarControllerOptions) {
  const [cursorVariant, setCursorVariant] = useState<PassiveCursorToolId>("cursor-default");
  const [freehandVariant, setFreehandVariant] = useState<FreehandToolId>("pen");
  const [lineVariant, setLineVariant] = useState<LineToolbarToolId>("line-segment");
  const [shapeVariant, setShapeVariant] = useState<ShapeToolId>("shape-rectangle");
  const [posVariant, setPosVariant] = useState<PositionToolId>("position-long");
  const [textVariant, setTextVariant] = useState<TextToolbarToolId>("text");
  const [flyoutOpen, setFlyoutOpen] = useState<DrawingToolbarFlyoutKey | null>(null);

  const chartTypeBtnRef = useRef<HTMLDivElement | null>(null);
  const cursorBtnRef = useRef<HTMLDivElement | null>(null);
  const freehandBtnRef = useRef<HTMLDivElement | null>(null);
  const lineBtnRef = useRef<HTMLDivElement | null>(null);
  const shapeBtnRef = useRef<HTMLDivElement | null>(null);
  const fibBtnRef = useRef<HTMLDivElement | null>(null);
  const posBtnRef = useRef<HTMLDivElement | null>(null);

  const cursorClickTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const freehandClickTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const clickTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const shapeClickTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const posClickTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const textClickTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const textBtnRef = useRef<HTMLDivElement | null>(null);

  const activeCursorVariant = CURSOR_VARIANTS.find((variant) => variant.id === activeTool);
  const activeFreehandVariant = FREEHAND_VARIANTS.find((variant) => variant.id === activeTool);
  const activeLineVariant = LINE_VARIANTS.find((variant) => variant.id === activeTool);
  const activeShapeVariant = SHAPE_VARIANTS.find((variant) => variant.id === activeTool);
  const activePositionVariant = POSITION_VARIANTS.find((variant) => variant.id === activeTool);
  const isCursorActive = activeCursorVariant != null;
  const isFreehandActive = activeFreehandVariant != null;
  const isEraserActive = activeTool === "eraser";
  const isLineActive = activeLineVariant != null;
  const isShapeActive = activeShapeVariant != null;
  const activeTextVariant = TEXT_VARIANTS.find((variant) => variant.id === activeTool);
  const isTextActive = activeTextVariant != null;
  const isFibonacciActive = activeTool === "fibonacci";
  const isPositionActive = activePositionVariant != null;

  const currentChartType = requireVariant(CHART_TYPE_VARIANTS, chartType, "candlestick");

  const closeFlyout = useCallback(() => {
    setFlyoutOpen(null);
  }, []);

  const handleChartTypeClick = useCallback(() => {
    setFlyoutOpen((prev) => (prev === "chart-type" ? null : "chart-type"));
  }, []);

  const handleSelectChartType = useCallback((id: MainChartType) => {
    onChartTypeChange?.(id);
  }, [onChartTypeChange]);

  const handleCursorClick = useCallback((event: MouseEvent<HTMLButtonElement>) => {
    if (event?.detail > 1) return;
    onToolChange(isCursorActive ? activeTool : cursorVariant);
    setFlyoutOpen(null);
  }, [activeTool, cursorVariant, isCursorActive, onToolChange]);

  const handleCursorDblClick = useCallback(() => {
    if (cursorClickTimerRef.current) {
      clearTimeout(cursorClickTimerRef.current);
      cursorClickTimerRef.current = null;
    }
    setFlyoutOpen((prev) => (prev === "cursor" ? null : "cursor"));
  }, []);

  const handleCursorContextMenu = useCallback((event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    if (cursorClickTimerRef.current) {
      clearTimeout(cursorClickTimerRef.current);
      cursorClickTimerRef.current = null;
    }
    setFlyoutOpen((prev) => (prev === "cursor" ? null : "cursor"));
  }, []);

  const handleSelectCursorVariant = useCallback(
    (id: PassiveCursorToolId) => {
      setCursorVariant(id);
      onToolChange(id);
    },
    [onToolChange],
  );

  const handleFreehandClick = useCallback((event: MouseEvent<HTMLButtonElement>) => {
    if (event?.detail > 1) return;
    if (!isFreehandActive) {
      onToolChange(freehandVariant);
      setFlyoutOpen(null);
      return;
    }
    if (freehandClickTimerRef.current) return;
    freehandClickTimerRef.current = setTimeout(() => {
      freehandClickTimerRef.current = null;
      onToolChange(null);
      setFlyoutOpen(null);
    }, 200);
  }, [freehandVariant, isFreehandActive, onToolChange]);

  const handleFreehandDblClick = useCallback(() => {
    if (freehandClickTimerRef.current) {
      clearTimeout(freehandClickTimerRef.current);
      freehandClickTimerRef.current = null;
    }
    setFlyoutOpen((prev) => (prev === "freehand" ? null : "freehand"));
  }, []);

  const handleFreehandContextMenu = useCallback((event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    if (freehandClickTimerRef.current) {
      clearTimeout(freehandClickTimerRef.current);
      freehandClickTimerRef.current = null;
    }
    setFlyoutOpen((prev) => (prev === "freehand" ? null : "freehand"));
  }, []);

  const handleSelectFreehandVariant = useCallback(
    (id: FreehandToolId) => {
      setFreehandVariant(id);
      onToolChange(id);
    },
    [onToolChange],
  );

  const handleEraserClick = useCallback(() => {
    onToolChange(isEraserActive ? null : "eraser");
    setFlyoutOpen(null);
  }, [isEraserActive, onToolChange]);

  const handleTextClick = useCallback((event?: MouseEvent<HTMLButtonElement>) => {
    if ((event?.detail ?? 0) > 1) return;
    if (!isTextActive) {
      onToolChange(textVariant);
      setFlyoutOpen(null);
      return;
    }
    if (textClickTimerRef.current) return;
    // A double-click opens the variants instead of leaving the tool.
    textClickTimerRef.current = setTimeout(() => {
      textClickTimerRef.current = null;
      onToolChange(null);
      setFlyoutOpen(null);
    }, 200);
  }, [isTextActive, onToolChange, textVariant]);

  const toggleTextFlyout = useCallback((event?: MouseEvent<HTMLButtonElement>) => {
    event?.preventDefault();
    if (textClickTimerRef.current) {
      clearTimeout(textClickTimerRef.current);
      textClickTimerRef.current = null;
    }
    setFlyoutOpen((prev) => (prev === "text" ? null : "text"));
  }, []);

  const handleSelectTextVariant = useCallback((id: TextToolbarToolId) => {
    setTextVariant(id);
    onToolChange(id);
  }, [onToolChange]);

  const handleFibonacciClick = useCallback(() => {
    onToolChange(isFibonacciActive ? null : "fibonacci");
    setFlyoutOpen(null);
  }, [isFibonacciActive, onToolChange]);

  const handleToggleFibonacciSettings = useCallback(() => {
    setFlyoutOpen((prev) => (prev === "fib-levels" ? null : "fib-levels"));
  }, []);

  const handleFibonacciSettingsContextMenu = useCallback(
    (event: MouseEvent<HTMLButtonElement>) => {
      event.preventDefault();
      handleToggleFibonacciSettings();
    },
    [handleToggleFibonacciSettings],
  );

  const handleLineClick = useCallback((event: MouseEvent<HTMLButtonElement>) => {
    if (event?.detail > 1) return;
    if (!isLineActive) {
      onToolChange(lineVariant);
      setFlyoutOpen(null);
      return;
    }
    if (clickTimerRef.current) return;
    clickTimerRef.current = setTimeout(() => {
      clickTimerRef.current = null;
      onToolChange(null);
      setFlyoutOpen(null);
    }, 200);
  }, [isLineActive, lineVariant, onToolChange]);

  const handleLineDblClick = useCallback(() => {
    if (clickTimerRef.current) {
      clearTimeout(clickTimerRef.current);
      clickTimerRef.current = null;
    }
    setFlyoutOpen((prev) => (prev === "line" ? null : "line"));
  }, []);

  const handleLineContextMenu = useCallback((event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    if (clickTimerRef.current) {
      clearTimeout(clickTimerRef.current);
      clickTimerRef.current = null;
    }
    setFlyoutOpen((prev) => (prev === "line" ? null : "line"));
  }, []);

  const handleSelectLineVariant = useCallback(
    (id: LineToolbarToolId) => {
      setLineVariant(id);
      onToolChange(id);
    },
    [onToolChange],
  );

  const handleShapeClick = useCallback((event: MouseEvent<HTMLButtonElement>) => {
    if (event?.detail > 1) return;
    if (!isShapeActive) {
      onToolChange(shapeVariant);
      setFlyoutOpen(null);
      return;
    }
    if (shapeClickTimerRef.current) return;
    shapeClickTimerRef.current = setTimeout(() => {
      shapeClickTimerRef.current = null;
      onToolChange(null);
      setFlyoutOpen(null);
    }, 200);
  }, [isShapeActive, onToolChange, shapeVariant]);

  const handleShapeDblClick = useCallback(() => {
    if (shapeClickTimerRef.current) {
      clearTimeout(shapeClickTimerRef.current);
      shapeClickTimerRef.current = null;
    }
    setFlyoutOpen((prev) => (prev === "shape" ? null : "shape"));
  }, []);

  const handleShapeContextMenu = useCallback((event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    if (shapeClickTimerRef.current) {
      clearTimeout(shapeClickTimerRef.current);
      shapeClickTimerRef.current = null;
    }
    setFlyoutOpen((prev) => (prev === "shape" ? null : "shape"));
  }, []);

  const handleSelectShapeVariant = useCallback(
    (id: ShapeToolId) => {
      setShapeVariant(id);
      onToolChange(id);
    },
    [onToolChange],
  );

  const handlePositionClick = useCallback((event: MouseEvent<HTMLButtonElement>) => {
    if (event?.detail > 1) return;
    if (!isPositionActive) {
      onToolChange(posVariant);
      setFlyoutOpen(null);
      return;
    }
    if (posClickTimerRef.current) return;
    posClickTimerRef.current = setTimeout(() => {
      posClickTimerRef.current = null;
      onToolChange(null);
      setFlyoutOpen(null);
    }, 200);
  }, [isPositionActive, onToolChange, posVariant]);

  const handlePositionDblClick = useCallback(() => {
    if (posClickTimerRef.current) {
      clearTimeout(posClickTimerRef.current);
      posClickTimerRef.current = null;
    }
    setFlyoutOpen((prev) => (prev === "position" ? null : "position"));
  }, []);

  const handlePositionContextMenu = useCallback((event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    if (posClickTimerRef.current) {
      clearTimeout(posClickTimerRef.current);
      posClickTimerRef.current = null;
    }
    setFlyoutOpen((prev) => (prev === "position" ? null : "position"));
  }, []);

  const handleSelectPositionVariant = useCallback(
    (id: PositionToolId) => {
      setPosVariant(id);
      onToolChange(id);
    },
    [onToolChange],
  );

  const handleTogglePositionSettings = useCallback(() => {
    setFlyoutOpen((prev) => (prev === "position-settings" ? null : "position-settings"));
  }, []);

  const handleExportClick = useCallback(() => {
    setFlyoutOpen(null);
    onToggleExportPanel?.();
  }, [onToggleExportPanel]);

  const currentCursorId = activeCursorVariant?.id ?? cursorVariant;
  const currentCursor = findVariant(CURSOR_VARIANTS, currentCursorId);
  const currentFreehandId = activeFreehandVariant?.id ?? freehandVariant;
  const currentFreehand = findVariant(FREEHAND_VARIANTS, currentFreehandId);
  const currentLine = activeLineVariant ?? findVariant(LINE_VARIANTS, lineVariant);
  const currentShape = findVariant(SHAPE_VARIANTS, shapeVariant);
  const currentPosition = findVariant(POSITION_VARIANTS, posVariant);
  const currentText = activeTextVariant ?? findVariant(TEXT_VARIANTS, textVariant);

  return {
    chartType,
    chartTypeBtnRef,
    closeFlyout,
    currentChartType,
    currentCursorIcon: currentCursor?.icon || MouseDefaultIcon,
    currentCursorId,
    currentCursorLabel: currentCursor
      ? drawingVariantLabel(currentCursor)
      : t("drawing.variant.cursor-default"),
    currentFreehandIcon: currentFreehand?.icon || PenIcon,
    currentFreehandId,
    currentFreehandLabel: currentFreehand
      ? drawingVariantLabel(currentFreehand)
      : t("drawing.variant.pen"),
    currentLineIcon: currentLine?.icon || SegmentIcon,
    currentLineLabel: currentLine
      ? drawingVariantLabel(currentLine)
      : t("drawing.variant.line-segment"),
    currentPosIcon: currentPosition?.icon || LongPositionIcon,
    currentPosLabel: currentPosition
      ? drawingVariantLabel(currentPosition)
      : t("drawing.variant.position-long"),
    currentShapeIcon: currentShape?.icon || RectangleIcon,
    currentTextIcon: currentText?.icon || TextIcon,
    currentTextId: currentText?.id ?? "text",
    currentTextLabel: currentText ? drawingVariantLabel(currentText) : t("drawing.textNote"),
    currentShapeLabel: currentShape
      ? drawingVariantLabel(currentShape)
      : t("drawing.variant.shape-rectangle"),
    cursorBtnRef,
    fibBtnRef,
    flyoutOpen,
    freehandBtnRef,
    freehandOptionLabel: currentFreehand
      ? drawingVariantLabel(currentFreehand)
      : t("drawing.variant.pen"),
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
    handleTextContextMenu: toggleTextFlyout,
    handleTextDblClick: toggleTextFlyout,
    handleSelectTextVariant,
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
    lineVariant: activeLineVariant?.id ?? lineVariant,
    posBtnRef,
    posVariant,
    shapeBtnRef,
    shapeVariant,
    textBtnRef,
    showFibonacciOptions: isFibonacciActive,
    showLineOptions: isLineActive,
    showPenOptions: isFreehandActive,
    showPositionOptions: isPositionActive,
    showShapeOptions: isShapeActive,
    // Price labels show a price, so only typed text offers font controls.
    showTextOptions: activeTool === "text" || activeTool === "callout",
  };
}
