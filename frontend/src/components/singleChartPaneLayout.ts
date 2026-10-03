import type { MutableRefObject } from "react";
import { ensurePane, setPaneHeights } from "../chart-adapter/paneManager.js";
import { chartSeriesTypes } from "../chart-adapter/lightweightChartSurface.js";
import type { createMainSeries, createFutureTimeAxisSeries } from "../chart-adapter/seriesLifecycle.js";
import type { MainSeriesHandle } from "../chart-adapter/chartAdapterTypes.js";
import { axisTimeKey } from "../features/chart-representation/index.js";
import type { AxisTime } from "../features/chart-representation/chartRepresentationTypes.js";
import { loadPaneHeights } from "../features/chart-session/paneLayoutStorage.js";

type AdapterChart = Parameters<typeof createMainSeries>[0];
type FutureTimeAxisSeries = ReturnType<typeof createFutureTimeAxisSeries>;

// Native pane topology and placeholder lifetime belong together: placeholders keep
// otherwise empty panes alive while indicator series are replaced or moved.
interface PanePlaceholderEntry {
  anchorKey: string | null;
  series: FutureTimeAxisSeries;
}

export interface PanePlaceholderState {
  chart: AdapterChart | null;
  seriesByPane: Map<number, PanePlaceholderEntry>;
}

export function resolvePaneHeightLayout(
  storageKey: string | null | undefined,
  subPaneCount: number,
  totalHeight: number,
  mainPaneIndex = 0,
): number[] | null {
  const expectedPaneCount = Math.max(1, subPaneCount + 1);
  const saved = storageKey ? loadPaneHeights()[storageKey] : undefined;
  if (Array.isArray(saved)
    && saved.length === expectedPaneCount
    && saved.every((height) => Number.isFinite(height) && height > 0)) {
    return saved;
  }
  if (subPaneCount <= 0 || !Number.isFinite(totalHeight) || totalHeight <= 0) return null;

  const mainHeight = Math.max(180, Math.round(totalHeight * 0.65));
  const subHeight = Math.max(80, Math.round((totalHeight - mainHeight) / subPaneCount));
  const safeMainPaneIndex = Number.isInteger(mainPaneIndex)
    ? Math.min(Math.max(mainPaneIndex, 0), expectedPaneCount - 1)
    : 0;
  return Array.from(
    { length: expectedPaneCount },
    (_unused, index) => index === safeMainPaneIndex ? mainHeight : subHeight,
  );
}

export function preparePaneLayout(chart: AdapterChart | null, {
  storageKey,
  subPaneCount,
  totalHeight,
  mainPaneIndex = 0,
}: {
  storageKey?: string | null;
  subPaneCount?: number;
  totalHeight?: number;
  mainPaneIndex?: number;
} = {}): boolean {
  const resolvedSubPaneCount = subPaneCount ?? -1;
  const resolvedTotalHeight = totalHeight ?? 0;
  if (!chart || !Number.isInteger(resolvedSubPaneCount) || resolvedSubPaneCount < 0) return false;
  for (let paneIndex = 1; paneIndex <= resolvedSubPaneCount; paneIndex += 1) {
    ensurePane(chart, paneIndex);
  }
  const paneHeights = resolvePaneHeightLayout(
    storageKey,
    resolvedSubPaneCount,
    resolvedTotalHeight,
    mainPaneIndex,
  );
  if (!paneHeights) return resolvedSubPaneCount === 0;
  setPaneHeights(chart, paneHeights);
  return true;
}

export function resolveMainPaneIndex(
  chart: AdapterChart | null | undefined,
  series: MainSeriesHandle | null | undefined,
  fallback = 0,
): number {
  try {
    const paneIndex = series?.getPane?.()?.paneIndex?.();
    if (typeof paneIndex === "number"
      && Number.isInteger(paneIndex)
      && paneIndex >= 0
      && paneIndex < (chart?.panes?.()?.length ?? 0)) {
      return paneIndex;
    }
  } catch {
    // Fall through to the last materialized index while panes are rebuilding.
  }
  return Number.isInteger(fallback) && fallback >= 0 ? fallback : 0;
}

