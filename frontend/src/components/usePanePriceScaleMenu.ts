import { useCallback, useState } from "react";
import type { MouseEvent as ReactMouseEvent, RefObject } from "react";
import type { createMainSeries } from "../chart-adapter/seriesLifecycle.js";
import type { PanePointerLayout } from "./panePointerModel.js";
import {
  applyPanePriceScaleOptions,
  resolvePanePriceScaleMenu,
  type PriceScaleContextMenuState,
  type PriceScaleOptionsPatch,
} from "./panePriceScaleMenuModel.js";
import { isTouchContextMenu } from "../app/touchLongPress.js";

interface PanePriceScaleMenuOptions {
  chartRef: RefObject<Parameters<typeof createMainSeries>[0] | null>;
  containerRef: RefObject<HTMLDivElement | null>;
  activePaneIdsRef: RefObject<readonly string[]>;
  panePointerLayoutRef: RefObject<PanePointerLayout | null>;
  onScaleChanged: () => void;
  priceAtPaneY?: (paneIndex: number, y: number) => number | null;
}

/** Owns the menu's state (the kit Menu closes it on Escape or a click outside); chart operations resolve the live pane id. */
export function usePanePriceScaleMenu({
  chartRef, containerRef, activePaneIdsRef, panePointerLayoutRef, onScaleChanged, priceAtPaneY,
}: PanePriceScaleMenuOptions) {
  const [contextMenu, setContextMenu] = useState<PriceScaleContextMenuState | null>(null);
  const close = useCallback(() => setContextMenu(null), []);
  const handleContextMenu = useCallback((event: ReactMouseEvent<HTMLDivElement>) => {
    // A drawing in progress uses right-click to cancel itself and marks the event handled.
    if (event.defaultPrevented) return;
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
      // A long press in the pane belongs to the crosshair, so on a touch screen the menu opens from
      // the price axis only (app/touchLongPress.ts turns long presses into this event).
      anywhere: !isTouchContextMenu(event.nativeEvent),
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

  return { contextMenu, close, handleContextMenu, applyOptions };
}
