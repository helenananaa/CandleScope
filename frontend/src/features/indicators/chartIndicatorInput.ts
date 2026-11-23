import type { MainChartType } from "../../shared/mainChartTypes.js";
import { normalizeMainChartType } from "../../shared/mainChartTypes.js";
import type { SeriesWindowView } from "../market-data/window/seriesWindowView.js";
import type { BackendSyntheticSource, SyntheticSettings, SyntheticSnapshot } from "../market-data/synthetic/syntheticSeries.js";
import type { KlineBar } from "../market-data/marketDataTypes.js";
import type { ChartSettings } from "../settings/chartAppearanceSettings.js";

export interface ChartIndicatorSelection {
  source: BackendSyntheticSource | null;
  reader: SeriesWindowView | null;
  chartType: MainChartType;
  settings: SyntheticSettings;
}

export function chartIndicatorSelection(source: BackendSyntheticSource | null, reader: SeriesWindowView | null,
  appearance: Partial<ChartSettings>): ChartIndicatorSelection {
  const chartType = normalizeMainChartType(appearance.chartType);
  const settings = chartType === "heikin-ashi" ? {} : chartType === "point-and-figure" ? {
    mode: appearance.pointFigureBoxSizeMode, atrLength: appearance.pointFigureAtrLength,
    boxSize: appearance.pointFigureBoxSize, reversalAmount: appearance.pointFigureReversalAmount,
  } : chartType === "kagi" ? { mode: appearance.kagiReversalMode, atrLength: appearance.kagiAtrLength,
    reversalAmount: appearance.kagiReversalAmount } : chartType === "line-break" ? {
    numberOfLines: appearance.lineBreakNumberOfLines,
  } : { mode: appearance.renkoBoxSizeMode, atrLength: appearance.renkoAtrLength, boxSize: appearance.renkoBoxSize };
  return { source, reader, chartType, settings: Object.fromEntries(Object.entries(settings).filter(([, value]) => value !== undefined)) };
}

/** Numeric execution keys preserve every same-time brick through numeric-only
 * indicator codecs. sourceTime remains the actual script clock; render mapping
 * converts execution keys to the exact display ordinal, never timestamp fanout. */
export function chartIndicatorBars(snapshot: SyntheticSnapshot, ordinal: boolean): KlineBar[] {
  if (snapshot.status !== "ready") return [];
  return snapshot.rows.map(row => {
    const clock = typeof row.time === "number" ? row.time : row.time.sourceTime;
    const metadata = row.customValues?.chartProjection as { provisional?: boolean } | undefined;
    return { time: (ordinal ? row.ordinal + 1 : clock) as KlineBar["time"], sourceTime: clock,
      open: Number(row.open), high: Number(row.high), low: Number(row.low), close: Number(row.close),
      volume: Number(row.volume ?? 0), is_closed: metadata?.provisional !== true };
  });
}

/** Unavailable/stale inputs are diagnostics, never an indefinite compute spinner. */
export function chartIndicatorSourceError(snapshot: SyntheticSnapshot, status: string): string | null {
  if (snapshot.status === "ready") return null;
  return snapshot.reason ?? (["", "preparing", "ready"].includes(status) ? null : status);
}