export function moveMainPane(
  chart: AdapterChart | null | undefined,
  series: MainSeriesHandle | null | undefined,
  targetIndex: number,
): number | null {
  const panes = chart?.panes?.() || [];
  if (!series || !Number.isInteger(targetIndex) || targetIndex < 0 || targetIndex >= panes.length) {
    return null;
  }
  const currentIndex = resolveMainPaneIndex(chart, series, 0);
  if (currentIndex === targetIndex) return currentIndex;
  try {
    series.getPane().moveTo(targetIndex);
    return resolveMainPaneIndex(chart, series, targetIndex);
  } catch {
    return null;
  }
}

export function reindexPanePlaceholderSeries(
  placeholderStateRef: MutableRefObject<PanePlaceholderState>,
): void {
  const state = placeholderStateRef.current;
  if (!state.chart || state.seriesByPane.size === 0) return;
  const next = new Map<number, PanePlaceholderEntry>();
  for (const [fallbackIndex, entry] of state.seriesByPane) {
    let paneIndex = fallbackIndex;
    try {
      const resolved = entry.series.getPane?.()?.paneIndex?.();
      if (Number.isInteger(resolved) && resolved >= 0) paneIndex = resolved;
    } catch {
      // Keep the last known key until LWC finishes the structural mutation.
    }
    next.set(paneIndex, entry);
  }
  state.seriesByPane = next;
}

export function ensurePanePlaceholderSeries(
  chart: AdapterChart | null,
  placeholderStateRef: MutableRefObject<PanePlaceholderState>,
  subPaneCount: number,
  anchorTime: AxisTime | null = null,
  { mainPaneIndex = 0 }: { mainPaneIndex?: number } = {},
): void {
  if (!chart || !placeholderStateRef || !Number.isInteger(subPaneCount) || subPaneCount < 0) return;
  if (placeholderStateRef.current.chart !== chart) {
    placeholderStateRef.current = { chart, seriesByPane: new Map() };
  }
  reindexPanePlaceholderSeries(placeholderStateRef);
  const seriesByPane = placeholderStateRef.current.seriesByPane;
  const baseAnchorKey = axisTimeKey(anchorTime);
  const anchorKey = baseAnchorKey && anchorTime && typeof anchorTime === "object"
    ? `${baseAnchorKey}:source:${anchorTime.sourceTime}:ordinal:${anchorTime.sourceOrdinal}`
    : baseAnchorKey;
  for (let paneIndex = 0; paneIndex <= subPaneCount; paneIndex += 1) {
    if (paneIndex === mainPaneIndex) continue;
    ensurePane(chart, paneIndex);
    let entry = seriesByPane.get(paneIndex);
    if (!entry) {
      const series = chart.addSeries(chartSeriesTypes.line, {
        color: "rgba(0, 0, 0, 0)",
        crosshairMarkerVisible: false,
        lastValueVisible: false,
        priceLineVisible: false,
        priceScaleId: "__pane-layout-placeholder",
        title: "",
      }, paneIndex);
      entry = { anchorKey: null, series };
      seriesByPane.set(paneIndex, entry);
    }
    if (anchorKey && anchorTime != null && entry.anchorKey !== anchorKey) {
      entry.series.setData([{ time: anchorTime, value: 0 }]);
      entry.anchorKey = anchorKey;
    }
  }
}

export function trimPanePlaceholderSeries(
  chart: AdapterChart | null,
  placeholderStateRef: MutableRefObject<PanePlaceholderState>,
  retainPaneCount: number,
): void {
  if (!chart || placeholderStateRef?.current?.chart !== chart) return;
  reindexPanePlaceholderSeries(placeholderStateRef);
  for (const [paneIndex, entry] of placeholderStateRef.current.seriesByPane) {
    if (paneIndex < retainPaneCount) continue;
    try {
      chart.removeSeries(entry.series);
    } catch {
      // The pane may already have been removed during surface disposal.
    }
    placeholderStateRef.current.seriesByPane.delete(paneIndex);
  }
}
