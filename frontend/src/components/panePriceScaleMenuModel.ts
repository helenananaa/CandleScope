import type { createMainSeries } from "../chart-adapter/seriesLifecycle.js";
import { paneTargetAtClientY, type PanePointerLayout } from "./panePointerModel.js";

type AdapterChart = Parameters<typeof createMainSeries>[0];
type AdapterPriceScale = ReturnType<AdapterChart["priceScale"]>;
type PriceScaleOptions = ReturnType<AdapterPriceScale["options"]>;
export type PriceScaleOptionsPatch = Parameters<AdapterPriceScale["applyOptions"]>[0];

export interface PriceScaleContextMenuState {
  x: number;
  y: number;
  paneId: string;
  paneIndex: number;
  autoScale: boolean;
  invertScale: boolean;
  mode: number;
  /** Price under the pointer on the main pane, for "add alert here". */
  price: number | null;
}

const PRICE_SCALE_CONTEXT_HIT_WIDTH = 96;
const PRICE_SCALE_CONTEXT_MENU_WIDTH = 220;
const PRICE_SCALE_CONTEXT_MENU_HEIGHT = 272;
const PRICE_SCALE_CONTEXT_MENU_MARGIN = 8;

export function resolvePanePriceScaleMenu({
  chart, activePaneIds, layout, rect, clientX, clientY, priceAtPaneY, anywhere = false,
}: {
  /** Open for a right-click anywhere in the pane, not only over the price axis. */
  anywhere?: boolean;
  priceAtPaneY?: ((paneIndex: number, y: number) => number | null) | undefined;
  chart: AdapterChart | null;
  activePaneIds: readonly string[];
  layout: PanePointerLayout | null;
  rect: Pick<DOMRect, "left" | "right" | "top" | "bottom">;
  clientX: number;
  clientY: number;
}): PriceScaleContextMenuState | null {
  if (!anywhere && clientX < rect.right - PRICE_SCALE_CONTEXT_HIT_WIDTH) return null;
  const target = paneTargetAtClientY(layout, clientY);
  if (!target || !chart
    || target.paneIndex >= chart.panes().length
    || activePaneIds[target.paneIndex] !== target.paneId) return null;
  let scaleOptions: PriceScaleOptions;
  try {
    scaleOptions = chart.priceScale("right", target.paneIndex).options();
  } catch {
    return null;
  }
  const margin = PRICE_SCALE_CONTEXT_MENU_MARGIN;
  const maxX = Math.max(rect.left + margin, rect.right - PRICE_SCALE_CONTEXT_MENU_WIDTH - margin);
  const maxY = Math.max(rect.top + margin, rect.bottom - PRICE_SCALE_CONTEXT_MENU_HEIGHT - margin);
  return {
    x: Math.min(Math.max(clientX, rect.left + margin), maxX),
    y: Math.min(Math.max(clientY, rect.top + margin), maxY),
    paneId: target.paneId,
    paneIndex: target.paneIndex,
    autoScale: scaleOptions.autoScale,
    invertScale: scaleOptions.invertScale,
    mode: scaleOptions.mode,
    price: priceAtPaneY?.(
      target.paneIndex,
      clientY - (layout?.boundaries[target.paneIndex]?.top ?? rect.top),
    ) ?? null,
  };
}

export function applyPanePriceScaleOptions(
  chart: AdapterChart | null,
  activePaneIds: readonly string[],
  paneId: string,
  options: PriceScaleOptionsPatch,
): boolean {
  const paneIndex = activePaneIds.indexOf(paneId);
  if (!chart || paneIndex < 0 || paneIndex >= chart.panes().length) return false;
  try {
    chart.priceScale("right", paneIndex).applyOptions(options);
    return true;
  } catch {
    return false;
  }
}
