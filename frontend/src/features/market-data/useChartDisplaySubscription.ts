import { useEffect, useId, useMemo } from "react";
import { ChartWorkScheduler } from "./chartWorkScheduler.js";
import { createChartDisplaySubscription, type ChartDisplayScheduler } from "./chartDisplaySubscription.js";
import { observeMarketWindowVisibility } from "./marketWindowVisibility.js";
import type { SeriesWindowView } from "./window/seriesWindowView.js";

export function useChartDisplaySubscription(
  source: SeriesWindowView | null,
  suspended: boolean,
  shared?: ChartDisplayScheduler,
) {
  const id = useId();
  const owned = useMemo(() => ({ scheduler: new ChartWorkScheduler(), cellId: `surface-${id}` }), [id]);
  const scheduler = shared?.scheduler ?? owned.scheduler;
  const cellId = shared?.cellId ?? owned.cellId;
  const driver = useMemo(() => ({ scheduler, cellId }), [cellId, scheduler]);
  useEffect(() => {
    if (shared) return;
    const releaseCell = owned.scheduler.registerCell(owned.cellId);
    const releaseVisibility = observeMarketWindowVisibility(visible => owned.scheduler.setWindowVisible(visible));
    // Unregister empties the queue and supports React StrictMode reacquisition.
    return () => { releaseVisibility(); releaseCell(); };
  }, [owned, shared]);
  useEffect(() => {
    if (!shared) owned.scheduler.setCellTier(owned.cellId, suspended ? "hidden" : "focused");
  }, [owned, shared, suspended]);
  return useMemo(() => source
    ? createChartDisplaySubscription(source, driver, `surface-${id}`)
    : null, [driver, id, source]);
}
