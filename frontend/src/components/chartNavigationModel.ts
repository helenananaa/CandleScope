import { sourceTimeRangeFromDisplayRow } from "../features/chart-representation/axisTime.js";
import type { DisplayRow } from "../features/chart-representation/chartRepresentationTypes.js";

export interface ChartNavigationWindow {
  targetIndex: number;
  logicalRange: { from: number; to: number };
  timeRange: { from: number; to: number } | null;
}

export function buildChartNavigationWindow(
  rows: readonly DisplayRow[],
  targetTime: number,
  {
    beforeBars = 60,
    afterBars = 20,
  }: {
    beforeBars?: number;
    afterBars?: number;
  } = {},
): ChartNavigationWindow | null {
  if (!Number.isFinite(targetTime) || rows.length < 2) return null;
  const targetIndex = rows.findIndex((row) => {
    const range = sourceTimeRangeFromDisplayRow(row);
    return range !== null && range.from <= targetTime && targetTime <= range.to;
  });
  if (targetIndex < 0) return null;
  const safeBefore = Math.max(0, Math.floor(Number(beforeBars)) || 0);
  const safeAfter = Math.max(0, Math.floor(Number(afterBars)) || 0);
  const from = Math.max(0, targetIndex - safeBefore);
  const to = Math.min(rows.length - 1, Math.max(from + 1, targetIndex + safeAfter));
  const fromTime = rows[from]?.time;
  const toTime = rows[to]?.time;
  return {
    targetIndex,
    logicalRange: { from, to },
    timeRange: typeof fromTime === "number" && typeof toTime === "number"
      ? { from: fromTime, to: toTime }
      : null,
  };
}
