import { useCallback, useEffect, useState } from "react";
import type { MouseEvent as ReactMouseEvent, RefObject } from "react";
import type { createMainSeries } from "../chart-adapter/seriesLifecycle.js";
import type { PanePointerLayout } from "./panePointerModel.js";
import {
  applyPanePriceScaleOptions,
  resolvePanePriceScaleMenu,
  type PriceScaleContextMenuState,
  type PriceScaleOptionsPatch,
} from "./panePriceScaleMenuModel.js";

interface PanePriceScaleMenuOptions {
  chartRef: RefObject<Parameters<typeof createMainSeries>[0] | null>;
  containerRef: RefObject<HTMLDivElement | null>;
  activePaneIdsRef: RefObject<readonly string[]>;
  panePointerLayoutRef: RefObject<PanePointerLayout | null>;
  onScaleChanged: () => void;
  priceAtPaneY?: (paneIndex: number, y: number) => number | null;
}

/** Owns menu selection and document listeners; chart operations resolve the live pane id. */
export function usePanePriceScaleMenu({
  chartRef, containerRef, activePaneIdsRef, panePointerLayoutRef, onScaleChanged, priceAtPaneY,
}: PanePriceScaleMenuOptions) {
  const [contextMenu, setContextMenu] = useState<PriceScaleContextMenuState | null>(null);
  const close = useCallback(() => setContextMenu(null), []);
  const handleContextMenu = useCallback((event: ReactMouseEvent<HTMLDivElement>) => {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;
    const next = resolvePanePriceScaleMenu({
      chart: chartRef.current,
      activePaneIds: activePaneIdsRef.current,
      layout: panePointerLayoutRef.current,
      rect,
      clientX: event.clientX,
      clientY: event.clientY,
      priceAtPaneY,
    });
    if (!next) return;
    event.preventDefault();
    event.stopPropagation();
    setContextMenu(next);
  }, [activePaneIdsRef, chartRef, containerRef, panePointerLayoutRef, priceAtPaneY]);
  const applyOptions = useCallback((options: PriceScaleOptionsPatch) => {
    if (!contextMenu || !applyPanePriceScaleOptions(
      chartRef.current, activePaneIdsRef.current, contextMenu.paneId, options,
    )) return false;
    onScaleChanged();
    return true;
  }, [activePaneIdsRef, chartRef, contextMenu, onScaleChanged]);

  useEffect(() => {
    if (!contextMenu) return undefined;
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    const timer = setTimeout(() => {
      document.addEventListener("mousedown", close);
      document.addEventListener("keydown", handleKey);
    }, 0);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", handleKey);
    };
  }, [close, contextMenu]);

  return { contextMenu, close, handleContextMenu, applyOptions };
}
